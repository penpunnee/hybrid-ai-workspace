import os, uuid, json, threading, logging
from contextlib import asynccontextmanager
from datetime import datetime
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from fastapi import FastAPI, Request, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from assistants.config import ASSISTANTS
from utils.llm import stream_response, OLLAMA_MODEL, GEMINI_MODEL, check_ollama_health, _last_failover
from utils.rag import inject_context_to_system, load_skills_folder
from utils.history import (save_message, load_history, get_sessions, clear_session, export_history_md,
    search_messages, pin_message, get_pinned_messages,
    delete_last_assistant_message, truncate_from_db_id, get_last_user_message, rename_session)
from utils.memory import (save_memory, search_memory, is_memory_available, save_lesson, save_preference,
    get_lessons, get_preferences, search_long_term_memory, get_memory_stats, cleanup_old_memories,
    list_lessons, list_preferences, delete_lesson, delete_preference)
from utils.skills import get_all_skills, get_skill_count, save_skill, auto_extract_skills, _load_skills_db, _save_skills_db, search_skills
from utils.obsidian_sync import sync_vault, search_vault, get_vault_stats
from utils.dream import run_dream_cycle, get_latest_report, list_reports
from utils.tts import generate_tts, VOICE_MAP, DEFAULT_VOICE
from utils.tokens import count_tokens_approx
from google import genai
from google.genai import types

GEMINI_LIVE_MODEL = os.getenv("GEMINI_LIVE_MODEL", "gemini-2.0-flash-exp")

# --- Auth config ---
UI_PASSWORD = os.getenv("UI_PASSWORD", "")
_OPEN_PATHS = {"/", "/api/config", "/api/status", "/api/auth/check", "/api/auth/login"}
_OPEN_PREFIXES = ("/static", "/assets", "/shared", "/ws")

def _is_local_request(request: Request) -> bool:
    """ตรวจว่า request มาจาก LAN โดยตรง (ไม่ผ่าน Cloudflare)
    Docker NAT ทำให้ client.host = 172.x เสมอ → ใช้ Host header แทน
    LAN:        Host = 192.168.x.x:8080  (IP ตรง)
    Cloudflare: Host = ai.pawinhome.com  + มี CF-Connecting-IP header
    """
    if request.headers.get("cf-connecting-ip"):
        return False
    host = request.headers.get("host", "")
    return (
        host.startswith("192.168.") or
        host.startswith("10.") or
        host.startswith("127.") or
        host.startswith("localhost")
    )

