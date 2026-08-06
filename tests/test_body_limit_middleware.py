"""เพดาน body ระดับ ASGI — กันไฟล์ลงดิสก์ตอน parse multipart

ที่มา (วัดจริงบน prod 2026-08-06): ยิง multipart 315 MB ไปที่ `/api/upload`
ได้ **413 ถูกต้อง** แต่กว่าจะได้ 413 นั้น **313.3 MB ถูกเขียนลงดิสก์ไปแล้ว**

เพราะ `read_capped(file, ...)` อยู่ใน handler ซึ่งรัน *หลัง* FastAPI แกะฟอร์มเสร็จ —
starlette เขียน file part ลง `SpooledTemporaryFile` (spool 1 MB) ตั้งแต่ตอน parse
⇒ `read_capped()` กันได้แค่ RAM ไม่ได้กันดิสก์ (คนละ lever ตามที่ CLAUDE.md เตือนไว้)

⚠️ **ไฟล์ spool ถูก `unlink` ทันทีที่สร้าง** — `os.scandir("/tmp")` มองไม่เห็นเลย
วัดรอบแรกด้วย scandir ได้ 0 MB แล้วเกือบสรุปว่า "ไม่ลงดิสก์" · ต้องดู `/proc/<pid>/fd`
ที่ชี้ไป `(deleted)` ถึงจะเห็นของจริง

ทางแก้: middleware ระดับ ASGI ที่นับไบต์ของ body **ก่อน** ส่งต่อให้ parser
"""

import io

import pytest
from fastapi.testclient import TestClient

import server
from core.body_limit import BodySizeLimitMiddleware
from utils.http_limits import MAX_BODY_BYTES

client = TestClient(server.app)

BOUNDARY = "----testboundary"


def _multipart(size: int) -> tuple[bytes, dict]:
    head = (
        f"--{BOUNDARY}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="big.txt"\r\n'
        f"Content-Type: text/plain\r\n\r\n"
    ).encode()
    body = head + b"x" * size + f"\r\n--{BOUNDARY}--\r\n".encode()
    return body, {"Content-Type": f"multipart/form-data; boundary={BOUNDARY}"}


# ── พฤติกรรมที่ผู้ใช้เห็น ──────────────────────────────────────────────────────

def test_multipart_เกินเพดานได้_413():
    body, headers = _multipart(MAX_BODY_BYTES + 1024)
    r = client.post("/api/upload", content=body, headers=headers)
    assert r.status_code == 413, r.text


def test_multipart_เล็กยังอัปได้ปกติ():
    """กลุ่มควบคุม — ถ้า middleware กันเข้มไป เทสข้างบนก็ยังเขียว"""
    r = client.post("/api/upload",
                    files={"file": ("small.txt", io.BytesIO(b"hello"), "text/plain")})
    assert r.status_code != 413, r.text


