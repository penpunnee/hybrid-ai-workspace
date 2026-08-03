import os
import logging
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from core.config import CORS_ORIGINS_LIST, RELOAD, GEMINI_API_KEY, GEMINI_LIVE_MODEL
from core.auth import auth_middleware, websocket_authorized
from core.ratelimit import rate_limit_middleware
from core.observability import install_logging, start_request, timing_summary
from core.scheduler import start_scheduler
from utils.skills import _load_skills_db

from routers import auth, chat, sessions, memory, skills, dream, vault, tools, system, agent, documents, feedback, sandbox

# install logging ก่อน import อื่นๆ ที่ใช้ logger — กัน duplicate handlers
install_logging()
logger = logging.getLogger(__name__)


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
    start_scheduler()
    yield


app = FastAPI(title="Hybrid AI Workspace", lifespan=lifespan)

app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS_LIST,
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


async def _request_id_middleware(request: Request, call_next):
    """กำหนด request_id + log start/end + timing"""
    # respect client-provided ID (สำหรับ end-to-end tracing) ไม่งั้น generate ใหม่
    rid = request.headers.get("x-request-id") or start_request()
    if request.headers.get("x-request-id"):
        from core.observability import _request_id_var
        _request_id_var.set(rid)

    start = time.perf_counter()
    method, path = request.method, request.url.path
    response = await call_next(request)
    elapsed = round((time.perf_counter() - start) * 1000, 1)

    # log บางอันเท่านั้น (กัน noise จาก static)
    if not path.startswith(("/static", "/assets")):
        ts = timing_summary()
        logger.info(f"{method} {path} → {response.status_code} ({elapsed}ms) {ts}")

    response.headers["X-Request-Id"] = rid
    return response


# ลำดับ (outer→inner): request_id → rate_limit → auth → route
# Starlette: middleware ที่ register ทีหลัง = outermost → register ย้อนลำดับ (inner ก่อน)
# rate_limit ต้องอยู่ "นอก" auth เพื่อเห็น 401 ของ auth (auth คืน 401 ตรงๆ ไม่เรียก inner)
# → feed brute-force lockout ได้จริง. request_id นอกสุด → tag ทุก response รวม 401
app.middleware("http")(auth_middleware)         # innermost
app.middleware("http")(rate_limit_middleware)   # middle (wrap auth)
app.middleware("http")(_request_id_middleware)  # outermost

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(sessions.router)
app.include_router(memory.router)
app.include_router(skills.router)
app.include_router(dream.router)
app.include_router(vault.router)
app.include_router(tools.router)
app.include_router(system.router)
app.include_router(agent.router)
app.include_router(documents.router)
app.include_router(feedback.router)
app.include_router(sandbox.router)

# ── Static files + SPA ───────────────────────────────────────────────────────
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
if os.path.exists("static/assets"):
    app.mount("/assets", StaticFiles(directory="static/assets"), name="assets")

# รูปที่ AI สร้าง (utils/image_gen.py) — เสิร์ฟผ่าน /gen/<file> (<img> ส่ง header ไม่ได้ → ต้อง open path)
from utils.image_gen import GEN_IMAGE_DIR
os.makedirs(GEN_IMAGE_DIR, exist_ok=True)
app.mount("/gen", StaticFiles(directory=GEN_IMAGE_DIR), name="gen_images")


@app.get("/", response_class=HTMLResponse)
async def root():
    with open("static/index.html", encoding="utf-8") as f:
        return f.read()


