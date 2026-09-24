"""Rate limiting + brute-force lockout — สำหรับ public exposure (ผ่าน Cloudflare)

2 ชั้น (in-memory, per-client-IP, thread-safe):
  1. request rate   — จำกัด req/นาที/IP (กัน abuse/scrape)
  2. auth-fail lockout — ถ้า 401 บ่อยเกินใน window → block IP ชั่วคราว (กัน brute-force token)

LAN/loopback bypass (ใช้ core.auth.is_local_request). ปิดได้ด้วย RATE_LIMIT_ENABLED=false
client key: cf-connecting-ip (ถ้าผ่าน Cloudflare) → ไม่งั้น TCP peer IP
"""
import threading
import time
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse

from core.auth import LOGIN_PATH, is_local_request
from core.env_registry import env_bool, env_float, env_int

# env ของ rate limit — ไฟล์นี้เป็นเจ้าของ 5 ชื่อ (ก้อน 4 · 2026-09-24 · ตัวกัน: tests/test_env_registry.py)
# conftest ตั้ง RATE_LIMIT_ENABLED=false ก่อน import ⇒ อ่านระดับโมดูลได้ (test_ratelimit เปิดเองผ่าน monkeypatch)
_G = "Rate Limiting"
_ENABLED = env_bool("RATE_LIMIT_ENABLED", True, group=_G,
                    doc="false = ปิดทั้ง rate limit และ brute-force lockout (LAN/loopback bypass อยู่แล้ว)")
_RPM = env_int("RATE_LIMIT_RPM", 120, group=_G, doc="คำขอ/นาที/IP (เกิน = 429)")
_WINDOW = 60.0
_AUTH_FAIL_MAX = env_int("AUTH_FAIL_MAX", 8, group=_G,
                         doc="401 กี่ครั้งใน AUTH_FAIL_WINDOW ก่อน lock IP (นับเฉพาะที่ส่ง x-auth-token ผิด หรือ /api/auth/login)")
_AUTH_FAIL_WINDOW = env_float("AUTH_FAIL_WINDOW", 300.0, group=_G, doc="วินาทีของหน้าต่างนับ 401")
_MAX_KEYS = env_int("RATE_LIMIT_MAX_KEYS", 50000, group=_G,
                    doc="จำนวน IP สูงสุดที่ track พร้อมกัน (กัน memory DoS จาก IP สุ่ม)")


class SlidingWindowLimiter:
    """นับ event ต่อ key ใน sliding window — thread-safe

    กัน memory DoS (C1): sweep ลบ key ที่ deque ว่างเป็นช่วงๆ + cap จำนวน key.
    over_limit (peek) ไม่สร้าง key ใหม่ — ไม่งั้นทุก IP ที่เช็คจะค้างใน dict ตลอดไป
    """

    def __init__(self, limit: int, window: float, max_keys: int = _MAX_KEYS):
        self.limit = limit
        self.window = window
        self.max_keys = max(1, max_keys)
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()
        self._last_sweep = 0.0

    def _prune(self, dq: deque, now: float) -> None:
        cutoff = now - self.window
        while dq and dq[0] < cutoff:
            dq.popleft()

    def _maybe_sweep(self, now: float) -> None:
        """ลบ key ที่หมดอายุทั้งหมด — เรียกเป็นช่วงๆ (ทุก window) ใต้ _lock"""
        if now - self._last_sweep < self.window:
            return
        self._last_sweep = now
        for k in list(self._hits.keys()):
            self._prune(self._hits[k], now)
            if not self._hits[k]:
                del self._hits[k]

    def _cap(self) -> None:
        """กัน burst โจมตี (many distinct keys ใน window เดียว) — drop จนต่ำกว่า cap"""
        while len(self._hits) > self.max_keys:
            self._hits.popitem()   # O(1), drop arbitrary — bound memory

    def hit(self, key: str) -> tuple[bool, int]:
        """บันทึก 1 hit → (allowed, retry_after_sec). allowed=True = "ผ่าน" (ยังไม่เกิน limit)
        ⚠️ N3: bool กลับด้านกับ over_limit — hit คืน allowed(True=ดี), over_limit คืน is_over(True=แย่)"""
        now = time.time()
        with self._lock:
            self._maybe_sweep(now)
            dq = self._hits[key]
            self._prune(dq, now)
            if len(dq) >= self.limit:
                return False, max(1, round(self.window - (now - dq[0])))
            dq.append(now)
            self._cap()
            return True, 0

    def over_limit(self, key: str) -> tuple[bool, int]:
        """peek (ไม่บันทึก/ไม่สร้าง key) → (is_over, retry_after_sec). is_over=True = "เกิน/ควร block"
        ⚠️ N3: bool กลับด้านกับ hit (ดู hit). call site ใช้ตัวแปร `blocked` ให้ชัด"""
        now = time.time()
        with self._lock:
            dq = self._hits.get(key)        # ไม่ใช้ [] เพื่อไม่สร้าง key ว่างทิ้งไว้
            if not dq:
                return False, 0
            self._prune(dq, now)
            if not dq:
                del self._hits[key]         # ว่างหลัง prune → เก็บกวาด
                return False, 0
            if len(dq) >= self.limit:
                return True, max(1, round(self.window - (now - dq[0])))
            return False, 0

    def record(self, key: str) -> None:
        """บันทึก event โดยไม่เช็ค limit (ใช้นับ auth failure)"""
        now = time.time()
        with self._lock:
            self._maybe_sweep(now)
            dq = self._hits[key]
            self._prune(dq, now)
            dq.append(now)
            self._cap()

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
            self._last_sweep = 0.0

    def reset_key(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)