# --- Skills sync on startup ---
def _startup_sync_skills():
    try:
        from utils.skills_search import sync_skills_to_search
        db = _load_skills_db()
        if db:
            sync_skills_to_search(db)
            logger.info(f"[Startup] Synced {len(db)} skills to ChromaDB")
    except Exception as e:
        logger.warning(f"[Startup] Skills sync skipped: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    threading.Thread(target=_startup_sync_skills, daemon=True).start()
    yield

# --- CORS from env ---
_cors_raw = os.getenv("CORS_ORIGINS", "")
_cors_origins = [o.strip() for o in _cors_raw.split(",") if o.strip()] or [
    "http://localhost:8000",
    "http://localhost:5173",
    f"http://192.168.51.49:8080",
]

app = FastAPI(title="Hybrid AI Workspace", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Auth middleware ---
# GET/HEAD/OPTIONS → ผ่านเสมอ (React โหลดได้, ไม่ใช้เงิน)
# POST/PATCH/DELETE → ต้อง token (chat, dream, tts ที่ใช้เงิน)
_WRITE_METHODS = {"POST", "PATCH", "DELETE", "PUT"}

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if not UI_PASSWORD:
        return await call_next(request)
    if request.method not in _WRITE_METHODS:
        return await call_next(request)
    path = request.url.path
    if path in _OPEN_PATHS or any(path.startswith(p) for p in _OPEN_PREFIXES):
        return await call_next(request)
    if _is_local_request(request):
        return await call_next(request)
    token = request.headers.get("x-auth-token", "")
    if token == UI_PASSWORD:
        return await call_next(request)
    return JSONResponse({"error": "Unauthorized"}, status_code=401)

_share_store: dict = {}  # fallback in-memory (also persisted to SQLite)
_SHARE_STORE_LIMIT = 500

def _share_store_set(token: str, data: dict):
    """เพิ่ม share link พร้อม evict เก่าสุดถ้าเกิน limit"""
    if len(_share_store) >= _SHARE_STORE_LIMIT:
        oldest = next(iter(_share_store))
        del _share_store[oldest]
        logger.debug(f"share_store evicted oldest entry (limit={_SHARE_STORE_LIMIT})")
    _share_store[token] = data

# --- Auto Dream Scheduler ---
def _scheduled_dream():
    """รัน dream cycle อัตโนมัติ (ตี 2 ทุกคืน) — fallback ไป gemini ถ้า ollama offline"""
    from utils.notify import send_line_notify
    provider = "gemini" if os.getenv("GEMINI_API_KEY") else "ollama"
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    logger.info(f"[Scheduler] รัน Dream Cycle ({ts}) provider={provider}")
    try:
        run_dream_cycle(provider=provider)
        logger.info("[Scheduler] Dream Cycle เสร็จ")
    except Exception as e:
        logger.error(f"[Scheduler] Dream error: {e}")
        send_line_notify(f"⚠️ Dream Cycle ล้มเหลว ({ts})\nError: {e}")

_scheduler = BackgroundScheduler(timezone="Asia/Bangkok")
_scheduler.add_job(_scheduled_dream, CronTrigger(hour=2, minute=0), id="dream_nightly", replace_existing=True)
_scheduler.start()
logger.info("[Scheduler] ตั้ง Dream รันทุกคืนตี 2 แล้ว")


@app.get("/api/auth/check")
def auth_check(request: Request):
    if not UI_PASSWORD:
        return {"required": False, "ok": True}
    if _is_local_request(request):
        return {"required": True, "ok": True, "bypass": "local_ip"}
    token = request.headers.get("x-auth-token", "")
    return {"required": True, "ok": token == UI_PASSWORD}


@app.post("/api/auth/login")
async def auth_login(request: Request):
    data = await request.json()
    pwd = data.get("password", "")
    if not UI_PASSWORD or pwd == UI_PASSWORD:
        return {"ok": True, "token": UI_PASSWORD}
    return JSONResponse({"ok": False, "error": "รหัสผ่านไม่ถูกต้อง"}, status_code=401)


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
        f1 = ex.submit(check_ollama_health)
        f2 = ex.submit(is_memory_available)
        try:
            ollama_ok, ollama_msg = f1.result(timeout=5)
        except Exception as e:
            ollama_ok, ollama_msg = False, "Health check error"
            logger.warning(f"Ollama health check failed: {e}")
        try:
            mem_ok = f2.result(timeout=5)
        except Exception as e:
            mem_ok = False
            logger.warning(f"Memory check failed: {e}")
    next_dream = None
    job = _scheduler.get_job("dream_nightly")
    if job and job.next_run_time:
        next_dream = job.next_run_time.strftime("%Y-%m-%d %H:%M")
    return {
        "ollama": ollama_ok,
        "ollama_message": ollama_msg,
        "gemini": bool(os.getenv("GEMINI_API_KEY", "")),
        "memory": mem_ok,
        "skills": get_skill_count(),
        "failover_active": _last_failover.get("active", False),
        "next_dream_schedule": next_dream,
    }


@app.get("/api/health")
def health_detail():
    import shutil
    from utils.memory import get_memory_stats

    # --- Disk ---
    try:
        data_path = os.getenv("NAS_DATA_PATH", "./data")
        usage = shutil.disk_usage(data_path if os.path.exists(data_path) else ".")
        disk = {
            "total_gb": round(usage.total / 1e9, 1),
            "used_gb": round(usage.used / 1e9, 1),
            "free_gb": round(usage.free / 1e9, 1),
            "used_pct": round(usage.used / usage.total * 100, 1),
        }
    except Exception as e:
        disk = {"error": str(e)}

    # --- RAM (อ่านจาก /proc/meminfo บน Linux/Docker) ---
    try:
        mem = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                mem[k.strip()] = int(v.strip().split()[0])  # kB
        total_mb = mem["MemTotal"] // 1024
        avail_mb = mem["MemAvailable"] // 1024
        used_mb = total_mb - avail_mb
        ram = {
            "total_mb": total_mb,
            "used_mb": used_mb,
            "free_mb": avail_mb,
            "used_pct": round(used_mb / total_mb * 100, 1),
        }
    except Exception as e:
        ram = {"error": str(e)}

    # --- Last Dream ---
    try:
        report = get_latest_report()
        last_dream = {
            "started_at": report.get("started_at", ""),
            "provider": report.get("provider", ""),
            "memories_processed": report.get("memories_processed", 0),
            "promoted": len(report.get("phase3_deep", {}).get("promoted", [])),
        } if "error" not in report else {"error": report["error"]}
    except Exception as e:
        last_dream = {"error": str(e)}

    next_dream = None
    job = _scheduler.get_job("dream_nightly")
    if job and job.next_run_time:
        next_dream = job.next_run_time.strftime("%Y-%m-%d %H:%M")

    # --- ChromaDB ---
    try:
        chroma = get_memory_stats()
    except Exception as e:
        chroma = {"available": False, "error": str(e)}

    # --- Skills & DB size ---
    try:
        db_path = os.getenv("DB_PATH", "./chat_history.db")
        db_size_mb = round(os.path.getsize(db_path) / 1e6, 2) if os.path.exists(db_path) else 0
    except Exception as e:
        db_size_mb = 0
        logger.warning(f"DB size check failed: {e}")

    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "disk": disk,
        "ram": ram,
        "dream": {
            "last": last_dream,
            "next_scheduled": next_dream,
        },
        "chromadb": chroma,
        "skills_count": get_skill_count(),
        "db_size_mb": db_size_mb,
    }


@app.get("/api/search")
def search_chat(q: str = "", assistant: str = "", limit: int = 20):
    if not q or len(q) < 2:
        return {"results": [], "query": q}
    results = search_messages(query=q, assistant=assistant, limit=limit)
    return {"results": results, "query": q, "count": len(results)}


@app.get("/api/sessions/{assistant}")
def list_sessions(assistant: str, q: str = ""):
    sessions = get_sessions(assistant)
    if q.strip():
        q_lower = q.strip().lower()
        sessions = [s for s in sessions if q_lower in s.get("first_msg", "").lower()]
    return sessions


@app.post("/api/sessions/{assistant}")
def new_session(assistant: str):
    sid = f"s_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    return {"session_id": sid}


@app.patch("/api/sessions/{assistant}/{session_id}")
async def patch_session(assistant: str, session_id: str, request: Request):
    data = await request.json()
    name = data.get("name", "").strip()
    if not name:
        return {"ok": False, "error": "ชื่อว่างไม่ได้"}
    rename_session(assistant, session_id, name)
    return {"ok": True, "session_id": session_id, "name": name}


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


@app.post("/api/tts/stream")
async def text_to_speech_stream(request: Request):
    """TTS แบบ streaming — แบ่งเป็น sentence แล้ว stream WAV chunks ทีละประโยค
    Response: SSE events  data: {"chunk": "<base64 wav>", "done": false}
              สุดท้าย    data: {"done": true}
    """
    import re, base64
    data = await request.json()
    text = data.get("text", "").strip()
    slug = data.get("assistant_slug", "")
    if not text:
        return {"error": "no text"}

    # ตัดเป็น sentences (จบด้วย .!?… หรือ newline)
    sentences = [s.strip() for s in re.split(r"(?<=[.!?…\n])\s+", text) if s.strip()]
    if not sentences:
        sentences = [text]

    async def event_gen():
        for sentence in sentences:
            if not sentence:
                continue
            try:
                wav = generate_tts(sentence, slug)
                b64 = base64.b64encode(wav).decode()
                yield f"data: {json.dumps({'chunk': b64, 'done': False})}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e), 'done': False})}\n\n"
        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.websocket("/ws/voice/{assistant_slug}")
async def voice_websocket(websocket: WebSocket, assistant_slug: str, session_id: str = "voice_default"):
    """Live Voice Chat ผ่าน Gemini Live API"""
    import asyncio, base64
    await websocket.accept()

    gemini_key = os.getenv("GEMINI_API_KEY", "")
    if not gemini_key:
        await websocket.send_json({"type": "error", "message": "GEMINI_API_KEY not set"})
        return

    voice = VOICE_MAP.get(assistant_slug.lower(), DEFAULT_VOICE)
    asst_name, asst = next(((k, v) for k, v in ASSISTANTS.items() if v.get("slug") == assistant_slug), ("", {}))
    if not asst_name:
        asst_name = assistant_slug
    sys_prompt = asst.get("system_prompt", "คุณเป็น AI ผู้ช่วยที่เป็นมิตร ตอบภาษาไทยกระชับ")

    client = genai.Client(api_key=gemini_key, http_options={"api_version": "v1alpha"})
    live_config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
            )
        ),
        system_instruction=types.Content(parts=[types.Part(text=sys_prompt)]),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        input_audio_transcription=types.AudioTranscriptionConfig(),
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
                user_transcript = ""
                ai_transcript = ""
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
                            it = getattr(sc, "input_transcription", None)
                            if it and getattr(it, "text", None):
                                user_transcript += it.text
                                await websocket.send_json({"type": "user_text", "text": it.text})
                            ot = getattr(sc, "output_transcription", None)
                            if ot and getattr(ot, "text", None):
                                ai_transcript += ot.text
                            mt = getattr(sc, "model_turn", None)
                            if mt:
                                for part in getattr(mt, "parts", []):
                                    if getattr(part, "text", None):
                                        ai_transcript += part.text
                                        await websocket.send_json({"type": "text", "text": part.text})
                            if getattr(sc, "turn_complete", False):
                                await websocket.send_json({"type": "done"})
                                if user_transcript.strip():
                                    save_message(asst_name, "user", user_transcript.strip(), "gemini_live", session_id)
                                    user_transcript = ""
                                if ai_transcript.strip():
                                    save_message(asst_name, "assistant", ai_transcript.strip(), "gemini_live", session_id)
                                    ai_transcript = ""
                except Exception as e:
                    logger.error(f"[Voice send_loop] {type(e).__name__}: {e}")
                    stop.set()
                    try:
                        await websocket.send_json({"type": "error", "message": str(e)})
                    except Exception as ws_err:
                        logger.debug(f"WS send error ignored: {ws_err}")

            await asyncio.gather(recv_loop(), send_loop())
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"[Voice WS] {type(e).__name__}: {e}")
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception as ws_err:
            logger.debug(f"WS send error ignored: {ws_err}")