def test_json_เกินเพดานยังได้_413_เหมือนเดิม():
    """middleware ต้องไม่ทำให้เส้น JSON ที่ปิดไปแล้วเปลี่ยนพฤติกรรม"""
    r = client.post("/api/chat", content=b'{"prompt":"' + b"x" * MAX_BODY_BYTES + b'"}',
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_GET_ไม่ถูกแตะ():
    assert client.get("/api/config").status_code == 200


# ── ระดับ ASGI: parser ต้องไม่เคยเห็นไบต์เกินเพดาน ──────────────────────────────
# นี่คือหัวใจ — 413 อย่างเดียวไม่พอ ต้องพิสูจน์ว่า "ตัดก่อนถึง parser" จริง

class _Spy:
    """ASGI app ปลอม — ดูดทั้ง body แล้วจำว่าได้รับไปกี่ไบต์"""

    def __init__(self):
        self.received = 0
        self.called = False

    async def __call__(self, scope, receive, send):
        self.called = True
        while True:
            msg = await receive()
            if msg["type"] == "http.request":
                self.received += len(msg.get("body", b""))
                if not msg.get("more_body"):
                    break
            elif msg["type"] == "http.disconnect":
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


async def _run(mw, body: bytes, headers: list, chunk: int = 64 * 1024):
    scope = {"type": "http", "method": "POST", "path": "/x", "headers": headers}
    parts = [body[i:i + chunk] for i in range(0, len(body), chunk)] or [b""]
    it = iter(parts)

    async def receive():
        try:
            p = next(it)
        except StopIteration:
            return {"type": "http.disconnect"}
        return {"type": "http.request", "body": p, "more_body": True}

    sent = []

    async def send(msg):
        sent.append(msg)

    await mw(scope, receive, send)
    start = next((m for m in sent if m["type"] == "http.response.start"), None)
    return (start or {}).get("status"), sent


@pytest.mark.asyncio
async def test_parser_ไม่เคยเห็นไบต์เกินเพดาน():
    """ต่อให้ client โกหก content-length ก็ต้องตัดตอนอ่านสตรีมจริง"""
    spy = _Spy()
    mw = BodySizeLimitMiddleware(spy, max_bytes=256 * 1024)
    status, _ = await _run(mw, b"y" * (2 * 1024 * 1024), headers=[])   # ไม่ส่ง content-length

    assert status == 413
    # ยอมให้เกินได้ไม่เกิน 1 chunk (รู้ตัวตอนอ่าน chunk ที่ทำให้เกิน)
    assert spy.received <= 256 * 1024 + 64 * 1024, f"parser ได้รับไป {spy.received} ไบต์"


@pytest.mark.asyncio
async def test_content_length_เกิน_ต้องไม่เรียก_app_เลย():
    """ถูกที่สุด: ปฏิเสธตั้งแต่เห็น header ไม่ต้องแตะ body สักไบต์"""
    spy = _Spy()
    mw = BodySizeLimitMiddleware(spy, max_bytes=1024)
    status, _ = await _run(mw, b"z" * 4096,
                           headers=[(b"content-length", b"999999999")])

    assert status == 413
    assert spy.called is False, "ไม่ควรเรียก app เลยเมื่อ content-length บอกว่าเกิน"


@pytest.mark.asyncio
async def test_body_ปกติต้องถึง_app_ครบทุกไบต์():
    """กลุ่มควบคุม — ถ้า middleware ตัดมั่ว เทสสองอันบนก็ยังเขียว"""
    spy = _Spy()
    mw = BodySizeLimitMiddleware(spy, max_bytes=1024 * 1024)
    payload = b"a" * (300 * 1024)
    status, _ = await _run(mw, payload, headers=[(b"content-length", str(len(payload)).encode())])

    assert status == 200
    assert spy.received == len(payload), f"ได้ {spy.received} ควรได้ {len(payload)}"


@pytest.mark.asyncio
async def test_ไม่แตะ_scope_ที่ไม่ใช่_http():
    """WebSocket ต้องผ่านไป **แบบไม่ถูกห่อ** — ส่ง receive/send ตัวเดิมต่อไปเลย

    ⚠️ เช็คแค่ "app ถูกเรียก" ไม่พอ — mutation test พิสูจน์แล้วว่าถ้าถอดเงื่อนไข
    scope ทิ้ง app ก็ยัง *ถูกเรียก* อยู่ดี (แค่ได้ receive/send ที่ถูกห่อไปแทน)
    ต้องเทียบ identity ถึงจะจับได้
    """
    seen = {}

    async def app(scope, receive, send):
        seen.update(type=scope["type"], recv=receive, send=send)

    async def orig_recv():
        return {"type": "websocket.receive"}

    async def orig_send(m):
        pass

    mw = BodySizeLimitMiddleware(app, max_bytes=10)
    await mw({"type": "websocket", "path": "/ws"}, orig_recv, orig_send)

    assert seen["type"] == "websocket"
    assert seen["recv"] is orig_recv, "receive ถูกห่อ — middleware ไม่ควรแตะ scope ที่ไม่ใช่ http"
    assert seen["send"] is orig_send, "send ถูกห่อ"


@pytest.mark.asyncio
async def test_GET_ที่มี_body_ใหญ่ก็ต้องไม่ถูกตัด():
    """GET/HEAD/DELETE ไม่อยู่ใน _BODY_METHODS — ต้องผ่านแม้ body ใหญ่กว่าเพดาน

    ⚠️ เดิมเทสนี้ส่ง body ว่างจึงจับ mutation "เพิ่ม GET เข้า _BODY_METHODS" ไม่ได้
    ต้องส่งของที่ใหญ่เกินเพดานจริงถึงจะพิสูจน์ว่ามันไม่ถูกนับ
    """
    spy = _Spy()
    mw = BodySizeLimitMiddleware(spy, max_bytes=1024)
    payload = b"g" * (8 * 1024)          # ใหญ่กว่าเพดาน 8 เท่า
    scope = {"type": "http", "method": "GET", "path": "/x",
             "headers": [(b"content-length", str(len(payload)).encode())]}

    async def receive():
        return {"type": "http.request", "body": payload, "more_body": False}

    sent = []

    async def send(msg):
        sent.append(msg)

    await mw(scope, receive, send)
    status = next((m for m in sent if m["type"] == "http.response.start"), {}).get("status")

    assert spy.called is True
    assert status == 200, f"GET ถูกตัดทั้งที่ไม่ควรนับ → {status}"
    assert spy.received == len(payload)
