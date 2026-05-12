"""Feedback Store — บันทึก thumbs up/down ของผู้ใช้ + propagate ไป memory

Tables (sqlite, share DB กับ chat_history.db):
  feedback(id, assistant, session_id, message_id, rating, comment, created_at)

ผลข้างเคียง:
  - thumbs up → mark memory ที่ link กับ message นี้เป็น verified + boost confidence
  - thumbs down → ลด confidence ของ memory
"""
import logging
import sqlite3
import threading
from datetime import datetime
from typing import Optional

from utils.history import _get_conn

logger = logging.getLogger(__name__)


def _ensure_table():
    conn = _get_conn()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assistant TEXT NOT NULL,
                session_id TEXT NOT NULL,
                message_id INTEGER NOT NULL,
                rating TEXT NOT NULL CHECK (rating IN ('up', 'down')),
                comment TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE(message_id, rating)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_assistant ON feedback(assistant)")
        conn.commit()
    finally:
        conn.close()


_ensure_table()


def save_feedback(
    assistant: str,
    session_id: str,
    message_id: int,
    rating: str,
    comment: str = "",
) -> dict:
    """บันทึก feedback — replace ถ้า user เปลี่ยน rating

    Args:
        assistant: slug
        session_id: session
        message_id: messages.id ใน SQLite (ของ AI response ที่ rate)
        rating: 'up' | 'down'
        comment: optional comment

    Returns:
        {ok, feedback_id?, error?}
    """
    rating = (rating or "").strip().lower()
    if rating not in ("up", "down"):
        return {"ok": False, "error": "rating must be 'up' or 'down'"}
    if not isinstance(message_id, int) or message_id <= 0:
        return {"ok": False, "error": "invalid message_id"}

    conn = _get_conn()
    try:
        # ลบ feedback เดิมของ message นี้ก่อน (กรณี user เปลี่ยนใจ)
        conn.execute("DELETE FROM feedback WHERE message_id = ?", (message_id,))
        cur = conn.execute(
            """INSERT INTO feedback (assistant, session_id, message_id, rating, comment, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (assistant, session_id, message_id, rating, comment, datetime.now().isoformat()),
        )
        conn.commit()
        fb_id = cur.lastrowid
    except sqlite3.Error as e:
        logger.error(f"[Feedback] save failed: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        conn.close()

    # ── propagate ไป memory ใน thread เพื่อไม่บล็อก API (ChromaDB อาจช้า) ────
    threading.Thread(
        target=_propagate_to_memory,
        args=(assistant, message_id, rating),
        daemon=True,
    ).start()

    return {"ok": True, "feedback_id": fb_id, "message_id": message_id, "rating": rating}


def _propagate_to_memory(assistant: str, message_id: int, rating: str) -> None:
    """thumbs up → verify+boost memory; thumbs down → reduce confidence

    รันใน thread แยก — ไม่ raise exception ออกไป
    """
    try:
        _propagate_impl(assistant, message_id, rating)
    except Exception as e:
        logger.debug(f"[Feedback] propagate failed (non-critical): {e}")


def _propagate_impl(assistant: str, message_id: int, rating: str) -> None:
    # ดึง content ของ message นั้น + คำถาม user ก่อนหน้า
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT id, role, content, session_id, provider FROM messages WHERE id = ?", (message_id,)
        ).fetchone()
        if not row:
            return
        msg_id, role, content, sid, provider = row
        if role != "assistant":
            return
        # หา user prompt ก่อนหน้า (ใน session เดียวกัน)
        prev = conn.execute(
            """SELECT content FROM messages
               WHERE assistant = ? AND session_id = ? AND id < ? AND role = 'user'
               ORDER BY id DESC LIMIT 1""",
            (assistant, sid, msg_id),
        ).fetchone()
        user_prompt = prev[0] if prev else ""
    finally:
        conn.close()

    if not user_prompt:
        return

    # ── 1. Response cache: up → save, down → delete ─────────────────────────
    try:
        from utils.response_cache import save as _rc_save, delete_for_message as _rc_delete
        if rating == "up":
            _rc_save(assistant, user_prompt, content, model=provider or "")
        elif rating == "down":
            _rc_delete(assistant, user_prompt)
    except Exception as e:
        logger.debug(f"[Feedback] response_cache propagation skipped: {e}")

    # ── 2. Memory confidence adjustment ─────────────────────────────────────
    try:
        from memory.store import update_confidence, search_entries
    except Exception:
        return

    matches = search_entries(assistant, user_prompt, n_results=2, min_confidence=0.0)
    if not matches:
        return

    delta = 0.15 if rating == "up" else -0.25
    for m in matches:
        cur = float(m.get("confidence", 0.7))
        new = max(0.0, min(1.0, cur + delta))
        update_confidence(assistant, m.get("content", "")[:200], new)
    logger.info(f"[Feedback] propagated {rating} → {len(matches)} memories (Δ={delta:+.2f})")


def get_feedback(message_id: int) -> Optional[dict]:
    """ดึง feedback ของ message ตัวเดียว"""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT id, assistant, rating, comment, created_at FROM feedback WHERE message_id = ?",
            (message_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "id": row[0], "assistant": row[1], "rating": row[2],
            "comment": row[3], "created_at": row[4],
        }
    finally:
        conn.close()


def get_stats(assistant: Optional[str] = None) -> dict:
    """summary stats — up/down ทั้งหมด + recent comments"""
    conn = _get_conn()
    try:
        where = ""
        params: tuple = ()
        if assistant:
            where = "WHERE assistant = ?"
            params = (assistant,)

        ups = conn.execute(
            f"SELECT COUNT(*) FROM feedback {where} AND rating='up'" if where else
            "SELECT COUNT(*) FROM feedback WHERE rating='up'", params
        ).fetchone()[0]
        downs = conn.execute(
            f"SELECT COUNT(*) FROM feedback {where} AND rating='down'" if where else
            "SELECT COUNT(*) FROM feedback WHERE rating='down'", params
        ).fetchone()[0]
        recent = conn.execute(
            f"""SELECT message_id, rating, comment, created_at FROM feedback
                {where} ORDER BY id DESC LIMIT 10""",
            params,
        ).fetchall()
    finally:
        conn.close()

    total = ups + downs
    return {
        "assistant": assistant or "all",
        "total": total,
        "ups": ups,
        "downs": downs,
        "ratio": round(ups / total, 3) if total else None,
        "recent": [
            {"message_id": r[0], "rating": r[1], "comment": r[2], "created_at": r[3]}
            for r in recent
        ],
    }


def list_low_rated_messages(assistant: Optional[str] = None, limit: int = 20) -> list[dict]:
    """รายการ message ที่โดน thumbs down — สำหรับ skill discovery / analysis"""
    conn = _get_conn()
    try:
        where = "WHERE f.rating='down'"
        params: tuple = ()
        if assistant:
            where += " AND f.assistant = ?"
            params = (assistant,)

        rows = conn.execute(
            f"""SELECT f.message_id, m.content, f.comment, f.created_at
                FROM feedback f JOIN messages m ON m.id = f.message_id
                {where} ORDER BY f.id DESC LIMIT ?""",
            (*params, limit),
        ).fetchall()
    finally:
        conn.close()
    return [
        {"message_id": r[0], "content": r[1][:300], "comment": r[2], "created_at": r[3]}
        for r in rows
    ]
