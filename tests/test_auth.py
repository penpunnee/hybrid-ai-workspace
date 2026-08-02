"""Tests สำหรับ core/auth.py — auth middleware + LAN bypass

ทำไมสำคัญ (security): `is_local_request()` ตัดสินว่าใครข้าม auth ได้
- ต้อง bypass เฉพาะ peer IP ที่เป็น LAN/loopback จริง (TCP socket)
- ต้อง **ไม่หลงเชื่อ** Cloudflare/proxy header (กัน spoof จากภายนอก)
- public client ที่เขียนข้อมูล (POST/DELETE) ต้องมี token ถูกต้อง
"""
import os
import sys
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import core.auth as auth
from core.auth import _ip_is_private, is_local_request, auth_middleware


# ── fake Request (พอสำหรับ logic ที่ middleware ใช้: url.path, method, client.host, headers) ──
class _FakeURL:
    def __init__(self, path):
        self.path = path


class _FakeClient:
    def __init__(self, host):
        self.host = host


class _FakeRequest:
    def __init__(self, path="/api/x", method="GET", host=None, headers=None):
        self.url = _FakeURL(path)
        self.method = method
        self.client = _FakeClient(host) if host is not None else None
        self.headers = headers or {}


async def _ok(_req):
    return "PASSED"


def _run_mw(req):
    return asyncio.run(auth_middleware(req, _ok))


# ─────────────────────────────────────────────────────────────
# _ip_is_private
# ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("ip", ["192.168.1.10", "10.0.0.5", "172.16.0.1", "127.0.0.1", "::1"])
def test_ip_is_private_true(ip):
    assert _ip_is_private(ip) is True


@pytest.mark.parametrize("ip", ["8.8.8.8", "1.1.1.1", "9.9.9.9", "", "not-an-ip", None])
def test_ip_is_private_false(ip):
    assert _ip_is_private(ip) is False


# ─────────────────────────────────────────────────────────────
# is_local_request
# ─────────────────────────────────────────────────────────────
def test_lan_peer_is_local():
    assert is_local_request(_FakeRequest(host="192.168.51.49")) is True


def test_loopback_peer_is_local():
    assert is_local_request(_FakeRequest(host="127.0.0.1")) is True


def test_public_peer_is_not_local():
    assert is_local_request(_FakeRequest(host="8.8.8.8")) is False


def test_no_client_is_not_local():
    assert is_local_request(_FakeRequest(host=None)) is False


def test_cloudflare_header_forces_not_local():
    """แม้ peer IP เป็น LAN แต่ถ้ามาผ่าน Cloudflare (cf-connecting-ip) → ไม่ใช่ local
    — กันกรณี tunnel origin วิ่งใน LAN เดียวกับ NAS"""
    req = _FakeRequest(host="192.168.51.49", headers={"cf-connecting-ip": "1.2.3.4"})
    assert is_local_request(req) is False


# ─────────────────────────────────────────────────────────────
# auth_middleware
# ─────────────────────────────────────────────────────────────
def test_middleware_disabled_when_no_password(monkeypatch):
    """UI_PASSWORD ว่าง = ปิด auth → ทุก request ผ่าน"""
    monkeypatch.setattr(auth, "UI_PASSWORD", "")
    req = _FakeRequest(path="/api/memory/x", method="POST", host="8.8.8.8")
    assert _run_mw(req) == "PASSED"


def test_middleware_open_path_bypasses(monkeypatch):
    monkeypatch.setattr(auth, "UI_PASSWORD", "secret")
    req = _FakeRequest(path="/api/config", method="GET", host="8.8.8.8")
    assert _run_mw(req) == "PASSED"


def test_middleware_local_request_bypasses(monkeypatch):
    monkeypatch.setattr(auth, "UI_PASSWORD", "secret")
    req = _FakeRequest(path="/api/memory/x", method="POST", host="192.168.1.5")
    assert _run_mw(req) == "PASSED"


def test_middleware_public_write_without_token_is_401(monkeypatch):
    monkeypatch.setattr(auth, "UI_PASSWORD", "secret")
    req = _FakeRequest(path="/api/memory/x", method="POST", host="8.8.8.8")
    resp = _run_mw(req)
    assert getattr(resp, "status_code", None) == 401


