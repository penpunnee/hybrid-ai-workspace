import os, uuid, json, threading
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from fastapi import FastAPI, Request, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from assistants.config import ASSISTANTS
from utils.llm import stream_response, OLLAMA_MODEL, GEMINI_MODEL, check_ollama_health, _last_failover
from utils.rag import inject_context_to_system, load_skills_folder
from utils.history import save_message, load_history, get_sessions, clear_session, export_history_md, search_messages, pin_message, get_pinned_messages
from utils.memory import save_memory, search_memory, is_memory_available, save_lesson, save_preference, get_lessons, get_preferences, search_long_term_memory, get_memory_stats, cleanup_old_memories
from utils.skills import get_all_skills, get_skill_count, save_skill, auto_extract_skills, _load_skills_db, _save_skills_db
from utils.obsidian_sync import sync_vault, search_vault, get_vault_stats
from utils.dream import run_dream_cycle, get_latest_report, list_reports

app = FastAPI(title="Hybrid AI Workspace")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# --- Auto Dream Scheduler ---
def _scheduled_dream():
    """รัน dream cycle อัตโนมัติ (ตี 2 ทุกคืน)"""
    provider = "gemini" if os.getenv("GEMINI_API_KEY") else "ollama"
    print(f"[Scheduler] รัน Dream Cycle อัตโนมัติ ({datetime.now().strftime('%Y-%m-%d %H:%M')}) provider={provider}")
    try:
        run_dream_cycle(provider=provider)
        print("[Scheduler] Dream Cycle เสร็จ")
    except Exception as e:
        print(f"[Scheduler] Dream error: {e}")

_scheduler = BackgroundScheduler(timezone="Asia/Bangkok")
_scheduler.add_job(_scheduled_dream, CronTrigger(hour=2, minute=0), id="dream_nightly", replace_existing=True)
_scheduler.start()
print("[Scheduler] ตั้ง Dream รันทุกคืนตี 2 แล้ว")
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
if os.path.exists("static/assets"):
    app.mount("/assets", StaticFiles(directory="static/assets"), name="assets")


@app.get("/", response_class=HTMLResponse)
async def root():
    with open("static/index.html", encoding="utf-8") as f:
        return f.read()


@app.get("/api/config")
def get_config():
    return {
        "assistants": [
            {
                "name": name,
                "slug": cfg["slug"],
                "templates": cfg.get("prompt_templates", []),
            }
            for name, cfg in ASSISTANTS.items()
        ],
        "ollama_model": OLLAMA_MODEL,
        "gemini_model": GEMINI_MODEL,
    }


@app.get("/api/status")
def status():
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as ex:
        f1 = ex.submit(lambda: check_ollama_health()[0])
        f2 = ex.submit(is_memory_available)
        try: ollama_ok = f1.result(timeout=5)
        except Exception: ollama_ok = False
        try: mem_ok = f2.result(timeout=5)
        except Exception: mem_ok = False
    next_dream = None
    job = _scheduler.get_job("dream_nightly")
    if job and job.next_run_time:
        next_dream = job.next_run_time.strftime("%Y-%m-%d %H:%M")
    return {
        "ollama": ollama_ok,
        "gemini": bool(os.getenv("GEMINI_API_KEY", "")),
        "memory": mem_ok,
        "skills": get_skill_count(),
        "failover_active": _last_failover.get("active", False),
        "next_dream_schedule": next_dream,
    }


@app.get("/api/search")
def search_chat(q: str = "", assistant: str = "", limit: int = 20):
    if not q or len(q) < 2:
        return {"results": [], "query": q}
    results = search_messages(query=q, assistant=assistant, limit=limit)
    return {"results": results, "query": q, "count": len(results)}


@app.get("/api/sessions/{assistant}")
def list_sessions(assistant: str):
    return get_sessions(assistant)


@app.post("/api/sessions/{assistant}")
def new_session(assistant: str):
    sid = f"s_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    return {"session_id": sid}


@app.delete("/api/sessions/{assistant}/{session_id}")
def delete_session(assistant: str, session_id: str):
    clear_session(assistant, session_id)
    return {"ok": True}


@app.get("/api/history/{assistant}/{session_id}")
def get_history(assistant: str, session_id: str):
    return load_history(assistant, session_id, include_meta=True)


@app.post("/api/pin/{db_id}")
async def toggle_pin(db_id: int, request: Request):
    data = await request.json()
    pinned = data.get("pinned", True)
    pin_message(db_id, pinned)
    return {"ok": True, "db_id": db_id, "pinned": pinned}


@app.get("/api/pinned/{assistant}/{session_id}")
def list_pinned(assistant: str, session_id: str):
    return get_pinned_messages(assistant, session_id)


@app.get("/api/export/{assistant}/{session_id}")
def export_session(assistant: str, session_id: str):
    md = export_history_md(assistant, session_id)
    return {"markdown": md}