@app.get("/api/vault/stats")
def vault_stats():
    return get_vault_stats()


@app.post("/api/dream")
async def dream(request: Request):
    try:
        data = await request.json()
    except Exception as e:
        logger.debug(f"Dream request body parse failed: {e}")
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
    import base64 as _b64, io
    content = await file.read()
    name = file.filename or "file"
    mime = file.content_type or ""
    ext = name.lower().rsplit(".", 1)[-1] if "." in name else ""

    # รูปภาพ
    if mime.startswith("image/") or ext in ('jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp'):
        b64 = _b64.b64encode(content).decode()
        return {"ok": True, "filename": name, "is_image": True, "b64": b64, "mime": mime or "image/jpeg"}

    # PDF
    if ext == "pdf" or mime == "application/pdf":
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(content))
            pages_text = [page.extract_text() or "" for page in reader.pages]
            raw_text = "\n\n".join(pages_text)
            text = f"[PDF: {name} — {len(reader.pages)} หน้า]\n{raw_text}"
        except ImportError:
            return {"ok": False, "error": "ไม่พบ library pypdf — กรุณา pip install pypdf"}
        except Exception as e:
            return {"ok": False, "error": f"อ่าน PDF ไม่ได้: {e}"}
        extracted = auto_extract_skills(raw_text, name)
        return {"ok": True, "filename": name, "is_image": False, "text": text[:8000], "skills_extracted": extracted}

    # DOCX
    if ext == "docx" or mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        try:
            import docx
            doc = docx.Document(io.BytesIO(content))
            raw_text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            text = f"[DOCX: {name}]\n{raw_text}"
        except ImportError:
            return {"ok": False, "error": "ไม่พบ library python-docx — กรุณา pip install python-docx"}
        except Exception as e:
            return {"ok": False, "error": f"อ่าน DOCX ไม่ได้: {e}"}
        extracted = auto_extract_skills(raw_text, name)
        return {"ok": True, "filename": name, "is_image": False, "text": text[:8000], "skills_extracted": extracted}

    # JSON / text-based files
    try:
        if ext == "json":
            import json as _json
            data = _json.loads(content)
            raw_text = _json.dumps(data, ensure_ascii=False, indent=2)
            text = f"[ไฟล์ JSON: {name}]\n{raw_text}"
        else:
            raw_text = content.decode('utf-8', errors='ignore')
            text = f"[ไฟล์: {name}]\n{raw_text}"
    except Exception as e:
        return {"ok": False, "error": str(e)}
    extracted = auto_extract_skills(raw_text, name)
    return {"ok": True, "filename": name, "is_image": False, "text": text[:8000], "skills_extracted": extracted}


