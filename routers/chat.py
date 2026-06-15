import os
import json
import logging
import threading
import base64
import asyncio
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from assistants.config import ASSISTANTS
from core.config import GEMINI_API_KEY, GEMINI_LIVE_MODEL, SKILLS_DIR
from utils.llm import stream_response
from utils.rag import inject_context_to_system, load_skills_relevant
from utils.history import (
    save_message, load_history, delete_last_assistant_message,
    get_last_user_message,
)
from utils.memory import save_lesson, save_preference, get_lessons, get_preferences, search_memory
from memory.operations import remember, recall, teach, push_working
from utils.skills import search_skills
from utils.obsidian_sync import search_vault
from utils.home_tools import detect_home_tools, build_tool_context
from reasoning.learn_gate import should_auto_learn
from utils.tts import VOICE_MAP, DEFAULT_VOICE
from utils.tokens import count_tokens_approx
from core.observability import log_timing, current_request_id, get_timings

router = APIRouter(prefix="/api", tags=["chat"])
logger = logging.getLogger(__name__)


@router.post("/chat")
async def chat(request: Request):
    data = await request.json()
    assistant   = data.get("assistant", list(ASSISTANTS.keys())[0])
    session_id  = data.get("session_id", "default")
    prompt      = data.get("prompt", "")
    if not isinstance(prompt, str):              # client ส่ง list/dict → crash ทุก provider + regex + ขยะลง DB
        prompt = "" if prompt is None else str(prompt)
    provider    = data.get("provider", "auto")
    req_model   = data.get("model", "")          # โมเดลที่เลือกจาก dropdown (per-request)
    req_thinking = data.get("thinking", None)    # None = ไม่ระบุ (ใช้ default ของ provider)
    if req_thinking is not None:
        req_thinking = bool(req_thinking)
    req_effort  = data.get("effort", "")
    image_b64   = data.get("image_b64", "")
    image_mime  = data.get("image_mime", "")
    agent_mode  = bool(data.get("agent_mode", False))
    tool_agent  = bool(data.get("tool_agent", False))
    obsidian_inject = bool(data.get("obsidian_inject", False))
    reflect     = bool(data.get("reflect", False))
    plan_mode   = bool(data.get("plan_mode", False))
    active_learning = data.get("active_learning", True)  # default ON

    config = ASSISTANTS.get(assistant, list(ASSISTANTS.values())[0])
    base_prompt = config["system_prompt"]
    # plan_mode bypass cache — คำตอบ plan-style คนละความหมายกับคำตอบปกติของ prompt เดียวกัน
    use_response_cache = bool(data.get("response_cache", True)) and not (tool_agent or agent_mode or image_b64 or plan_mode)

    # ── Image generation short-circuit (วาดรูป/สร้างภาพ → Gemini Image) ─────
    # อยู่ก่อน teach/cache — คำสั่งวาดรูปไม่ใช่ knowledge ห้ามเข้า cache/memory
    from utils.image_gen import detect_image_request, generate_image
    if prompt and detect_image_request(prompt) and not (tool_agent or agent_mode):
        save_message(assistant, "user", prompt, "image_gen", session_id)
        result = generate_image(prompt, image_b64=image_b64, image_mime=image_mime)
        if result.get("ok"):
            caption = result.get("text") or "วาดเสร็จแล้วค่ะ 🎨"
            reply = f"{caption}\n\n![generated image]({result['url']})"
        else:
            reply = f"⚠️ {result.get('error', 'สร้างรูปไม่สำเร็จ')}"
        img_aid = save_message(assistant, "assistant", reply, "image_gen", session_id)

        def gen_image_resp():
            yield f"data: {json.dumps({'chunk': reply}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'done': True, 'model': 'gemini-image', 'provider': 'image_gen', 'message_id': img_aid}, ensure_ascii=False)}\n\n"

        logger.info(f"[Chat] image generation short-circuit (ok={result.get('ok')})")
        return StreamingResponse(gen_image_resp(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                                          "X-Provider-Used": "image_gen"})

    # ── ตรวจจับ Teaching signal จาก user ────────────────────────────────────
    teach(assistant, prompt)

    # ── Semantic response cache (short-circuit ถ้า Q ใกล้ของที่ thumbs-up) ─
    if use_response_cache and prompt:
        try:
            from utils.response_cache import lookup as _rc_lookup
            hit = _rc_lookup(assistant, prompt)
            if hit:
                cached_resp = hit["response"]
                cached_mid = save_message(assistant, "user", prompt, "cache", session_id)
                cached_aid = save_message(assistant, "assistant", cached_resp, "cache", session_id)

                def gen_cached():
                    yield f"data: {json.dumps({'cache_hit': {'similarity': hit['similarity'], 'source_prompt': hit['source_prompt']}}, ensure_ascii=False)}\n\n"
                    yield f"data: {json.dumps({'chunk': cached_resp}, ensure_ascii=False)}\n\n"
                    yield f"data: {json.dumps({'done': True, 'model': hit.get('model','cache'), 'provider': 'cache', 'message_id': cached_aid}, ensure_ascii=False)}\n\n"

                logger.info(f"[Chat] response cache hit (sim={hit['similarity']}) — bypass LLM")
                return StreamingResponse(gen_cached(), media_type="text/event-stream",
                                         headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                                                  "X-Provider-Used": "cache"})
        except Exception as e:
            logger.debug(f"[Chat] response cache lookup skipped: {e}")

    # ── ดึง context จากทุก tier ──────────────────────────────────────────────
    from utils.citations import CitationTracker
    citations = CitationTracker()

    with log_timing("context_assembly"):
        lessons    = get_lessons(prompt)
        prefs      = get_preferences()
        skills_dir = SKILLS_DIR
        skills_md  = load_skills_relevant(skills_dir, prompt)

        # New: tiered memory recall (working + episodic + long-term)
        memory_ctx = recall(assistant, prompt, session_id=session_id)

    vault_ctx = ""
    if obsidian_inject:
        vault_results = search_vault(prompt, n=3)
        if vault_results:
            vault_ctx = "\n\n".join([f"[Note: {r['title']}]\n{r['content'][:500]}" for r in vault_results])
            try:
                citations.add_vault_notes(vault_results)
            except Exception as e:
                logger.debug(f"[Chat] vault citations skipped: {e}")

    home_tool_ctx = ""
    home_tools_needed = detect_home_tools(prompt)
    if home_tools_needed:
        home_tool_ctx = build_tool_context(home_tools_needed)

    # ── Document retrieval (RAG จาก uploaded docs) ──────────────────────────
    # ใช้ per-session cache — ถ้า topic เดิม ไม่ต้องเรียก ChromaDB ใหม่
    docs_ctx = ""
    doc_chunks: list[dict] = []
    with log_timing("retrieval"):
        try:
            from utils.retrieval_cache import get_cached as _retr_get, store as _retr_store
            from utils.documents import retrieve_chunks, format_for_context as _doc_fmt

            cached = _retr_get(session_id, prompt)
            if cached:
                doc_chunks = cached["chunks"]
                logger.info(f"[Chat] retrieval cache hit (sim={cached['similarity']})")
            else:
                doc_chunks = retrieve_chunks(prompt, top_k=3, min_score=0.3)
                if doc_chunks:
                    _retr_store(session_id, prompt, doc_chunks)

            if doc_chunks:
                docs_ctx = _doc_fmt(doc_chunks, max_chars=1500)
                citations.add_doc_chunks(doc_chunks)
                logger.info(f"[Chat] retrieved {len(doc_chunks)} doc chunks")
        except Exception as e:
            logger.debug(f"[Chat] doc retrieval skipped: {e}")

    # ── Prefix-stable context ordering ─────────────────────────────────────
    # หลักการ: ส่วนที่เปลี่ยนน้อย (prefs/lessons) ขึ้นก่อน — llama.cpp KV cache hit
    # ส่วน volatile (memory/skill search/docs/home tools) ลงท้าย — miss แค่ตอนท้าย
    stable_block = "\n\n".join(filter(None, [
        f"[ความชอบของผู้ใช้]\n{prefs}" if prefs else "",
        f"[บทเรียนสะสม]\n{lessons}" if lessons else "",
        f"[Skills & Knowledge]\n{skills_md}" if skills_md else "",
    ]))
    volatile_block = "\n\n".join(filter(None, [
        memory_ctx,
        search_skills(prompt, n_results=3),
        f"[Obsidian Vault Notes]\n{vault_ctx}" if vault_ctx else "",
        f"[ข้อมูลจากบ้านแบบ Real-time]\n{home_tool_ctx}" if home_tool_ctx else "",
        docs_ctx,
        citations.format_inline_legend(),
    ]))
    full_context = "\n\n".join(filter(None, [stable_block, volatile_block]))

    if provider == "ollama" and len(full_context) > 2000:
        full_context = full_context[:2000]
    system_prompt = inject_context_to_system(base_prompt, full_context)

    history = load_history(assistant, session_id)

    # ── Active Learning: ตรวจว่าควรให้ AI ถามกลับก่อนตอบไหม ─────────────────
    al_decision = None
    try:
        from reasoning.active_learning import decide as _al_decide
        retrieval_scores = [c.score for c in citations._items if c.score > 0]
        # ข้อความ user ก่อนหน้า — ใช้หา location ที่เคยบอกแล้ว (กันถามซ้ำ)
        recent_user = " ".join(m["content"] for m in history[-6:] if m.get("role") == "user")
        al_decision = _al_decide(
            prompt, retrieval_scores=retrieval_scores,
            history_length=len(history),
            enabled=bool(active_learning),
            recent_user_text=recent_user,
        )
        if al_decision.should_ask and not al_decision.clarify_directly:
            system_prompt = system_prompt + al_decision.instruction
            logger.info(f"[Chat/AL] {al_decision.reason}")
    except Exception as e:
        logger.debug(f"[Chat/AL] skipped: {e}")

    # ── Deterministic clarify (weather ไม่มี location ฯลฯ) ───────────────────
    # ถามกลับเองโดยไม่เรียก LLM — โมเดลกุข้อมูล real-time ไม่ได้เลย (root cause
    # บั๊ก "อำเภอละเว" 2026-06-14). ไม่ remember() กัน episodic ปนเปื้อนคำถาม clarify
    if al_decision and al_decision.clarify_directly:
        clarify = al_decision.clarify_message
        logger.info(f"[Chat/AL] {al_decision.reason} — short-circuit clarify (no LLM)")
        save_message(assistant, "user", prompt, provider, session_id)
        clarify_aid = save_message(assistant, "assistant", clarify, "active_learning", session_id)
        push_working(session_id, "user", prompt)
        push_working(session_id, "assistant", clarify)

        def gen_clarify():
            yield f"data: {json.dumps({'active_learning': al_decision.to_dict()}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'chunk': clarify}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'done': True, 'model': 'active_learning', 'provider': 'active_learning', 'message_id': clarify_aid}, ensure_ascii=False)}\n\n"

        return StreamingResponse(gen_clarify(), media_type="text/event-stream",
                                 headers={
                                     "Cache-Control": "no-cache",
                                     "X-Accel-Buffering": "no",
                                     "X-Model-Used": "active_learning",
                                     "X-Provider-Used": "active_learning",
                                     "Access-Control-Expose-Headers": "X-Model-Used, X-Provider-Used",
                                 })

    # ── Plan mode (§22 ChatBox) — ฉีด instruction เข้า system prompt เท่านั้น ──
    # ห้ามแตะ prompt: save_message/push_working/remember ใช้ prompt เดิม
    # → DB/memory/fine-tune corpus สะอาด (scrutinize 2026-06-10, Major 2)
    if plan_mode:
        system_prompt += "\n\n[โหมดวางแผน] ผู้ใช้เปิดโหมด Plan: ช่วยวางแผนเป็นขั้นตอนสั้นๆ ก่อน แล้วค่อยลงรายละเอียด"
        logger.info("[Chat] plan_mode on — inject plan instruction (system prompt)")

    save_message(assistant, "user", prompt, provider, session_id)

    messages = [{"role": "system", "content": system_prompt}]
    messages += [{"role": m["role"], "content": m["content"]} for m in history]
    messages.append({"role": "user", "content": prompt})

    if provider == "ollama":
        if len(messages[0]["content"]) > 4000:
            messages[0] = {"role": "system", "content": messages[0]["content"][:4000]}
        while len(messages) > 2 and count_tokens_approx(messages) > 3000:
            messages.pop(1)

    # ── Tool Agent branch ───────────────────────────────────────────────────
    # เปิดด้วย {"tool_agent": true} → route ไป agent orchestrator (multi-step tool use)
    if tool_agent:
        from agents.orchestrator import run_agent

        def gen_agent():
            full_response = ""
            if citations:
                yield f"data: {json.dumps({'citations': citations.to_list()}, ensure_ascii=False)}\n\n"
            try:
                agent_provider = provider if provider in ("gemini", "lmstudio", "ollama") else "gemini"
                for kind, payload in run_agent(messages, provider=agent_provider):
                    if kind == "event":
                        # SSE event สำหรับ enhanced.js timeline — React อ่านแล้ว ignore
                        yield f"data: {json.dumps({'agent': payload}, ensure_ascii=False)}\n\n"
                    elif kind == "chunk":
                        full_response += payload
                        yield f"data: {json.dumps({'chunk': payload}, ensure_ascii=False)}\n\n"
            except Exception as e:
                logger.exception("[Chat/agent] run failed")
                yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
                return

            # persist เหมือน /api/chat ปกติ
            agent_msg_id = 0
            try:
                agent_msg_id = save_message(assistant, "assistant", full_response, "agent", session_id)
                push_working(session_id, "user", prompt)
                push_working(session_id, "assistant", full_response)
                remember(assistant, prompt, full_response)
            except Exception as e:
                logger.warning(f"[Chat/agent] persist failed: {e}")

            yield f"data: {json.dumps({'done': True, 'model': 'agent', 'provider': 'agent', 'message_id': agent_msg_id}, ensure_ascii=False)}\n\n"

        return StreamingResponse(gen_agent(), media_type="text/event-stream",
                                 headers={
                                     "Cache-Control": "no-cache",
                                     "X-Accel-Buffering": "no",
                                     "X-Model-Used": "agent",
                                     "X-Provider-Used": "agent",
                                     "Access-Control-Expose-Headers": "X-Model-Used, X-Provider-Used",
                                 })

    # ── Get routing decision ก่อน stream เพื่อส่ง model info ─────────────────
    model_used = ""
    provider_used = provider
    model_override = ""
    if provider == "auto":
        try:
            from reasoning.router import route
            decision = route(prompt, provider_hint="auto",
                             has_image=bool(image_b64), agent_mode=agent_mode)
            provider_used = decision.provider
            model_override = decision.model
            model_used = decision.model.split("/")[-1] if decision.model else decision.provider
            logger.info(f"[Chat] route → {decision.provider}/{decision.model} ({decision.reason})")

            # ── Web search: ค้น DDG แล้ว inject context ─────────────────────
            if decision.provider == "lmstudio_web":
                try:
                    from utils.websearch import web_search_with_results
                    web_ctx, web_results = web_search_with_results(prompt)
                    if web_ctx:
                        try:
                            citations.add_web_results(web_results)
                        except Exception as ce:
                            logger.debug(f"[Chat] web citations skipped: {ce}")
                        legend = citations.format_inline_legend()
                        # inject เป็น system instruction + user prompt
                        sys_extra = (
                            "\n\n=== INTERNET CONTEXT (real-time data) ===\n"
                            f"{web_ctx}\n"
                            "=== END INTERNET CONTEXT ===\n"
                            f"{legend}\n"
                            "**กฎเหล็ก**: ใช้ข้อมูลด้านบนตอบคำถาม ห้ามบอกว่าไม่มี internet/ไม่มีข้อมูล real-time "
                            "เพราะระบบดึงข้อมูลให้แล้ว สรุปจากข้อมูลและอ้างอิงแหล่งที่มาด้วยเลข [n]"
                        )
                        messages[0] = {
                            "role": "system",
                            "content": messages[0]["content"] + sys_extra,
                        }
                        provider_used = "lmstudio"
                        logger.info(f"[Chat] web search injected ({len(web_ctx)} chars, {len(web_results)} sources)")
                    else:
                        provider_used = "lmstudio"
                except Exception as e:
                    logger.warning(f"[Chat] web search failed: {e}")
                    provider_used = "lmstudio"

        except Exception as e:
            logger.warning(f"[Chat] route failed: {e}")
    elif req_model:
        # provider ชัดเจน + เลือกโมเดลจาก dropdown → ใช้ตัวนั้น (per-request override)
        model_override = req_model
        model_used = req_model.split("/")[-1]

    def generate():
        nonlocal provider_used, model_used, messages
        import time as _time
        from core.observability import record_timing
        full_response = ""
        llm_start = _time.perf_counter()
        _provider = provider_used if provider_used and provider_used != "auto" else provider

        # ส่ง citations event ก่อน stream chunks (ถ้ามี) — frontend แสดง source list ได้ก่อนตอบ
        if citations:
            yield f"data: {json.dumps({'citations': citations.to_list()}, ensure_ascii=False)}\n\n"
        # ส่ง active learning signal (เผื่อ frontend แสดง badge "AI กำลังถามกลับ")
        if al_decision and al_decision.should_ask:
            yield f"data: {json.dumps({'active_learning': al_decision.to_dict()}, ensure_ascii=False)}\n\n"

        def _try_stream(prov, mdl=""):
            for ck in stream_response(messages, provider=prov, image_b64=image_b64,
                                      image_mime=image_mime, agent_mode=agent_mode,
                                      model_override=mdl,
                                      thinking=req_thinking, effort=req_effort):
                yield ck

        try:
            for chunk in _try_stream(_provider, model_override):
                full_response += chunk
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
        except Exception as e:
            from utils.llm import GeminiQuotaExhausted, GeminiUnavailable
            # Gemini ล้ม → fallback ไป local model + web search (ถ้าเป็น internet query)
            # เลือก local provider: LM Studio ถ้าตั้งค่าไว้ ไม่งั้นใช้ Ollama
            if isinstance(e, (GeminiQuotaExhausted, GeminiUnavailable)) and _provider in ("gemini", "gemini_agent"):
                try:
                    from core.config import LMSTUDIO_BASE_URL, LMSTUDIO_CHAT_MODEL, OLLAMA_MODEL
                    from reasoning.classifier import needs_internet
                    # router ตัดสินใจ local provider — LMStudio/DeepSeek ก่อน, Ollama เป็น last resort
                    from reasoning.router import route as _route
                    _fb_decision = _route(prompt, provider_hint="auto")
                    if _fb_decision.provider in ("lmstudio", "lmstudio_web"):
                        fb_provider, fb_model = "lmstudio", _fb_decision.model
                        fb_model_label = _fb_decision.model.split("/")[-1] if _fb_decision.model else "LMStudio"
                    else:
                        fb_provider, fb_model = "ollama", ""
                        fb_model_label = OLLAMA_MODEL
                    fallback_msg = ("⚠️ Gemini quota หมด — กำลังลอง local model + web search...\n\n"
                                    if isinstance(e, GeminiQuotaExhausted)
                                    else "⚠️ Gemini ใช้ไม่ได้ — fallback เป็น local model...\n\n")
                    yield f"data: {json.dumps({'chunk': fallback_msg})}\n\n"
                    full_response += fallback_msg

                    if needs_internet(prompt):
                        try:
                            from utils.websearch import web_search_with_results
                            web_ctx, web_results = web_search_with_results(prompt)
                            if web_ctx:
                                try:
                                    citations.add_web_results(web_results)
                                except Exception as ce:
                                    logger.debug(f"[Chat] fallback web citations skipped: {ce}")
                                legend = citations.format_inline_legend()
                                messages[0] = {
                                    "role": "system",
                                    "content": messages[0]["content"] + (
                                        "\n\n=== INTERNET CONTEXT ===\n" + web_ctx +
                                        f"\n=== END ===\n{legend}\n"
                                        "**กฎเหล็ก**: ใช้ข้อมูลข้างบนตอบ ห้ามบอกว่าไม่มี internet อ้างอิงด้วยเลข [n]"
                                    )
                                }
                                # ส่ง citations event ระหว่าง fallback ด้วย
                                if citations:
                                    yield f"data: {json.dumps({'citations': citations.to_list()}, ensure_ascii=False)}\n\n"
                                logger.info(f"[Chat] Gemini fallback → web search injected ({len(web_ctx)} chars)")
                        except Exception as ws_err:
                            logger.warning(f"[Chat] fallback web search failed: {ws_err}")

                    provider_used = fb_provider
                    model_used = fb_model_label
                    for chunk in _try_stream(fb_provider, fb_model):
                        full_response += chunk
                        yield f"data: {json.dumps({'chunk': chunk})}\n\n"
                except Exception as e2:
                    yield f"data: {json.dumps({'error': f'Fallback ล้มด้วย: {e2}'})}\n\n"
                    return
            else:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
                return

        record_timing("llm_stream", (_time.perf_counter() - llm_start) * 1000)
        message_id = save_message(assistant, "assistant", full_response, provider_used, session_id)

        # ── Reflection: ตรวจคำตอบหลัง stream เสร็จ → ส่ง revision เป็น SSE event ─
        if reflect and full_response:
            try:
                from utils.reflection import reflect_answer, should_reflect
                if should_reflect(prompt, full_response):
                    refl = reflect_answer(prompt, full_response, context=full_context)
                    payload = {"reflection": {
                        "score": refl.score,
                        "verdict": refl.verdict,
                        "issues": refl.issues,
                        "revised": refl.revised if refl.needs_revision else "",
                    }}
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    logger.info(f"[Chat/reflect] verdict={refl.verdict} score={refl.score}")
            except Exception as e:
                logger.warning(f"[Chat/reflect] failed: {e}")

        push_working(session_id, "user", prompt)
        push_working(session_id, "assistant", full_response)
        remember(assistant, prompt, full_response)
        teach(assistant, prompt, ai_response=full_response)

        _learn_ok, _learn_reason = should_auto_learn(prompt)
        if not _learn_ok:
            logger.info(f"[Chat/auto-learn] skip lesson — reason={_learn_reason}")
        if len(full_response) > 100 and _learn_ok:
            def _learn(p=prompt, r=full_response, pv=provider_used):
                try:
                    msgs = [
                        {"role": "system", "content": "สรุปบทเรียนเป็นภาษาไทย 1-2 ประโยค ถ้าไม่มีตอบว่า SKIP"},
                        {"role": "user", "content": f"คำถาม: {p}\nคำตอบ: {r[:500]}"},
                    ]
                    lesson = "".join(stream_response(msgs, provider=pv)).strip()
                    if lesson and lesson != "SKIP" and len(lesson) > 10:
                        save_lesson(p[:50], lesson)
                    for kw, (k, v) in {"ตอบสั้น": ("style", "ชอบสั้น"), "อธิบาย": ("style", "ชอบละเอียด")}.items():
                        if kw in p:
                            save_preference(k, v)
                except Exception as e:
                    logger.debug(f"Auto-learn failed: {e}")
            threading.Thread(target=_learn, daemon=True).start()

        # ใส่ timing + request_id ใน done event เพื่อ debug / metrics
        done_payload = {
            "done": True, "model": model_used, "provider": provider_used,
            "message_id": message_id,
            "request_id": current_request_id(),
            "timings": get_timings(),
        }
        yield f"data: {json.dumps(done_payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={
                                 "Cache-Control": "no-cache",
                                 "X-Accel-Buffering": "no",
                                 "X-Model-Used": model_used,
                                 "X-Provider-Used": provider_used,
                                 "Access-Control-Expose-Headers": "X-Model-Used, X-Provider-Used",
                             })


