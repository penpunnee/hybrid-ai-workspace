"""ลบ session แล้วต้องไม่ทิ้ง orphan ไว้ในตารางพ่วง

ที่มา (2026-08-06): ล้าง session ทดสอบ 37 ตัวแล้วพบว่า `DELETE /api/sessions/{a}/{s}`
เก็บแค่ `messages` + `session_names` — แถวใน `skill_shadow` ค้างอยู่ทุกครั้ง
ต้องมาไล่ลบมือเองรอบแล้วรอบเล่า

`skill_shadow` ผูกกับ `message_id` ของคำตอบ AI (ดู docstring ของ `skills_shadow.record`)
พอ message ถูกลบ แถวนั้นก็ชี้ไปที่ id ที่ไม่มีอยู่แล้ว = ขยะล้วน ไม่มีใครใช้ได้อีก
"""

import sqlite3

import pytest

from utils.history import DB_PATH, _get_conn, clear_session

ASST = "🧡 ขวัญ (Logic)"
OTHER_ASST = "ผู้ช่วยอีกคน"


def _seed(conn: sqlite3.Connection, assistant: str, session_id: str, msg_id: int) -> None:
    conn.execute(
        "INSERT INTO messages (id, assistant, role, content, created_at, session_id) VALUES (?,?,?,?,?,?)",
        (msg_id, assistant, "assistant", "ตอบแล้วค่ะ", "2026-08-06T00:00:00", session_id),
    )
    conn.execute(
        "INSERT OR REPLACE INTO session_names (assistant, session_id, name) VALUES (?,?,?)",
        (assistant, session_id, "ชื่อที่ตั้งเอง"),
    )
    conn.execute(
        """INSERT INTO skill_shadow
           (message_id, assistant, session_id, prompt, thai_only, injected, choices, created_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (msg_id, assistant, session_id, "คำถาม", 1, "[]", "[]", "2026-08-06T00:00:00"),
    )


@pytest.fixture()
def db():
    """สร้างตารางให้ครบแล้วเคลียร์ของเก่า — ใช้ DB_PATH ชั่วคราวจาก conftest"""
    from utils import skills_shadow

    conn = _get_conn()          # _init_schema สร้าง messages/session_names ให้แล้ว
    conn.close()
    skills_shadow._ensure_table()

    conn = _get_conn()
    for t in ("messages", "session_names", "skill_shadow"):
        conn.execute(f"DELETE FROM {t}")
    conn.commit()
    yield conn
    conn.close()


def _count(conn, table, assistant, session_id):
    return conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE assistant=? AND session_id=?",
        (assistant, session_id),
    ).fetchone()[0]


def test_ลบ_session_แล้ว_skill_shadow_ต้องหายด้วย(db):
    _seed(db, ASST, "s_ลบ", 101)
    db.commit()
    assert _count(db, "skill_shadow", ASST, "s_ลบ") == 1, "seed ไม่ติด — เทสวัดผิด"

    clear_session(ASST, "s_ลบ")

    conn = _get_conn()
    try:
        assert _count(conn, "messages", ASST, "s_ลบ") == 0
        assert _count(conn, "session_names", ASST, "s_ลบ") == 0
        assert _count(conn, "skill_shadow", ASST, "s_ลบ") == 0
    finally:
        conn.close()


def test_ไม่แตะ_session_อื่นของผู้ช่วยคนเดียวกัน(db):
    """กลุ่มควบคุม: ถ้าเขียน DELETE โดยลืม WHERE session_id เทสบนก็ยังเขียว"""
    _seed(db, ASST, "s_ลบ", 201)
    _seed(db, ASST, "s_เก็บ", 202)
    db.commit()

    clear_session(ASST, "s_ลบ")

    conn = _get_conn()
    try:
        assert _count(conn, "skill_shadow", ASST, "s_ลบ") == 0
        assert _count(conn, "skill_shadow", ASST, "s_เก็บ") == 1
        assert _count(conn, "messages", ASST, "s_เก็บ") == 1
    finally:
        conn.close()


def test_ไม่แตะ_session_ชื่อเดียวกันของผู้ช่วยคนอื่น(db):
    """กลุ่มควบคุม: ต้อง scope ด้วย assistant เหมือน messages/session_names"""
    _seed(db, ASST, "s_ซ้ำ", 301)
    _seed(db, OTHER_ASST, "s_ซ้ำ", 302)
    db.commit()

    clear_session(ASST, "s_ซ้ำ")

    conn = _get_conn()
    try:
        assert _count(conn, "skill_shadow", ASST, "s_ซ้ำ") == 0
        assert _count(conn, "skill_shadow", OTHER_ASST, "s_ซ้ำ") == 1
        assert _count(conn, "messages", OTHER_ASST, "s_ซ้ำ") == 1
    finally:
        conn.close()


def test_ไม่มีตาราง_skill_shadow_ก็ต้องไม่พัง(db):
    """DB เก่าที่ยังไม่เคยเขียน shadow เลยจะไม่มีตารางนี้ — ลบ session ต้องยังทำงานได้

    (shadow เป็นเครื่องมือวัด ห้ามทำให้เส้นหลักพัง — กติกาเดียวกับ `skills_shadow.record`)
    """
    _seed(db, ASST, "s_ลบ", 401)
    db.commit()
    db.execute("DROP TABLE skill_shadow")
    db.commit()

    clear_session(ASST, "s_ลบ")   # ต้องไม่โยน

    conn = _get_conn()
    try:
        assert _count(conn, "messages", ASST, "s_ลบ") == 0
    finally:
        conn.close()


def test_ใช้ฐานข้อมูลชั่วคราวจริง():
    """กันพลาด: ถ้าเทสไปวิ่งบน DB จริง แปลว่า conftest ไม่ทำงานแล้ว"""
    assert "chat_history.db" not in DB_PATH or "/tmp" in DB_PATH or "pytest" in DB_PATH