@app.post("/api/skills/extract")
async def skills_extract(request: Request):
    """ให้ Gemini สกัดและจัดระเบียบ content เป็น skill .md แล้วบันทึกลง skills/ folder"""
    data = await request.json()
    content = data.get("content", "").strip()
    topic = data.get("topic", "").strip()
    if not content:
        return {"ok": False, "error": "ไม่มี content"}

    if not topic:
        topic = f"skill-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    safe_topic = "".join(c if c.isalnum() or c in "-_" else "-" for c in topic.lower()).strip("-")
    filename = f"{safe_topic}.md"
    skills_dir = os.path.join(os.path.dirname(__file__), "skills")
    os.makedirs(skills_dir, exist_ok=True)
    filepath = os.path.join(skills_dir, filename)

    msgs = [
        {"role": "system", "content": (
            "คุณคือ Technical Writer ที่เชี่ยวชาญ\n"
            "งาน: อ่าน content ด้านล่าง แล้วสกัดออกมาเป็น Skill Reference .md ที่ดี\n"
            "รูปแบบที่ต้องการ:\n"
            "- ใช้ # สำหรับชื่อหัวข้อหลัก\n"
            "- ใช้ ## สำหรับแต่ละ subtopic\n"
            "- ใส่ code block ``` ทุกครั้งที่มี code\n"
            "- สรุปกระชับ อ่านง่าย เป็น quick reference\n"
            "- ตอบเป็น markdown ล้วนๆ ไม่ต้องมีคำอธิบายเพิ่ม\n"
            f"- ชื่อหัวข้อหลัก: {topic}"
        )},
        {"role": "user", "content": content[:6000]},
    ]
    try:
        md_content = "".join(stream_response(msgs, provider="gemini"))
    except Exception as e:
        return {"ok": False, "error": f"Gemini error: {e}"}

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(md_content)
    except Exception as e:
        return {"ok": False, "error": f"บันทึกไฟล์ไม่ได้: {e}"}

    return {"ok": True, "filename": filename, "path": filepath, "preview": md_content[:500]}


