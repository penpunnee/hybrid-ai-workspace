import hmac
import ipaddress
from fastapi import Request, WebSocket
from fastapi.responses import JSONResponse
from core.config import UI_PASSWORD

# endpoint ที่รับรหัสผ่านใน body (ไม่ใช่ header) — ratelimit ต้องรู้เพื่อนับ brute-force
LOGIN_PATH = "/api/auth/login"


def token_matches(provided: str) -> bool:
    """เทียบ token/password แบบ constant-time (กัน timing attack)

    คืน False ถ้า UI_PASSWORD ว่าง (auth ปิด) — caller จัดการกรณีนั้นเอง
    """
    if not UI_PASSWORD:
        return False
    return hmac.compare_digest(str(provided or ""), str(UI_PASSWORD))

# fail-closed: ทุก request ต้อง token เว้นแต่อยู่ใน open allowlist นี้
# (เดิม fail-open สำหรับ GET ที่ไม่ตรง denylist → endpoint ใหม่/ที่ตกหล่นหลุด public)
# /api/shared = public share link (token อยู่ใน URL), /api/health = monitoring probe
_OPEN_PATHS = {"/", "/api/config", "/api/status", "/api/health",
               "/api/auth/check", "/api/auth/login"}
_OPEN_PREFIXES = ("/static", "/assets", "/shared", "/api/shared", "/ws", "/gen")


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
    How: กติกาเดียวกับ auth_middleware — password ปิด → ผ่าน, LAN peer → ผ่าน, ไม่งั้นต้องมี token
    token มาทาง query param เพราะ browser ตั้ง header บน WebSocket ไม่ได้
    """
    if not UI_PASSWORD:
        return True
    if is_local_request(websocket):   # WebSocket มี .headers/.client เหมือน Request
        return True
    return token_matches(token)


async def auth_middleware(request: Request, call_next):
    if not UI_PASSWORD:
        return await call_next(request)
    path = request.url.path
    if path in _OPEN_PATHS or _under_open_prefix(path):
        return await call_next(request)
    if is_local_request(request):
        return await call_next(request)
    token = request.headers.get("x-auth-token", "")
    if token_matches(token):
        return await call_next(request)
    return JSONResponse({"error": "Unauthorized"}, status_code=401)
