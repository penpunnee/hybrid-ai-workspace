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
from core.body_limit import BodySizeLimitMiddleware
from utils.http_limits import MAX_BODY_BYTES
from core.observability import install_logging, start_request, timing_summary
from core.scheduler import start_scheduler
from utils.skills import _load_skills_db

from routers import auth, chat, sessions, memory, skills, dream, vault, tools, system, agent, documents, feedback, sandbox, reader

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
# body_limit อยู่ในสุด (register ก่อน) — ให้ auth/rate-limit ปฏิเสธก่อนได้ ถูกกว่า
# แต่ยังอยู่ **นอก route** จึงคุม `receive` ได้ก่อน multipart parser จะเขียนลงดิสก์
# (`read_capped()` ใน handler สายเกินไป — form ถูก parse ไปแล้วตอน resolve dependency)
app.add_middleware(BodySizeLimitMiddleware, max_bytes=MAX_BODY_BYTES)
app.middleware("http")(auth_middleware)         # innermost ของ BaseHTTPMiddleware
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
app.include_router(reader.router)
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
    from utils.voice import (
        AUTO_CONTINUE_TEXT, SEARCH_LIMIT_REPLY, AudioLevelMeter, build_live_config,
        live_server_content_events, live_tool_call_queries, resolve_voice,
        should_auto_continue, should_run_search,
    )
    from utils.history import save_message as _save_msg

    await websocket.accept()
    if not GEMINI_API_KEY:
        await websocket.send_json({"type": "error", "message": "GEMINI_API_KEY not set"})
        return

    voice = resolve_voice(assistant_slug)
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

    # config ทั้งก้อนอยู่ที่ `utils/voice.py:build_live_config()` — รวมทั้งค่าที่ตรึงเสียง
    # (`seed`/`temperature`/`enable_affective_dialog`) เพื่อให้ session ใหม่ฟังเหมือนเดิม
    def _live_config(resume_handle: str | None):
        return build_live_config(assistant_slug, sys_prompt, resume_handle)

    # `stop` = เลิกทั้งหมด (client ตัด/สั่ง close) · `regen` = ต่อ session ใหม่แต่ยังคุยกับ client เดิม
    stop = asyncio.Event()
    resume_handle: str | None = None
    announced = False
    # เล่าต่ออัตโนมัติ — ปิดเป็นค่าเริ่มต้น เปิดจาก client เท่านั้น (ดู utils/voice.py)
    # อยู่ **นอก**ลูป reconnect เพื่อให้สวิตช์ไม่ถูกรีเซ็ตทุกครั้งที่โดน go_away
    auto_continue = False
    auto_count = 0
    # นับจำนวนครั้งที่ค้นใน turn ปัจจุบัน — กันโมเดลวนค้นจนไม่ยอมพูด
    # (เกิดจริง 2026-08-10: ค้น 5 ครั้งใน 53 วิ แล้วไม่ส่งเสียงกลับมาเลย)
    search_count = 0
    # ⚠️ สร้าง **นอก**ลูป reconnect โดยตั้งใจ — ถ้าอยู่ในลูป นาฬิกาจะรีเซ็ตทุกนาทีที่ 10
    # ซึ่งพอดีกับจุดที่เราสงสัยว่าเสียงเบาลง = มองไม่เห็นสิ่งที่ตั้งใจจะดู
    meter = AudioLevelMeter()
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
                                # ผู้ใช้พิมพ์แทรกระหว่างคุยด้วยเสียง (กล่องพิมพ์ในหน้าจอ voice)
                                # วัดกับ Gemini Live จริงแล้ว: ส่งตอนโมเดลกำลังพูดอยู่ →
                                # ตัด turn เดิม (`interrupted`) แล้วตอบใหม่จริง · ส่งตอนเงียบก็ได้
                                # `session.send()` deprecated แล้ว → ใช้ send_client_content
                                text = (msg.get("text") or "").strip()
                                if text:
                                    await session.send_client_content(
                                        turns=types.Content(
                                            role="user", parts=[types.Part(text=text)]
                                        ),
                                        turn_complete=True,
                                    )
                            elif t == "autocontinue":
                                # สวิตช์ "เล่าต่ออัตโนมัติ" จากหน้าเสียง
                                nonlocal auto_continue, auto_count
                                auto_continue = bool(msg.get("on"))
                                auto_count = 0          # เปิด/ปิดใหม่ = เริ่มนับใหม่เสมอ
                                logger.info(f"[Voice WS] เล่าต่ออัตโนมัติ = {auto_continue}")
                            elif t == "close":
                                stop.set()
                            elif t == "reread":
                                # 🔁 ฟังไม่ทัน — ตอนอ่านไมค์ปิด (user เคาะ 2026-08-17)
                                # จึงสั่งด้วยเสียงไม่ได้ ต้องมาทางปุ่ม
                                reread.set()
                    except WebSocketDisconnect:
                        stop.set()
                    except Exception as e:
                        logger.error(f"[Voice WS] recv_loop {type(e).__name__}: {e}")
                        stop.set()

                async def answer_tool_calls(session, response):
                    """โมเดลขอค้นเว็บ → ค้นจริงแล้วส่งผลกลับ

                    ⚠️ **ต้องตอบให้ครบทุก function_call ที่มันส่งมา** ไม่ใช่เฉพาะตัวที่
                    เราค้นให้ — ตัวที่ไม่ตอบจะทำให้โมเดลรอไปเรื่อยๆ = เงียบค้างกลางบทสนทนา
                    ซึ่งผู้ใช้แยกไม่ออกจาก "เสียงหาย" (`live_tool_call_queries` คัดทิ้ง
                    ชื่อฟังก์ชันที่เราไม่ได้ประกาศ + ตัวที่ไม่มี query โดยตั้งใจ)

                    ค้นแบบ blocking → ต้องผ่าน `to_thread` ไม่งั้น event loop ค้างทั้งเส้น
                    รวมถึงการส่งเสียงที่ค้างอยู่ในคิว
                    """
                    from utils.voice import WEB_SEARCH_TOOL_NAME

                    nonlocal search_count
                    wanted = {cid: q for cid, _n, q in live_tool_call_queries(response)}
                    replies = []
                    for fc in (getattr(response.tool_call, "function_calls", None) or []):
                        cid = getattr(fc, "id", "") or ""
                        name = getattr(fc, "name", "") or WEB_SEARCH_TOOL_NAME
                        query = wanted.get(cid)
                        if query is None:
                            logger.warning(f"[Voice WS] tool call ที่ไม่รับ: {name} → ตอบว่าใช้ไม่ได้")
                            payload = {"error": "เรียกเครื่องมือนี้ไม่ได้ ให้บอกผู้ใช้ตรงๆ ว่าค้นไม่ได้"}
                        elif not should_run_search(search_count):
                            # 🔴 ถึงเพดานแล้ว — **ต้องตอบกลับ ไม่ใช่เงียบ** ไม่งั้นโมเดลรอค้าง
                            # และต้องสั่งให้มันตอบด้วยของที่มี ไม่งั้นมันจะค้นใหม่รอบหน้า
                            logger.warning(
                                f"[Voice WS] ค้นครบเพดาน {search_count} ครั้งใน turn นี้ "
                                f"→ ปฏิเสธ {query!r} แล้วสั่งให้ตอบเลย"
                            )
                            payload = {"error": SEARCH_LIMIT_REPLY}
                        else:
                            try:
                                search_count += 1
                                from utils.llm import gemini_web_search
                                ctx, srcs = await asyncio.to_thread(gemini_web_search, query)
                                if not ctx:
                                    from utils.websearch import web_search_with_results
                                    ctx, srcs = await asyncio.to_thread(
                                        web_search_with_results, query
                                    )
                                logger.info(
                                    f"[Voice WS] ค้น {query!r} → {len(ctx)} ตัวอักษร "
                                    f"{len(srcs or [])} แหล่ง"
                                )
                                payload = (
                                    {"result": ctx}
                                    if ctx
                                    else {"error": "หาไม่เจอ ให้บอกผู้ใช้ตรงๆ ว่าหาไม่เจอ ห้ามแต่ง"}
                                )
                            except Exception as se:
                                # ค้นล้มต้องไม่ทำให้ session ตาย — ปล่อยให้โมเดลพูดต่อได้
                                logger.error(f"[Voice WS] ค้นล้ม {type(se).__name__}: {se}")
                                payload = {"error": "ค้นไม่สำเร็จ ให้บอกผู้ใช้ตรงๆ ห้ามแต่งคำตอบ"}
                        replies.append(
                            types.FunctionResponse(id=cid, name=name, response=payload)
                        )
                    if replies:
                        await session.send_tool_response(function_responses=replies)

                async def send_loop():
                    nonlocal resume_handle, auto_count, search_count
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

                                # โมเดลขอค้นเว็บ — เราค้นให้แล้วส่งผลกลับ
                                # (grounding ตรงๆ บนสาย Live ถูกกั้น tier → ดู utils/voice.py)
                                if getattr(response, "tool_call", None) is not None:
                                    await answer_tool_calls(session, response)

                                if response.data:
                                    # วัด **ก่อน**ส่งออก — ทุกอย่างหลังจุดนี้ (worklet,
                                    # OS mixer, Bluetooth HFP) ไม่มีผลกับตัวเลขนี้
                                    # นั่นคือสิ่งที่ทำให้มันแยก "ต้นทางเบา" กับ "ปลายทางหรี่" ได้
                                    level = meter.add(response.data)
                                    if level:
                                        logger.info(AudioLevelMeter.format_line(level))
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
                                        # เพดานค้นนับต่อ turn — คำถามใหม่เริ่มนับใหม่เสมอ
                                        # ไม่งั้นคุยยาวๆ จะชนเพดานถาวรแล้วค้นไม่ได้อีกทั้ง session
                                        search_count = 0
                                        # พี่ปอยพูดใน turn นี้ไหม — ตัดสินก่อนล้าง buffer
                                        spoke = bool(user_transcript.strip())
                                        if spoke:
                                            _save_msg(asst_name, "user", user_transcript.strip(), "gemini_live", session_id)
                                            user_transcript = ""
                                            auto_count = 0      # user สั่งเอง = เริ่มนับใหม่
                                        if ai_transcript.strip():
                                            _save_msg(asst_name, "assistant", ai_transcript.strip(), "gemini_live", session_id)
                                            ai_transcript = ""
                                        # เล่าต่อให้เองแทนที่จะให้ user ต้องพูดว่า "ต่อ" ทุก ~40 วินาที
                                        # (โมเดลจบ turn ถี่มากและชอบถามกลับ — วัดได้ 62% ของ turn
                                        #  ทั้งที่ prompt สั่งห้ามไว้ตรงๆ ดู utils/voice.py)
                                        if should_auto_continue(auto_continue, spoke, auto_count):
                                            auto_count += 1
                                            logger.info(f"[Voice WS] เล่าต่ออัตโนมัติ ครั้งที่ {auto_count}")
                                            await session.send_client_content(
                                                turns=types.Content(
                                                    role="user",
                                                    parts=[types.Part(text=AUTO_CONTINUE_TEXT)],
                                                ),
                                                turn_complete=True,
                                            )
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