@app.get("/api/skills/list")
def skills_list():
    """รายชื่อไฟล์ .md ทั้งหมดใน skills/ folder"""
    skills_dir = os.path.join(os.path.dirname(__file__), "skills")
    if not os.path.isdir(skills_dir):
        return {"files": []}
    files = []
    for f in sorted(os.listdir(skills_dir)):
        fp = os.path.join(skills_dir, f)
        if os.path.isfile(fp) and f.endswith(".md"):
            files.append({"name": f, "size": os.path.getsize(fp)})
    return {"files": files}


# BUG FIX: รวม route ซ้ำ DELETE /api/skills/{id} เข้าเป็น route เดียว
# ลบทั้งไฟล์ .md ใน skills/ folder และลบออกจาก skills_db.json ในครั้งเดียว
@app.delete("/api/skills/{skill_id}")
def skills_delete(skill_id: str):
    """ลบ skill — รองรับทั้ง filename (.md) และ topic name จาก skills_db.json"""
    from urllib.parse import unquote
    skill_id = unquote(skill_id)

    deleted_file = False
    deleted_db = False

    # 1) ลบไฟล์ .md จาก skills/ folder (ถ้าชื่อลงท้าย .md หรือมีไฟล์ตรงกัน)
    skills_dir = os.path.join(os.path.dirname(__file__), "skills")
    if ".." not in skill_id and "/" not in skill_id:
        # ลองหาทั้ง exact match และ .md version
        candidates = [skill_id, f"{skill_id}.md"]
        for fname in candidates:
            fp = os.path.join(skills_dir, fname)
            if os.path.exists(fp):
                os.remove(fp)
                deleted_file = True
                break

    # 2) ลบออกจาก skills_db.json (ถ้ามี topic ตรงกัน)
    db = _load_skills_db()
    if skill_id in db:
        del db[skill_id]
        _save_skills_db(db)
        deleted_db = True
    # ลองลบ topic ที่ไม่มี .md extension ด้วย
    topic_no_ext = skill_id.replace(".md", "")
    if topic_no_ext in db:
        del db[topic_no_ext]
        _save_skills_db(db)
        deleted_db = True

    if deleted_file or deleted_db:
        return {"ok": True, "deleted_file": deleted_file, "deleted_db": deleted_db}
    return {"ok": False, "error": "ไม่พบ skill นี้"}