@app.post("/api/tts")
async def text_to_speech(request: Request):
    """TTS โดย Gemini Native Audio — คืนค่า WAV bytes"""
    from utils.tts import generate_tts
    data = await request.json()
    text = data.get("text", "").strip()
    slug = data.get("assistant_slug", "")
    if not text:
        return {"error": "no text"}
    try:
        wav = generate_tts(text, slug)
        return Response(content=wav, media_type="audio/wav",
                        headers={"Cache-Control": "no-cache"})
    except Exception as e:
        return {"error": str(e)}


@app.websocket("/ws/voice/{assistant_slug}")
async def voice_websocket(websocket: WebSocket, assistant_slug: str):
    """Live Voice Chat ผ่าน Gemini Live API"""
    import asyncio, base64
    await websocket.accept()

    gemini_key = os.getenv("GEMINI_API_KEY", "")
    if not gemini_key:
        await websocket.send_json({"type": "error", "message": "GEMINI_API_KEY not set"})
        return

    from utils.voice import GEMINI_LIVE_MODEL, VOICE_MAP, DEFAULT_VOICE
    from google import genai
    from google.genai import types

    voice = VOICE_MAP.get(assistant_slug.lower(), DEFAULT_VOICE)
    asst  = next((v for v in ASSISTANTS.values() if v.get("slug") == assistant_slug), {})
    sys_prompt = asst.get("system_prompt", "คุณเป็น AI ผู้ช่วยที่เป็นมิตร ตอบภาษาไทยกระชับ")

    client = genai.Client(api_key=gemini_key, http_options={"api_version": "v1beta"})
    live_config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
            )
        ),
        system_instruction=types.Content(parts=[types.Part(text=sys_prompt)]),
    )

    try:
        async with client.aio.live.connect(model=GEMINI_LIVE_MODEL, config=live_config) as session:
            await websocket.send_json({"type": "connected", "voice": voice})
            stop = asyncio.Event()

            async def recv_loop():
                try:
                    while not stop.is_set():
                        try:
                            msg = await asyncio.wait_for(websocket.receive_json(), timeout=60.0)
                        except asyncio.TimeoutError:
                            continue
                        t = msg.get("type", "")
                        if t == "audio":
                            pcm = base64.b64decode(msg["data"])
                            await session.send(input=types.LiveClientRealtimeInput(
                                media_chunks=[types.Blob(data=pcm, mime_type="audio/pcm;rate=16000")]
                            ))
                        elif t == "end_turn":
                            await session.send(input=".", end_of_turn=True)
                        elif t == "text":
                            await session.send(input=msg.get("text", ""), end_of_turn=True)
                        elif t == "close":
                            stop.set()
                except (WebSocketDisconnect, Exception):
                    stop.set()

            async def send_loop():
                try:
                    async for response in session.receive():
                        if stop.is_set():
                            break
                        if response.data:
                            await websocket.send_json({
                                "type": "audio",
                                "data": base64.b64encode(response.data).decode()
                            })
                        sc = getattr(response, "server_content", None)
                        if sc:
                            if getattr(sc, "turn_complete", False):
                                await websocket.send_json({"type": "done"})
                            mt = getattr(sc, "model_turn", None)
                            if mt:
                                for part in getattr(mt, "parts", []):
                                    if getattr(part, "text", None):
                                        await websocket.send_json({"type": "text", "text": part.text})
                except Exception as e:
                    stop.set()
                    try:
                        await websocket.send_json({"type": "error", "message": str(e)})
                    except Exception:
                        pass

            await asyncio.gather(recv_loop(), send_loop())
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass


@app.get("/api/vault/stats")
def vault_stats():
    return get_vault_stats()


@app.post("/api/dream")
async def dream(request: Request):
    try:
        data = await request.json()
    except Exception:
        data = {}
    provider = data.get("provider", "ollama") if isinstance(data, dict) else "ollama"
    hours = data.get("hours", 24) if isinstance(data, dict) else 24
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=1) as ex:
        try:
            result = ex.submit(run_dream_cycle, provider, hours).result(timeout=120)
        except Exception as e:
            return {"ok": False, "error": str(e)}
    return {"ok": True, "report": result}


@app.get("/api/dream/report")
def dream_report():
    return get_latest_report()


@app.get("/api/dream/history")
def dream_history(limit: int = 10):
    return {"reports": list_reports(limit)}


@app.post("/api/vault/sync")
async def vault_sync(request: Request):
    data = await request.json()
    vault_path = data.get("vault_path", "")
    result = sync_vault(vault_path)
    return result


