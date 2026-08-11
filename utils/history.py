import sqlite3
import os
import logging
import threading
from datetime import datetime
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

_default_db = os.path.join(os.path.dirname(__file__), "..", "chat_history.db")
DB_PATH = os.getenv("DB_PATH", _default_db)

_schema_lock = threading.Lock()
_schema_ready = False


def _init_schema(conn: sqlite3.Connection) -> None:
    """รัน DDL ครั้งเดียวต่อ process (idempotent, thread-safe)."""
    global _schema_ready
    if _schema_ready:
        return
    with _schema_lock:
        if _schema_ready:
            return
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assistant TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                provider TEXT DEFAULT 'ollama',
                created_at TEXT NOT NULL,
                session_id TEXT DEFAULT 'default',
                pinned INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS session_names (
                assistant TEXT NOT NULL,
                session_id TEXT NOT NULL,
                name TEXT NOT NULL,
                PRIMARY KEY (assistant, session_id)
            )
        """)
        # backward-compat ALTER (สำหรับ DB เก่าก่อนเพิ่ม columns)
        for col, default in [("session_id", "'default'"), ("pinned", "0")]:
            try:
                col_type = "TEXT" if col == "session_id" else "INTEGER"
                conn.execute(f"ALTER TABLE messages ADD COLUMN {col} {col_type} DEFAULT {default}")
            except sqlite3.OperationalError:
                pass  # column มีอยู่แล้ว — ปกติ
        conn.commit()
        _schema_ready = True


def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    _init_schema(conn)
    return conn


def save_message(assistant: str, role: str, content: str, provider: str = "ollama", session_id: str = "default") -> int:
    """บันทึกข้อความลง SQLite พร้อม session_id — คืน id ของ row ที่เพิ่งบันทึก"""
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO messages (assistant, role, content, provider, created_at, session_id) VALUES (?, ?, ?, ?, ?, ?)",
        # astimezone() = ISO พร้อม UTC offset — container prod เป็น UTC แต่ผู้ใช้อยู่ ICT
        # ถ้าเก็บ naive string UI จะโชว์เวลา UTC ตรงๆ (เพี้ยน +7 ชม. — เจอจริง 2026-08-11)
        (assistant, role, content, provider, datetime.now().astimezone().isoformat(), session_id),
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return int(new_id) if new_id else 0


def load_history(assistant: str, session_id: str = "default", include_meta: bool = False) -> list[dict]:
    """โหลดประวัติแชทของ session นั้นจาก DB"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, role, content, pinned, created_at FROM messages WHERE assistant = ? AND session_id = ? ORDER BY id ASC",
        (assistant, session_id),
    ).fetchall()
    conn.close()
    if include_meta:
        return [
            {"db_id": r[0], "role": r[1], "content": r[2], "pinned": bool(r[3]), "created_at": r[4]}
            for r in rows
        ]
    return [{"role": r[1], "content": r[2]} for r in rows]


def get_sessions(assistant: str) -> list[dict]:
    """ดึงรายการ sessions ทั้งหมดของ assistant พร้อม first message และ custom name"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT session_id, MIN(created_at) as started_at FROM messages WHERE assistant = ? GROUP BY session_id ORDER BY started_at DESC LIMIT 30",
        (assistant,),
    ).fetchall()
    sessions = []
    for session_id, started_at in rows:
        first = conn.execute(
            "SELECT content FROM messages WHERE assistant = ? AND session_id = ? AND role = 'user' ORDER BY id ASC LIMIT 1",
            (assistant, session_id),
        ).fetchone()
        custom_name = conn.execute(
            "SELECT name FROM session_names WHERE assistant = ? AND session_id = ?",
            (assistant, session_id),
        ).fetchone()
        sessions.append({
            "session_id": session_id,
            "started_at": started_at or "",
            "first_msg": (first[0] if first else "การสนทนา")[:50],
            "name": custom_name[0] if custom_name else None,
        })
    conn.close()
    return sessions


def rename_session(assistant: str, session_id: str, name: str):
    """ตั้งชื่อ session แบบ custom ลงใน session_names table"""
    conn = _get_conn()
    conn.execute(
        "INSERT INTO session_names (assistant, session_id, name) VALUES (?, ?, ?) "
        "ON CONFLICT(assistant, session_id) DO UPDATE SET name = excluded.name",
        (assistant, session_id, name.strip()),
    )
    conn.commit()
    conn.close()


def clear_session(assistant: str, session_id: str):
    """ลบประวัติแชทของ session นั้น รวมถึง custom name และตารางพ่วง

    ⚠️ เพิ่ม table ที่มี `session_id` เมื่อไหร่ ต้องมาต่อท้ายลิสต์นี้ด้วย —
    ไม่งั้นจะเหลือ orphan ที่ไม่มีใครลบให้ (เจอจริง 2026-08-06: `skill_shadow`
    ค้างทุกครั้งที่ลบ session ต้องไล่เก็บมือ · `tests/test_clear_session_cascade.py` คุมไว้แล้ว)
    """
    conn = _get_conn()
    for table in ("messages", "session_names", "skill_shadow", "share_links"):
        try:
            conn.execute(
                f"DELETE FROM {table} WHERE assistant = ? AND session_id = ?",
                (assistant, session_id),
            )
        except sqlite3.OperationalError:
            # DB เก่าที่ยังไม่เคยเขียน shadow/share เลย = ไม่มีตารางนี้ — ห้ามทำให้การลบ session พัง
            logger.debug("clear_session: ข้ามตาราง %s (ยังไม่มีในฐานข้อมูล)", table)
    conn.commit()
    conn.close()

    # share link มี "สองที่เก็บ" — ลบแต่ DB ไม่พอ เพราะ get_shared_data() อ่าน in-memory
    # ก่อนแล้วเติม cache กลับจาก DB ⇒ token ที่ถูก cache ไว้จะยังตอบ ok:true ต่อไป
    from core.state import share_store_delete_by_session

    dropped = share_store_delete_by_session(assistant, session_id)
    if dropped:
        logger.info("clear_session: ถอด share token ออกจาก store %d รายการ", len(dropped))


def pin_message(db_id: int, pinned: bool = True):
    """Pin/Unpin ข้อความตาม db id"""
    conn = _get_conn()
    conn.execute("UPDATE messages SET pinned = ? WHERE id = ?", (1 if pinned else 0, db_id))
    conn.commit()
    conn.close()


def get_pinned_messages(assistant: str, session_id: str) -> list[dict]:
    """ดึง pinned messages ของ session"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, role, content, created_at FROM messages WHERE assistant = ? AND session_id = ? AND pinned = 1 ORDER BY id ASC",
        (assistant, session_id),
    ).fetchall()
    conn.close()
    return [{"db_id": r[0], "role": r[1], "content": r[2], "created_at": r[3]} for r in rows]