@pytest.mark.parametrize("path", ["/static/enhanced.js", "/assets/index.js", "/shared/tok",
                                  "/api/shared/tok", "/ws/voice/kwan", "/gen/a.png"])
def test_middleware_open_prefixes_still_pass(monkeypatch, path):
    monkeypatch.setattr(auth, "UI_PASSWORD", "secret")
    assert _run_mw(_FakeRequest(path=path, host="8.8.8.8")) == "PASSED"


@pytest.mark.parametrize("path", ["/api/sharedsecrets", "/staticky", "/gen-keys", "/wsx"])
def test_middleware_open_prefix_is_segment_bounded(monkeypatch, path):
    """prefix ต้องตรงทั้ง segment — `startswith` ดิบๆ ทำให้ route ใหม่ที่ชื่อขึ้นต้นเหมือนกัน
    (เช่น `/api/sharedsecrets`) หลุด public เงียบๆ ซึ่งขัดเจตนา fail-closed"""
    monkeypatch.setattr(auth, "UI_PASSWORD", "secret")
    resp = _run_mw(_FakeRequest(path=path, host="8.8.8.8"))
    assert getattr(resp, "status_code", None) == 401


def test_middleware_public_write_with_correct_token(monkeypatch):
    monkeypatch.setattr(auth, "UI_PASSWORD", "secret")
    req = _FakeRequest(path="/api/memory/x", method="POST", host="8.8.8.8",
                       headers={"x-auth-token": "secret"})
    assert _run_mw(req) == "PASSED"


def test_middleware_public_write_with_wrong_token_is_401(monkeypatch):
    monkeypatch.setattr(auth, "UI_PASSWORD", "secret")
    req = _FakeRequest(path="/api/memory/x", method="POST", host="8.8.8.8",
                       headers={"x-auth-token": "wrong"})
    resp = _run_mw(req)
    assert getattr(resp, "status_code", None) == 401


def test_middleware_protected_get_requires_token(monkeypatch):
    """GET ที่อยู่ใน _PROTECTED_GET_PREFIXES จาก public → ต้องมี token"""
    monkeypatch.setattr(auth, "UI_PASSWORD", "secret")
    req = _FakeRequest(path="/api/memory/list", method="GET", host="8.8.8.8")
    resp = _run_mw(req)
    assert getattr(resp, "status_code", None) == 401


def test_middleware_sensitive_get_requires_token_failclosed(monkeypatch):
    """fail-closed: GET ที่ไม่ใช่ open path จาก public → ต้องมี token
    (เดิม fail-open: vault/documents/skills/feedback/sandbox หลุดโดยไม่ต้อง token = ช่องโหว่)"""
    monkeypatch.setattr(auth, "UI_PASSWORD", "secret")
    for path in ("/api/skills", "/api/vault/stats", "/api/vault/search",
                 "/api/documents", "/api/feedback/low-rated", "/api/sandbox/info",
                 "/api/agent/tools"):
        req = _FakeRequest(path=path, method="GET", host="8.8.8.8")
        resp = _run_mw(req)
        assert getattr(resp, "status_code", None) == 401, f"{path} ควร 401 (fail-closed)"


def test_middleware_open_get_paths_allowed_public(monkeypatch):
    """open allowlist ยังเปิด public ได้ (bootstrap UI + public share link)"""
    monkeypatch.setattr(auth, "UI_PASSWORD", "secret")
    for path in ("/", "/api/status", "/api/config", "/api/health",
                 "/api/auth/check", "/api/shared/abc123", "/shared/abc123",
                 "/static/index.js"):
        req = _FakeRequest(path=path, method="GET", host="8.8.8.8")
        assert _run_mw(req) == "PASSED", f"{path} ควรเปิด public"


def test_middleware_sensitive_get_with_token_ok(monkeypatch):
    """GET sensitive + token ถูก → ผ่าน"""
    monkeypatch.setattr(auth, "UI_PASSWORD", "secret")
    req = _FakeRequest(path="/api/vault/search", method="GET", host="8.8.8.8",
                       headers={"x-auth-token": "secret"})
    assert _run_mw(req) == "PASSED"
