"""ก้อน 1 ของ audit 2026-09-24 — เลิกใช้รหัสผ่านดิบเป็น token (docs/audit/2026-09-24-full-audit.md ข้อ 1-2, 7)

ค้นก่อนลงมือ (devlog [2026-09-24 ต่อ 10]): OWASP Session Management — session ID ≥64 bit entropy ·
ต้องไม่มีข้อมูลอ่อนไหว · ห้ามเก็บใน localStorage · ห้ามส่งใน URL · cookie `Secure; HttpOnly; SameSite=Strict`
· uvicorn log บรรทัด `[accepted]` ของ WS ผ่าน logger `uvicorn.error` พร้อม query string (ซอร์สที่ติดตั้ง)
· กติกาที่ user เคาะ: session 30 วัน · header `x-auth-token` รับ**เฉพาะ session token** (รหัสดิบใช้ได้แค่ /login)
"""
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import core.auth as auth
import core.ratelimit as rl
import server

PW = "s3cret-pw"


@pytest.fixture
def pw(monkeypatch):
    monkeypatch.setattr(auth, "UI_PASSWORD", PW)
    monkeypatch.setattr(rl, "_ENABLED", True)
    rl.reset_all()
    yield PW
    rl.reset_all()


def _client(host="8.8.8.8"):
    return TestClient(server.app, client=(host, 50000))


# ── 1) session token: สุ่ม · ลงนาม · หมดอายุ · ไม่ใช่รหัสผ่าน ─────────────────────────────
def test_session_token_ไม่ใช่รหัสผ่านและมี_entropy_พอ(pw):
    t1, t2 = auth.issue_session_token(), auth.issue_session_token()
    assert PW not in t1 and t1 != t2
    nonce = t1.split(".")[0]
    assert len(nonce) >= 16, "nonce ต้อง ≥ 96 bit (OWASP ≥64 bit)"


def test_session_token_ตรวจผ่านและรหัสดิบไม่ผ่าน(pw):
    tok = auth.issue_session_token()
    assert auth.session_token_valid(tok) is True
    assert auth.session_token_valid(PW) is False
    assert auth.session_token_valid("") is False and auth.session_token_valid(None) is False


def test_session_token_ถูกดัดแปลงต้องไม่ผ่าน(pw):
    tok = auth.issue_session_token()
    nonce, exp, sig = tok.split(".")
    assert auth.session_token_valid(f"{nonce}.{int(exp) + 999999}.{sig}") is False, "ยืดอายุเองไม่ได้"
    assert auth.session_token_valid(f"{nonce}.{exp}.{'0' * len(sig)}") is False


def test_session_token_หมดอายุ_30_วัน(pw):
    from core.config import SESSION_TTL_DAYS
    assert SESSION_TTL_DAYS == 30
    now = 1_800_000_000
    tok = auth.issue_session_token(now=now)
    assert auth.session_token_valid(tok, now=now + 29 * 86400) is True
    assert auth.session_token_valid(tok, now=now + 30 * 86400 + 1) is False


def test_เปลี่ยนรหัสผ่าน_เพิกถอนทุก_session(pw, monkeypatch):
    tok = auth.issue_session_token()
    monkeypatch.setattr(auth, "UI_PASSWORD", "new-pw")
    assert auth.session_token_valid(tok) is False


def test_password_matches_ยังเทียบรหัสดิบ_และ_token_matches_รับเฉพาะ_session(pw):
    assert auth.password_matches(PW) is True and auth.password_matches("x") is False
    assert auth.token_matches(PW) is False, "header ห้ามรับรหัสดิบอีก (user เคาะ 09-24)"
    assert auth.token_matches(auth.issue_session_token()) is True


# ── 2) /api/auth/login ออก session token + cookie ตามกติกา OWASP ──────────────────────────
def test_login_คืน_session_token_ไม่ใช่รหัส_และตั้ง_cookie(pw):
    r = _client().post("/api/auth/login", json={"password": PW})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["token"] != PW and auth.session_token_valid(body["token"])
    sc = r.headers.get("set-cookie", "")
    assert sc.startswith(f"{auth.SESSION_COOKIE}=")
    low = sc.lower()
    assert "httponly" in low and "secure" in low and "samesite=strict" in low and "path=/" in low
    assert f"max-age={30 * 86400}" in low
    assert PW not in sc


