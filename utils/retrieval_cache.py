"""Per-session retrieval cache — กัน re-retrieve ซ้ำใน turn ที่ topic เดียวกัน

หลักการ:
  - เก็บ {prompt_vec, retrieved_chunks, retrieved_at} ต่อ session_id (in-memory)
  - turn ใหม่ — embed prompt, เทียบ cosine กับของล่าสุดใน session
  - ถ้า similar (≥ 0.85) → reuse retrieved chunks (skip ChromaDB call)
  - TTL 10 นาที (กัน stale + leak memory)
"""
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from utils.embed import embed_query, cosine_similarity

logger = logging.getLogger(__name__)


@dataclass
class _Entry:
    prompt: str
    vec: list[float]
    chunks: list[dict]
    citations: list[dict] = field(default_factory=list)  # serialized citations
    ts: float = 0.0


_TTL = 600.0   # 10 min
_MAX_SESSIONS = 200
_SIM_THRESHOLD = 0.85

_lock = threading.Lock()
_cache: dict[str, _Entry] = {}

# hit-rate metrics (Phase G4) — นับใต้ _lock
_metrics = {"lookups": 0, "hits": 0, "misses": 0}


def reset_metrics() -> None:
    """รีเซ็ตตัวนับ (ใช้ตอน bench/test)"""
    with _lock:
        _metrics.update(lookups=0, hits=0, misses=0)


def _evict_old(now: float) -> None:
    """ลบ entry ที่หมดอายุ — call ใต้ _lock"""
    expired = [sid for sid, e in _cache.items() if now - e.ts > _TTL]
    for sid in expired:
        _cache.pop(sid, None)
    # LRU style: ถ้ายังเยอะ ลบเก่าสุด
    if len(_cache) > _MAX_SESSIONS:
        sorted_items = sorted(_cache.items(), key=lambda x: x[1].ts)
        for sid, _ in sorted_items[: len(_cache) - _MAX_SESSIONS]:
            _cache.pop(sid, None)


def get_cached(session_id: str, prompt: str, threshold: float = _SIM_THRESHOLD) -> Optional[dict]:
    """ค้น cache ของ session — คืน {chunks, citations, similarity, source_prompt} หรือ None

    Args:
        session_id: id ของ session
        prompt: prompt ใหม่ของ user
        threshold: cosine similarity ขั้นต่ำที่ยอมรับ
    """
    if not session_id or not prompt:
        return None

    with _lock:
        _metrics["lookups"] += 1
        entry = _cache.get(session_id)
        if not entry:
            _metrics["misses"] += 1
            return None
        if time.time() - entry.ts > _TTL:
            _cache.pop(session_id, None)
            _metrics["misses"] += 1
            return None

    # embed นอก lock (อาจช้า)
    new_vec = embed_query(prompt)
    if not new_vec or not entry.vec:
        with _lock:
            _metrics["misses"] += 1
        return None

    sim = cosine_similarity(new_vec, entry.vec)
    if sim < threshold:
        with _lock:
            _metrics["misses"] += 1
        return None

    with _lock:
        _metrics["hits"] += 1
    logger.info(f"[RetrCache] hit session={session_id} sim={sim:.3f} (vs {entry.prompt[:40]!r})")
    return {
        "chunks": list(entry.chunks),
        "citations": list(entry.citations),
        "similarity": round(sim, 3),
        "source_prompt": entry.prompt,
    }


def store(
    session_id: str,
    prompt: str,
    chunks: list[dict],
    citations: list[dict] | None = None,
) -> None:
    """เก็บผล retrieval ของ turn นี้"""
    if not session_id or not prompt:
        return
    vec = embed_query(prompt)
    if not vec:
        return  # embed fail → ไม่ cache (จะ retrieve ใหม่ next turn เลยดีกว่า)

    now = time.time()
    with _lock:
        # insert ก่อน แล้วค่อย evict → cache ไม่เกิน _MAX_SESSIONS (เดิม evict ก่อน insert
        # ทำให้ค้างที่ _MAX_SESSIONS+1). entry ใหม่ ts ล่าสุด → ไม่ถูก evict เอง
        _cache[session_id] = _Entry(
            prompt=prompt, vec=vec, chunks=list(chunks),
            citations=list(citations or []), ts=now,
        )
        _evict_old(now)
    logger.debug(f"[RetrCache] store session={session_id} chunks={len(chunks)}")


def invalidate(session_id: str) -> None:
    """ล้าง cache ของ session — เรียกเมื่อ user เริ่ม topic ใหม่ (เช่น clear chat)"""
    with _lock:
        _cache.pop(session_id, None)


def stats() -> dict:
    with _lock:
        lookups = _metrics["lookups"]
        hits = _metrics["hits"]
        return {
            "sessions": len(_cache),
            "ttl_seconds": _TTL,
            "max_sessions": _MAX_SESSIONS,
            "threshold": _SIM_THRESHOLD,
            "lookups": lookups,
            "hits": hits,
            "misses": _metrics["misses"],
            "hit_rate": round(hits / lookups, 3) if lookups else None,
        }
