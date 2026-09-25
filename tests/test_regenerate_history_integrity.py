"""/api/regenerate ต้องไม่ลบคำตอบผิดตัว และไม่ส่ง prompt ซ้ำสองให้โมเดล (audit 2026-09-24 MEDIUM)

`routers/chat.py regenerate_response`:
  1. `delete_last_assistant_message()` ลบ assistant *ล่าสุดของ session* โดยไม่ดูว่ามันอยู่หลัง user ล่าสุดไหม
     → session ที่ turn สุดท้ายเป็น orphan (U1,A1,U2 — เช่น client ตัดสายกลาง stream) กด regenerate = **ลบ A1** ทิ้ง
  2. `load_history()` ยังมี U2 อยู่ แล้ว `messages.append(last_prompt)` อีก → โมเดลเห็น U2,U2
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
import server
import routers.chat as chatmod
from utils.history import _get_conn, load_history

client = TestClient(server.app)
ASST = "kwan"


def _seed(session_id: str, turns: list[tuple[str, str]]):
    conn = _get_conn()
    conn.execute("DELETE FROM messages WHERE assistant=? AND session_id=?", (ASST, session_id))
    for role, content in turns:
        conn.execute(
            "INSERT INTO messages (assistant, role, content, created_at, session_id) VALUES (?,?,?,?,?)",
            (ASST, role, content, "2026-09-25T00:00:00", session_id),
        )
    conn.commit()
    conn.close()


def _regen(monkeypatch, session_id: str):
    seen: dict = {}

    def fake_stream(messages, **k):
        seen["messages"] = messages
        yield "คำตอบใหม่"

    monkeypatch.setattr(chatmod, "stream_response", fake_stream)
    monkeypatch.setattr(chatmod, "search_memory", lambda *a, **k: "")
    r = client.post("/api/regenerate", json={"assistant": ASST, "session_id": session_id, "provider": "ollama"})
    assert r.status_code == 200
    _ = r.text
    return seen["messages"], load_history(ASST, session_id)


@pytest.mark.xfail(strict=True, reason="audit MEDIUM ก้อน 6 — เทสแดงที่เขียนไว้ก่อน ยังไม่แก้ (devlog [2026-09-25 ปิดเซสชัน]) · ถอด marker นี้ตอนเริ่มแก้")
def test_ปกติ_ลบคำตอบล่าสุดแล้วส่งประวัติไม่ซ้ำ(monkeypatch):
    sid = "s_regen_normal"
    _seed(sid, [("user", "U1"), ("assistant", "A1"), ("user", "U2"), ("assistant", "A2")])
    messages, history = _regen(monkeypatch, sid)
    non_sys = [m["content"] for m in messages if m["role"] != "system"]
    assert non_sys == ["U1", "A1", "U2"], f"โมเดลต้องเห็น U2 ครั้งเดียว ไม่ใช่ซ้ำ ({non_sys})"
    assert [m["content"] for m in history] == ["U1", "A1", "U2", "คำตอบใหม่"]


@pytest.mark.xfail(strict=True, reason="audit MEDIUM ก้อน 6 — เทสแดงที่เขียนไว้ก่อน ยังไม่แก้ (devlog [2026-09-25 ปิดเซสชัน]) · ถอด marker นี้ตอนเริ่มแก้")
def test_turn_สุดท้ายเป็น_orphan_ต้องไม่ลบ_A1(monkeypatch):
    """เคสที่เกิดจริงหลัง client ตัดสาย: U1,A1,U2 (ไม่มี A2) → regenerate ต้องตอบ U2 โดย A1 ยังอยู่"""
    sid = "s_regen_orphan"
    _seed(sid, [("user", "U1"), ("assistant", "A1"), ("user", "U2")])
    messages, history = _regen(monkeypatch, sid)
    contents = [m["content"] for m in history]
    assert "A1" in contents, f"regenerate ลบ A1 ทิ้ง — ลบผิดตัว ({contents})"
    assert contents == ["U1", "A1", "U2", "คำตอบใหม่"]
    non_sys = [m["content"] for m in messages if m["role"] != "system"]
    assert non_sys == ["U1", "A1", "U2"]