def test_login_รหัสผิด_401(pw):
    r = _client().post("/api/auth/login", json={"password": "nope"})
    assert r.status_code == 401 and "set-cookie" not in r.headers


# ── 3) middleware: cookie หรือ header (session token เท่านั้น) ────────────────────────────
def test_header_รหัสดิบ_401_แต่_session_token_ผ่าน(pw):
    c = _client()
    assert c.get("/api/memory/stats", headers={"x-auth-token": PW}).status_code == 401
    tok = auth.issue_session_token()
    assert c.get("/api/memory/stats", headers={"x-auth-token": tok}).status_code != 401


def test_cookie_session_ผ่าน_และ_cookie_ผิด_401(pw):
    c = _client()
    tok = auth.issue_session_token()
    assert c.get("/api/memory/stats", headers={"cookie": f"{auth.SESSION_COOKIE}={tok}"}).status_code != 401
    assert c.get("/api/memory/stats", headers={"cookie": f"{auth.SESSION_COOKIE}=bad"}).status_code == 401


def test_cookie_หมดอายุ_401_แต่ไม่นับเข้า_lockout(pw):
    """หลายคำขอตอนโหลดหน้าด้วย cookie เก่า = ไม่ใช่ brute-force · ห้าม lock ผู้ใช้จริง"""
    c = _client()
    old = auth.issue_session_token(now=time.time() - 31 * 86400)
    for _ in range(rl._AUTH_FAIL_MAX + 2):
        assert c.get("/api/memory/stats", headers={"cookie": f"{auth.SESSION_COOKIE}={old}"}).status_code == 401
    assert rl._authfail_limiter.over_limit("8.8.8.8")[0] is False


def test_header_ผิดซ้ำ_ยังนับเข้า_lockout(pw):
    c = _client()
    for _ in range(rl._AUTH_FAIL_MAX):
        c.get("/api/memory/stats", headers={"x-auth-token": "guess"})
    assert c.get("/api/memory/stats", headers={"x-auth-token": "guess"}).status_code == 429


# ── 4) /api/auth/check ต้องเป็น 401 เมื่อผิด (ไม่ใช่ oracle 200) ────────────────────────
def test_auth_check_ผิดตอบ_401_และเข้า_lockout(pw):
    c = _client()
    r = c.get("/api/auth/check", headers={"x-auth-token": PW})
    assert r.status_code == 401 and r.json()["ok"] is False
    for _ in range(rl._AUTH_FAIL_MAX):
        c.get("/api/auth/check", headers={"x-auth-token": "guess"})
    assert c.get("/api/auth/check", headers={"x-auth-token": "guess"}).status_code == 429


def test_auth_check_cookie_ถูกตอบ_200(pw):
    tok = auth.issue_session_token()
    r = _client().get("/api/auth/check", headers={"cookie": f"{auth.SESSION_COOKIE}={tok}"})
    assert r.status_code == 200 and r.json() == {"required": True, "ok": True}


def test_auth_check_ไม่มี_credential_401_แต่ไม่นับ(pw):
    c = _client()
    for _ in range(rl._AUTH_FAIL_MAX + 2):
        assert c.get("/api/auth/check").status_code == 401
    assert rl._authfail_limiter.over_limit("8.8.8.8")[0] is False


def test_logout_ล้าง_cookie(pw):
    r = _client().post("/api/auth/logout")
    assert r.status_code == 200
    assert f"{auth.SESSION_COOKIE}=" in r.headers.get("set-cookie", "") and "max-age=0" in r.headers["set-cookie"].lower()


# ── 5) WebSocket: cookie ใช้ได้ · รหัสดิบใน query ไม่ได้ · ล้มแล้วเข้า lockout ──────────────
@pytest.fixture(autouse=True)
def no_gemini(monkeypatch):
    monkeypatch.setattr(server, "GEMINI_API_KEY", "")


def test_ws_cookie_session_ต่อติด(pw):
    tok = auth.issue_session_token()
    with _client().websocket_connect("/ws/voice/kwan", headers={"cookie": f"{auth.SESSION_COOKIE}={tok}"}) as ws:
        assert ws.receive_json()["type"] == "error"