@app.get("/api/vault/search")
def vault_search(q: str, n: int = 5):
    results = search_vault(q, n)
    return {"results": results}


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    import base64 as _b64
    content = await file.read()
    name = file.filename or "file"
    mime = file.content_type or ""
    # ตรวจว่าเป็นรูปภาพ
    if mime.startswith("image/") or name.lower().split('.')[-1] in ('jpg','jpeg','png','gif','webp','bmp'):
        b64 = _b64.b64encode(content).decode()
        return {"ok": True, "filename": name, "is_image": True, "b64": b64, "mime": mime or "image/jpeg"}
    try:
        if name.lower().endswith(".json"):
            import json as _json
            data = _json.loads(content)
            text = f"[ไฟล์ JSON: {name}]\n{_json.dumps(data, ensure_ascii=False, indent=2)}"
        else:
            text = f"[ไฟล์: {name}]\n{content.decode('utf-8', errors='ignore')}"
    except Exception as e:
        return {"ok": False, "error": str(e)}
    raw_text = content.decode('utf-8', errors='ignore')
    extracted = auto_extract_skills(raw_text, name)
    return {"ok": True, "filename": name, "is_image": False, "text": text[:8000], "skills_extracted": extracted}


@app.get("/api/stats")
def usage_stats():
    """Dashboard stats: messages, sessions, memory"""
    import sqlite3
    from datetime import date
    db_path = os.path.join(os.path.dirname(__file__), "chat_history.db")
    result = {"total_messages": 0, "today_messages": 0, "total_sessions": 0,
              "by_assistant": {}, "sessions_by_assistant": {}, "memory": {}}
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM messages")
        result["total_messages"] = cur.fetchone()[0]
        today = date.today().isoformat()
        cur.execute("SELECT COUNT(*) FROM messages WHERE created_at >= ?", (today,))
        result["today_messages"] = cur.fetchone()[0]
        cur.execute("SELECT COUNT(DISTINCT session_id) FROM messages")
        result["total_sessions"] = cur.fetchone()[0]
        cur.execute("SELECT assistant, COUNT(*) FROM messages GROUP BY assistant")
        result["by_assistant"] = {r[0]: r[1] for r in cur.fetchall()}
        cur.execute("SELECT assistant, COUNT(DISTINCT session_id) FROM messages GROUP BY assistant")
        result["sessions_by_assistant"] = {r[0]: r[1] for r in cur.fetchall()}
        conn.close()
    result["memory"] = get_memory_stats()
    return result


@app.get("/api/skills")
def list_skills():
    db = _load_skills_db()
    return {"skills": db, "count": len(db)}


@app.delete("/api/skills/{topic}")
def delete_skill(topic: str):
    from urllib.parse import unquote
    topic = unquote(topic)
    db = _load_skills_db()
    if topic in db:
        del db[topic]
        _save_skills_db(db)
        return {"ok": True, "deleted": topic}
    return {"ok": False, "error": "ไม่พบ topic นี้"}


@app.get("/api/memory/stats")
def memory_stats():
    return get_memory_stats()


@app.post("/api/memory/cleanup")
async def memory_cleanup(request: Request):
    try:
        data = await request.json()
    except Exception:
        data = {}
    days = data.get("days", 30) if isinstance(data, dict) else 30
    return cleanup_old_memories(days=days)


@app.post("/api/memory/{assistant}")
async def save_mem(assistant: str, request: Request):
    data = await request.json()
    text = data.get("text", "")
    save_memory(assistant, "remember", f"ข้อมูลที่บันทึก: {text}")
    save_lesson("ข้อมูลจากพี่ปอย", text)
    return {"ok": True, "saved": text}


@app.post("/api/chat")
async def chat(request: Request):
    data = await request.json()
    assistant = data.get("assistant", list(ASSISTANTS.keys())[0])
    session_id = data.get("session_id", "default")
    prompt = data.get("prompt", "")
    provider = data.get("provider", "ollama")
    image_b64 = data.get("image_b64", "")
    image_mime = data.get("image_mime", "")

    config = ASSISTANTS.get(assistant, list(ASSISTANTS.values())[0])
    base_prompt = config["system_prompt"]

    lessons = get_lessons(prompt)
    prefs = get_preferences()
    long_term = search_long_term_memory(prompt)
    skills_folder_path = os.path.join(os.path.dirname(__file__), "skills")
    skills_md = load_skills_folder(skills_folder_path)
    full_context = "\n\n".join(filter(None, [
        search_memory(assistant, prompt),
        long_term,
        get_all_skills(),
        f"[Skills & Knowledge]\n{skills_md}" if skills_md else "",
        f"[บทเรียนสะสม]\n{lessons}" if lessons else "",
        f"[ความชอบ]\n{prefs}" if prefs else "",
    ]))
    system_prompt = inject_context_to_system(base_prompt, full_context)

    history = load_history(assistant, session_id)
    save_message(assistant, "user", prompt, provider, session_id)

    messages = [{"role": "system", "content": system_prompt}]
    messages += [{"role": m["role"], "content": m["content"]} for m in history]
    messages.append({"role": "user", "content": prompt})

    def generate():
        full_response = ""
        try:
            for chunk in stream_response(messages, provider=provider, image_b64=image_b64, image_mime=image_mime):
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
                except Exception:
                    pass
            threading.Thread(target=_learn, daemon=True).start()

        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


if __name__ == "__main__":
    import uvicorn
    print("🚀 Hybrid AI Workspace  →  http://localhost:8000")
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