@router.post("/regenerate")
async def regenerate_response(request: Request):
    data = await request.json()
    assistant  = data.get("assistant", list(ASSISTANTS.keys())[0])
    session_id = data.get("session_id", "default")
    provider   = data.get("provider", "auto")
    agent_mode = bool(data.get("agent_mode", False))

    delete_last_assistant_message(assistant, session_id)
    last_prompt = get_last_user_message(assistant, session_id)
    if not last_prompt:
        async def _err():
            yield "data: " + json.dumps({'error': 'ไม่พบข้อความ'}) + "\n\n"
        return StreamingResponse(_err(), media_type="text/event-stream")

    cfg = ASSISTANTS.get(assistant, list(ASSISTANTS.values())[0])
    system_prompt = inject_context_to_system(
        cfg["system_prompt"],
        "\n\n".join(filter(None, [search_memory(assistant, last_prompt)])),
    )
    history = load_history(assistant, session_id)
    messages = [{"role": "system", "content": system_prompt}]
    messages += [{"role": m["role"], "content": m["content"]} for m in history]
    messages.append({"role": "user", "content": last_prompt})

    def gen_regen():
        full_response = ""
        try:
            for chunk in stream_response(messages, provider=provider, agent_mode=agent_mode):
                full_response += chunk
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            return
        save_message(assistant, "assistant", full_response, provider, session_id)
        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(gen_regen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
