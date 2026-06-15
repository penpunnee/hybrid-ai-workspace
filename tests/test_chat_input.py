"""Tests: /api/chat input sanitization (scrutinize Major 1, 2026-06-15)

`prompt` อ่านจาก `await request.json()` แบบไม่ validate type — ถ้า client ส่ง
list/dict มา จะไหลเข้า messages → crash ทุก provider (types.Part / .lower() ฯลฯ)
+ ขยะลง DB. coerce เป็น str ที่ entry point กันครบทุก provider ในที่เดียว
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
import server
import routers.chat as chatmod

client = TestClient(server.app)


def test_chat_coerces_nonstr_prompt(monkeypatch):
    cap = {}

    def fake_stream(messages, **k):
        cap["messages"] = messages
        yield "ok"

    monkeypatch.setattr(chatmod, "stream_response", fake_stream)
    r = client.post("/api/chat", json={
        "session_id": "scrut-coerce",
        "prompt": ["a", "b"],          # ❌ ไม่ใช่ str — เคยทำ crash ทุก provider
        "provider": "ollama",
        "active_learning": False,      # กัน short-circuit ถามกลับ (ไม่เรียก stream)
        "response_cache": False,       # กัน cache short-circuit
    })
    assert r.status_code == 200
    _ = r.text  # consume SSE → generator รัน → cap ถูกเซ็ต
    assert "messages" in cap, "stream_response ไม่ถูกเรียก"
    user_msgs = [m for m in cap["messages"] if m["role"] == "user"]
    assert user_msgs, "ไม่มี user message"
    assert all(isinstance(m["content"], str) for m in user_msgs), \
        f"user content ต้องเป็น str ทั้งหมด ได้ {[type(m['content']).__name__ for m in user_msgs]}"


def test_chat_normal_str_prompt_unchanged(monkeypatch):
    cap = {}

    def fake_stream(messages, **k):
        cap["messages"] = messages
        yield "ok"

    monkeypatch.setattr(chatmod, "stream_response", fake_stream)
    r = client.post("/api/chat", json={
        "session_id": "scrut-normal",
        "prompt": "สวัสดีครับ",
        "provider": "ollama",
        "active_learning": False,
        "response_cache": False,
    })
    assert r.status_code == 200
    _ = r.text
    user_msgs = [m for m in cap["messages"] if m["role"] == "user"]
    assert any(m["content"] == "สวัสดีครับ" for m in user_msgs)