_req_limiter = SlidingWindowLimiter(_RPM, _WINDOW)
_authfail_limiter = SlidingWindowLimiter(_AUTH_FAIL_MAX, _AUTH_FAIL_WINDOW)


def websocket_auth_ok(websocket, token: str = "", authorize=None) -> bool:
    """gate ของ WS ที่เข้า lockout เดียวกับ HTTP (audit 09-24 ข้อ 7 — WS ไม่ผ่าน middleware http)

    · IP ที่ถูก lock อยู่ → ปฏิเสธแม้ token ถูก (เหมือน 429 ฝั่ง http)
    · ล้มโดย**มี credential แนบมา** (query/cookie) → นับเข้า `_authfail_limiter` · ไม่มี credential = ไม่นับ
      (browser ที่ยังไม่ login ไม่ควรถูก lock)
    """
    from core.auth import SESSION_COOKIE, websocket_authorized
    authorize = authorize or websocket_authorized   # server.py ส่ง `websocket_authorized` ของตัวเองมา (เทส patch ได้)
    if not _ENABLED or is_local_request(websocket):
        return authorize(websocket, token)
    key = client_key(websocket)
    if _authfail_limiter.over_limit(key)[0]:
        return False
    ok = authorize(websocket, token)
    if not ok and (token or websocket.cookies.get(SESSION_COOKIE)):
        _authfail_limiter.record(key)
    return ok


def unlock_ip(ip: str) -> None:
    """ล้าง auth-fail lock สำหรับ IP นั้น — เรียกจาก admin endpoint (LAN-only)"""
    _authfail_limiter.reset_key(ip)


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

    # บันทึกก่อน call (body อ่านซ้ำไม่ได้ แต่ header/path อ่านได้)
    # login ส่งรหัสใน body ไม่ใช่ header → ต้องดูจาก path ไม่งั้น endpoint เดียวที่ lockout
    # มีไว้ป้องกันจะไม่เคยถูกนับเลย (เดารหัสได้ไม่จำกัด ติดแค่ RPM)
    is_credential_attempt = (bool(request.headers.get("x-auth-token", "").strip())
                             or request.url.path == LOGIN_PATH)

    response = await call_next(request)

    # นับ auth failure เฉพาะ request ที่ "พยายามใช้ credential แล้วผิด" (brute-force จริง)
    # request เปล่าที่ 401 = client ยังไม่ได้ login → ไม่นับ (กัน false lockout ตอนโหลดหน้า)
    if response.status_code == 401 and is_credential_attempt:
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
