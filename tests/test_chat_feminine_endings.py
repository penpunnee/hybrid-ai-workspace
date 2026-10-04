"""ขวัญในแชทต้องลงท้าย ค่ะ/คะ — persona เดิมไม่ได้กำหนดคำลงท้ายไว้เลย (ต่อ 87 · 2026-10-04)

A/B ผ่าน handler แชทจริงบน prod (3 คำถาม × 2 รอบ): ให้ qwen คิดก่อน → "ครับ" 2/6 ·
ข้ามช่วงคิด (`LMSTUDIO_SKIP_THINKING`) → "ครับ" 4/6
กติกาเติมเฉพาะเส้นแชท/regenerate — **ห้ามเติมใน `ASSISTANTS[...]["system_prompt"]`**
เพราะโหมดเสียงต่อจากตัวนั้น (`voice_system_prompt`) และเสียงถูกล็อก 🔒 (sha ต้องเท่าเดิม)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
import server
import routers.chat as chatmod
from assistants.config import ASSISTANTS, voice_system_prompt
from utils.history import _get_conn

client = TestClient(server.app)
KWAN = "🧡 ขวัญ (Logic)"
RULE = "ลงท้ายด้วย ค่ะ/คะ"


def _system(messages):
    return next(m["content"] for m in messages if m["role"] == "system")


def test_แชท_system_prompt_มีกติกาคำลงท้าย(monkeypatch):
    cap = {}

    def fake_stream(messages, **k):
        cap["messages"] = messages
        yield "ok"

    monkeypatch.setattr(chatmod, "stream_response", fake_stream)
    r = client.post("/api/chat", json={
        "assistant": KWAN, "session_id": "t-fem-chat", "prompt": "สวัสดี",
        "provider": "ollama", "active_learning": False, "response_cache": False,
    })
    assert r.status_code == 200
    _ = r.text
    assert "messages" in cap, "stream_response ไม่ถูกเรียก"
    assert RULE in _system(cap["messages"])


def test_regenerate_system_prompt_มีกติกาคำลงท้าย(monkeypatch):
    sid = "t-fem-regen"
    conn = _get_conn()
    conn.execute("DELETE FROM messages WHERE assistant=? AND session_id=?", (KWAN, sid))
    for role, content in [("user", "U1"), ("assistant", "A1")]:
        conn.execute("INSERT INTO messages (assistant, role, content, created_at, session_id) VALUES (?,?,?,?,?)",
                     (KWAN, role, content, "2026-10-04T00:00:00", sid))
    conn.commit()
    conn.close()
    cap = {}

    def fake_stream(messages, **k):
        cap["messages"] = messages
        yield "ใหม่"

    monkeypatch.setattr(chatmod, "stream_response", fake_stream)
    monkeypatch.setattr(chatmod, "search_memory", lambda *a, **k: "")
    r = client.post("/api/regenerate", json={"assistant": KWAN, "session_id": sid, "provider": "ollama"})
    assert r.status_code == 200
    _ = r.text
    assert "messages" in cap, "stream_response ไม่ถูกเรียก"
    assert RULE in _system(cap["messages"])


def test_persona_กลางและโหมดเสียง_ไม่ถูกแตะ():
    assert RULE not in ASSISTANTS[KWAN]["system_prompt"]
    assert RULE not in voice_system_prompt("kwan")
