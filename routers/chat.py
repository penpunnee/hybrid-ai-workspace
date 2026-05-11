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
from utils.memory import (
    save_memory, search_memory, save_lesson, save_preference,
    get_lessons, get_preferences, search_long_term_memory,
)
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
    provider    = data.get("provider", "ollama")
    image_b64   = data.get("image_b64", "")
    image_mime  = data.get("image_mime", "")
    agent_mode  = bool(data.get("agent_mode", False))
    obsidian_inject = bool(data.get("obsidian_inject", False))

    config = ASSISTANTS.get(assistant, list(ASSISTANTS.values())[0])
    base_prompt = config["system_prompt"]

    lessons    = get_lessons(prompt)
    prefs      = get_preferences()
    long_term  = search_long_term_memory(prompt)
    skills_dir = os.path.join(os.path.dirname(__file__), "..", "skills")
    skills_md  = load_skills_relevant(skills_dir, prompt)

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
        search_memory(assistant, prompt),
        long_term,
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

    def generate():
        full_response = ""
        try:
            for chunk in stream_response(messages, provider=provider, image_b64=image_b64,
                                         image_mime=image_mime, agent_mode=agent_mode):
                full_response += chunk
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            return

        save_message(assistant, "assistant", full_response, provider, session_id)
        save_memory(assistant, prompt, full_response)

        if len(full_response) > 100:
            def _learn(p=prompt, r=full_response, pv=provider):
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

        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


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
