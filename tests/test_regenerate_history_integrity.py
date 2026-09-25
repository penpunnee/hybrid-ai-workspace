"""/api/regenerate ต้องไม่ลบคำตอบผิดตัว และไม่ส่ง prompt ซ้ำสองให้โมเดล (audit 2026-09-24 MEDIUM)

`routers/chat.py regenerate_response`:
  1. `delete_last_assistant_message()` ลบ assistant *ล่าสุดของ session* โดยไม่ดูว่ามันอยู่หลัง user ล่าสุดไหม
     → session ที่ turn สุดท้ายเป็น orphan (U1,A1,U2 — เช่น client ตัดสายกลาง stream) กด regenerate = **ลบ A1** ทิ้ง
  2. `load_history()` ยังมี U2 อยู่ แล้ว `messages.append(last_prompt)` อีก → โมเดลเห็น U2,U2
"""

import os
import sys


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


def test_ปกติ_ลบคำตอบล่าสุดแล้วส่งประวัติไม่ซ้ำ(monkeypatch):
    sid = "s_regen_normal"
    _seed(sid, [("user", "U1"), ("assistant", "A1"), ("user", "U2"), ("assistant", "A2")])
    messages, history = _regen(monkeypatch, sid)
    non_sys = [m["content"] for m in messages if m["role"] != "system"]
    assert non_sys == ["U1", "A1", "U2"], f"โมเดลต้องเห็น U2 ครั้งเดียว ไม่ใช่ซ้ำ ({non_sys})"
    assert [m["content"] for m in history] == ["U1", "A1", "U2", "คำตอบใหม่"]


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


def test_regenerate_ต้องกวาด_feedback_ของคำตอบที่ลบ(monkeypatch):
    """พบเพิ่มระหว่างแก้ (09-25): `delete_last_assistant_message` เดิมไม่เคยเรียก
    `_purge_message_side_tables` → 👍/👎 ที่ผูกกับ A2 ค้างเป็น orphan ทุกครั้งที่ regenerate
    (คนละพฤติกรรมกับ truncate/delete เดี่ยวที่ก้อน 2 กวาดให้แล้ว)"""
    from utils import feedback as fb
    fb._ensure_table()
    sid = "s_regen_feedback"
    _seed(sid, [("user", "U1"), ("assistant", "A1"), ("user", "U2"), ("assistant", "A2")])
    conn = _get_conn()
    a1_id, a2_id = [
        r[0] for r in conn.execute(
            "SELECT id FROM messages WHERE assistant=? AND session_id=? AND role='assistant' ORDER BY id",
            (ASST, sid),
        )
    ]
    conn.execute("DELETE FROM feedback WHERE session_id=?", (sid,))
    for mid in (a1_id, a2_id):
        conn.execute(
            "INSERT INTO feedback (assistant, session_id, message_id, rating, created_at) VALUES (?,?,?,?,?)",
            (ASST, sid, mid, "up", "2026-09-25T00:00:00"),
        )
    conn.commit()
    conn.close()

    _regen(monkeypatch, sid)

    conn = _get_conn()
    left = [r[0] for r in conn.execute("SELECT message_id FROM feedback WHERE session_id=? ORDER BY message_id", (sid,))]
    conn.close()
    assert left == [a1_id], f"feedback ของ A2 (ที่ถูกลบ) ต้องหายตาม · ของ A1 ต้องอยู่ ({left} · A1={a1_id} A2={a2_id})"
