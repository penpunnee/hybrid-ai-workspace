import json
import logging
import os
import threading
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from assistants.config import ASSISTANTS
from core.config import SKILLS_DIR
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
from reasoning.learn_gate import should_auto_learn, clean_lesson, should_remember, detect_preferences
from utils.tokens import count_tokens_approx
from core.observability import log_timing, current_request_id, get_timings

router = APIRouter(prefix="/api", tags=["chat"])
logger = logging.getLogger(__name__)

# คะแนน similarity ขั้นต่ำที่จะดึง chunk เอกสารเข้า context (ปรับได้ทาง .env)
_DOC_MIN_SCORE = float(os.getenv("DOC_RETRIEVAL_MIN_SCORE", "0.5"))


def _is_test_request(request: Request) -> bool:
    """`X-Test-Request` header → smoke test เรียก /api/chat จริงได้โดยไม่ปนเปื้อน
    episodic memory/lessons/preferences (แก้ pain ที่ต้องต่อ ChromaDB ตรงลบทีหลัง —
    ดู P2-9 ROADMAP.md + Known Quirks ใน CLAUDE.md)"""
    return bool(request.headers.get("x-test-request"))


def _inject_web_context(messages: list, prompt: str, citations) -> bool:
    """เสิร์ชเว็บแล้ว inject ผลเป็น system context — ground คำตอบทุกโมเดล (local/Gemini/Gemma)
    สำหรับคำถาม real-time. คืน True ถ้า inject สำเร็จ. ใช้ร่วมกันทั้ง auto→lmstudio_web และ
    path ที่เลือกโมเดลเฉพาะ"""
    try:
        # ให้ local/Claude/Kimi "ยืม" Gemini grounding (Google จริง) เป็นหลัก — คุณภาพดีกว่า DDG
        # + ไม่ต้องมี Custom Search API key. ถ้า Gemini ไม่พร้อม/ล้ม → fallback DDG
        web_ctx, web_results = "", []
        try:
            from utils.llm import gemini_web_search
            web_ctx, web_results = gemini_web_search(prompt)
        except Exception as ge:
            logger.debug(f"[Chat] gemini grounding skipped: {ge}")
        if not web_ctx:
            from utils.websearch import web_search_with_results
            web_ctx, web_results = web_search_with_results(prompt)
        if not web_ctx:
            return False
        try:
            citations.add_web_results(web_results)
        except Exception as ce:
            logger.debug(f"[Chat] web citations skipped: {ce}")
        legend = citations.format_inline_legend()
        sys_extra = (
            "\n\n=== INTERNET CONTEXT (real-time data) ===\n"
            f"{web_ctx}\n"
            "=== END INTERNET CONTEXT ===\n"
            f"{legend}\n"
            "**กฎเหล็ก**: ใช้ข้อมูลด้านบนตอบคำถาม ห้ามบอกว่าไม่มี internet/ไม่มีข้อมูล real-time "
            "เพราะระบบดึงข้อมูลให้แล้ว สรุปจากข้อมูลและอ้างอิงแหล่งที่มาด้วยเลข [n]. "
            "ถ้าข้อมูลที่ให้ไม่มีคำตอบที่ถาม (เช่น เลขตอนล่าสุด) ให้บอกตรงๆ ว่าไม่พบ ห้ามเดา/แต่งตัวเลขเอง"
        )
        messages[0] = {"role": "system", "content": messages[0]["content"] + sys_extra}
        logger.info(f"[Chat] web search injected ({len(web_ctx)} chars, {len(web_results)} sources)")
        return True
    except Exception as e:
        logger.warning(f"[Chat] web search failed: {e}")
        return False


