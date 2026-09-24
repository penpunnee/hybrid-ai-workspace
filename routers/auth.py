from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from core import auth as _auth
from core.auth import (SESSION_COOKIE, SESSION_TTL_SECONDS, is_local_request, issue_session_token,
                       password_matches, presented_token, token_matches)
from utils.http_limits import json_body_capped, MAX_BODY_BYTES

router = APIRouter(prefix="/api/auth", tags=["auth"])

# อ่าน UI_PASSWORD ผ่านโมดูล core.auth ตอนเรียก (เทส patch `core.auth.UI_PASSWORD`) — ไม่ bind ตอน import


def _set_session_cookie(resp: JSONResponse, token: str) -> None:
    # OWASP: Secure + HttpOnly + SameSite=Strict · Max-Age = อายุเดียวกับ token
    # (LAN ผ่าน http ไม่ต้องใช้ cookie อยู่แล้ว — bypass ด้วย peer IP)
    resp.set_cookie(SESSION_COOKIE, token, max_age=SESSION_TTL_SECONDS, path="/",
                    httponly=True, secure=True, samesite="strict")


@router.get("/check")
def auth_check(request: Request):
    """ตอบ **401** เมื่อ credential ผิด (เดิม 200 ok:false = oracle ที่ไม่เข้า lockout · audit ข้อ 7)
    ratelimit นับเฉพาะเคสที่ส่ง header ผิด — cookie หมดอายุตอนโหลดหน้าไม่นับ (กัน false lockout)"""
    if not _auth.UI_PASSWORD:
        return {"required": False, "ok": True}
    if is_local_request(request):
        return {"required": True, "ok": True, "bypass": "local_ip"}
    if token_matches(presented_token(request)):
        return {"required": True, "ok": True}
    return JSONResponse({"required": True, "ok": False}, status_code=401)


@router.post("/login")
async def auth_login(request: Request):
    data = await json_body_capped(request, MAX_BODY_BYTES)
    pwd = data.get("password", "") if isinstance(data, dict) else ""
    if not _auth.UI_PASSWORD:
        return {"ok": True, "token": ""}
    if password_matches(pwd):
        token = issue_session_token()   # ไม่คืนรหัสดิบอีก (audit ข้อ 1-2) · body มี token ให้สคริปต์/ไม่ใช่ browser
        resp = JSONResponse({"ok": True, "token": token})
        _set_session_cookie(resp, token)
        return resp
    return JSONResponse({"ok": False, "error": "รหัสผ่านไม่ถูกต้อง"}, status_code=401)


@router.post("/logout")
def auth_logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(SESSION_COOKIE, path="/", httponly=True, secure=True, samesite="strict")
    return resp
