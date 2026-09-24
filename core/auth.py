import hashlib
import hmac
import ipaddress
import secrets
import time
from fastapi import Request, WebSocket
from fastapi.responses import JSONResponse
from core.config import SESSION_TTL_DAYS, UI_PASSWORD

# endpoint ที่รับรหัสผ่านใน body (ไม่ใช่ header) — ratelimit ต้องรู้เพื่อนับ brute-force
LOGIN_PATH = "/api/auth/login"

# ── session token (2026-09-24 · audit ข้อ 1-2) ───────────────────────────────────────
# เดิม /api/auth/login คืน UI_PASSWORD ดิบเป็น "token" → อยู่ใน localStorage + URL ของ WS + access log
# ตอนนี้ออก token สุ่ม 128-bit ลงนาม HMAC ด้วย secret ที่ derive จาก UI_PASSWORD (stdlib ล้วน ไม่มี store):
#   token = <nonce urlsafe 16 ไบต์>.<exp unix>.<hmac-sha256 hex>
# · รอด restart (ไม่มี state ฝั่ง server) · เปลี่ยนรหัส = เพิกถอนทุก session · หมดอายุ SESSION_TTL_DAYS
# · OWASP Session Management: ≥64 bit entropy · ไม่มีข้อมูลอ่อนไหวใน id · cookie HttpOnly/Secure/SameSite=Strict
SESSION_COOKIE = "hw_session"
SESSION_TTL_SECONDS = SESSION_TTL_DAYS * 86400


def _session_secret() -> bytes:
    return hmac.new(str(UI_PASSWORD).encode(), b"hybrid-ai-session-v1", hashlib.sha256).digest()


def _sign(payload: str) -> str:
    return hmac.new(_session_secret(), payload.encode(), hashlib.sha256).hexdigest()


def issue_session_token(now: float | None = None) -> str:
    """ออก session token ใหม่ — เรียกหลัง password_matches() ผ่านเท่านั้น"""
    if not UI_PASSWORD:
        raise RuntimeError("auth ปิดอยู่ (UI_PASSWORD ว่าง) — ไม่มี session ให้ออก")
    exp = int((time.time() if now is None else now) + SESSION_TTL_SECONDS)
    payload = f"{secrets.token_urlsafe(16)}.{exp}"
    return f"{payload}.{_sign(payload)}"


def session_token_valid(token: str | None, now: float | None = None) -> bool:
    """ตรวจลายเซ็น (constant-time) + วันหมดอายุ · รหัสผ่านดิบ/ค่าว่าง = False เสมอ"""
    if not UI_PASSWORD or not token:
        return False
    parts = str(token).split(".")
    if len(parts) != 3:
        return False
    nonce, exp_s, sig = parts
    if not exp_s.isdigit():
        return False
    if not hmac.compare_digest(sig, _sign(f"{nonce}.{exp_s}")):
        return False
    return int(exp_s) > (time.time() if now is None else now)


def password_matches(provided: str) -> bool:
    """เทียบรหัสผ่านดิบแบบ constant-time — ใช้ได้ที่ /api/auth/login เท่านั้น

    คืน False ถ้า UI_PASSWORD ว่าง (auth ปิด) — caller จัดการกรณีนั้นเอง
    """
    if not UI_PASSWORD:
        return False
    return hmac.compare_digest(str(provided or ""), str(UI_PASSWORD))


def token_matches(provided: str) -> bool:
    """credential ที่มากับ header/cookie/query ต้องเป็น **session token** (user เคาะ 09-24: รหัสดิบใช้ไม่ได้)"""
    return session_token_valid(provided)


def presented_token(conn) -> str:
    """credential ที่ client ส่งมา — header ก่อน (สคริปต์/เทส) แล้ว cookie (browser · WS ส่งเองตอน handshake)"""
    return conn.headers.get("x-auth-token", "") or conn.cookies.get(SESSION_COOKIE, "")

