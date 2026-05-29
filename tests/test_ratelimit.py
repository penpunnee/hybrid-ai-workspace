"""Tests สำหรับ core/ratelimit.py + constant-time token compare (auth hardening)

limiter: clock ถูก monkeypatch (deterministic, ไม่ใช้ sleep จริง)
middleware: ทดสอบ function ตรงๆ ด้วย fake Request + async call_next
"""
import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from starlette.responses import Response

import core.ratelimit as rl
import core.auth as auth


# ── controllable clock ────────────────────────────────────────────────────────
class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(rl.time, "time", c)
    return c


# ── SlidingWindowLimiter ──────────────────────────────────────────────────────
def test_limiter_allows_up_to_limit(clock):
    lim = rl.SlidingWindowLimiter(limit=3, window=60)
    assert lim.hit("ip")[0] is True
    assert lim.hit("ip")[0] is True
    assert lim.hit("ip")[0] is True
    allowed, retry = lim.hit("ip")        # ตัวที่ 4 เกิน
    assert allowed is False and retry > 0


def test_limiter_window_expiry(clock):
    lim = rl.SlidingWindowLimiter(limit=1, window=60)
    assert lim.hit("ip")[0] is True
    assert lim.hit("ip")[0] is False      # เต็ม window
    clock.t += 61                          # ผ่าน window
    assert lim.hit("ip")[0] is True        # ปลดล็อก


def test_limiter_per_key_isolation(clock):
    lim = rl.SlidingWindowLimiter(limit=1, window=60)
    assert lim.hit("a")[0] is True
    assert lim.hit("b")[0] is True         # คนละ key → ไม่กระทบกัน
    assert lim.hit("a")[0] is False


def test_limiter_over_limit_peek_does_not_record(clock):
    lim = rl.SlidingWindowLimiter(limit=1, window=60)
    assert lim.over_limit("ip")[0] is False     # peek ไม่บันทึก
    assert lim.over_limit("ip")[0] is False     # ยังไม่เกิน เพราะ peek ไม่นับ
    lim.hit("ip")
    assert lim.over_limit("ip")[0] is True


def test_limiter_record_and_reset(clock):
    lim = rl.SlidingWindowLimiter(limit=2, window=60)
    lim.record("ip"); lim.record("ip")
    assert lim.over_limit("ip")[0] is True
    lim.reset()
    assert lim.over_limit("ip")[0] is False


# ── client_key ────────────────────────────────────────────────────────────────
# หมายเหตุ: ใช้ public IP จริง (8.8.8.8 ฯลฯ) — TEST-NET (203.0.113.x) ถูก Python 3.14
# จัดเป็น is_private=True → is_local_request bypass → rate limit ไม่ทำงาน
def _req(host="8.8.8.8", headers=None):
    return SimpleNamespace(headers=headers or {}, client=SimpleNamespace(host=host))


def test_client_key_prefers_cf_header():
    assert rl.client_key(_req(headers={"cf-connecting-ip": "9.9.9.9"})) == "9.9.9.9"


def test_client_key_falls_back_to_peer():
    assert rl.client_key(_req(host="203.0.113.5")) == "203.0.113.5"


def test_client_key_unknown_when_no_client():
    assert rl.client_key(SimpleNamespace(headers={}, client=None)) == "unknown"


# ── middleware ────────────────────────────────────────────────────────────────
@pytest.fixture
def fresh_limiters(monkeypatch, clock):
    """เปิด rate limit + ใส่ limiter เล็ก deterministic"""
    monkeypatch.setattr(rl, "_ENABLED", True)
    monkeypatch.setattr(rl, "_req_limiter", rl.SlidingWindowLimiter(limit=3, window=60))
    monkeypatch.setattr(rl, "_authfail_limiter", rl.SlidingWindowLimiter(limit=2, window=300))
    return clock


def _call_next_factory(status=200):
    async def call_next(request):
        return Response(status_code=status)
    return call_next


def _run_mw(request, status=200):
    return asyncio.run(rl.rate_limit_middleware(request, _call_next_factory(status)))


def test_mw_disabled_passes_through(monkeypatch):
    monkeypatch.setattr(rl, "_ENABLED", False)
    resp = _run_mw(_req())
    assert resp.status_code == 200


def test_mw_local_request_bypasses(fresh_limiters):
    # private IP → ไม่ถูก limit แม้ยิงเกิน
    for _ in range(10):
        resp = _run_mw(_req(host="10.0.0.5"))
        assert resp.status_code == 200


def test_mw_public_under_limit_passes(fresh_limiters):
    assert _run_mw(_req()).status_code == 200


def test_mw_public_over_limit_429(fresh_limiters):
    pub = _req(host="8.8.8.8")
    for _ in range(3):
        assert _run_mw(pub).status_code == 200
    resp = _run_mw(pub)                    # ตัวที่ 4 เกิน limit 3
    assert resp.status_code == 429
    assert resp.headers.get("Retry-After")


def test_mw_auth_fail_lockout(fresh_limiters):
    pub = _req(host="8.8.4.4")
    # 401 สองครั้ง (limit auth_fail = 2) → ครั้งถัดไปถูก lock
    assert _run_mw(pub, status=401).status_code == 401
    assert _run_mw(pub, status=401).status_code == 401
    resp = _run_mw(pub, status=200)        # over_limit ของ authfail → block ก่อนถึง route
    assert resp.status_code == 429
    assert "auth" in resp.body.decode("utf-8")


def test_mw_success_does_not_count_as_authfail(fresh_limiters):
    pub = _req(host="1.1.1.1")
    for _ in range(3):
        _run_mw(pub, status=200)
    # 200 ไม่ feed lockout → authfail ยังว่าง (ไม่ block จากสาเหตุ auth)
    assert rl._authfail_limiter.over_limit("1.1.1.1")[0] is False


# ── constant-time token compare ───────────────────────────────────────────────
def test_token_matches_correct(monkeypatch):
    monkeypatch.setattr(auth, "UI_PASSWORD", "s3cret")
    assert auth.token_matches("s3cret") is True


def test_token_matches_wrong(monkeypatch):
    monkeypatch.setattr(auth, "UI_PASSWORD", "s3cret")
    assert auth.token_matches("nope") is False
    assert auth.token_matches("") is False
    assert auth.token_matches(None) is False


def test_token_matches_false_when_password_unset(monkeypatch):
    monkeypatch.setattr(auth, "UI_PASSWORD", "")
    assert auth.token_matches("anything") is False
