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


@pytest.mark.asyncio
async def test_ตัดสายหลังคำตอบ_save_แล้ว_ต้องไม่บันทึกซ้ำ(monkeypatch):
    """ตัดสายตอน chunk สุดท้าย: inner จะ save คำตอบเต็มก่อนถึง `done` แล้ว CancelledError
    ค่อยมาถึง wrapper → ต้องเห็นว่า assistant ถูก save แล้ว ห้ามบันทึก "หยุดกลางคัน" ซ้ำอีกใบ"""
    monkeypatch.setattr(chatmod, "stream_response", _slow_stream)
    sid = "s_disconnect_after_save"
    with patch.object(chatmod, "remember"), patch.object(chatmod, "teach", return_value=False):
        await _post_then_drop(sid, drop_after_chunks=6)   # _slow_stream มี 6 chunk พอดี
    history = load_history("kwan", sid)
    roles = [m["role"] for m in history]
    assert roles == ["user", "assistant"], f"ต้องมีคู่เดียว ไม่บันทึกซ้ำ ({roles})"
    assert "หยุดกลางคัน" not in history[1]["content"]
    assert "ท่อน5" in history[1]["content"]


@pytest.mark.asyncio
async def test_ตัดสายแล้วมีคำตอบใหม่มาก่อน_ต้องไม่ต่อฟองซ้ำ(monkeypatch):
    """เห็นจริงบน prod 09-25: CancelledError มาถึง wrapper ช้า 63 วิ (anyio รอ thread ที่ค้างรอ
    qwen คิด) — ถ้าระหว่างนั้น user กด regenerate จนได้คำตอบใหม่แล้ว handler ต้องเห็นว่ามีคำตอบ
    คู่ user message แล้วและข้าม ไม่บันทึก "หยุดกลางคัน" ต่อท้ายเป็นฟองเกิน
    จำลอง: chunk ที่ 3 (ซึ่ง thread กำลังทำอยู่ตอนถูก cancel) แทรก assistant row เหมือน regenerate ตอบ"""
    from utils.history import save_message
    sid = "s_disconnect_regen_race"

    def _stream_with_regen(messages, **k):
        import time
        yield "ท่อน0 "
        yield "ท่อน1 "
        save_message("kwan", "assistant", "คำตอบจาก regenerate", "ollama", sid)   # มาก่อน handler เสมอ
        time.sleep(0.05)
        yield "ท่อน2 "

    monkeypatch.setattr(chatmod, "stream_response", _stream_with_regen)
    with patch.object(chatmod, "remember"), patch.object(chatmod, "teach", return_value=False):
        await _post_then_drop(sid, drop_after_chunks=2)
    history = load_history("kwan", sid)
    contents = [m["content"] for m in history]
    assert contents == ["ยิงแล้วตัดสาย", "คำตอบจาก regenerate"], f"ห้ามต่อฟอง 'หยุดกลางคัน' ซ้ำ ({contents})"


@pytest.mark.asyncio
async def test_ตัดสายใน_session_ที่มี_turn_เก่า_ต้องยังบันทึกคู่(monkeypatch):
    """กลุ่มควบคุมของ guard `has_reply_after`: คำตอบของ turn *ก่อนหน้า* (A1) ต้องไม่ถูกนับว่า
    "ตอบ U2 แล้ว" — ไม่งั้น session ที่คุยมาก่อนจะกลับไปทิ้ง orphan เหมือนเดิม (mutation จับได้)"""
    from utils.history import save_message
    sid = "s_disconnect_prev_turn"
    save_message("kwan", "user", "U1", "ollama", sid)
    save_message("kwan", "assistant", "A1", "ollama", sid)
    monkeypatch.setattr(chatmod, "stream_response", _slow_stream)
    with patch.object(chatmod, "remember"), patch.object(chatmod, "teach", return_value=False):
        await _post_then_drop(sid, drop_after_chunks=2)
    history = load_history("kwan", sid)
    roles = [m["role"] for m in history]
    assert roles == ["user", "assistant", "user", "assistant"], f"turn ใหม่ต้องได้คู่ของตัวเอง ({roles})"
    assert "หยุดกลางคัน" in history[3]["content"]
