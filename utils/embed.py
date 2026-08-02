"""Embedding utilities — ใช้ multilingual embedding ผ่าน Ollama (รองรับภาษาไทย)

⚠️ ห้ามกลับไปใช้ `nomic-embed-text` เป็นตัวหลัก — พิสูจน์บน prod แล้ว (2026-08-02)
ว่า **แมปประโยคภาษาไทยทุกประโยคเป็น vector เดียวกันหมด** (cosine ระหว่าง
"ราคาทองวันนี้เท่าไหร่" กับ "สุนัขน่ารักมาก" = 1.0000 เป๊ะ ส่วนภาษาอังกฤษแยกได้ปกติ
0.38-0.44) = tokenizer มองอักษรไทยเป็น UNK ทั้งหมด บั๊กชนิดเดียวกับ ChromaDB
default MiniLM ที่แก้ไปแล้ว 2026-07-09 แต่เส้น documents/cache นี้ถูกข้ามไปตอนนั้น
ผลคือ: document RAG ภาษาไทยคืนผลมั่วทุกครั้ง + response cache (threshold 0.92)
จะ match คำถามไทยอะไรก็ได้เข้าหากันที่ 1.0 → เสิร์ฟคำตอบผิดคนละเรื่อง

Cache:
  - Persistent sqlite cache (รอด server restart) — key = (sha256(text), model)
    เปลี่ยนชื่อ model = invalidate ของเก่าอัตโนมัติ ไม่ต้องล้างมือ
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
# LM Studio รุ่นใหม่บังคับ API token — ตั้ง LMSTUDIO_API_KEY ให้ตรง (default dummy)
_LMSTUDIO_API_KEY = os.getenv("LMSTUDIO_API_KEY", "lmstudio")
_EMBED_TIMEOUT = int(os.getenv("LMSTUDIO_EMBED_TIMEOUT", "30"))
_OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
# ตัวหลัก = multilingual model บน Ollama (ตัวเดียวกับที่ ChromaDB memory ใช้ผ่าน
# EMBEDDING_MODEL ตั้งแต่ 2026-07-09) — single source of truth ว่า "ตัวไหนอ่านไทยได้"
_EMBED_MODEL = os.getenv("EMBEDDING_MODEL") or "paraphrase-multilingual"
# fallback = โมเดล**ชื่อเดียวกัน**บน LM Studio เท่านั้น ห้าม fallback ข้ามโมเดล:
# vector คนละโมเดล = คนละ space ถึงมิติเท่ากันก็ตาม → cosine เพี้ยนแบบเงียบๆ
# (ถ้า LM Studio ไม่มีโมเดลนี้จะ raise → caller จัดการเอง ดีกว่าคืนค่ามั่ว)
_EMBED_FALLBACK_ENABLED = os.getenv("EMBED_FALLBACK_LMSTUDIO", "true").lower() == "true"
_CACHE_DB = os.getenv("EMBED_CACHE_DB", _DEFAULT_CACHE_DB)
_CACHE_ENABLED = os.getenv("EMBED_CACHE_ENABLED", "true").lower() == "true"

_client = OpenAI(base_url=_LMSTUDIO_BASE_URL or "http://localhost:1234/v1",
                 api_key=_LMSTUDIO_API_KEY, timeout=_EMBED_TIMEOUT)
_ollama_client = OpenAI(base_url=_OLLAMA_BASE_URL, api_key="ollama", timeout=_EMBED_TIMEOUT)


def _create_embeddings(inputs: list[str]) -> tuple[list[list[float]], str]:
    """embed ผ่าน Ollama (multilingual) → fallback LM Studio ด้วยโมเดลชื่อเดียวกัน
    คืน (vecs, model_ที่ใช้จริง). raise ถ้าทั้งคู่ fail

    fallback ใช้ชื่อโมเดลเดิมเสมอ — คนละโมเดล = คนละ vector space ปนกันแล้ว
    cosine เพี้ยนเงียบๆ (ดู docstring ของโมดูล: บั๊กไทย nomic-embed-text)
    """
    try:
        resp = _ollama_client.embeddings.create(model=_EMBED_MODEL, input=inputs)
        vecs = [list(d.embedding) for d in resp.data]
        with _metrics_lock:
            _metrics["api_calls"] += 1
        return vecs, _EMBED_MODEL
    except Exception as e:
        if not _EMBED_FALLBACK_ENABLED:
            raise
        logger.warning(f"[Embed] Ollama embed fail ({e}) → fallback LM Studio (model เดิม {_EMBED_MODEL})")
        resp = _client.embeddings.create(model=_EMBED_MODEL, input=inputs)
        vecs = [list(d.embedding) for d in resp.data]
        with _metrics_lock:
            _metrics["api_calls"] += 1
            _metrics["ollama_fallback"] += 1
        return vecs, _EMBED_MODEL

# ── Persistent cache (sqlite) ────────────────────────────────────────────────
_cache_lock = threading.Lock()
_cache_conn: sqlite3.Connection | None = None

# hit-rate metrics (Phase G4): LRU hits/misses ดึงจาก _embed_one_cached.cache_info()
# ส่วน sqlite_hits (warm) + api_calls (cold round-trips) นับเอง
_metrics_lock = threading.Lock()
_metrics = {"sqlite_hits": 0, "api_calls": 0, "ollama_fallback": 0}


def reset_metrics() -> None:
    """รีเซ็ตตัวนับ + ล้าง LRU (ใช้ตอน bench/test)"""
    with _metrics_lock:
        _metrics.update(sqlite_hits=0, api_calls=0, ollama_fallback=0)
    _embed_one_cached.cache_clear()


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
        if row:
            with _metrics_lock:
                _metrics["sqlite_hits"] += 1
            return _unpack(row[1], row[0])
        return None
    except Exception as e:
        logger.debug(f"[Embed] cache get failed: {e}")
        return None


def _cache_set(text: str, vec: list[float], model: str | None = None) -> None:
    conn = _cache_init()
    if conn is None or not vec:
        return
    try:
        # เก็บใต้ชื่อ model ที่ผลิต vec จริง (W2) — _cache_get อ่านด้วย _EMBED_MODEL
        # เท่านั้น → vec จาก Ollama-fallback (ใต้ชื่ออื่น) จะไม่ถูกอ่านปนกับ LM Studio
        conn.execute(
            "INSERT OR REPLACE INTO embed_cache (key, model, dim, vec) VALUES (?,?,?,?)",
            (_cache_key(text), model or _EMBED_MODEL, len(vec), _pack(vec)),
        )
    except Exception as e:
        logger.debug(f"[Embed] cache set failed: {e}")


def _metrics_block() -> dict:
    """รวม LRU cache_info + counters → hit-rate (Phase G4)"""
    info = _embed_one_cached.cache_info()
    with _metrics_lock:
        sqlite_hits = _metrics["sqlite_hits"]
        api_calls = _metrics["api_calls"]
        ollama_fallback = _metrics["ollama_fallback"]
    # embed_query (hot path) ผ่าน LRU: total = hits + misses
    lru_total = info.hits + info.misses
    return {
        "lru_hits": info.hits,
        "lru_misses": info.misses,
        "lru_size": info.currsize,
        "lru_maxsize": info.maxsize,
        "sqlite_hits": sqlite_hits,     # warm hits (LRU miss → sqlite ใช้ได้)
        "api_calls": api_calls,         # cold round-trips (LM Studio หรือ Ollama)
        "ollama_fallback": ollama_fallback,   # กี่ครั้งที่ตก fallback ไป Ollama (LM Studio fail)
        # hit rate ของ hot path embed_query
        "lru_hit_rate": round(info.hits / lru_total, 3) if lru_total else None,
    }


def cache_stats() -> dict:
    """รายงาน hit/size + hit-rate — สำหรับ /api/cache/stats"""
    metrics = _metrics_block()
    conn = _cache_init()
    if conn is None:
        return {"enabled": False, **metrics}
    try:
        n = conn.execute("SELECT COUNT(*) FROM embed_cache").fetchone()[0]
        size = os.path.getsize(_CACHE_DB) if os.path.exists(_CACHE_DB) else 0
        return {"enabled": True, "entries": n, "db_bytes": size,
                "model": _EMBED_MODEL, **metrics}
    except Exception:
        return {"enabled": True, "entries": 0, **metrics}


# ── Embedding API ─────────────────────────────────────────────────────────────
@lru_cache(maxsize=512)
def _embed_one_cached(text: str) -> tuple:
    """Two-tier cache: LRU (hot) → sqlite (warm) → LMStudio/Ollama (cold)"""
    cached = _cache_get(text)
    if cached:
        return tuple(cached)
    try:
        vecs, used_model = _create_embeddings([text])   # LM Studio → fallback Ollama
        vec = vecs[0]
        _cache_set(text, vec, used_model)
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

    # fetch missing batch (LM Studio → fallback Ollama)
    try:
        new_vecs, used_model = _create_embeddings(miss_texts)
    except Exception as e:
        logger.warning(f"[Embed] batch failed ({len(miss_texts)} items): {e}")
        # คืนเฉพาะที่มี cache (เพื่อไม่ให้ pipeline พัง)
        return [c for c in cached if c]

    # save new + reconstruct order
    for idx, vec in zip(miss_idx, new_vecs):
        cached[idx] = vec
        _cache_set(texts[idx], vec, used_model)

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
