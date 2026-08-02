"""Tests: /api/chat และ /api/regenerate ต้อง save คำตอบบางส่วนก่อน return
เมื่อ stream พังกลางคัน (พบจาก audit 2026-08-01)

เดิม: stream_response() โยน exception ที่ไม่ใช่ GeminiQuotaExhausted/GeminiUnavailable
(หรือ fallback เองก็พังอีก) → generator yield error event แล้ว return ทันที
โดยไม่เคย save_message() คำตอบที่ full_response สะสมไว้แล้ว (ที่ user เห็น
stream มาบนจอแล้วบางส่วน) → reload แล้วหายไป + user message กลายเป็น orphan
ไม่มีคำตอบคู่ใน history
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
import server
import routers.chat as chatmod
from utils.history import load_history

client = TestClient(server.app)


def test_chat_saves_partial_answer_when_stream_crashes_midway(monkeypatch):
    def crashing_stream(messages, **k):
        yield "ตอบไปครึ่งทาง"
        raise RuntimeError("boom - LM Studio connection dropped")

    monkeypatch.setattr(chatmod, "stream_response", crashing_stream)
    session_id = "crash-test-1"
    r = client.post("/api/chat", json={
        "session_id": session_id,
        "assistant": "kwan",
        "prompt": "คำถามทดสอบ",
        "provider": "ollama",
        "active_learning": False,
        "response_cache": False,
    })
    assert r.status_code == 200
    _ = r.text  # consume SSE → generator รันจนจบ

    history = load_history("kwan", session_id)
    roles = [m["role"] for m in history]
    assert "user" in roles, "user message ต้องถูก save เหมือนเดิม"
    assert "assistant" in roles, "assistant ต้อง save คำตอบ (แม้พัง) ไม่ปล่อยเป็น orphan"

    assistant_msg = next(m for m in history if m["role"] == "assistant")
    assert "ตอบไปครึ่งทาง" in assistant_msg["content"], "คำตอบบางส่วนที่ stream มาแล้วต้องไม่หาย"
    assert "boom" in assistant_msg["content"] or "หยุดกลางคัน" in assistant_msg["content"]


def test_chat_saves_error_notice_when_stream_crashes_before_any_chunk(monkeypatch):
    def crashing_stream(messages, **k):
        raise RuntimeError("boom - crashed immediately")
        yield  # pragma: no cover (unreachable, makes this a generator)

    monkeypatch.setattr(chatmod, "stream_response", crashing_stream)
    session_id = "crash-test-2"
    r = client.post("/api/chat", json={
        "session_id": session_id,
        "assistant": "kwan",
        "prompt": "คำถามทดสอบ 2",
        "provider": "ollama",
        "active_learning": False,
        "response_cache": False,
    })
    assert r.status_code == 200
    _ = r.text

    history = load_history("kwan", session_id)
    roles = [m["role"] for m in history]
    assert "assistant" in roles, "แม้ไม่มี chunk เลยสักตัว ก็ต้อง save error notice กันข้อความ user เป็น orphan"


def test_regenerate_saves_partial_answer_when_stream_crashes_midway(monkeypatch):
    session_id = "crash-regen-1"
    # ตั้ง history เดิมไว้ก่อน (user + assistant) ให้ regenerate มีอะไรให้ลบ/สร้างใหม่
    from utils.history import save_message
    save_message("kwan", "user", "คำถามเดิม", "ollama", session_id)
    save_message("kwan", "assistant", "คำตอบเดิม", "ollama", session_id)

    def crashing_stream(messages, **k):
        yield "กำลังตอบ"
        raise RuntimeError("boom - regen crash")

    monkeypatch.setattr(chatmod, "stream_response", crashing_stream)
    r = client.post("/api/regenerate", json={
        "session_id": session_id,
        "assistant": "kwan",
        "provider": "ollama",
    })
    assert r.status_code == 200
    _ = r.text

    history = load_history("kwan", session_id)
    assistant_msgs = [m for m in history if m["role"] == "assistant"]
    assert assistant_msgs, "regenerate พังแล้วต้องยังมี assistant reply คู่ user message อยู่ (ไม่ใช่ orphan)"
    assert "กำลังตอบ" in assistant_msgs[-1]["content"]