def search_messages(query: str, assistant: str = "", limit: int = 20) -> list[dict]:
    """ค้นหาข้อความใน chat history ด้วย keyword"""
    conn = _get_conn()
    q = f"%{query}%"
    if assistant:
        rows = conn.execute(
            "SELECT assistant, session_id, role, content, created_at FROM messages "
            "WHERE assistant = ? AND content LIKE ? ORDER BY id DESC LIMIT ?",
            (assistant, q, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT assistant, session_id, role, content, created_at FROM messages "
            "WHERE content LIKE ? ORDER BY id DESC LIMIT ?",
            (q, limit),
        ).fetchall()
    conn.close()
    results = []
    for assistant_name, session_id, role, content, created_at in rows:
        # highlight snippet รอบ keyword
        idx = content.lower().find(query.lower())
        start = max(0, idx - 40)
        end = min(len(content), idx + len(query) + 60)
        snippet = ("..." if start > 0 else "") + content[start:end] + ("..." if end < len(content) else "")
        results.append({
            "assistant": assistant_name,
            "session_id": session_id,
            "role": role,
            "snippet": snippet,
            "created_at": created_at,
        })
    return results


def delete_last_assistant_message(assistant: str, session_id: str) -> bool:
    """ลบ assistant message ล่าสุดของ session คืน True ถ้าลบได้"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT id FROM messages WHERE assistant = ? AND session_id = ? AND role = 'assistant' ORDER BY id DESC LIMIT 1",
        (assistant, session_id),
    ).fetchone()
    if row:
        conn.execute("DELETE FROM messages WHERE id = ?", (row[0],))
        conn.commit()
    conn.close()
    return bool(row)


def truncate_from_db_id(db_id: int):
    """ลบข้อความทุกรายการที่มี id >= db_id"""
    conn = _get_conn()
    conn.execute("DELETE FROM messages WHERE id >= ?", (db_id,))
    conn.commit()
    conn.close()


def delete_message_by_id(db_id: int):
    """ลบ message เดี่ยวตาม db_id"""
    conn = _get_conn()
    conn.execute("DELETE FROM messages WHERE id = ?", (db_id,))
    conn.commit()
    conn.close()


def get_last_user_message(assistant: str, session_id: str) -> str:
    """ดึง user message ล่าสุดของ session"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT content FROM messages WHERE assistant = ? AND session_id = ? AND role = 'user' ORDER BY id DESC LIMIT 1",
        (assistant, session_id),
    ).fetchone()
    conn.close()
    return row[0] if row else ""


def clear_history(assistant: str):
    """ลบประวัติแชทของ assistant ทั้งหมด"""
    conn = _get_conn()
    conn.execute("DELETE FROM messages WHERE assistant = ?", (assistant,))
    conn.commit()
    conn.close()


def export_history_md(assistant: str, session_id: str = "default") -> str:
    """Export ประวัติแชทเป็น Markdown string"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT role, content, created_at FROM messages WHERE assistant = ? AND session_id = ? ORDER BY id ASC",
        (assistant, session_id),
    ).fetchall()
    conn.close()

    if not rows:
        return f"# {assistant}\n\nยังไม่มีประวัติแชท"

    lines = [f"# ประวัติแชทกับ {assistant}\n"]
    for role, content, created_at in rows:
        ts = created_at[:19].replace("T", " ")
        label = "👤 User" if role == "user" else "🤖 Assistant"
        lines.append(f"### {label} — {ts}\n{content}\n")

    return "\n---\n\n".join(lines)
