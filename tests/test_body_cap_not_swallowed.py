"""body เกินเพดานแบบ chunked ต้องได้ 413 และ **handler ต้องไม่ทำงาน** (audit 2026-09-24 ข้อ 11)

ทางเดินของบั๊ก: `core/body_limit.py` โยน `_BodyTooLarge` (Exception ธรรมดา ตั้งใจไม่สืบ
HTTPException) จาก `receive()` → ทะลุ `request.stream()` ใน `json_body_capped()` (loop อยู่นอก try)
→ ถึง handler ที่มี `except Exception: data = {}` (`/api/memory/cleanup` `/api/dream`
`/api/admin/unlock`) → ถูกกลืน → **รัน dream / ลบ memory / unlock IP ด้วย body ว่าง แล้วตอบ 200**
ส่วน `except _BodyTooLarge` ของ middleware ไม่เคยได้ทำงาน

ต้องพิสูจน์ที่ระดับ `app` ทั้งก้อน (ไม่ใช่ mock `json_body_capped` ให้โยน) — ไม่งั้นจะเขียวทั้งที่
ของจริงอาจตอบ 500 ถ้า exception ไปไม่ถึง `BodySizeLimitMiddleware` ผ่าน ExceptionMiddleware
"""

import ast
import pathlib
from unittest.mock import patch

import pytest

from server import app
from utils.http_limits import MAX_BODY_BYTES

_CHUNK = 256 * 1024


async def _post_chunked(path: str, total: int):
    """ยิง POST แบบไม่มี content-length (chunked) ขนาด `total` ไบต์ ตรงเข้า ASGI app จริง"""
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
        "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": b"",
        "root_path": "", "headers": [(b"host", b"testserver"), (b"content-type", b"application/json")],
        "client": ("127.0.0.1", 1234), "server": ("testserver", 80),
    }
    sent_total = 0

    async def receive():
        nonlocal sent_total
        if sent_total >= total:
            return {"type": "http.request", "body": b"", "more_body": False}
        n = min(_CHUNK, total - sent_total)
        sent_total += n
        return {"type": "http.request", "body": b"x" * n, "more_body": True}

    sent = []

    async def send(msg):
        sent.append(msg)

    await app(scope, receive, send)
    start = next((m for m in sent if m["type"] == "http.response.start"), None)
    return (start or {}).get("status"), sent


OVER = MAX_BODY_BYTES + 3 * _CHUNK


@pytest.mark.asyncio
async def test_memory_cleanup_body_เกิน_chunked_ต้อง413_และห้ามลบ():
    with patch("routers.memory.cleanup_old_memories") as fn:
        status, _ = await _post_chunked("/api/memory/cleanup", OVER)
    assert status == 413, f"ได้ {status}"
    fn.assert_not_called()


@pytest.mark.asyncio
async def test_dream_body_เกิน_chunked_ต้อง413_และห้ามรัน():
    with patch("routers.dream.run_dream_cycle") as fn:
        status, _ = await _post_chunked("/api/dream", OVER)
    assert status == 413, f"ได้ {status}"
    fn.assert_not_called()


@pytest.mark.asyncio
async def test_admin_unlock_body_เกิน_chunked_ต้อง413_และห้ามปลดล็อก():
    with patch("core.ratelimit.unlock_ip") as fn:
        status, _ = await _post_chunked("/api/admin/unlock", OVER)
    assert status == 413, f"ได้ {status}"
    fn.assert_not_called()


@pytest.mark.asyncio
async def test_กลุ่มควบคุม_body_เล็กยังถึง_handler():
    """กัน mutant ที่ปฏิเสธทุกอย่าง — chunked ปกติต้องผ่านและ handler ต้องถูกเรียก"""
    with patch("routers.memory.cleanup_old_memories", return_value={"ok": True, "deleted": 0}) as fn:
        status, _ = await _post_chunked("/api/memory/cleanup", 0)
    assert status == 200, f"ได้ {status}"
    fn.assert_called_once()


# ---------- ratchet: handler ที่เรียก json_body_capped ห้ามมี bare except ----------

_ROUTERS = pathlib.Path(__file__).resolve().parents[1] / "routers"


def _bare_except_around_capped(path: pathlib.Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    bad = []
    for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        for node in ast.walk(fn):
            if not isinstance(node, ast.Try):
                continue
            calls_capped = any(
                isinstance(c, ast.Call) and getattr(c.func, "id", getattr(c.func, "attr", "")) == "json_body_capped"
                for c in ast.walk(ast.Module(body=node.body, type_ignores=[]))
            )
            if not calls_capped:
                continue
            for h in node.handlers:
                if h.type is None or (isinstance(h.type, ast.Name) and h.type.id in ("Exception", "BaseException")):
                    bad.append(f"{path.name}:{h.lineno} ใน {fn.name}()")
    return bad


def test_ratchet_ห้ามกลืน_Exception_รอบ_json_body_capped():
    found = [b for p in sorted(_ROUTERS.glob("*.py")) for b in _bare_except_around_capped(p)]
    assert not found, (
        "`except Exception` รอบ json_body_capped() กลืน _BodyTooLarge ของ middleware "
        "แล้วรัน handler ด้วย body ว่าง — ดัก HTTPException เฉพาะ 400 พอ:\n  " + "\n  ".join(found)
    )


def test_ratchet_สแกนเจอของจริง(tmp_path):
    p = tmp_path / "r.py"
    p.write_text(
        "async def h(request):\n    try:\n        data = await json_body_capped(request, 1)\n"
        "    except Exception:\n        data = {}\n    return data\n", encoding="utf-8")
    assert _bare_except_around_capped(p) == ["r.py:4 ใน h()"]