# ── ขวัญอ่านหนังสือ (2026-08-11) — ป้อนท่อนจาก BookStore ให้ Gemini Live อ่าน ────
@app.websocket("/ws/reader")
async def reader_websocket(websocket: WebSocket, source: str = "", token: str = ""):
    """สตรีมเสียงขวัญอ่านหนังสือทีละท่อน · พัก/อ่านต่อได้ · ที่คั่นหน้าอยู่ใน SQLite

    โปรโตคอล:
      client → {type:"pause"} | {type:"resume"} | {type:"close"}
      server → {type:"connected", source, pos, percent}
             | {type:"audio", data:b64} | {type:"block", pos, percent}
             | {type:"done_book"} | {type:"error", message}

    การไหล: อ่าน bookmark → next_block → ป้อนให้โมเดลอ่าน → turn จบ → เลื่อน bookmark
    → ป้อนท่อนถัดไป วนจนจบเล่มหรือ client สั่งพัก/ปิด

    🔑 **ที่คั่นหน้าเลื่อนเมื่อโมเดลอ่านท่อนจบเท่านั้น** — เลื่อนตอนป้อนแล้วหลุดกลางท่อน
    = ท่อนนั้นหายถาวร · เลื่อนหลังจบ = อย่างแย่แค่ฟังซ้ำท่อนเดียว
    """
    if not websocket_authorized(websocket, token):
        await websocket.close(code=1008)
        return

    import asyncio
    import base64

    from google import genai
    from google.genai import types
    from routers.reader import _books, _marks   # ที่เก็บชุดเดียวกับ /api/reader
    from utils.reader import next_block
    from utils.voice import (
        READER_FEED_PREFIX, build_reader_config, live_control_signals, next_read_action,
        reader_stream_action,
    )

    await websocket.accept()
    if not GEMINI_API_KEY:
        await websocket.send_json({"type": "error", "message": "GEMINI_API_KEY not set"})
        return

    text = _books.text(source)
    if text is None:
        await websocket.send_json({"type": "error", "message": f"ยังไม่มีเล่มนี้: {source}"})
        await websocket.close()
        return

    client = genai.Client(api_key=GEMINI_API_KEY, http_options={"api_version": "v1alpha"})

    stop = asyncio.Event()
    paused = asyncio.Event()        # set = พักอยู่
    reread = asyncio.Event()        # set = 🔁 ขออ่านท่อนปัจจุบันใหม่ตั้งแต่ต้น
    resume_handle: str | None = None
    announced = False

    # 🔑 ท่อนี้เคย **ไม่ log อะไรเลยนอกจากทางสายพัง** — 17 วันมี 3 บรรทัด ⇒ อาการ
    # "สองเสียง/ที่คั่นวิ่ง/พักไม่หยุด" ทุกอย่างพิสูจน์จาก log ไม่ได้เลยสักข้อ
    # (เจอ 2026-08-17) · หนึ่งบรรทัดต่อ session = ตอบคำถาม "เปิดซ้อนกันไหม" ได้ตรงๆ
    # โดยไม่กลบ log อื่น (ทั้งวันมีราว 3,000 บรรทัด · rotate ที่ 10MB)
    session_tag = f"{source}#{id(websocket) & 0xFFFF:04x}"
    logger.info(f"[Reader WS] เปิด {session_tag} ที่คั่น {_marks.get(source)}")

    def _progress(pos: int) -> dict:
        return {"pos": pos, "percent": 100 if pos >= len(text) else int(pos * 100 / len(text))}

    try:
        while not stop.is_set():
            regen = asyncio.Event()
            async with client.aio.live.connect(
                model=GEMINI_LIVE_MODEL, config=build_reader_config(resume_handle)
            ) as session:
                if not announced:
                    await websocket.send_json(
                        {"type": "connected", "source": source, **_progress(_marks.get(source))}
                    )
                    announced = True

                async def recv_loop():
                    """รับคำสั่งพัก/อ่านต่อ/ปิดจาก client"""
                    try:
                        while not stop.is_set() and not regen.is_set():
                            try:
                                msg = await asyncio.wait_for(websocket.receive_json(), timeout=1.0)
                            except asyncio.TimeoutError:
                                continue
                            t = msg.get("type", "")
                            if t == "pause":
                                paused.set()
                            elif t == "resume":
                                paused.clear()
                            elif t == "close":
                                stop.set()
                            elif t == "reread":
                                # 🔁 ฟังไม่ทัน — ตอนอ่านไมค์ปิด (user เคาะ 2026-08-17)
                                # จึงสั่งด้วยเสียงไม่ได้ ต้องมาทางปุ่ม
                                reread.set()
                    except WebSocketDisconnect:
                        stop.set()
                    except Exception as e:
                        logger.error(f"[Reader WS] recv_loop {type(e).__name__}: {e}")
                        stop.set()

                async def feed_loop():
                    """ป้อนท่อน → สตรีมเสียง → เลื่อนที่คั่น → ท่อนถัดไป"""
                    nonlocal resume_handle
                    try:
                        while not stop.is_set() and not regen.is_set():
                            pos = _marks.get(source)
                            block, new_pos = next_block(text, pos)
                            act = next_read_action(
                                paused=paused.is_set(), block=block, at_end=(not block and new_pos >= len(text))
                            )
                            if act == "wait":
                                await asyncio.sleep(0.3)
                                continue
                            if act == "finish":
                                await websocket.send_json({"type": "done_book", **_progress(pos)})
                                stop.set()
                                return
                            if act == "skip":
                                _marks.set(source, new_pos)
                                continue

                            reread.clear()   # ธงเป็นของท่อนที่กำลังจะอ่าน ไม่ใช่ท่อนก่อน
                            await session.send_client_content(
                                turns=types.Content(
                                    role="user", parts=[types.Part(text=READER_FEED_PREFIX + block)]
                                ),
                                turn_complete=True,
                            )
                            turn_done = False
                            async for r in session.receive():
                                act_now = reader_stream_action(
                                    stopped=stop.is_set(), paused=paused.is_set(),
                                    reread=reread.is_set(),
                                )
                                if act_now == "stop":
                                    return
                                if act_now == "abort":
                                    # 🔴 user กดพักกลางท่อน (2026-08-15 "กดพักแล้วไม่พักเลย")
                                    # ต้องหยุดส่งเสียง **เดี๋ยวนี้** ไม่ใช่รอจบท่อน (ท่อนละ
                                    # ~1 นาทีของเสียง) · ไม่เลื่อนที่คั่น ⇒ กดอ่านต่อแล้ว
                                    # ได้ยินท่อนนี้ใหม่ตั้งแต่ต้น (ฟังซ้ำดีกว่าเนื้อหาหาย)
                                    # · regen เพราะ turn นี้ถูกทิ้งกลางคัน ปล่อยค้างบน
                                    #   session เดิมแล้วป้อนซ้ำทีหลัง = สองท่อนพันกัน
                                    logger.info(
                                        "[Reader WS] พักกลางท่อน → หยุดส่งเสียงทันที "
                                        "· ที่คั่นไม่ขยับ อ่านท่อนนี้ซ้ำเมื่อกดอ่านต่อ"
                                    )
                                    regen.set()
                                    return
                                if act_now == "restart":
                                    # ที่คั่นยังไม่ขยับ ⇒ session ใหม่จะป้อนท่อนเดิม
                                    # ซ้ำเอง · regen สั่ง flush ให้อยู่แล้ว
                                    reread.clear()
                                    logger.info(
                                        "[Reader WS] 🔁 อ่านท่อนนี้ใหม่ตามคำสั่งผู้ใช้"
                                    )
                                    regen.set()
                                    return
                                got_go_away, _secs, new_handle = live_control_signals(r)
                                if new_handle:
                                    resume_handle = new_handle
                                if got_go_away:
                                    # ยังไม่เลื่อนที่คั่น — reconnect แล้วอ่านท่อนนี้ใหม่ทั้งท่อน
                                    logger.info("[Reader WS] go_away → ต่อ session ใหม่")
                                    regen.set()
                                    return
                                if r.data:
                                    await websocket.send_json(
                                        {"type": "audio", "data": base64.b64encode(r.data).decode()}
                                    )
                                sc = getattr(r, "server_content", None)
                                if sc and getattr(sc, "turn_complete", False):
                                    turn_done = True
                                    break
                            if turn_done:
                                # โมเดลอ่านท่อนนี้จบจริง → ค่อยเลื่อนที่คั่นหน้า
                                _marks.set(source, new_pos)
                                await websocket.send_json({"type": "block", **_progress(new_pos)})
                    except Exception as e:
                        logger.error(f"[Reader WS] feed_loop {type(e).__name__}: {e}")
                        stop.set()
                        try:
                            await websocket.send_json({"type": "error", "message": str(e)})
                        except Exception:
                            pass

                await asyncio.gather(recv_loop(), feed_loop())

            if regen.is_set() and not stop.is_set():
                # 🔴 ต่อ session ใหม่ = อ่านท่อนเดิม **ซ้ำตั้งแต่ต้น** (ตั้งใจ: ฟังซ้ำ
                # ดีกว่าเนื้อหาหาย) แต่ WebSocket เป็นสายเดิม — เสียงท่อนเก่าที่ยังค้าง
                # ใน jitter buffer ฝั่ง client จะเล่นต่อแล้วตามด้วยท่อนเดิมทั้งท่อน
                # = "ประโยคเดิมซ้ำ" (user ยืนยันด้วยหู 2026-08-14)
                # ⇒ สั่งล้างก่อนเสมอ · บทเรียนเดียวกับปุ่มพักใน bookreader.ts:101
                await websocket.send_json({"type": "flush"})
                continue
            break
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"[Reader WS] {type(e).__name__}: {e}")
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        # คู่กับบรรทัด "เปิด" — สอง session ที่ทับช่วงเวลากันจะเห็นได้ทันทีจาก log
        logger.info(f"[Reader WS] ปิด {session_tag} ที่คั่น {_marks.get(source)}")


if __name__ == "__main__":
    import uvicorn
    logger.info("Hybrid AI Workspace → http://localhost:8000")
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=RELOAD)