@app.get("/shared/{token}", response_class=HTMLResponse)
async def shared_page(token: str):
    """Shared chat page — HTML served here, data fetched via /api/shared/{token}"""
    html = f"""<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Shared Chat</title>
<link href="https://fonts.googleapis.com/css2?family=Sora:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Sora',sans-serif;background:#060810;color:#e2e8f0;min-height:100vh}}
.bg{{position:fixed;inset:0;pointer-events:none;z-index:0;overflow:hidden}}
.orb{{position:absolute;border-radius:50%;filter:blur(80px);opacity:.5}}
.orb1{{width:400px;height:400px;background:radial-gradient(circle,rgba(168,85,247,.5),transparent 70%);top:-100px;right:10%}}
.orb2{{width:300px;height:300px;background:radial-gradient(circle,rgba(236,72,153,.4),transparent 70%);bottom:50px;left:5%}}
.wrap{{position:relative;z-index:1;max-width:800px;margin:0 auto;padding:24px 16px 60px}}
header{{display:flex;align-items:center;gap:12px;padding:20px 0 24px;border-bottom:1px solid rgba(255,255,255,.07);margin-bottom:28px}}
.avatar{{width:40px;height:40px;border-radius:50%;background:linear-gradient(135deg,#a855f7,#ec4899);display:flex;align-items:center;justify-content:center;font-weight:700;font-size:14px;color:#fff;flex-shrink:0}}
.title{{font-size:1rem;font-weight:600;color:#e2e8f0}}
.subtitle{{font-size:.72rem;color:rgba(148,163,184,.5);margin-top:2px}}
.badge{{margin-left:auto;font-size:.65rem;padding:3px 10px;border-radius:20px;background:rgba(168,85,247,.12);border:1px solid rgba(168,85,247,.25);color:#c4b5fd}}
.msgs{{display:flex;flex-direction:column;gap:16px}}
.msg{{display:flex;gap:12px}}
.msg.user{{flex-direction:row-reverse}}
.bubble-avatar{{width:32px;height:32px;border-radius:50%;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;margin-top:2px}}
.msg.ai .bubble-avatar{{background:linear-gradient(135deg,#a855f7,#7c3aed);color:#fff}}
.msg.user .bubble-avatar{{background:linear-gradient(135deg,#2dd4bf,#06b6d4);color:#fff}}
.bubble{{max-width:72%;padding:12px 16px;border-radius:18px;font-size:.88rem;line-height:1.65}}
.msg.ai .bubble{{background:linear-gradient(135deg,rgba(99,102,241,.09),rgba(139,92,246,.06));border:1px solid rgba(99,102,241,.2);border-radius:4px 18px 18px 18px}}
.msg.user .bubble{{background:linear-gradient(135deg,rgba(45,212,191,.1),rgba(6,182,212,.07));border:1px solid rgba(45,212,191,.22);border-radius:18px 4px 18px 18px}}
.role-label{{font-size:.65rem;font-weight:600;margin-bottom:5px;opacity:.5;text-transform:uppercase}}
pre{{background:rgba(0,0,0,.4);border:1px solid rgba(255,255,255,.08);border-radius:8px;padding:10px 14px;overflow-x:auto;margin:.5em 0;font-family:'JetBrains Mono',monospace;font-size:.78em}}
code{{background:rgba(255,255,255,.1);border-radius:4px;padding:1px 5px;font-family:'JetBrains Mono',monospace;font-size:.82em}}
.empty{{text-align:center;padding:60px 20px;color:rgba(148,163,184,.35)}}
.spinner{{width:32px;height:32px;border:2px solid rgba(168,85,247,.2);border-top-color:#a855f7;border-radius:50%;animation:spin 1s linear infinite;margin:0 auto 12px}}
.footer{{text-align:center;padding-top:40px;font-size:.7rem;color:rgba(148,163,184,.25)}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
@media(max-width:600px){{.bubble{{max-width:88%}}}}
</style>
</head>
<body>
<div class="bg"><div class="orb orb1"></div><div class="orb orb2"></div></div>
<div class="wrap">
  <header>
    <div class="avatar" id="avatar">AI</div>
    <div><div class="title" id="title">Shared Chat</div><div class="subtitle" id="subtitle">กำลังโหลด...</div></div>
    <div class="badge">Shared</div>
  </header>
  <div class="msgs" id="msgs"><div style="text-align:center;padding:80px 20px"><div class="spinner"></div></div></div>
  <div class="footer">Hybrid AI Workspace · Shared via link</div>
</div>
<script>
function esc(s){{return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}}
function fmt(s){{
  s=esc(s);
  s=s.replace(/```([\\s\\S]*?)```/g,'<pre><code>$1</code></pre>');
  s=s.replace(/`([^`]+)`/g,'<code>$1</code>');
  s=s.replace(/\\*\\*([^*]+)\\*\\*/g,'<strong>$1</strong>');
  s=s.replace(/\\n/g,'<br>');
  return s;
}}
fetch('/api/shared/{token}').then(r=>r.json()).then(d=>{{
  if(!d.ok){{document.getElementById('msgs').innerHTML='<div class="empty">❌ ไม่พบแชทนี้</div>';return;}}
  document.getElementById('title').textContent='💬 '+d.assistant;
  document.getElementById('avatar').textContent=d.assistant.charAt(0).toUpperCase();
  document.getElementById('subtitle').textContent=(d.messages?.length||0)+' ข้อความ';
  const c=document.getElementById('msgs');
  if(!d.messages?.length){{c.innerHTML='<div class="empty">ไม่มีข้อความ</div>';return;}}
  c.innerHTML='';
  d.messages.forEach(m=>{{
    const isUser=m.role==='user';
    const el=document.createElement('div');
    el.className='msg '+(isUser?'user':'ai');
    el.innerHTML=`<div class="bubble-avatar">${{isUser?'U':'A'}}</div><div class="bubble"><div class="role-label">${{isUser?'User':'AI'}}</div>${{fmt(m.content)}}</div>`;
    c.appendChild(el);
  }});
}}).catch(()=>{{document.getElementById('msgs').innerHTML='<div class="empty">❌ โหลดไม่ได้</div>';}});
</script>
</body>
</html>"""
    return HTMLResponse(content=html)