def test_ws_query_รหัสดิบ_ถูกปฏิเสธ(pw):
    with pytest.raises(WebSocketDisconnect) as exc:
        with _client().websocket_connect(f"/ws/voice/kwan?token={PW}"):
            pass
    assert exc.value.code == 1008


def test_ws_ล้มซ้ำ_เข้า_lockout_เดียวกับ_http(pw):
    c = _client()
    for _ in range(rl._AUTH_FAIL_MAX):
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect("/ws/voice/kwan?token=guess"):
                pass
    assert rl._authfail_limiter.over_limit("8.8.8.8")[0] is True
    # ถูก lock แล้ว แม้ token ถูกก็ต้องไม่ต่อติดจนกว่าจะพ้น window
    tok = auth.issue_session_token()
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect(f"/ws/voice/kwan?token={tok}"):
            pass


def test_ws_ไม่มี_credential_ไม่นับ_lockout(pw):
    c = _client()
    for _ in range(rl._AUTH_FAIL_MAX + 2):
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect("/ws/voice/kwan"):
                pass
    assert rl._authfail_limiter.over_limit("8.8.8.8")[0] is False


# ── 6) /shared/{token}: ไม่ interpolate token ลง HTML/JS อีก (XSS) ──────────────────────────
def test_shared_page_ไม่สะท้อน_token_ลง_html(pw):
    xss = "x')-alert(document.cookie)-('"
    r = _client().get(f"/shared/{xss}")
    assert r.status_code == 404
    assert "alert(" not in r.text
    r = _client().get("/shared/abcdef0123")
    assert r.status_code == 200 and "abcdef0123" not in r.text, "token ต้องมาจาก location.pathname ฝั่ง browser เท่านั้น"


def test_share_token_ใหม่_มี_entropy_128_bit(pw, monkeypatch):
    import routers.sessions as s
    captured = {}
    monkeypatch.setattr(s, "share_store_set", lambda t, info: captured.setdefault("t", t))
    monkeypatch.setattr(s, "get_pinned_messages", lambda *a, **k: [], raising=False)
    tok = auth.issue_session_token()
    r = _client().post("/api/share", json={"assistant": "kwan", "session_id": "s1"},
                       headers={"x-auth-token": tok})
    assert r.status_code == 200, r.text
    t = captured["t"]
    assert len(t) >= 22 and all(ch.isalnum() or ch in "-_" for ch in t), t


# ── 7) uvicorn log ต้องไม่มี query string (token ของ bundle เก่า/ticket) ────────────────────
def _ws_record(path):
    return logging.LogRecord("uvicorn.error", logging.INFO, __file__, 1,
                             '%s - "WebSocket %s" [accepted]', ("1.2.3.4:1", path), None)


def test_filter_ตัด_query_string_ออกจาก_args():
    from core.observability import DropQueryStringFilter
    rec = _ws_record("/ws/voice/kwan?session_id=s&token=SECRET")
    assert DropQueryStringFilter().filter(rec) is True
    assert rec.args == ("1.2.3.4:1", "/ws/voice/kwan") and "SECRET" not in rec.getMessage()
    rec2 = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1,
                             '%s - "%s %s HTTP/%s" %d', ("c", "GET", "/api/x?token=S", "1.1", 200), None)
    DropQueryStringFilter().filter(rec2)
    assert rec2.args[2] == "/api/x"


def test_filter_ติดตั้งบน_uvicorn_loggers_และรอด_dictConfig_ของ_uvicorn():
    import logging.config
    import uvicorn.config
    from core.observability import DropQueryStringFilter, install_uvicorn_redaction
    install_uvicorn_redaction()
    logging.config.dictConfig(uvicorn.config.LOGGING_CONFIG)  # สิ่งที่ uvicorn.run ทำตอน start
    install_uvicorn_redaction()  # lifespan เรียกซ้ำ — ต้อง idempotent
    for name in ("uvicorn.access", "uvicorn.error"):
        fs = [f for f in logging.getLogger(name).filters if isinstance(f, DropQueryStringFilter)]
        assert len(fs) == 1, name
