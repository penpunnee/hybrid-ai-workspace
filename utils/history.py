import sqlite3
import os
from datetime import datetime, date, timedelta
from dotenv import load_dotenv

load_dotenv()

_default_db = os.path.join(os.path.dirname(__file__), "..", "chat_history.db")
DB_PATH = os.getenv("DB_PATH", _default_db)


def _get_conn():
    conn = sqlite3.connect(DB_PATH)
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
    for col, default in [("session_id", "'default'"), ("pinned", "0")]:
        try:
            conn.execute(f"ALTER TABLE messages ADD COLUMN {col} {'TEXT' if col=='session_id' else 'INTEGER'} DEFAULT {default}")
        except Exception:
            pass
    conn.commit()
    return conn


def save_message(assistant: str, role: str, content: str, provider: str = "ollama", session_id: str = "default"):
    """บันทึกข้อความลง SQLite พร้อม session_id"""
    conn = _get_conn()
    conn.execute(
        "INSERT INTO messages (assistant, role, content, provider, created_at, session_id) VALUES (?, ?, ?, ?, ?, ?)",
        (assistant, role, content, provider, datetime.now().isoformat(), session_id),
    )
    conn.commit()
    conn.close()


def load_history(assistant: str, session_id: str = "default", include_meta: bool = False) -> list[dict]:
    """โหลดประวัติแชทของ session นั้นจาก DB"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, role, content, pinned FROM messages WHERE assistant = ? AND session_id = ? ORDER BY id ASC",
        (assistant, session_id),
    ).fetchall()
    conn.close()
    if include_meta:
        return [{"db_id": r[0], "role": r[1], "content": r[2], "pinned": bool(r[3])} for r in rows]
    return [{"role": r[1], "content": r[2]} for r in rows]


def get_sessions(assistant: str) -> list[dict]:
    """ดึงรายการ sessions ทั้งหมดของ assistant พร้อม first message"""
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
        sessions.append({
            "session_id": session_id,
            "started_at": started_at or "",
            "first_msg": (first[0] if first else "การสนทนา")[:50],
        })
    conn.close()
    return sessions


def clear_session(assistant: str, session_id: str):
    """ลบประวัติแชทของ session นั้น"""
    conn = _get_conn()
    conn.execute("DELETE FROM messages WHERE assistant = ? AND session_id = ?", (assistant, session_id))
    conn.commit()
    conn.close()


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
