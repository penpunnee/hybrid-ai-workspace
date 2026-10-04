"""ไทม์ไลน์ tool + บรรทัด `↓ N tokens · วิ · t/s` ต้องรอดรีเฟรช (งานเปิด ฌ · user ขอจดไว้ ต่อ 86)

เดิมทั้งสองอย่างเกิดจาก SSE ระหว่าง stream เท่านั้น ไม่ลง DB ⇒ รีเฟรช/เปิด session เก่า = หาย
เก็บเป็น `messages.meta` (JSON) ตอนบันทึกคำตอบ · `/api/history` ส่งกลับ · React สร้างคืน
"""
import json

from fastapi.testclient import TestClient

import routers.chat as chatmod
import server
from utils.history import load_history, save_message, save_message_meta

client = TestClient(server.app)


def _hist(assistant, sid):
    r = client.get(f"/api/history/{assistant}/{sid}")
    assert r.status_code == 200
    return r.json()


def test_meta_roundtrip_and_absent_is_none():
    a = save_message("kwan", "assistant", "x", "lmstudio", "meta-db-1")
    b = save_message("kwan", "assistant", "y", "lmstudio", "meta-db-1")
    save_message_meta(a, {"elapsed_ms": 1234, "usage": {"output_tokens": 5}})
    rows = load_history("kwan", "meta-db-1", include_meta=True)
    by = {r["db_id"]: r for r in rows}
    assert by[a]["meta"] == {"elapsed_ms": 1234, "usage": {"output_tokens": 5}}
    assert by[b]["meta"] is None


def test_chat_reply_meta_survives_reload(monkeypatch):
    def fake_stream(messages, usage_sink=None, **k):
        yield "คำตอบ"
        usage_sink.update({"input_tokens": 12, "output_tokens": 34})
    monkeypatch.setattr(chatmod, "stream_response", fake_stream)
    r = client.post("/api/chat", json={"session_id": "meta-chat-1", "assistant": "kwan", "prompt": "ทดสอบ meta",
                                       "provider": "ollama", "active_learning": False, "response_cache": False})
    assert r.status_code == 200
    ai = [m for m in _hist("kwan", "meta-chat-1") if m["role"] == "assistant"][-1]
    meta = ai["meta"]
    assert meta["usage"] == {"input_tokens": 12, "output_tokens": 34}
    assert isinstance(meta["elapsed_ms"], int) and meta["elapsed_ms"] >= 0
    assert isinstance(meta["started_at_ms"], int) and meta["started_at_ms"] > 1_700_000_000_000
    assert "agent_steps" not in meta


def test_agent_reply_meta_keeps_timeline(monkeypatch):
    import agents.orchestrator as orch

    def fake_agent(messages, usage_sink=None, **k):
        yield ("event", {"type": "thinking", "step": 1})
        yield ("event", {"type": "tool_call", "name": "calculator", "args": {"expression": "2+2"}})
        yield ("event", {"type": "tool_result", "name": "calculator", "preview": "2+2 = 4", "length": 7})
        yield ("chunk", "ได้ 4")
        usage_sink.update({"input_tokens": 3000, "output_tokens": 80, "reasoning_tokens": 60})
    monkeypatch.setattr(orch, "run_agent", fake_agent)
    r = client.post("/api/chat", json={"session_id": "meta-agent-1", "assistant": "kwan", "prompt": "2+2",
                                       "tool_agent": True, "provider": "lmstudio", "response_cache": False})
    assert r.status_code == 200
    ai = [m for m in _hist("kwan", "meta-agent-1") if m["role"] == "assistant"][-1]
    assert ai["content"] == "ได้ 4"
    assert [s["type"] for s in ai["meta"]["agent_steps"]] == ["thinking", "tool_call", "tool_result"]
    assert ai["meta"]["usage"]["reasoning_tokens"] == 60


def test_regenerate_reply_meta(monkeypatch):
    save_message("kwan", "user", "คำถามเดิม", session_id="meta-regen-1")
    save_message("kwan", "assistant", "คำตอบเดิม", session_id="meta-regen-1")

    def fake_stream(messages, usage_sink=None, **k):
        yield "คำตอบใหม่"
        usage_sink.update({"input_tokens": 5, "output_tokens": 9})
    monkeypatch.setattr(chatmod, "stream_response", fake_stream)
    r = client.post("/api/regenerate", json={"assistant": "kwan", "session_id": "meta-regen-1"})
    assert r.status_code == 200
    ai = [m for m in _hist("kwan", "meta-regen-1") if m["role"] == "assistant"][-1]
    assert ai["content"] == "คำตอบใหม่" and ai["meta"]["usage"]["output_tokens"] == 9


def test_agent_steps_are_capped():
    from utils.history import reply_meta
    steps = [{"type": "tool_result", "name": "t", "preview": "x" * 5000, "length": 5000}] * 500
    m = reply_meta(0.0, None, steps)
    assert len(m["agent_steps"]) <= 60
    assert all(len(s.get("preview", "")) <= 300 for s in m["agent_steps"])
    assert len(json.dumps(m)) < 40_000
