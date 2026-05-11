from fastapi import Request
from fastapi.responses import JSONResponse
from core.config import UI_PASSWORD

_OPEN_PATHS = {"/", "/api/config", "/api/status", "/api/auth/check", "/api/auth/login"}
_OPEN_PREFIXES = ("/static", "/assets", "/shared", "/ws")
_WRITE_METHODS = {"POST", "PATCH", "DELETE", "PUT"}
_PROTECTED_GET_PREFIXES = (
    "/api/history/", "/api/export/", "/api/pinned/",
    "/api/memory/", "/api/sessions/", "/api/dream/",
    "/api/tools/home/",
)


def is_local_request(request: Request) -> bool:
    """LAN request ไม่ผ่าน Cloudflare → bypass auth"""
    if request.headers.get("cf-connecting-ip"):
        return False
    host = request.headers.get("host", "")
    return (
        host.startswith("192.168.")
        or host.startswith("10.")
        or host.startswith("127.")
        or host.startswith("localhost")
    )


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