def persist_agent_turn(assistant: str, prompt: str, full_response: str, session_id: str,
                        is_test_request: bool = False) -> int:
    """persist คำตอบ agent → save_message + push_working เสมอ, แต่ **gate** remember()
    (episodic) ด้วย should_auto_learn — คำตอบ agent มาจาก tool real-time เสมอ
    ดังนั้นงาน realtime/home-tool ไม่ควรตกผลึกลง episodic (กันปนเปื้อน volatile).
    is_test_request (P2-9): smoke test ผ่าน X-Test-Request ก็ข้าม remember เหมือนกัน"""
    agent_msg_id = save_message(assistant, "assistant", full_response, "agent", session_id)
    push_working(session_id, "user", prompt)
    push_working(session_id, "assistant", full_response)
    if is_test_request:
        logger.info("[Chat/agent] skip remember (episodic): test_request")
        return agent_msg_id
    ok, reason = should_auto_learn(prompt)
    if ok:
        remember(assistant, prompt, full_response)
    else:
        logger.info(f"[Chat/agent] skip remember (episodic): {reason}")
    return agent_msg_id


@router.post("/chat")
async def chat(request: Request):
    data = await request.json()
    is_test_request = _is_test_request(request)
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
    if not is_test_request:
        teach(assistant, prompt)

    # ── Semantic response cache (short-circuit ถ้า Q ใกล้ของที่ thumbs-up) ─
    if use_response_cache and prompt:
        try:
            from utils.response_cache import lookup as _rc_lookup
            hit = _rc_lookup(assistant, prompt)
            if hit:
                cached_resp = hit["response"]
                save_message(assistant, "user", prompt, "cache", session_id)
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
    # หมายเหตุสถาปัตยกรรม (2026-07-13): งานทั้งหมดข้างล่างนี้ (context assembly →
    # retrieval → routing → LLM stream) ย้ายเข้ามาอยู่ใน generator เดียวกัน (แทนที่จะ
    # รันแบบ sync ก่อน return StreamingResponse เหมือนเดิม) เพื่อให้ยิง SSE
    # {"phase": "..."} บอกความคืบหน้าจริงระหว่างที่ backend ยังไม่มี token ให้นับ —
    # ก่อนหน้านี้ frontend เห็นแค่ "0 tokens" ค้างนิ่งช่วง 1-3 วิแรกทั้งที่ backend
    # กำลังทำงานอยู่จริง (คนหา context/routing model) เพราะ headers/body ยังไม่เริ่ม
    # ส่งเลยจนกว่างานทั้งหมดนี้จะเสร็จ (ดู utils/streamstatus.ts formatPhaseStatus)
    def generate():
        import time as _time
        from core.observability import record_timing
        from utils.citations import CitationTracker
        citations = CitationTracker()

        yield f"data: {json.dumps({'phase': 'recall'}, ensure_ascii=False)}\n\n"
        with log_timing("context_assembly"):
            lessons    = get_lessons(prompt)
            prefs      = get_preferences()
            skills_dir = SKILLS_DIR
            skills_md  = load_skills_relevant(skills_dir, prompt)

            # New: tiered memory recall (working + episodic + long-term)
            memory_ctx = recall(assistant, prompt, session_id=session_id)

        yield f"data: {json.dumps({'phase': 'retrieval'}, ensure_ascii=False)}\n\n"
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
                    # threshold วัดจากข้อมูลจริงบน prod (2026-08-02 หลังแก้ embedding ไทย):
                    # คำถามที่ไม่เกี่ยวกับเอกสารได้ 0.33-0.42 (outlier 0.55 คือคำถามตัวเลข
                    # ไปตรงกับสเปรดชีตตัวเลข) ส่วนคำถามที่เกี่ยวจริงได้ 0.56-0.73
                    # ที่ 0.3 เดิม = ดึงเอกสารมาแปะเป็น citation ทุกข้อความแม้ไม่เกี่ยวเลย
                    doc_chunks = retrieve_chunks(prompt, top_k=3, min_score=_DOC_MIN_SCORE)
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

        yield f"data: {json.dumps({'phase': 'thinking'}, ensure_ascii=False)}\n\n"

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

            yield f"data: {json.dumps({'active_learning': al_decision.to_dict()}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'chunk': clarify}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'done': True, 'model': 'active_learning', 'provider': 'active_learning', 'message_id': clarify_aid}, ensure_ascii=False)}\n\n"
            return

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

            yield f"data: {json.dumps({'phase': 'agent'}, ensure_ascii=False)}\n\n"
            full_response = ""
            if citations:
                yield f"data: {json.dumps({'citations': citations.to_list()}, ensure_ascii=False)}\n\n"
            try:
                agent_provider = provider if provider in ("gemini", "lmstudio", "ollama") else "gemini"
                for kind, payload in run_agent(messages, provider=agent_provider):
                    if kind == "event":
                        # SSE agent event → React parse เป็น AgentTimeline (utils/agentsteps.ts, 2026-06-16)
                        yield f"data: {json.dumps({'agent': payload}, ensure_ascii=False)}\n\n"
                    elif kind == "chunk":
                        full_response += payload
                        yield f"data: {json.dumps({'chunk': payload}, ensure_ascii=False)}\n\n"
            except Exception as e:
                logger.exception("[Chat/agent] run failed")
                yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
                return

            # persist เหมือน /api/chat ปกติ (gate remember ด้วย should_auto_learn)
            agent_msg_id = 0
            try:
                agent_msg_id = persist_agent_turn(assistant, prompt, full_response, session_id,
                                                   is_test_request=is_test_request)
            except Exception as e:
                logger.warning(f"[Chat/agent] persist failed: {e}")

            yield f"data: {json.dumps({'done': True, 'model': 'agent', 'provider': 'agent', 'message_id': agent_msg_id}, ensure_ascii=False)}\n\n"
            return

        # ── Get routing decision ก่อน stream เพื่อส่ง model info ─────────────────
        model_used = ""
        provider_used = provider
        model_override = ""
        web_injected = False
        if provider == "auto":
            try:
                from reasoning.router import route
                decision = route(prompt, provider_hint="auto",
                                 has_image=bool(image_b64), agent_mode=agent_mode)
                provider_used = decision.provider
                model_override = decision.model
                model_used = decision.model.split("/")[-1] if decision.model else decision.provider
                logger.info(f"[Chat] route → {decision.provider}/{decision.model} ({decision.reason})")

                # ── Web search: ค้นแล้ว inject context (router เลือก lmstudio_web) ──
                if decision.provider == "lmstudio_web":
                    web_injected = _inject_web_context(messages, prompt, citations)
                    provider_used = "lmstudio"

            except Exception as e:
                logger.warning(f"[Chat] route failed: {e}")
        elif req_model:
            # provider ชัดเจน + เลือกโมเดลจาก dropdown → ใช้ตัวนั้น (per-request override)
            model_override = req_model
            model_used = req_model.split("/")[-1]

        # ── Grounding ทุกโมเดล: คำถาม real-time → เสิร์ชเว็บ inject ───────────────────
        # เดิมเสิร์ชเฉพาะ auto→lmstudio_web เท่านั้น → เลือกโมเดลเฉพาะ (qwen/Gemini/Gemma)
        # ตอบ real-time จาก training กว้างๆ. ทำให้ทุกโมเดลได้ข้อมูลจริงก่อนตอบ
        # (ข้าม agent — เสิร์ชเอง · vision — คนละโหมด · ที่ inject แล้ว — กันซ้ำ)
        # Option B (2026-06-15): โมเดล Gemini → ใช้ Google Search grounding ในตัว (real Google)
        # แทน DDG · provider อื่น (local/Claude/Kimi) ยัง inject DDG เหมือนเดิม
        gemini_grounding = False
        if not web_injected and not agent_mode and not image_b64:
            try:
                from reasoning.classifier import needs_internet
                if needs_internet(prompt):
                    _eff = provider_used if provider_used and provider_used != "auto" else provider
                    if _eff in ("gemini", "gemini_agent"):
                        gemini_grounding = True
                    else:
                        web_injected = _inject_web_context(messages, prompt, citations)
            except Exception as e:
                logger.warning(f"[Chat] grounding check failed: {e}")

        yield f"data: {json.dumps({'phase': 'generating', 'model': model_used, 'provider': provider_used}, ensure_ascii=False)}\n\n"

        full_response = ""
        llm_start = _time.perf_counter()
        _provider = provider_used if provider_used and provider_used != "auto" else provider

        # ส่ง citations event ก่อน stream chunks (ถ้ามี) — frontend แสดง source list ได้ก่อนตอบ
        if citations:
            yield f"data: {json.dumps({'citations': citations.to_list()}, ensure_ascii=False)}\n\n"
        # ส่ง active learning signal (เผื่อ frontend แสดง badge "AI กำลังถามกลับ")
        if al_decision and al_decision.should_ask:
            yield f"data: {json.dumps({'active_learning': al_decision.to_dict()}, ensure_ascii=False)}\n\n"

        # แหล่งอ้างอิงจาก Gemini Google Search grounding — generator yield ได้แต่ str
        # จึงรับผ่าน out-param แล้วค่อยแปลงเป็น citations หลัง stream จบ
        grounding_sources: list[dict] = []

        def _try_stream(prov, mdl=""):
            for ck in stream_response(messages, provider=prov, image_b64=image_b64,
                                      image_mime=image_mime, agent_mode=agent_mode,
                                      model_override=mdl,
                                      thinking=req_thinking, effort=req_effort,
                                      web_grounding=gemini_grounding,
                                      sources_sink=grounding_sources):
                yield ck

        def _save_crash(err_text: str):
            # stream พังกลางคัน — user message ถูก save ไปแล้ว (บรรทัดก่อนหน้า generate())
            # ถ้าไม่ save assistant reply คู่กันด้วย turn นี้จะกลายเป็น orphan (user
            # ไม่มีคำตอบคู่ใน history) และคำตอบบางส่วนที่ user เห็น stream มาแล้วบนจอ
            # จะหายไปทันทีที่ reload — ไม่เข้า remember()/teach()/push_working เพราะ
            # เป็นคำตอบที่ไม่สมบูรณ์ ไม่ควรถูกเรียนรู้เป็นตัวอย่าง
            text = (full_response + "\n\n" if full_response.strip() else "") + f"⚠️ การตอบหยุดกลางคัน: {err_text}"
            try:
                save_message(assistant, "assistant", text, provider_used or provider, session_id)
            except Exception as save_err:
                logger.error(f"[Chat] save partial response after crash failed too: {save_err}")

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
                    from core.config import OLLAMA_MODEL
                    from reasoning.classifier import needs_internet
                    # router ตัดสินใจ local provider — LMStudio/DeepSeek ก่อน, Ollama เป็น last resort
                    # exclude_gemini=True กัน route() เลือก gemini/gemini_agent ซ้ำ — Gemini เพิ่ง fail
                    # มาหมาดๆ แต่ GEMINI_API_KEY ยังตั้งอยู่ (แค่ quota หมด ไม่ใช่ key หาย) ทำให้เดิม
                    # route() คืน "gemini_agent" กลับมาซ้ำ แล้วโค้ดข้างล่างไม่รู้จัก provider นี้ →
                    # ตกไป else (Ollama) ทันทีทั้งที่ LM Studio ว่างอยู่จริง (เจอบั๊กนี้ 2026-07-30)
                    from reasoning.router import route as _route
                    _fb_decision = _route(prompt, provider_hint="auto", exclude_gemini=True)
                    if _fb_decision.provider in ("lmstudio", "lmstudio_web"):
                        fb_provider, fb_model = "lmstudio", _fb_decision.model
                        fb_model_label = _fb_decision.model.split("/")[-1] if _fb_decision.model else "LMStudio"
                    else:
                        fb_provider, fb_model = "ollama", ""
                        fb_model_label = OLLAMA_MODEL
                    # แจ้งเป็น SSE event แยกต่างหาก (เหมือน active_learning/reflection)
                    # ห้ามปนเข้า chunk/full_response — ไม่งั้นติดหน้าคำตอบจริงที่ผู้ใช้เห็น
                    # + ถูก save ลง DB + เข้า remember()/teach() ปนเปื้อน episodic memory
                    fb_reason = "quota" if isinstance(e, GeminiQuotaExhausted) else "unavailable"
                    fb_message = ("Gemini quota หมด — กำลังลอง local model + web search..."
                                  if fb_reason == "quota"
                                  else "Gemini ใช้ไม่ได้ — fallback เป็น local model...")
                    yield f"data: {json.dumps({'provider_fallback': {'from': 'gemini', 'to': fb_provider, 'reason': fb_reason, 'message': fb_message}}, ensure_ascii=False)}\n\n"

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
                    _save_crash(f"Fallback ล้มด้วย: {e2}")
                    return
            else:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
                _save_crash(str(e))
                return

        record_timing("llm_stream", (_time.perf_counter() - llm_start) * 1000)

        # Gemini grounding → citations (ส่งหลัง stream เพราะ grounding_metadata มากับ
        # chunk ท้ายๆ) เดิมเส้น Gemini ที่แม่นสุดกลับไม่มี citation เลย ผู้ใช้ตรวจสอบ
        # ที่มาของตัวเลขไม่ได้ ต่างจากโมเดล local ที่ยืม gemini_web_search แล้วมี
        if grounding_sources:
            try:
                citations.add_web_results(grounding_sources)
                yield f"data: {json.dumps({'citations': citations.to_list()}, ensure_ascii=False)}\n\n"
                logger.info(f"[Chat] Gemini grounding → {len(grounding_sources)} citations")
            except Exception as e:
                logger.debug(f"[Chat] grounding citations skipped: {e}")

        # ── Empty-response guard (เจอจริง qwen3.5-9b 2026-07-05) ─────────────
        # reasoning model "คิด" จนหมด token ไม่เคยตอบจริง → stream จบว่างเปล่า
        # เดิม: บับเบิลว่างค้างบนจอ + save '' ลง DB (ปนเปื้อน history/fine-tune)
        # ชั้นแรก salvage อยู่ที่ parser (stream_with_thinking) — ชั้นนี้กันทุก provider
        empty_guard_fired = False
        if not full_response.strip():
            empty_guard_fired = True
            notice = ("⚠️ โมเดลไม่ได้ให้คำตอบ (อาจใช้เวลาคิดจนหมดโควตา token) — "
                      "ลองกด Regenerate หรือเปลี่ยนโมเดลดูนะคะ")
            logger.warning(f"[Chat] empty response from provider={provider_used} — inject notice")
            yield f"data: {json.dumps({'chunk': notice}, ensure_ascii=False)}\n\n"
            full_response = notice

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

        # คำตอบที่ผิดของเทิร์นก่อน — ต้องอ่าน **ก่อน** push เทิร์นนี้ ไม่งั้นจะได้
        # คำตอบที่เพิ่ง generate (ตัวที่ *รับทราบ* การแก้ไข) แทนตัวที่ user บอกว่าผิด
        try:
            from memory.correction import last_assistant_answer
            from memory.working import working_memory
            _prev_answer = last_assistant_answer(working_memory.get_recent(session_id, n=6))
        except Exception as e:
            logger.debug(f"[Chat/teach] อ่านคำตอบก่อนหน้าไม่ได้: {e}")
            _prev_answer = ""

        push_working(session_id, "user", prompt)
        push_working(session_id, "assistant", full_response)
        # empty-guard notice ห้ามเข้า episodic memory/teach — ไม่ใช่คำตอบจริง
        # (กัน contamination แบบเดียวกับ clarify ของ active learning)
        # is_test_request: smoke test ผ่าน X-Test-Request ก็ข้ามเหมือนกัน (P2-9)
        # gate ให้ตรงกับเส้น agent (persist_agent_turn) ที่ผ่าน should_auto_learn อยู่แล้ว
        # เดิมเส้นนี้ไม่มี gate เลย → episodic เก็บข้อมูลสด/error ทุกเทิร์น
        # (วัดจริง 2026-08-02: memory_kwan 57/92 · memory_logic 47/62 เป็นข้อมูลสดเน่า)
        if not empty_guard_fired and not is_test_request:
            _rem_ok, _rem_reason = should_remember(prompt, full_response)
            if _rem_ok:
                remember(assistant, prompt, full_response)
            else:
                logger.info(f"[Chat/remember] ข้าม episodic — reason={_rem_reason}")
            teach(assistant, prompt, ai_response=full_response, prev_answer=_prev_answer)

        # preference detection แยกจากเธรด lesson — เดิมฝังอยู่ข้างในทำให้ทำงานเฉพาะ
        # ตอนคำตอบยาว >100 ตัวอักษร + ผ่าน gate ของ lesson → preferences ว่าง 0 รายการ
        # ตลอด 3 เดือน (audit 2026-08-02). ตรงนี้ไม่เรียก LLM จึงทำได้ทุกเทิร์น
        if not is_test_request:
            try:
                for _pk, _pv in detect_preferences(prompt):
                    # ต้องเช็คค่าที่คืนมา — save_preference กลืน exception แล้วคืน False
                    # (เคยพลาดตรงนี้เอง: log ว่า "บันทึกแล้ว" ทั้งที่เขียนไม่สำเร็จ
                    #  = failure ที่หน้าตาเหมือน success ซึ่งเป็นบั๊กที่ไล่แก้มาทั้งวัน)
                    if save_preference(_pk, _pv):
                        logger.info(f"[Chat/preference] บันทึก {_pk}={_pv}")
                    else:
                        logger.warning(f"[Chat/preference] เขียนไม่สำเร็จ {_pk}={_pv}")
            except Exception as e:
                logger.debug(f"[Chat/preference] skipped: {e}")

        _learn_ok, _learn_reason = should_auto_learn(prompt)
        if empty_guard_fired:
            _learn_ok, _learn_reason = False, "empty_response_notice"
        if is_test_request:
            _learn_ok, _learn_reason = False, "test_request"
        if not _learn_ok:
            logger.info(f"[Chat/auto-learn] skip lesson — reason={_learn_reason}")
        if len(full_response) > 100 and _learn_ok:
            def _learn(p=prompt, r=full_response, pv=provider_used):
                try:
                    msgs = [
                        {"role": "system", "content": "สรุปบทเรียนเป็นภาษาไทย 1-2 ประโยค ถ้าไม่มีตอบว่า SKIP"},
                        {"role": "user", "content": f"คำถาม: {p}\nคำตอบ: {r[:500]}"},
                    ]
                    raw_lesson = "".join(stream_response(msgs, provider=pv)).strip()
                    # กรองก่อนเก็บ: SKIP ที่มีคำอื่นปน / error message / คำนำของโมเดล
                    # (เดิมเช็ค `!= "SKIP"` เป๊ะๆ → "คืนนี้ฝนจะตกไหม? SKIP" หลุดเข้า prod จริง)
                    lesson = clean_lesson(raw_lesson)
                    if lesson:
                        save_lesson(p[:50], lesson)
                    else:
                        logger.info(f"[Chat/auto-learn] ทิ้งบทเรียนที่ไม่ผ่านการกรอง: {raw_lesson[:60]!r}")
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
                                 # model/provider ตัดสินใจ "ระหว่าง" stream แล้ว (ดูเหตุผลบน generate())
                                 # ไม่ใช่ก่อน response เริ่มเหมือนเดิม จึงไม่ทราบค่าจริงตอนตั้ง header —
                                 # ค่าจริงอยู่ใน SSE {"phase":"generating", model, provider} และ {"done":...}
                                 # เสมอ (ไม่มี consumer ฝั่ง frontend อ่าน header คู่นี้แล้ว — ย้ายไปอ่านจาก
                                 # SSE ใน static/enhanced.js แทน ดู commit นี้)
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
            # delete_last_assistant_message() ลบคำตอบเก่าไปแล้วก่อนเริ่ม stream —
            # ถ้าไม่ save อะไรเลยตอนนี้ turn จะไม่มีคำตอบคู่กับ user message เลย
            # (แย่กว่า chat() ปกติ เพราะที่นี่ลบของเดิมทิ้งไปแล้วด้วย)
            text = (full_response + "\n\n" if full_response.strip() else "") + f"⚠️ การตอบหยุดกลางคัน: {e}"
            try:
                save_message(assistant, "assistant", text, provider, session_id)
            except Exception as save_err:
                logger.error(f"[Regenerate] save partial response after crash failed too: {save_err}")
            return
        save_message(assistant, "assistant", full_response, provider, session_id)
        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(gen_regen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
