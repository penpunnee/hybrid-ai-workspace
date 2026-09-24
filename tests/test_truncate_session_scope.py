"""`truncate_from_db_id` ต้องลบเฉพาะใน session เดียวกัน และเก็บกวาดตารางพ่วง

ที่มา (audit 2026-09-24 ข้อ 3): `DELETE FROM messages WHERE id >= ?` ไม่กรอง
assistant/session ⇒ "แก้ข้อความแล้วส่งใหม่" (`app.tsx submitEdit` / enhanced.js §19)
ในแชทเก่า = ลบทุกแชทของทุกผู้ช่วยที่คุยหลังจากนั้น · ไม่มีเทสมาก่อน

caller ทั้งสองส่งมาแค่ db_id ⇒ ฝั่ง server ต้องหา assistant/session จาก row นั้นเอง
(ไม่ต้องแก้ frontend) · ตารางพ่วงที่ผูกกับ message_id (`skill_shadow` · `feedback`)
ต้องหายตาม — บทเรียนเดียวกับ `clear_session` (`tests/test_clear_session_cascade.py`)
"""

import sqlite3

import pytest

from utils import feedback as fb
from utils import skills_shadow
from utils.history import _get_conn, delete_message_by_id, truncate_from_db_id

ASST = "🧡 ขวัญ (Logic)"
OTHER = "ผู้ช่วยอีกคน"


@pytest.fixture()
def db():
    conn = _get_conn()
    conn.close()
    skills_shadow._ensure_table()
    fb._ensure_table()
    conn = _get_conn()
    for t in ("messages", "skill_shadow", "feedback"):
        conn.execute(f"DELETE FROM {t}")
    conn.commit()
    yield conn
    conn.close()


def _msg(conn: sqlite3.Connection, msg_id: int, assistant: str, session_id: str, role: str) -> None:
    conn.execute(
        "INSERT INTO messages (id, assistant, role, content, created_at, session_id) VALUES (?,?,?,?,?,?)",
        (msg_id, assistant, role, f"ข้อความ {msg_id}", "2026-09-24T00:00:00", session_id),
    )


def _shadow(conn: sqlite3.Connection, msg_id: int, assistant: str, session_id: str) -> None:
    conn.execute(
        """INSERT INTO skill_shadow
           (message_id, assistant, session_id, prompt, thai_only, injected, choices, created_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (msg_id, assistant, session_id, "คำถาม", 1, "[]", "[]", "2026-09-24T00:00:00"),
    )


def _feedback(conn: sqlite3.Connection, msg_id: int, assistant: str, session_id: str) -> None:
    conn.execute(
        "INSERT INTO feedback (assistant, session_id, message_id, rating, created_at) VALUES (?,?,?,?,?)",
        (assistant, session_id, msg_id, "up", "2026-09-24T00:00:00"),
    )


def _ids(conn, table="messages", col="id"):
    return sorted(r[0] for r in conn.execute(f"SELECT {col} FROM {table}"))


def _seed_interleaved(conn):
    """id สลับกันข้าม session/ผู้ช่วย เหมือนของจริงที่ทุกแชทใช้ AUTOINCREMENT ร่วมกัน"""
    _msg(conn, 10, ASST, "s_เก่า", "user")
    _msg(conn, 11, ASST, "s_เก่า", "assistant")
    _msg(conn, 12, ASST, "s_ใหม่", "user")        # session อื่นของผู้ช่วยเดียวกัน
    _msg(conn, 13, ASST, "s_ใหม่", "assistant")
    _msg(conn, 14, OTHER, "s_เก่า", "user")       # session id ซ้ำ แต่คนละผู้ช่วย
    _msg(conn, 15, OTHER, "s_เก่า", "assistant")
    _msg(conn, 16, ASST, "s_เก่า", "user")        # ต่อท้าย session เดิม — ต้องหาย
    _msg(conn, 17, ASST, "s_เก่า", "assistant")
    conn.commit()


def test_truncate_ต้องลบเฉพาะ_session_เดียวกัน(db):
    _seed_interleaved(db)
    assert _ids(db) == [10, 11, 12, 13, 14, 15, 16, 17], "seed ไม่ติด — เทสวัดผิด"

    truncate_from_db_id(11)      # แก้คำตอบที่ 11 ของ ASST/s_เก่า แล้วส่งใหม่

    conn = _get_conn()
    try:
        assert _ids(conn) == [10, 12, 13, 14, 15], (
            "ต้องเหลือ session อื่น/ผู้ช่วยอื่นครบ และ s_เก่า เหลือแค่ก่อน 11"
        )
    finally:
        conn.close()


def test_truncate_ต้องกวาด_skill_shadow_และ_feedback_ของข้อความที่ลบ(db):
    _seed_interleaved(db)
    _shadow(db, 11, ASST, "s_เก่า")
    _shadow(db, 17, ASST, "s_เก่า")
    _shadow(db, 13, ASST, "s_ใหม่")      # session อื่น — ต้องอยู่
    _feedback(db, 11, ASST, "s_เก่า")
    _feedback(db, 15, OTHER, "s_เก่า")   # ผู้ช่วยอื่น — ต้องอยู่
    db.commit()

    truncate_from_db_id(11)

    conn = _get_conn()
    try:
        assert _ids(conn, "skill_shadow", "message_id") == [13]
        assert _ids(conn, "feedback", "message_id") == [15]
    finally:
        conn.close()


def test_truncate_id_ที่ไม่มี_ต้องไม่ลบอะไรเลย(db):
    """โค้ดเดิม `id >= ?` กับ id ที่ไม่มีอยู่ = ลบทุกอย่างที่ใหม่กว่า — ต้องเป็น no-op แทน"""
    _seed_interleaved(db)

    found = truncate_from_db_id(5)

    conn = _get_conn()
    try:
        assert found is False
        assert _ids(conn) == [10, 11, 12, 13, 14, 15, 16, 17]
    finally:
        conn.close()


def test_delete_message_by_id_ต้องกวาดตารางพ่วงด้วย(db):
    """เส้นลบเดี่ยว (enhanced.js ลบคู่) มี orphan แบบเดียวกัน — ใช้ helper ตัวเดียวกัน"""
    _seed_interleaved(db)
    _shadow(db, 11, ASST, "s_เก่า")
    _shadow(db, 13, ASST, "s_ใหม่")
    _feedback(db, 11, ASST, "s_เก่า")
    db.commit()

    delete_message_by_id(11)

    conn = _get_conn()
    try:
        assert 11 not in _ids(conn)
        assert _ids(conn, "skill_shadow", "message_id") == [13]
        assert _ids(conn, "feedback", "message_id") == []
    finally:
        conn.close()


# ---------- endpoint ----------

def _client():
    from fastapi.testclient import TestClient

    from server import app
    return TestClient(app)   # ไม่ใช้ with → lifespan ไม่ fire (แบบเดียวกับ test_routers.py)


def test_endpoint_404_เมื่อไม่มี_id_และไม่ลบอะไร(db):
    _seed_interleaved(db)
    r = _client().delete("/api/truncate/5")
    assert r.status_code == 404
    conn = _get_conn()
    try:
        assert _ids(conn) == [10, 11, 12, 13, 14, 15, 16, 17]
    finally:
        conn.close()


def test_endpoint_ลบใน_session_เดียวกันแล้วตอบ_ok(db):
    _seed_interleaved(db)
    r = _client().delete("/api/truncate/11")
    assert r.status_code == 200 and r.json() == {"ok": True}
    conn = _get_conn()
    try:
        assert _ids(conn) == [10, 12, 13, 14, 15]
    finally:
        conn.close()
