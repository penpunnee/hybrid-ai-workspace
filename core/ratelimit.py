"""Rate limiting + brute-force lockout — สำหรับ public exposure (ผ่าน Cloudflare)

2 ชั้น (in-memory, per-client-IP, thread-safe):
  1. request rate   — จำกัด req/นาที/IP (กัน abuse/scrape)
  2. auth-fail lockout — ถ้า 401 บ่อยเกินใน window → block IP ชั่วคราว (กัน brute-force token)

LAN/loopback bypass (ใช้ core.auth.is_local_request). ปิดได้ด้วย RATE_LIMIT_ENABLED=false
client key: cf-connecting-ip (ถ้าผ่าน Cloudflare) → ไม่งั้น TCP peer IP
"""
import os
import threading
import time
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse

from core.auth import is_local_request

_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true"
_RPM = int(os.getenv("RATE_LIMIT_RPM", "120"))                  # req/นาที/IP
_WINDOW = 60.0
_AUTH_FAIL_MAX = int(os.getenv("AUTH_FAIL_MAX", "8"))           # 401 กี่ครั้งก่อน lock
_AUTH_FAIL_WINDOW = float(os.getenv("AUTH_FAIL_WINDOW", "300")) # 5 นาที


class SlidingWindowLimiter:
    """นับ event ต่อ key ใน sliding window — thread-safe"""

    def __init__(self, limit: int, window: float):
        self.limit = limit
        self.window = window
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, dq: deque, now: float) -> None:
        cutoff = now - self.window
        while dq and dq[0] < cutoff:
            dq.popleft()

    def hit(self, key: str) -> tuple[bool, int]:
        """บันทึก hit ถ้ายังไม่เกิน limit → (allowed, retry_after_sec)"""
        now = time.time()
        with self._lock:
            dq = self._hits[key]
            self._prune(dq, now)
            if len(dq) >= self.limit:
                return False, max(1, round(self.window - (now - dq[0])))
            dq.append(now)
            return True, 0

    def over_limit(self, key: str) -> tuple[bool, int]:
        """peek — เกิน limit ไหม (ไม่บันทึก)"""
        now = time.time()
        with self._lock:
            dq = self._hits[key]
            self._prune(dq, now)
            if len(dq) >= self.limit:
                return True, max(1, round(self.window - (now - dq[0])))
            return False, 0

    def record(self, key: str) -> None:
        """บันทึก event โดยไม่เช็ค limit (ใช้นับ auth failure)"""
        now = time.time()
        with self._lock:
            dq = self._hits[key]
            self._prune(dq, now)
            dq.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


_req_limiter = SlidingWindowLimiter(_RPM, _WINDOW)
_authfail_limiter = SlidingWindowLimiter(_AUTH_FAIL_MAX, _AUTH_FAIL_WINDOW)


def client_key(request: Request) -> str:
    """ระบุ client — cf-connecting-ip ก่อน (เชื่อ Cloudflare) ไม่งั้น TCP peer"""
    cf = request.headers.get("cf-connecting-ip")
    if cf:
        return cf.strip()
    client = request.client
    return client.host if client else "unknown"


def _429(message: str, retry_after: int) -> JSONResponse:
    return JSONResponse(
        {"error": message, "retry_after": retry_after},
        status_code=429,
        headers={"Retry-After": str(retry_after)},
    )


async def rate_limit_middleware(request: Request, call_next):
    if not _ENABLED or is_local_request(request):
        return await call_next(request)

    key = client_key(request)

    # 1. brute-force lockout — IP ที่ auth fail บ่อยเกิน → block
    blocked, retry = _authfail_limiter.over_limit(key)
    if blocked:
        return _429("too many failed auth attempts — locked out", retry)

    # 2. request rate
    allowed, retry = _req_limiter.hit(key)
    if not allowed:
        return _429("rate limit exceeded", retry)

    response = await call_next(request)

    # นับ auth failure (401 จาก auth_middleware/login) → feed lockout
    if response.status_code == 401:
        _authfail_limiter.record(key)

    return response


def reset_all() -> None:
    """รีเซ็ตทั้ง 2 limiter (ใช้ตอน test)"""
    _req_limiter.reset()
    _authfail_limiter.reset()


def stats() -> dict:
    """สำหรับ debug/monitoring"""
    return {
        "enabled": _ENABLED,
        "rpm": _RPM,
        "auth_fail_max": _AUTH_FAIL_MAX,
        "auth_fail_window": _AUTH_FAIL_WINDOW,
        "tracked_ips": len(_req_limiter._hits),
    }
