"""Embedding utilities — ใช้ nomic-embed-text-v1.5 ผ่าน LM Studio

LM Studio รองรับ OpenAI-compatible /v1/embeddings endpoint
"""
import logging
import math
import os
from functools import lru_cache
from typing import Sequence

from openai import OpenAI

logger = logging.getLogger(__name__)

_LMSTUDIO_BASE_URL = os.getenv("LMSTUDIO_BASE_URL", "http://192.168.51.235:1234/v1")
_EMBED_MODEL = os.getenv("LMSTUDIO_EMBED_MODEL", "text-embedding-nomic-embed-text-v1.5")
_EMBED_TIMEOUT = int(os.getenv("LMSTUDIO_EMBED_TIMEOUT", "30"))

_client = OpenAI(base_url=_LMSTUDIO_BASE_URL, api_key="lmstudio", timeout=_EMBED_TIMEOUT)


@lru_cache(maxsize=512)
def _embed_one_cached(text: str) -> tuple:
    """Cache hits ใน-memory สำหรับ query ที่เคยถาม (max 512 entries)"""
    try:
        resp = _client.embeddings.create(model=_EMBED_MODEL, input=[text])
        return tuple(resp.data[0].embedding)
    except Exception as e:
        logger.warning(f"[Embed] failed for text {text[:40]!r}: {e}")
        return tuple()


def embed_texts(texts: Sequence[str]) -> list[list[float]]:
    """Batch embed (ไม่ cache เพราะ batching ที่ LM Studio จะเร็วกว่า)

    Args:
        texts: list ของ strings
    Returns:
        list ของ vectors (empty list ถ้า embed fail)
    """
    texts = [t for t in texts if t and t.strip()]
    if not texts:
        return []
    try:
        resp = _client.embeddings.create(model=_EMBED_MODEL, input=list(texts))
        return [list(d.embedding) for d in resp.data]
    except Exception as e:
        logger.warning(f"[Embed] batch failed ({len(texts)} items): {e}")
        return []


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