@app.post("/api/admin/sync-skills")
def sync_skills_to_search_endpoint():
    """Sync skills จาก skills_db.json ไป ChromaDB search index"""
    try:
        from utils.skills_search import sync_skills_to_search
        db = _load_skills_db()
        if not db:
            return {"ok": False, "error": "No skills found in skills_db.json"}
        sync_skills_to_search(db)
        return {"ok": True, "synced": len(db), "message": f"Synced {len(db)} skills to ChromaDB"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


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


@app.get("/api/memory/stats")
def memory_stats():
    return get_memory_stats()


@app.get("/api/memory/lessons")
def api_list_lessons():
    return {"ok": True, "lessons": list_lessons(50)}


@app.get("/api/memory/preferences")
def api_list_preferences():
    return {"ok": True, "preferences": list_preferences()}


@app.delete("/api/memory/lessons/{doc_id}")
def api_delete_lesson(doc_id: str):
    ok = delete_lesson(doc_id)
    return {"ok": ok}


@app.delete("/api/memory/preferences/{doc_id}")
def api_delete_preference(doc_id: str):
    ok = delete_preference(doc_id)
    return {"ok": ok}


@app.post("/api/memory/cleanup")
async def memory_cleanup(request: Request):
    try:
        data = await request.json()
    except Exception as e:
        logger.debug(f"Memory cleanup request body parse failed: {e}")
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


@app.get("/api/digest")
def daily_digest():
    """Daily digest: สรุปแชทเมื่อวานด้วย Gemini"""
    import sqlite3 as _sql
    from datetime import date, timedelta
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    today = date.today().isoformat()
    db_path = os.path.join(os.path.dirname(__file__), "chat_history.db")
    if not os.path.exists(db_path):
        return {"ok": False, "message": "ยังไม่มีข้อมูล"}
    conn = _sql.connect(db_path)
    rows = conn.execute(
        "SELECT assistant, role, content FROM messages WHERE created_at >= ? AND created_at < ? ORDER BY id ASC LIMIT 80",
        (yesterday, today)
    ).fetchall()
    conn.close()
    if not rows:
        return {"ok": False, "message": "ไม่มีแชทเมื่อวาน"}
    chat_text = "\n".join([f"[{r[0]}] {r[1]}: {r[2][:150]}" for r in rows])
    msgs = [
        {"role": "system", "content": "สรุปการสนทนาเป็นภาษาไทย ใช้ bullet points ไม่เกิน 5 ข้อ กระชับมีประโยชน์"},
        {"role": "user", "content": f"สนทนา {yesterday}:\n{chat_text[:2500]}"},
    ]
    try:
        summary = "".join(stream_response(msgs, provider="gemini"))
    except Exception as e:
        summary = f"(สรุปไม่ได้: {e})"
    return {"ok": True, "date": yesterday, "summary": summary, "count": len(rows)}


@app.post("/api/share")
async def create_share(request: Request):
    data = await request.json()
    assistant = data.get("assistant", "")
    session_id = data.get("session_id", "")
    if not assistant or not session_id:
        return {"ok": False, "error": "ระบุ assistant และ session_id"}
    token = uuid.uuid4().hex[:10]
    created = datetime.now().isoformat()
    _share_store_set(token, {"assistant": assistant, "session_id": session_id, "created": created})
    try:
        from utils.history import _get_conn
        conn = _get_conn()
        conn.execute("CREATE TABLE IF NOT EXISTS share_links (token TEXT PRIMARY KEY, assistant TEXT, session_id TEXT, created TEXT)")
        conn.execute("INSERT OR REPLACE INTO share_links (token, assistant, session_id, created) VALUES (?,?,?,?)",
                     (token, assistant, session_id, created))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Share link persist failed: {e}")
    return {"ok": True, "token": token}


@app.get("/api/shared/{token}")
def get_shared_data(token: str):
    info = _share_store.get(token)
    if not info:
        try:
            from utils.history import _get_conn
            conn = _get_conn()
            conn.execute("CREATE TABLE IF NOT EXISTS share_links (token TEXT PRIMARY KEY, assistant TEXT, session_id TEXT, created TEXT)")
            row = conn.execute("SELECT assistant, session_id, created FROM share_links WHERE token=?", (token,)).fetchone()
            conn.close()
            if row:
                info = {"assistant": row[0], "session_id": row[1], "created": row[2]}
                _share_store_set(token, info)
        except Exception as e:
            logger.warning(f"Share link lookup failed: {e}")
    if not info:
        return {"ok": False, "error": "ไม่พบ link"}
    msgs = load_history(info["assistant"], info["session_id"], include_meta=False)
    return {"ok": True, "assistant": info["assistant"], "messages": msgs, "created": info["created"]}


@app.get("/shared/{token}", response_class=HTMLResponse)
def shared_page(token: str):
    html = f"""<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Shared Chat</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Sora:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Sora',sans-serif;background:#060810;color:#e2e8f0;min-height:100vh;padding:0}}
.bg{{position:fixed;inset:0;pointer-events:none;z-index:0;overflow:hidden}}
.orb{{position:absolute;border-radius:50%;filter:blur(80px);opacity:.5}}
.orb1{{width:400px;height:400px;background:radial-gradient(circle,rgba(168,85,247,.5),transparent 70%);top:-100px;right:10%}}
.orb2{{width:300px;height:300px;background:radial-gradient(circle,rgba(236,72,153,.4),transparent 70%);bottom:50px;left:5%}}
.wrap{{position:relative;z-index:1;max-width:800px;margin:0 auto;padding:24px 16px 60px}}
header{{display:flex;align-items:center;gap:12px;padding:20px 0 24px;border-bottom:1px solid rgba(255,255,255,.07);margin-bottom:28px}}
.avatar{{width:40px;height:40px;border-radius:50%;background:linear-gradient(135deg,#a855f7,#ec4899);display:flex;align-items:center;justify-content:center;font-weight:700;font-size:14px;color:#fff;flex-shrink:0;box-shadow:0 0 20px rgba(168,85,247,.4)}}
.title{{font-size:1rem;font-weight:600;color:#e2e8f0}}
.subtitle{{font-size:.72rem;color:rgba(148,163,184,.5);margin-top:2px}}
.badge{{margin-left:auto;font-size:.65rem;padding:3px 10px;border-radius:20px;background:rgba(168,85,247,.12);border:1px solid rgba(168,85,247,.25);color:#c4b5fd}}
.msgs{{display:flex;flex-direction:column;gap:16px}}
.msg{{display:flex;gap:12px;animation:fadeIn .3s ease forwards}}
.msg.user{{flex-direction:row-reverse}}
.bubble-avatar{{width:32px;height:32px;border-radius:50%;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;margin-top:2px}}
.msg.ai .bubble-avatar{{background:linear-gradient(135deg,#a855f7,#7c3aed);color:#fff;box-shadow:0 0 12px rgba(168,85,247,.35)}}
.msg.user .bubble-avatar{{background:linear-gradient(135deg,#2dd4bf,#06b6d4);color:#fff;box-shadow:0 0 12px rgba(6,182,212,.3)}}
.bubble{{max-width:72%;padding:12px 16px;border-radius:18px;font-size:.88rem;line-height:1.65;position:relative}}
.msg.ai .bubble{{background:linear-gradient(135deg,rgba(99,102,241,.09),rgba(139,92,246,.06));border:1px solid rgba(99,102,241,.2);border-radius:4px 18px 18px 18px}}
.msg.user .bubble{{background:linear-gradient(135deg,rgba(45,212,191,.1),rgba(6,182,212,.07));border:1px solid rgba(45,212,191,.22);border-radius:18px 4px 18px 18px;text-align:left}}
.role-label{{font-size:.65rem;font-weight:600;margin-bottom:5px;opacity:.5;text-transform:uppercase;letter-spacing:.06em}}
.msg.ai .role-label{{color:#a5b4fc}}
.msg.user .role-label{{color:#5eead4}}
pre{{background:rgba(0,0,0,.4);border:1px solid rgba(255,255,255,.08);border-radius:8px;padding:10px 14px;overflow-x:auto;margin:.5em 0;font-family:'JetBrains Mono',monospace;font-size:.78em;line-height:1.5}}
code{{background:rgba(255,255,255,.1);border-radius:4px;padding:1px 5px;font-family:'JetBrains Mono',monospace;font-size:.82em}}
.empty{{text-align:center;padding:60px 20px;color:rgba(148,163,184,.35);font-size:.9rem}}
.load{{text-align:center;padding:80px 20px}}
.spinner{{width:32px;height:32px;border:2px solid rgba(168,85,247,.2);border-top-color:#a855f7;border-radius:50%;animation:spin 1s linear infinite;margin:0 auto 12px}}
.footer{{text-align:center;padding-top:40px;font-size:.7rem;color:rgba(148,163,184,.25)}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
@keyframes fadeIn{{from{{opacity:0;transform:translateY(8px)}}to{{opacity:1;transform:translateY(0)}}}}
@media(max-width:600px){{.bubble{{max-width:88%}}.wrap{{padding:16px 12px 50px}}}}
</style>
</head>
<body>
<div class="bg"><div class="orb orb1"></div><div class="orb orb2"></div></div>
<div class="wrap">
  <header>
    <div class="avatar" id="avatar">AI</div>
    <div>
      <div class="title" id="title">Shared Chat</div>
      <div class="subtitle" id="subtitle">กำลังโหลด...</div>
    </div>
    <div class="badge">Shared</div>
  </header>
  <div class="msgs" id="msgs">
    <div class="load"><div class="spinner"></div><div style="color:rgba(148,163,184,.4);font-size:.85rem">กำลังโหลด...</div></div>
  </div>
  <div class="footer">Hybrid AI Workspace · Shared via link</div>
</div>
<script>
function esc(s){{return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}}
function fmt(s){{
  s=esc(s);
  s=s.replace(/```([\\s\\S]*?)```/g,'<pre><code>$1</code></pre>');
  s=s.replace(/`([^`]+)`/g,'<code>$1</code>');
  s=s.replace(/\\*\\*([^*]+)\\*\\*/g,'<strong>$1</strong>');
  s=s.replace(/\\*([^*]+)\\*/g,'<em>$1</em>');
  s=s.replace(/^#{1,3} (.+)$/gm,'<strong style="font-size:1.05em;display:block;margin:.5em 0 .2em">$1</strong>');
  s=s.replace(/\\n/g,'<br>');
  return s;
}}
fetch('/api/shared/{token}').then(r=>r.json()).then(d=>{{
  if(!d.ok){{document.getElementById('msgs').innerHTML='<div class="empty">❌ ไม่พบแชทนี้ หรือ link หมดอายุแล้ว</div>';return;}}
  document.getElementById('title').textContent='💬 '+d.assistant;
  document.getElementById('avatar').textContent=d.assistant.charAt(0).toUpperCase();
  document.getElementById('subtitle').textContent=(d.messages?.length||0)+' ข้อความ · '+new Date(d.created).toLocaleDateString('th-TH',{{day:'numeric',month:'short',year:'2-digit'}});
  const c=document.getElementById('msgs');
  if(!d.messages?.length){{c.innerHTML='<div class="empty">ไม่มีข้อความใน session นี้</div>';return;}}
  c.innerHTML='';
  d.messages.forEach(m=>{{
    const isUser=m.role==='user';
    const el=document.createElement('div');
    el.className='msg '+(isUser?'user':'ai');
    el.innerHTML=`<div class="bubble-avatar">${{isUser?'U':'A'}}</div><div class="bubble"><div class="role-label">${{isUser?'User':'AI'}}</div>${{fmt(m.content)}}</div>`;
    c.appendChild(el);
  }});
}}).catch(()=>{{document.getElementById('msgs').innerHTML='<div class="empty">❌ โหลดไม่ได้ — ตรวจสอบการเชื่อมต่อ</div>';}});
</script>
</body>
</html>"""
    return HTMLResponse(content=html)


@app.post("/api/regenerate")
async def regenerate_response(request: Request):
    """ลบ AI response ล่าสุดแล้ว stream ใหม่"""
    data = await request.json()
    assistant = data.get("assistant", list(ASSISTANTS.keys())[0])
    session_id = data.get("session_id", "default")
    provider = data.get("provider", "ollama")
    agent_mode = bool(data.get("agent_mode", False))

    delete_last_assistant_message(assistant, session_id)
    last_prompt = get_last_user_message(assistant, session_id)
    if not last_prompt:
        async def _err():
            yield "data: " + json.dumps({'error': 'ไม่พบข้อความ'}) + "\n\n"
        return StreamingResponse(_err(), media_type="text/event-stream")

    cfg = ASSISTANTS.get(assistant, list(ASSISTANTS.values())[0])
    base_prompt = cfg["system_prompt"]
    full_context = "\n\n".join(filter(None, [search_memory(assistant, last_prompt)]))
    system_prompt = inject_context_to_system(base_prompt, full_context)
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


@app.delete("/api/truncate/{db_id}")
def truncate_endpoint(db_id: int):
    """ลบข้อความทุกรายการที่มี id >= db_id (ใช้สำหรับ Edit & Resend)"""
    truncate_from_db_id(db_id)
    return {"ok": True}


@app.post("/api/chat")
async def chat(request: Request):
    data = await request.json()
    assistant = data.get("assistant", list(ASSISTANTS.keys())[0])
    session_id = data.get("session_id", "default")
    prompt = data.get("prompt", "")
    provider = data.get("provider", "ollama")
    image_b64 = data.get("image_b64", "")
    image_mime = data.get("image_mime", "")
    agent_mode = bool(data.get("agent_mode", False))
    obsidian_inject_flag = bool(data.get("obsidian_inject", False))

    config = ASSISTANTS.get(assistant, list(ASSISTANTS.values())[0])
    base_prompt = config["system_prompt"]

    lessons = get_lessons(prompt)
    prefs = get_preferences()
    long_term = search_long_term_memory(prompt)
    skills_folder_path = os.path.join(os.path.dirname(__file__), "skills")
    skills_md = load_skills_folder(skills_folder_path)
    vault_ctx = ""
    if obsidian_inject_flag:
        vault_results = search_vault(prompt, n=3)
        if vault_results:
            vault_ctx = "\n\n".join([f"[Note: {r['title']}]\n{r['content'][:500]}" for r in vault_results])

    full_context = "\n\n".join(filter(None, [
        search_memory(assistant, prompt),
        long_term,
        search_skills(prompt, n_results=3),
        f"[Skills & Knowledge]\n{skills_md}" if skills_md else "",
        f"[บทเรียนสะสม]\n{lessons}" if lessons else "",
        f"[ความชอบ]\n{prefs}" if prefs else "",
        f"[Obsidian Vault Notes]\n{vault_ctx}" if vault_ctx else "",
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
        MAX_INPUT_TOKENS = 3000
        sys_msg = messages[0]
        if len(sys_msg["content"]) > 4000:
            sys_msg = {"role": "system", "content": sys_msg["content"][:4000]}
            messages[0] = sys_msg
        while len(messages) > 2 and count_tokens_approx(messages) > MAX_INPUT_TOKENS:
            messages.pop(1)

    def generate():
        full_response = ""
        try:
            for chunk in stream_response(messages, provider=provider, image_b64=image_b64, image_mime=image_mime, agent_mode=agent_mode):
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


if __name__ == "__main__":
    import uvicorn
    logging.basicConfig(level=logging.INFO)
    logger.info("Hybrid AI Workspace → http://localhost:8000")
    reload = os.getenv("RELOAD", "false").lower() == "true"
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=reload)