# fail-closed: ทุก request ต้อง token เว้นแต่อยู่ใน open allowlist นี้
# (เดิม fail-open สำหรับ GET ที่ไม่ตรง denylist → endpoint ใหม่/ที่ตกหล่นหลุด public)
# /api/shared = public share link (token อยู่ใน URL), /api/health = monitoring probe
_OPEN_PATHS = {"/", "/api/config", "/api/status", "/api/health",
               "/api/auth/check", "/api/auth/login", "/api/auth/logout"}
# /api/files = ลิงก์ดาวน์โหลดจาก tool export_file — <a download> เป็น navigation
# แนบ header ไม่ได้ (นอกบ้านโดน 401 → ได้ไฟล์เปล่า) · ความปลอดภัยอยู่ที่
# token 128-bit ใน URL แบบเดียวกับ /gen
_OPEN_PREFIXES = ("/static", "/assets", "/shared", "/api/shared", "/ws", "/gen",
                  "/api/files")


def _ip_is_private(ip_str: str) -> bool:
    """True ถ้า IP เป็น LAN/loopback — ใช้ ipaddress lib แทน prefix match"""
    try:
        ip = ipaddress.ip_address(ip_str)
        return ip.is_private or ip.is_loopback
    except (ValueError, TypeError):
        return False


def is_local_request(request: Request) -> bool:
    """LAN request bypass auth — ตรวจ TCP peer IP (spoof-resistant)

    Why: เดิมตรวจ host header — spoof ได้ง่ายผ่าน proxy reverse
    How: ใช้ request.client.host (TCP socket peer) — proxy ไม่สามารถปลอม
    Cloudflare กรณีพิเศษ: cf-connecting-ip header → not local (public client)
    """
    # ถ้ามาผ่าน Cloudflare tunnel → ไม่ใช่ local ไม่ว่า peer IP จะเป็นอะไร
    if request.headers.get("cf-connecting-ip"):
        return False
    # ตรวจ TCP peer IP (เชื่อถือได้กว่า host header)
    client = request.client
    if client and _ip_is_private(client.host):
        return True
    return False


def _under_open_prefix(path: str) -> bool:
    """prefix ต้องตรงทั้ง segment — `startswith` ดิบๆ ทำให้ route ที่ชื่อขึ้นต้นเหมือน
    open prefix (`/api/sharedsecrets`) หลุด public เงียบๆ ขัดเจตนา fail-closed"""
    return any(path == p or path.startswith(p + "/") for p in _OPEN_PREFIXES)


def websocket_authorized(websocket: WebSocket, token: str = "") -> bool:
    """gate ของ WebSocket — ต้องเรียกเองใน handler ก่อน accept()

    Why: `app.middleware("http")` = BaseHTTPMiddleware ซึ่งลัดผ่านทุก scope ที่ไม่ใช่ http
    → auth/rate-limit ไม่เคยแตะ WebSocket เลย (endpoint หลุด public แม้ตั้ง UI_PASSWORD)
    How: กติกาเดียวกับ auth_middleware — password ปิด → ผ่าน, LAN peer → ผ่าน, ไม่งั้นต้องมี session token
    · ทางหลัก = cookie `hw_session` (browser แนบเองตอน handshake · ไม่โผล่ใน log)
    · query `?token=` ยังรับ session token ไว้ให้ bundle เก่า/สคริปต์ — **ห้ามส่งรหัสดิบ** และ
      core/observability.DropQueryStringFilter ตัด query ออกจาก log ของ uvicorn แล้ว
    """
    if not UI_PASSWORD:
        return True
    if is_local_request(websocket):   # WebSocket มี .headers/.client เหมือน Request
        return True
    return token_matches(token or websocket.cookies.get(SESSION_COOKIE, ""))


async def auth_middleware(request: Request, call_next):
    if not UI_PASSWORD:
        return await call_next(request)
    path = request.url.path
    if path in _OPEN_PATHS or _under_open_prefix(path):
        return await call_next(request)
    if is_local_request(request):
        return await call_next(request)
    if token_matches(presented_token(request)):
        return await call_next(request)
    return JSONResponse({"error": "Unauthorized"}, status_code=401)
