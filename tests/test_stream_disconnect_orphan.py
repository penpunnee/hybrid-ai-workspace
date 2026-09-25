"""client ตัดสายกลาง stream (กด Stop / ปิด tab) ต้องไม่ทิ้ง user message เป็น orphan (audit 2026-09-24 MEDIUM)

`generate()` ใน routers/chat.py มี `except Exception` + `_save_crash()` สำหรับ stream พัง แต่การที่ client
หายไปมาถึง generator เป็น **GeneratorExit** (BaseException) ตอน starlette ปิด generator → ไม่เข้า except →
ไม่ save assistant → history เหลือ user เดี่ยว · ผลพวง: /api/regenerate ที่ตามมาจะลบ **A1** ทิ้ง
(ดู test_regenerate_history_integrity.py)

พิสูจน์ที่ระดับ ASGI กับ app จริง: `send` โยนหลังได้ chunk ที่ 2 = uvicorn เจอ client disconnect
"""

import asyncio
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import app
import routers.chat as chatmod
from utils.history import load_history

BODY = ('{"assistant":"kwan","session_id":"%s","prompt":"ยิงแล้วตัดสาย","provider":"ollama",'
        '"active_learning":false,"response_cache":false}')


class _ClientGone(Exception):
    pass


async def _post_then_drop(session_id: str, drop_after_chunks: int):
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
        "scheme": "http", "path": "/api/chat", "raw_path": b"/api/chat", "query_string": b"",
        "root_path": "", "headers": [(b"host", b"t"), (b"content-type", b"application/json")],
        "client": ("127.0.0.1", 1), "server": ("t", 80),
    }
    body = (BODY % session_id).encode()
    delivered = False
    gone = asyncio.Event()

    async def receive():
        # uvicorn: หลัง body แล้ว receive() จะ *รอ* จนกว่า client จะหายไป ถึงคืน http.disconnect
        # (คืนทันที = Starlette ยกเลิก stream ก่อน generator เริ่ม — เทสจะแดงผิดเหตุ)
        nonlocal delivered
        if delivered:
            await gone.wait()
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": body, "more_body": False}

    chunks = 0
    meta = {"status": None}

    async def send(msg):
        nonlocal chunks
        if msg["type"] == "http.response.start":
            meta["status"] = msg["status"]
        if msg["type"] == "http.response.body" and b'"chunk"' in (msg.get("body") or b""):
            chunks += 1
            if chunks >= drop_after_chunks:
                gone.set()          # client ปิด tab / กด Stop → Starlette ยกเลิก stream → generator ถูก close

    await app(scope, receive, send)
    # generator ถูกปิดใน threadpool — รอให้ GeneratorExit/finally ทำงานจบ
    await asyncio.sleep(0.5)
    assert meta["status"] == 200, f"request ไม่ถึง handler: {meta}"


def _slow_stream(messages, **k):
    import time
    for i in range(6):
        time.sleep(0.02)
        yield f"ท่อน{i} "


@pytest.mark.xfail(strict=True, reason="audit MEDIUM ก้อน 6 — เทสแดงที่เขียนไว้ก่อน ยังไม่แก้ (devlog [2026-09-25 ปิดเซสชัน]) · ถอด marker นี้ตอนเริ่มแก้")
@pytest.mark.asyncio
async def test_client_ตัดสายกลาง_stream_ต้องไม่เหลือ_user_orphan(monkeypatch):
    monkeypatch.setattr(chatmod, "stream_response", _slow_stream)
    sid = "s_disconnect_1"
    with patch.object(chatmod, "remember") as rem, patch.object(chatmod, "teach", return_value=False):
        await _post_then_drop(sid, drop_after_chunks=2)
    history = load_history("kwan", sid)
    roles = [m["role"] for m in history]
    assert roles[:1] == ["user"], f"user message ต้องถูก save ก่อนเสมอ ({roles})"
    assert "assistant" in roles, f"client ตัดสาย → ต้อง save คำตอบบางส่วนคู่กัน ไม่ทิ้ง orphan ({roles})"
    a = next(m for m in history if m["role"] == "assistant")
    assert "ท่อน0" in a["content"], "ของที่ stream ไปแล้วต้องไม่หาย"
    assert "หยุดกลางคัน" in a["content"] or "ตัดสาย" in a["content"], "ต้องบอกว่าคำตอบไม่สมบูรณ์"
    rem.assert_not_called()   # คำตอบไม่สมบูรณ์ห้ามเข้า episodic memory


@pytest.mark.asyncio
async def test_กลุ่มควบคุม_stream_จบปกติ_ยัง_save_เหมือนเดิม(monkeypatch):
    monkeypatch.setattr(chatmod, "stream_response", _slow_stream)
    sid = "s_disconnect_ctrl"
    with patch.object(chatmod, "remember"), patch.object(chatmod, "teach", return_value=False):
        await _post_then_drop(sid, drop_after_chunks=10 ** 6)   # ไม่ตัดสาย
    history = load_history("kwan", sid)
    assert [m["role"] for m in history] == ["user", "assistant"]
    assert "หยุดกลางคัน" not in history[1]["content"]
