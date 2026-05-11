import os
import json
import logging
import threading
import base64
import asyncio
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from assistants.config import ASSISTANTS
from core.config import GEMINI_API_KEY, GEMINI_LIVE_MODEL
from utils.llm import stream_response
from utils.rag import inject_context_to_system, load_skills_relevant
from utils.history import (
    save_message, load_history, delete_last_assistant_message,
    get_last_user_message,
)
from utils.memory import save_lesson, save_preference, get_lessons, get_preferences
from memory.operations import remember, recall, teach, push_working
from utils.skills import search_skills
from utils.obsidian_sync import search_vault
from utils.home_tools import detect_home_tools, build_tool_context
from utils.tts import VOICE_MAP, DEFAULT_VOICE
from utils.tokens import count_tokens_approx

router = APIRouter(prefix="/api", tags=["chat"])
logger = logging.getLogger(__name__)


@router.post("/chat")
async def chat(request: Request):
    data = await request.json()
    assistant   = data.get("assistant", list(ASSISTANTS.keys())[0])
    session_id  = data.get("session_id", "default")
    prompt      = data.get("prompt", "")
    provider    = data.get("provider", "auto")
    image_b64   = data.get("image_b64", "")
    image_mime  = data.get("image_mime", "")
    agent_mode  = bool(data.get("agent_mode", False))
    tool_agent  = bool(data.get("tool_agent", False))
    obsidian_inject = bool(data.get("obsidian_inject", False))

    config = ASSISTANTS.get(assistant, list(ASSISTANTS.values())[0])
    base_prompt = config["system_prompt"]

    # ── ตรวจจับ Teaching signal จาก user ────────────────────────────────────
    teach(assistant, prompt)

    # ── ดึง context จากทุก tier ──────────────────────────────────────────────
    lessons    = get_lessons(prompt)
    prefs      = get_preferences()
    skills_dir = os.path.join(os.path.dirname(__file__), "..", "skills")
    skills_md  = load_skills_relevant(skills_dir, prompt)

    # New: tiered memory recall (working + episodic + long-term)
    memory_ctx = recall(assistant, prompt, session_id=session_id)

    vault_ctx = ""
    if obsidian_inject:
        vault_results = search_vault(prompt, n=3)
        if vault_results:
            vault_ctx = "\n\n".join([f"[Note: {r['title']}]\n{r['content'][:500]}" for r in vault_results])

    home_tool_ctx = ""
    home_tools_needed = detect_home_tools(prompt)
    if home_tools_needed:
        home_tool_ctx = build_tool_context(home_tools_needed)

    full_context = "\n\n".join(filter(None, [
        memory_ctx,
        search_skills(prompt, n_results=3),
        f"[Skills & Knowledge]\n{skills_md}" if skills_md else "",
        f"[บทเรียนสะสม]\n{lessons}" if lessons else "",
        f"[ความชอบ]\n{prefs}" if prefs else "",
        f"[Obsidian Vault Notes]\n{vault_ctx}" if vault_ctx else "",
        f"[ข้อมูลจากบ้านแบบ Real-time]\n{home_tool_ctx}" if home_tool_ctx else "",
    ]))

    if provider == "ollama" and len(full_context) > 2000:
        full_context = full_context[:2000]
    system_prompt = inject_context_to_system(base_prompt, full_context)

    history = load_history(assistant, session_id)
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
            try:
                for kind, payload in run_agent(messages):
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
            try:
                save_message(assistant, "assistant", full_response, "agent", session_id)
                push_working(session_id, "user", prompt)
                push_working(session_id, "assistant", full_response)
                remember(assistant, prompt, full_response)
            except Exception as e:
                logger.warning(f"[Chat/agent] persist failed: {e}")

            yield f"data: {json.dumps({'done': True, 'model': 'agent', 'provider': 'agent'}, ensure_ascii=False)}\n\n"

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
                    from utils.websearch import web_search_context
                    web_ctx = web_search_context(prompt)
                    if web_ctx:
                        # inject เป็น system instruction + user prompt
                        sys_extra = (
                            "\n\n=== INTERNET CONTEXT (real-time data) ===\n"
                            f"{web_ctx}\n"
                            "=== END INTERNET CONTEXT ===\n"
                            "**กฎเหล็ก**: ใช้ข้อมูลด้านบนตอบคำถาม ห้ามบอกว่าไม่มี internet/ไม่มีข้อมูล real-time "
                            "เพราะระบบดึงข้อมูลให้แล้ว สรุปจากข้อมูลและอ้างอิงแหล่งที่มา"
                        )
                        messages[0] = {
                            "role": "system",
                            "content": messages[0]["content"] + sys_extra,
                        }
                        provider_used = "lmstudio"
                        logger.info(f"[Chat] web search injected ({len(web_ctx)} chars)")
                    else:
                        provider_used = "lmstudio"
                except Exception as e:
                    logger.warning(f"[Chat] web search failed: {e}")
                    provider_used = "lmstudio"

        except Exception as e:
            logger.warning(f"[Chat] route failed: {e}")

    def generate():
        nonlocal provider_used, model_used, messages
        full_response = ""
        _provider = provider_used if provider_used and provider_used != "auto" else provider

        def _try_stream(prov, mdl=""):
            for ck in stream_response(messages, provider=prov, image_b64=image_b64,
                                      image_mime=image_mime, agent_mode=agent_mode,
                                      model_override=mdl):
                yield ck

        try:
            for chunk in _try_stream(_provider, model_override):
                full_response += chunk
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
        except Exception as e:
            from utils.llm import GeminiQuotaExhausted, GeminiUnavailable
            # Gemini ล้ม → fallback ไป LM Studio + web search (ถ้าเป็น internet query)
            # หรือ LM Studio chat (ถ้าไม่ใช่)
            if isinstance(e, (GeminiQuotaExhausted, GeminiUnavailable)) and _provider in ("gemini", "gemini_agent"):
                try:
                    from core.config import LMSTUDIO_CHAT_MODEL
                    from reasoning.classifier import needs_internet
                    fallback_msg = ("⚠️ Gemini quota หมด — กำลังลอง local model + web search...\n\n"
                                    if isinstance(e, GeminiQuotaExhausted)
                                    else "⚠️ Gemini ใช้ไม่ได้ — fallback เป็น local model...\n\n")
                    yield f"data: {json.dumps({'chunk': fallback_msg})}\n\n"
                    full_response += fallback_msg

                    if needs_internet(prompt):
                        try:
                            from utils.websearch import web_search_context
                            web_ctx = web_search_context(prompt)
                            if web_ctx:
                                messages[0] = {
                                    "role": "system",
                                    "content": messages[0]["content"] + (
                                        "\n\n=== INTERNET CONTEXT ===\n" + web_ctx +
                                        "\n=== END ===\n**กฎเหล็ก**: ใช้ข้อมูลข้างบนตอบ ห้ามบอกว่าไม่มี internet"
                                    )
                                }
                                logger.info(f"[Chat] Gemini fallback → web search injected ({len(web_ctx)} chars)")
                        except Exception as ws_err:
                            logger.warning(f"[Chat] fallback web search failed: {ws_err}")

                    provider_used = "lmstudio"
                    model_used = LMSTUDIO_CHAT_MODEL.split("/")[-1]
                    for chunk in _try_stream("lmstudio", LMSTUDIO_CHAT_MODEL):
                        full_response += chunk
                        yield f"data: {json.dumps({'chunk': chunk})}\n\n"
                except Exception as e2:
                    yield f"data: {json.dumps({'error': f'Fallback ล้มด้วย: {e2}'})}\n\n"
                    return
            else:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
                return

        save_message(assistant, "assistant", full_response, provider_used, session_id)

        push_working(session_id, "user", prompt)
        push_working(session_id, "assistant", full_response)
        remember(assistant, prompt, full_response)
        teach(assistant, prompt, ai_response=full_response)

        if len(full_response) > 100:
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

        yield f"data: {json.dumps({'done': True, 'model': model_used, 'provider': provider_used})}\n\n"

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
    provider   = data.get("provider", "ollama")
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
