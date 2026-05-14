"""Embedding utilities — ใช้ nomic-embed-text-v1.5 ผ่าน LM Studio

LM Studio รองรับ OpenAI-compatible /v1/embeddings endpoint

Cache:
  - Persistent sqlite cache (รอด server restart)
  - In-memory LRU on top (fast path)
"""
import hashlib
import logging
import math
import os
import sqlite3
import struct
import threading
from functools import lru_cache
from typing import Sequence

from openai import OpenAI

from core.config import EMBED_CACHE_DB as _DEFAULT_CACHE_DB

logger = logging.getLogger(__name__)

_LMSTUDIO_BASE_URL = os.getenv("LMSTUDIO_BASE_URL", "http://192.168.51.235:1234/v1")
_EMBED_MODEL = os.getenv("LMSTUDIO_EMBED_MODEL", "text-embedding-nomic-embed-text-v1.5")
_EMBED_TIMEOUT = int(os.getenv("LMSTUDIO_EMBED_TIMEOUT", "30"))
_CACHE_DB = os.getenv("EMBED_CACHE_DB", _DEFAULT_CACHE_DB)
_CACHE_ENABLED = os.getenv("EMBED_CACHE_ENABLED", "true").lower() == "true"

_client = OpenAI(base_url=_LMSTUDIO_BASE_URL, api_key="lmstudio", timeout=_EMBED_TIMEOUT)

# ── Persistent cache (sqlite) ────────────────────────────────────────────────
_cache_lock = threading.Lock()
_cache_conn: sqlite3.Connection | None = None


