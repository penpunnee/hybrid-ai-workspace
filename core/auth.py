import ipaddress
from fastapi import Request
from fastapi.responses import JSONResponse
from core.config import UI_PASSWORD

_OPEN_PATHS = {"/", "/api/config", "/api/status", "/api/auth/check", "/api/auth/login"}
_OPEN_PREFIXES = ("/static", "/assets", "/shared", "/ws")
_WRITE_METHODS = {"POST", "PATCH", "DELETE", "PUT"}
_PROTECTED_GET_PREFIXES = (
    "/api/history/", "/api/export/", "/api/pinned/",
    "/api/memory/", "/api/sessions/", "/api/dream/",
    "/api/tools/home/", "/api/cache/", "/api/routing/",
    "/api/digest", "/api/search", "/api/stats",
)


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


async def auth_middleware(request: Request, call_next):
    if not UI_PASSWORD:
        return await call_next(request)
    path = request.url.path
    if path in _OPEN_PATHS or any(path.startswith(p) for p in _OPEN_PREFIXES):
        return await call_next(request)
    if is_local_request(request):
        return await call_next(request)
    if request.method not in _WRITE_METHODS:
        if not any(path.startswith(p) for p in _PROTECTED_GET_PREFIXES):
            return await call_next(request)
    token = request.headers.get("x-auth-token", "")
    if token == UI_PASSWORD:
        return await call_next(request)
    return JSONResponse({"error": "Unauthorized"}, status_code=401)
