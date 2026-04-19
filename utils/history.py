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
            session_id TEXT DEFAULT 'default'
        )
    """)
    try:
        conn.execute("ALTER TABLE messages ADD COLUMN session_id TEXT DEFAULT 'default'")
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


def load_history(assistant: str, session_id: str = "default") -> list[dict]:
    """โหลดประวัติแชทของ session นั้นจาก DB"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE assistant = ? AND session_id = ? ORDER BY id ASC",
        (assistant, session_id),
    ).fetchall()
    conn.close()
    return [{"role": row[0], "content": row[1]} for row in rows]


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