def _cache_init() -> sqlite3.Connection | None:
    """Lazy-init sqlite cache — None ถ้าปิด/ล้ม"""
    global _cache_conn
    if not _CACHE_ENABLED:
        return None
    if _cache_conn is not None:
        return _cache_conn
    with _cache_lock:
        if _cache_conn is not None:
            return _cache_conn
        try:
            os.makedirs(os.path.dirname(_CACHE_DB), exist_ok=True)
            conn = sqlite3.connect(_CACHE_DB, check_same_thread=False, isolation_level=None)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS embed_cache (
                    key TEXT PRIMARY KEY,
                    model TEXT NOT NULL,
                    dim INTEGER NOT NULL,
                    vec BLOB NOT NULL,
                    created_at REAL DEFAULT (strftime('%s','now'))
                )
            """)
            _cache_conn = conn
            return conn
        except Exception as e:
            logger.warning(f"[Embed] cache init failed (running w/o persistent cache): {e}")
            return None


def _cache_key(text: str) -> str:
    """SHA256 ของ text — กัน collision ระหว่างข้อความยาว"""
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def _pack(vec: list[float]) -> bytes:
    """encode vec → bytes (float32 LE) สำหรับเก็บ sqlite"""
    return struct.pack(f"<{len(vec)}f", *vec)


def _unpack(blob: bytes, dim: int) -> list[float]:
    return list(struct.unpack(f"<{dim}f", blob))


def _cache_get(text: str) -> list[float] | None:
    conn = _cache_init()
    if conn is None:
        return None
    try:
        row = conn.execute(
            "SELECT dim, vec FROM embed_cache WHERE key=? AND model=?",
            (_cache_key(text), _EMBED_MODEL),
        ).fetchone()
        return _unpack(row[1], row[0]) if row else None
    except Exception as e:
        logger.debug(f"[Embed] cache get failed: {e}")
        return None


def _cache_set(text: str, vec: list[float]) -> None:
    conn = _cache_init()
    if conn is None or not vec:
        return
    try:
        conn.execute(
            "INSERT OR REPLACE INTO embed_cache (key, model, dim, vec) VALUES (?,?,?,?)",
            (_cache_key(text), _EMBED_MODEL, len(vec), _pack(vec)),
        )
    except Exception as e:
        logger.debug(f"[Embed] cache set failed: {e}")


def cache_stats() -> dict:
    """รายงาน hit/size — สำหรับ /api/system"""
    conn = _cache_init()
    if conn is None:
        return {"enabled": False}
    try:
        n = conn.execute("SELECT COUNT(*) FROM embed_cache").fetchone()[0]
        size = os.path.getsize(_CACHE_DB) if os.path.exists(_CACHE_DB) else 0
        return {"enabled": True, "entries": n, "db_bytes": size, "model": _EMBED_MODEL}
    except Exception:
        return {"enabled": True, "entries": 0}


# ── Embedding API ─────────────────────────────────────────────────────────────
@lru_cache(maxsize=512)
def _embed_one_cached(text: str) -> tuple:
    """Two-tier cache: LRU (hot) → sqlite (warm) → LMStudio (cold)"""
    cached = _cache_get(text)
    if cached:
        return tuple(cached)
    try:
        resp = _client.embeddings.create(model=_EMBED_MODEL, input=[text])
        vec = list(resp.data[0].embedding)
        _cache_set(text, vec)
        return tuple(vec)
    except Exception as e:
        logger.warning(f"[Embed] failed for text {text[:40]!r}: {e}")
        return tuple()


def embed_texts(texts: Sequence[str]) -> list[list[float]]:
    """Batch embed — ใช้ persistent cache ก่อน แล้ว fetch เฉพาะที่ miss

    Args:
        texts: list ของ strings
    Returns:
        list ของ vectors (empty list ถ้า embed fail)
    """
    texts = [t for t in texts if t and t.strip()]
    if not texts:
        return []

    # check cache แต่ละตัว
    cached: list[list[float] | None] = []
    miss_idx: list[int] = []
    miss_texts: list[str] = []
    for i, t in enumerate(texts):
        c = _cache_get(t)
        if c:
            cached.append(c)
        else:
            cached.append(None)
            miss_idx.append(i)
            miss_texts.append(t)

    if not miss_texts:
        return [c for c in cached if c]

    # fetch missing batch
    try:
        resp = _client.embeddings.create(model=_EMBED_MODEL, input=miss_texts)
        new_vecs = [list(d.embedding) for d in resp.data]
    except Exception as e:
        logger.warning(f"[Embed] batch failed ({len(miss_texts)} items): {e}")
        # คืนเฉพาะที่มี cache (เพื่อไม่ให้ pipeline พัง)
        return [c for c in cached if c]

    # save new + reconstruct order
    for idx, vec in zip(miss_idx, new_vecs):
        cached[idx] = vec
        _cache_set(texts[idx], vec)

    return [c for c in cached if c]


def embed_query(query: str) -> list[float]:
    """Embed query (cached) — return list ว่างเมื่อ fail"""
    v = _embed_one_cached(query)
    return list(v) if v else []


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity ระหว่าง 2 vectors — คืน 0.0 ถ้าใส่ผิด"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def rerank_by_similarity(
    query: str,
    items: list[dict],
    text_keys: Sequence[str] = ("body", "fetched_text", "title"),
    top_k: int = 3,
    min_score: float = 0.0,
) -> list[dict]:
    """Rerank items ตาม similarity กับ query

    Args:
        query: คำค้น
        items: list ของ dict (เช่น search results) — แต่ละ item ต้องมี text field
        text_keys: field names ที่จะใช้สร้าง text สำหรับ embed (รวมกัน)
        top_k: เก็บกี่ items ที่คะแนนสูงสุด
        min_score: ตัดทิ้งถ้าคะแนนต่ำกว่านี้
    Returns:
        items ที่ rerank แล้ว (มี field "_rerank_score" เพิ่ม) — ถ้า embed fail
        คืน items[:top_k] เหมือนเดิมไม่ rerank
    """
    if not items:
        return items

    q_vec = embed_query(query)
    if not q_vec:
        logger.info(f"[Rerank] embed failed — fallback to original order top {top_k}")
        return items[:top_k]

    # สร้าง text สำหรับ embed แต่ละ item
    texts = []
    for it in items:
        parts = []
        for k in text_keys:
            v = it.get(k, "")
            if v:
                parts.append(str(v)[:800])  # cap 800 chars per field
        texts.append(" ".join(parts) or "(empty)")

    vecs = embed_texts(texts)
    if not vecs or len(vecs) != len(items):
        logger.info(f"[Rerank] batch embed mismatch ({len(vecs)} vs {len(items)}) — fallback")
        return items[:top_k]

    scored = []
    for it, v in zip(items, vecs):
        score = cosine_similarity(q_vec, v)
        if score >= min_score:
            scored.append({**it, "_rerank_score": round(score, 4)})

    scored.sort(key=lambda x: x["_rerank_score"], reverse=True)
    top = scored[:top_k]
    if top:
        logger.info(
            f"[Rerank] query={query[:40]!r} | "
            f"{len(items)}→{len(top)} | "
            f"scores={[x['_rerank_score'] for x in top]}"
        )
    return top
