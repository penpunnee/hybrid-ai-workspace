from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from core.auth import is_local_request
from core.config import UI_PASSWORD

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/check")
def auth_check(request: Request):
    if not UI_PASSWORD:
        return {"required": False, "ok": True}
    if is_local_request(request):
        return {"required": True, "ok": True, "bypass": "local_ip"}
    token = request.headers.get("x-auth-token", "")
    return {"required": True, "ok": token == UI_PASSWORD}


@router.post("/login")
async def auth_login(request: Request):
    data = await request.json()
    pwd = data.get("password", "")
    if not UI_PASSWORD or pwd == UI_PASSWORD:
        return {"ok": True, "token": UI_PASSWORD}
    return JSONResponse({"ok": False, "error": "รหัสผ่านไม่ถูกต้อง"}, status_code=401)
