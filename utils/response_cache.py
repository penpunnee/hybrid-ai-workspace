"""Semantic Response Cache — เก็บคำตอบที่ user thumbs-up แล้ว reuse กับ Q ใกล้กัน

หลักการ:
  - เมื่อ user thumbs-up → save (prompt_vec, response, assistant, model_used)
  - turn ใหม่ — embed prompt, KNN กับ response_cache, threshold 0.92
  - return cached response → ไม่ต้องเรียก LLM

เก็บใน sqlite (data/response_cache.db), embeddings เก็บเป็น float32 blob
"""
import hashlib
import logging
import os
import sqlite3
import struct
import threading
import time
from typing import Optional

from core.config import RESPONSE_CACHE_DB as _DEFAULT_DB
from utils.embed import embed_query, cosine_similarity

logger = logging.getLogger(__name__)

_DB_PATH = os.getenv("RESPONSE_CACHE_DB", _DEFAULT_DB)
_ENABLED = os.getenv("RESPONSE_CACHE_ENABLED", "true").lower() == "true"
_SIM_THRESHOLD = float(os.getenv("RESPONSE_CACHE_THRESHOLD", "0.92"))
_TTL_DAYS = int(os.getenv("RESPONSE_CACHE_TTL_DAYS", "30"))
_MAX_ENTRIES = int(os.getenv("RESPONSE_CACHE_MAX", "1000"))

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def _init() -> sqlite3.Connection | None:
    global _conn
    if not _ENABLED:
        return None
    if _conn is not None:
        return _conn
    with _lock:
        if _conn is not None:
            return _conn
        try:
            os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
            conn = sqlite3.connect(_DB_PATH, check_same_thread=False, isolation_level=None)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS response_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    assistant TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    prompt_hash TEXT NOT NULL,
                    vec_dim INTEGER NOT NULL,
                    vec BLOB NOT NULL,
                    response TEXT NOT NULL,
                    model TEXT DEFAULT '',
                    created_at REAL NOT NULL,
                    hit_count INTEGER DEFAULT 0,
                    UNIQUE(assistant, prompt_hash)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_assistant ON response_cache(assistant)")
            _conn = conn
            return conn
        except Exception as e:
            logger.warning(f"[ResponseCache] init failed: {e}")
            return None


def _pack(vec: list[float]) -> bytes:
    return struct.pack(f"<{len(vec)}f", *vec)


def _unpack(blob: bytes, dim: int) -> list[float]:
    return list(struct.unpack(f"<{dim}f", blob))


def _prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8", errors="ignore")).hexdigest()


def save(assistant: str, prompt: str, response: str, model: str = "") -> bool:
    """บันทึก Q&A pair — เรียกเมื่อ user thumbs-up"""
    conn = _init()
    if conn is None:
        return False
    if not prompt.strip() or not response.strip():
        return False
    vec = embed_query(prompt)
    if not vec:
        return False
    try:
        conn.execute(
            """INSERT OR REPLACE INTO response_cache
               (assistant, prompt, prompt_hash, vec_dim, vec, response, model, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (assistant, prompt, _prompt_hash(prompt), len(vec), _pack(vec),
             response, model, time.time()),
        )
        logger.info(f"[ResponseCache] saved {assistant}/{prompt[:40]!r}")
        # cleanup ถ้าเกิน max
        _evict_if_needed(conn)
        return True
    except Exception as e:
        logger.warning(f"[ResponseCache] save failed: {e}")
        return False


def _evict_if_needed(conn: sqlite3.Connection) -> None:
    """ตัด entry เก่าถ้าเกิน max — keep ที่ hit เยอะกว่า + ใหม่กว่า"""
    try:
        n = conn.execute("SELECT COUNT(*) FROM response_cache").fetchone()[0]
        if n <= _MAX_ENTRIES:
            return
        # ลบเก่าสุด/hit น้อยสุด
        excess = n - _MAX_ENTRIES
        conn.execute(
            """DELETE FROM response_cache WHERE id IN (
                 SELECT id FROM response_cache
                 ORDER BY hit_count ASC, created_at ASC
                 LIMIT ?)""",
            (excess,),
        )
    except Exception as e:
        logger.debug(f"[ResponseCache] evict failed: {e}")


def lookup(assistant: str, prompt: str, threshold: float = _SIM_THRESHOLD) -> Optional[dict]:
    """หา cached response ที่ Q ใกล้กับ prompt — คืน {response, similarity, source_prompt, model} หรือ None"""
    conn = _init()
    if conn is None or not prompt.strip():
        return None

    vec = embed_query(prompt)
    if not vec:
        return None

    # ดึง entries ของ assistant (ภายใน TTL) แล้วเทียบใน Python
    # — ChromaDB-less approach: ใช้ได้กับ < few thousand entries
    cutoff = time.time() - (_TTL_DAYS * 86400)
    try:
        rows = conn.execute(
            """SELECT id, prompt, vec_dim, vec, response, model
               FROM response_cache WHERE assistant=? AND created_at >= ?""",
            (assistant, cutoff),
        ).fetchall()
    except Exception as e:
        logger.debug(f"[ResponseCache] lookup query failed: {e}")
        return None

    best = None
    best_sim = 0.0
    for row in rows:
        rid, src_prompt, dim, blob, resp, model = row
        try:
            cached_vec = _unpack(blob, dim)
        except Exception:
            continue
        sim = cosine_similarity(vec, cached_vec)
        if sim > best_sim:
            best_sim, best = sim, (rid, src_prompt, resp, model)

    if not best or best_sim < threshold:
        return None

    rid, src_prompt, resp, model = best
    # bump hit_count async (ไม่ critical)
    try:
        conn.execute("UPDATE response_cache SET hit_count = hit_count + 1 WHERE id=?", (rid,))
    except Exception:
        pass

    logger.info(f"[ResponseCache] hit {assistant}/{prompt[:30]!r} ↔ {src_prompt[:30]!r} sim={best_sim:.3f}")
    return {
        "response": resp,
        "similarity": round(best_sim, 3),
        "source_prompt": src_prompt,
        "model": model,
    }


def delete_for_message(assistant: str, prompt_match: str) -> bool:
    """ลบ entry เฉพาะของ prompt นี้ — เรียกตอน user เปลี่ยน thumbs-up เป็น thumbs-down"""
    conn = _init()
    if conn is None:
        return False
    try:
        conn.execute(
            "DELETE FROM response_cache WHERE assistant=? AND prompt_hash=?",
            (assistant, _prompt_hash(prompt_match)),
        )
        return True
    except Exception:
        return False


def stats() -> dict:
    conn = _init()
    if conn is None:
        return {"enabled": False}
    try:
        total = conn.execute("SELECT COUNT(*) FROM response_cache").fetchone()[0]
        hits = conn.execute("SELECT SUM(hit_count) FROM response_cache").fetchone()[0] or 0
        by_assistant = dict(conn.execute(
            "SELECT assistant, COUNT(*) FROM response_cache GROUP BY assistant"
        ).fetchall())
        size = os.path.getsize(_DB_PATH) if os.path.exists(_DB_PATH) else 0
        return {
            "enabled": True,
            "entries": total,
            "total_hits": hits,
            "by_assistant": by_assistant,
            "db_bytes": size,
            "threshold": _SIM_THRESHOLD,
            "ttl_days": _TTL_DAYS,
        }
    except Exception as e:
        return {"enabled": True, "error": str(e)}