# ── Voice WebSocket (ยังอยู่ใน server.py เพราะต้องการ lifespan context) ──────
@app.websocket("/ws/voice/{assistant_slug}")
async def voice_websocket(websocket: WebSocket, assistant_slug: str, session_id: str = "voice_default",
                          token: str = ""):
    # gate ก่อน accept — middleware ไม่แตะ WebSocket (ดู core.auth.websocket_authorized)
    if not websocket_authorized(websocket, token):
        await websocket.close(code=1008)
        return

    from google import genai
    from google.genai import types
    from assistants.config import ASSISTANTS, voice_system_prompt
    from utils.tts import VOICE_MAP, DEFAULT_VOICE
    from utils.voice import live_server_content_events
    from utils.history import save_message as _save_msg

    await websocket.accept()
    if not GEMINI_API_KEY:
        await websocket.send_json({"type": "error", "message": "GEMINI_API_KEY not set"})
        return

    voice = VOICE_MAP.get(assistant_slug.lower(), DEFAULT_VOICE)
    asst_name, asst = next(((k, v) for k, v in ASSISTANTS.items() if v.get("slug") == assistant_slug), ("", {}))
    if not asst_name:
        asst_name = assistant_slug
    # ⚠️ ห้ามใช้ asst["system_prompt"] ดิบ — persona แชทสั่งให้ "กระชับ" + "ถามไถ่เชิงรุก"
    # ทำให้เล่าเรื่องยาวๆ แล้วถามกลับทุกท่อน ("จะให้เล่าต่อเลยไหมคะ") ซึ่งใน voice
    # แปลว่าเสียงหยุดและคนต้องพูดตอบทุกครั้ง (user รายงาน 2026-08-04)
    sys_prompt = voice_system_prompt(assistant_slug)

    import asyncio
    from utils.voice import live_control_signals

    client = genai.Client(api_key=GEMINI_API_KEY, http_options={"api_version": "v1alpha"})

    def _live_config(resume_handle: str | None) -> "types.LiveConnectConfig":
        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                )
            ),
            system_instruction=types.Content(parts=[types.Part(text=sys_prompt)]),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            input_audio_transcription=types.AudioTranscriptionConfig(),
            # hands-free: เปิด automatic VAD → Gemini จับเริ่ม/หยุดพูดจากเสียงเอง (พูดได้เลยไม่ต้องกด)
            # กัน echo ที่ฝั่ง client (half-duplex: ปิดไมค์ตอน AI พูด) แทนการพึ่ง manual VAD.
            # NO_INTERRUPTION = เผื่อ echo หลุดขอบ tail ก็ไม่ตัดคำตอบ AI กลางคัน (belt-and-suspenders)
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(),
                activity_handling=types.ActivityHandling.NO_INTERRUPTION,
            ),
            # ⚠️ คอมเมนต์เดิมตรงนี้เขียนว่า compression ทำให้ "session ไม่มีลิมิตอายุ →
            # ไม่มี go_away จาก duration" — **ไม่จริง** log prod เจอ go_away 2 ครั้ง
            # (2026-08-03 18:14:14 และ 21:33:32 UTC ทั้งคู่ราวนาทีที่ 10 ของ session)
            # compression ช่วยเรื่อง context ยาว แต่ไม่ได้ยกเลิก go_away → ต้องรับมือเอง
            context_window_compression=types.ContextWindowCompressionConfig(
                sliding_window=types.SlidingWindow(),
            ),
            # ขอ handle ไว้ต่อ session ใหม่ตอนโดน go_away — ไม่มีอันนี้ = ต่อใหม่ได้แต่
            # ความจำหายหมด (เล่านิยายอยู่แล้วเริ่มเรื่องใหม่)
            session_resumption=types.SessionResumptionConfig(handle=resume_handle),
        )

    # `stop` = เลิกทั้งหมด (client ตัด/สั่ง close) · `regen` = ต่อ session ใหม่แต่ยังคุยกับ client เดิม
    stop = asyncio.Event()
    resume_handle: str | None = None
    announced = False
    try:
        while not stop.is_set():
            regen = asyncio.Event()
            async with client.aio.live.connect(
                model=GEMINI_LIVE_MODEL, config=_live_config(resume_handle)
            ) as session:
                if not announced:
                    # ส่งครั้งเดียวตอนแรก — ต่อ session ใหม่ไม่ควรรีเซ็ต state ฝั่ง UI
                    await websocket.send_json({"type": "connected", "voice": voice})
                    announced = True

                async def recv_loop():
                    try:
                        while not stop.is_set() and not regen.is_set():
                            try:
                                msg = await asyncio.wait_for(websocket.receive_json(), timeout=1.0)
                            except asyncio.TimeoutError:
                                continue
                            t = msg.get("type", "")
                            if t == "audio":
                                import base64
                                pcm = base64.b64decode(msg["data"])
                                await session.send_realtime_input(
                                    audio=types.Blob(data=pcm, mime_type="audio/pcm;rate=16000")
                                )
                            elif t in ("activity_start", "activity_end", "end_turn"):
                                # automatic VAD เปิดอยู่ → Gemini จับ turn เอง. ไม่ forward
                                # activity_* (จะ error "supported only when auto VAD disabled").
                                # ไว้รับ client เก่าที่ cache ไว้ → ละเลยเฉย ๆ กัน session ตาย
                                pass
                            elif t == "text":
                                await session.send(input=msg.get("text", ""), end_of_turn=True)
                            elif t == "close":
                                stop.set()
                    except WebSocketDisconnect:
                        stop.set()
                    except Exception as e:
                        logger.error(f"[Voice WS] recv_loop {type(e).__name__}: {e}")
                        stop.set()

                async def send_loop():
                    nonlocal resume_handle
                    import base64
                    user_transcript = ""
                    ai_transcript = ""
                    try:
                        # ⚠️ session.receive() yield แค่ turn เดียวแล้ว generator จบ —
                        # ต้องวน while เรียกใหม่ทุก turn ไม่งั้น turn 2 เป็นต้นไปไม่มีใครอ่านคำตอบ
                        while not stop.is_set() and not regen.is_set():
                            async for response in session.receive():
                                if stop.is_set() or regen.is_set():
                                    break

                                # สัญญาณควบคุม session — ต้องอ่านก่อนอย่างอื่น
                                # (เดิมไม่เคยอ่านเลย → Gemini เตือนแล้วเราเงียบ มันเลยตัดทิ้งด้วย 1008
                                #  ราวนาทีที่ 10 ยืนยันจาก prod 2 ครั้ง)
                                got_go_away, secs_left, new_handle = live_control_signals(response)
                                if new_handle:
                                    resume_handle = new_handle
                                if got_go_away:
                                    logger.info(
                                        f"[Voice WS] go_away (เหลือ {secs_left if secs_left is not None else '?'}s) "
                                        f"→ ต่อ session ใหม่ handle={'มี' if resume_handle else 'ไม่มี'}"
                                    )
                                    regen.set()
                                    break

                                if response.data:
                                    await websocket.send_json({
                                        "type": "audio",
                                        "data": base64.b64encode(response.data).decode()
                                    })
                                sc = getattr(response, "server_content", None)
                                if sc:
                                    events, user_delta, ai_delta = live_server_content_events(sc)
                                    user_transcript += user_delta
                                    ai_transcript += ai_delta
                                    for evt in events:
                                        await websocket.send_json(evt)
                                    if getattr(sc, "turn_complete", False):
                                        await websocket.send_json({"type": "done"})
                                        if user_transcript.strip():
                                            _save_msg(asst_name, "user", user_transcript.strip(), "gemini_live", session_id)
                                            user_transcript = ""
                                        if ai_transcript.strip():
                                            _save_msg(asst_name, "assistant", ai_transcript.strip(), "gemini_live", session_id)
                                            ai_transcript = ""
                            # generator ของ turn นี้จบ → วนกลับไปรับ turn ถัดไป
                    except Exception as e:
                        logger.error(f"[Voice WS] send_loop {type(e).__name__}: {e}")
                        stop.set()
                        try:
                            await websocket.send_json({"type": "error", "message": str(e)})
                        except Exception:
                            pass

                await asyncio.gather(recv_loop(), send_loop())

            # ออกจาก `async with` = session เก่าปิดเรียบร้อยแล้ว (ไม่ค้างให้ Gemini ตัดเอง)
            if regen.is_set() and not stop.is_set():
                # ไม่ส่ง event ให้ client — เสียงจะสะดุดสั้น ๆ แต่ UI ไม่ต้องรีเซ็ต
                continue
            break
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"[Voice WS] {type(e).__name__}: {e}")
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass



if __name__ == "__main__":
    import uvicorn
    logger.info("Hybrid AI Workspace → http://localhost:8000")
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=RELOAD)
