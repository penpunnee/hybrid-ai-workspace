import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "chat_history.db")


def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            assistant TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            provider TEXT DEFAULT 'ollama',
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def save_message(assistant: str, role: str, content: str, provider: str = "ollama"):
    """บันทึกข้อความ 1 ข้อความลง SQLite"""
    conn = _get_conn()
    conn.execute(
        "INSERT INTO messages (assistant, role, content, provider, created_at) VALUES (?, ?, ?, ?, ?)",
        (assistant, role, content, provider, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def load_history(assistant: str) -> list[dict]:
    """โหลดประวัติแชทของ assistant คนนั้นจาก DB"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE assistant = ? ORDER BY id ASC",
        (assistant,),
    ).fetchall()
    conn.close()
    return [{"role": row[0], "content": row[1]} for row in rows]


def clear_history(assistant: str):
    """ลบประวัติแชทของ assistant คนนั้น"""
    conn = _get_conn()
    conn.execute("DELETE FROM messages WHERE assistant = ?", (assistant,))
    conn.commit()
    conn.close()


def export_history_md(assistant: str) -> str:
    """Export ประวัติแชทเป็น Markdown string"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT role, content, created_at FROM messages WHERE assistant = ? ORDER BY id ASC",
        (assistant,),
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
