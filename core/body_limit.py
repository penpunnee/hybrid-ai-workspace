"""เพดานขนาด request body ระดับ ASGI — ตัด **ก่อน** ถึง parser

## ทำไมต้องมี ทั้งที่มี `utils/http_limits.py` แล้ว

`read_capped()` / `json_body_capped()` อยู่ **ในตัว handler** ซึ่งรันหลัง FastAPI
แกะ dependency เสร็จแล้ว สำหรับ `UploadFile = File(...)` แปลว่า `request.form()`
ทำงานจบไปแล้ว — และ starlette เขียน file part ลง `SpooledTemporaryFile`
(`spool_max_size = 1 MB`) ตั้งแต่ตอน parse

วัดจริงบน prod 2026-08-06: ยิง multipart **315 MB** ไป `/api/upload`
→ ตอบ 413 ถูกต้อง **แต่ 313.3 MB ลงดิสก์ไปแล้ว**

⇒ `read_capped()` กันได้แค่ RAM · ดิสก์ต้องกันที่ชั้นนี้ (คนละ lever)

⚠️ **ไฟล์ spool ถูก `unlink` ทันทีที่สร้าง** — `os.scandir("/tmp")` มองไม่เห็น
วัดด้วย scandir จะได้ 0 MB แล้วสรุปผิดว่า "ไม่ลงดิสก์" · ต้องดู `/proc/<pid>/fd`
ที่ชี้ไป `(deleted)`

## สองด่าน (เหมือน `utils/http_limits.py`)

1. `content-length` เกิน → ตอบ 413 **โดยไม่เรียก app เลย** (ถูกที่สุด)
2. นับไบต์จริงตอนอ่านสตรีม → กัน client ที่ไม่ส่ง `content-length` หรือโกหก

ด่านที่ 2 ยอมให้เกินได้ไม่เกิน 1 chunk (รู้ตัวตอนอ่าน chunk ที่ทำให้เกิน) —
ซึ่งยังห่างจาก `spool_max_size` ที่ 1 MB มาก
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# method ที่มี body — GET/HEAD/DELETE/OPTIONS ไม่ต้องนับ
_BODY_METHODS = frozenset({"POST", "PUT", "PATCH"})

_TOO_LARGE_BODY = b'{"detail":"body too large"}'


class _BodyTooLarge(Exception):
    """สัญญาณภายในของ middleware นี้เท่านั้น

    ⚠️ ตั้งใจ **ไม่** สืบทอด `HTTPException` — ไม่งั้น handler ที่ดัก
    `except HTTPException` (เช่น `/api/dream`, `/api/admin/unlock`) จะกลืนมันทิ้ง
    แล้วทำงานต่อด้วย body ที่ไม่ครบ
    """


class BodySizeLimitMiddleware:
    """ASGI middleware — ต้องเป็น pure ASGI ไม่ใช่ `BaseHTTPMiddleware`

    `BaseHTTPMiddleware` ให้ `Request` มา ซึ่งอ่าน body ไปแล้ว = สายเกินไป
    ที่นี่เราต้องแทรกที่ `receive` เพื่อคุมไบต์ก่อน parser จะเห็น
    """

    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        # websocket/lifespan ต้องผ่านไปเฉยๆ — middleware ที่เผลอแตะ scope อื่น
        # เคยทำ WS หลุด auth มาแล้ว (ดู CLAUDE.md: BaseHTTPMiddleware ลัดผ่าน scope ที่ไม่ใช่ http)
        if scope.get("type") != "http" or scope.get("method", "").upper() not in _BODY_METHODS:
            return await self.app(scope, receive, send)

        # ── ด่าน 1: content-length ──
        for k, v in scope.get("headers") or []:
            if k.lower() == b"content-length":
                try:
                    if int(v) > self.max_bytes:
                        logger.info(
                            "body_limit: ปฏิเสธจาก content-length %s > %s (%s %s)",
                            v.decode(errors="replace"), self.max_bytes,
                            scope.get("method"), scope.get("path"),
                        )
                        return await self._reject(send)
                except (TypeError, ValueError):
                    pass  # อ่านไม่ออก = ไม่รู้ → ปล่อยให้ด่าน 2 รับต่อ
                break

        # ── ด่าน 2: นับไบต์จริง ──
        counted = 0
        started = False

        async def recv_capped():
            nonlocal counted
            msg = await receive()
            if msg.get("type") == "http.request":
                counted += len(msg.get("body", b"") or b"")
                if counted > self.max_bytes:
                    logger.info(
                        "body_limit: ปฏิเสธตอนอ่านสตรีม %d > %d (%s %s)",
                        counted, self.max_bytes, scope.get("method"), scope.get("path"),
                    )
                    raise _BodyTooLarge
            return msg

        async def send_wrapper(msg):
            nonlocal started
            if msg.get("type") == "http.response.start":
                started = True
            await send(msg)

        try:
            await self.app(scope, recv_capped, send_wrapper)
        except _BodyTooLarge:
            if not started:
                await self._reject(send)
            # response เริ่มส่งไปแล้ว (streaming) → แก้ status ไม่ได้ ปล่อยให้ connection ขาด

    async def _reject(self, send):
        await send({
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(_TOO_LARGE_BODY)).encode()),
            ],
        })
        await send({"type": "http.response.body", "body": _TOO_LARGE_BODY})
