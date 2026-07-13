"""Document Indexing & Retrieval — chunk + embed + ChromaDB

ใช้ collection ชื่อ 'documents' ใน ChromaDB เก็บ chunks ของไฟล์ที่ user upload
สำหรับ semantic retrieval ในตอน chat
"""
import hashlib
import logging
import time
from typing import Optional

from utils.chunking import chunk_text, chunk_stats

logger = logging.getLogger(__name__)

_COLLECTION = "documents"


def _get_collection():
    """get/create ChromaDB collection 'documents' — None ถ้า ChromaDB ไม่พร้อม"""
    try:
        from utils.memory import _get_client
        client = _get_client()
        if client is None:
            return None
        return client.get_or_create_collection(
            _COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
    except Exception as e:
        logger.warning(f"[Documents] cannot get collection: {e}")
        return None


def _doc_id(source: str, chunk_index: int) -> str:
    """deterministic ID สำหรับ chunk — ทำให้ re-index ของเดิมจะ upsert ทับ"""
    h = hashlib.md5(source.encode("utf-8", errors="ignore")).hexdigest()[:10]
    return f"doc_{h}_{chunk_index:04d}"


def index_document(
    content: str,
    source: str,
    metadata: Optional[dict] = None,
    chunk_size: int = 500,
    overlap: int = 50,
) -> dict:
    """chunk + embed + เก็บลง ChromaDB

    Args:
        content: เนื้อหา document
        source: ชื่อ/path (ใช้เป็น identifier — re-index จะทับของเดิม)
        metadata: dict metadata เพิ่ม (เช่น title, uploaded_at, content_type)
        chunk_size, overlap: ส่งต่อ chunk_text

    Returns:
        dict {ok, source, chunks_count, stats, error?}
    """
    col = _get_collection()
    if col is None:
        return {"ok": False, "error": "ChromaDB unavailable", "source": source}

    chunks = chunk_text(content, source=source, chunk_size=chunk_size,
                        overlap=overlap, metadata=metadata or {})
    if not chunks:
        return {"ok": False, "error": "no content", "source": source}

    # embed batch
    try:
        from utils.embed import embed_texts
        texts = [c.text for c in chunks]
        vectors = embed_texts(texts)
    except Exception as e:
        logger.warning(f"[Documents] embed failed: {e}")
        vectors = []

    # ลบ chunks เก่าของ source นี้ก่อน (กรณี content เปลี่ยน → จำนวน chunk เปลี่ยน)
    try:
        col.delete(where={"source": source})
    except Exception as e:
        logger.debug(f"[Documents] delete-before-upsert failed (non-critical): {e}")

    now_ts = int(time.time())
    ids: list[str] = []
    docs: list[str] = []
    metas: list[dict] = []
    for c in chunks:
        ids.append(_doc_id(source, c.index))
        docs.append(c.text)
        meta = {
            "source": source,
            "chunk_index": c.index,
            "start": c.start,
            "end": c.end,
            "indexed_at": now_ts,
            **{k: v for k, v in (metadata or {}).items() if isinstance(v, (str, int, float, bool))},
        }
        metas.append(meta)

    try:
        if vectors and len(vectors) == len(docs):
            col.upsert(ids=ids, documents=docs, metadatas=metas, embeddings=vectors)
        else:
            # ChromaDB จะ embed เองด้วย default embedder (ช้ากว่าแต่ใช้ได้)
            col.upsert(ids=ids, documents=docs, metadatas=metas)
        stats = chunk_stats(chunks)
        logger.info(f"[Documents] indexed {source}: {stats}")
        return {"ok": True, "source": source, "chunks_count": len(chunks), "stats": stats}
    except Exception as e:
        logger.error(f"[Documents] upsert failed: {e}")
        return {"ok": False, "error": str(e), "source": source}


def retrieve_chunks(
    query: str,
    top_k: int = 5,
    source_filter: Optional[str] = None,
    min_score: float = 0.0,
) -> list[dict]:
    """ค้น chunks ที่ตรงกับ query → คืน list พร้อม score+source

    Args:
        query: คำค้น
        top_k: คืนกี่ chunks
        source_filter: filter เฉพาะ source ที่ระบุ
        min_score: คะแนน similarity ขั้นต่ำ (0-1)

    Returns:
        list[dict] — {text, source, chunk_index, score, start, end}
    """
    if not query or not query.strip():
        return []

    col = _get_collection()
    if col is None:
        return []

    # ต้อง embed query ด้วย embed_texts() ตัวเดียวกับตอน insert (index_document
    # เก็บ vector explicit ผ่าน LM Studio nomic-embed-text) ไม่งั้น ChromaDB จะ
    # auto-embed query_texts ด้วย default embedder (MiniLM 384-dim) ซึ่งมิติไม่ตรง
    # กับ vector ที่ persist ไว้ (768-dim) → query พังทุกครั้งแบบเงียบๆ (เจอจริง
    # 2026-07-13 ทดสอบ upload PDF scan — ดู tests/test_documents_retrieve.py)
    query_vec: list = []
    try:
        from utils.embed import embed_texts
        query_vec = embed_texts([query])
    except Exception as e:
        logger.debug(f"[Documents] query embed failed, fallback to query_texts: {e}")

    where = {"source": source_filter} if source_filter else None
    try:
        # query มากกว่า top_k เพื่อ rerank
        n = min(top_k * 2, 20)
        kwargs = {"n_results": n}
        if query_vec:
            kwargs["query_embeddings"] = query_vec
        else:
            kwargs["query_texts"] = [query]
        if where:
            kwargs["where"] = where
        res = col.query(**kwargs)
    except Exception as e:
        logger.warning(f"[Documents] query failed: {e}")
        return []

    docs  = res.get("documents", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    dists = res.get("distances", [[]])[0]

    items: list[dict] = []
    for doc, meta, dist in zip(docs, metas, dists):
        meta = meta or {}
        score = round(1 - float(dist), 4)  # cosine sim
        if score < min_score:
            continue
        items.append({
            "text": doc,
            "source": meta.get("source", "?"),
            "chunk_index": int(meta.get("chunk_index", 0)),
            "start": int(meta.get("start", 0)),
            "end": int(meta.get("end", 0)),
            "score": score,
        })

    # rerank กับ embedding ของ query (LMStudio) เพื่อ accuracy
    try:
        from utils.embed import rerank_by_similarity
        reranked = rerank_by_similarity(
            query, items,
            text_keys=("text",),
            top_k=top_k,
        )
        if reranked:
            items = reranked
    except Exception as e:
        logger.debug(f"[Documents] rerank skipped: {e}")
        items = items[:top_k]

    # context budget: trim low-score + token cap
    try:
        from utils.context_budget import filter_by_score, trim_to_budget
        items = filter_by_score(items, score_key="score", min_score=max(min_score, 0.3))
        items = trim_to_budget(items, text_keys=("text",), max_tokens=1500)
    except Exception as e:
        logger.debug(f"[Documents] budget trim skipped: {e}")

    return items


def list_documents() -> list[dict]:
    """list documents ที่ index อยู่ — group ตาม source"""
    col = _get_collection()
    if col is None:
        return []
    try:
        res = col.get(include=["metadatas"])
        metas = res.get("metadatas", [])
    except Exception as e:
        logger.warning(f"[Documents] list failed: {e}")
        return []

    by_source: dict[str, dict] = {}
    for meta in metas:
        if not meta:
            continue
        src = meta.get("source", "?")
        d = by_source.setdefault(src, {"source": src, "chunks_count": 0,
                                       "indexed_at": meta.get("indexed_at", 0)})
        d["chunks_count"] += 1
        # ใช้ indexed_at ล่าสุด
        if meta.get("indexed_at", 0) > d["indexed_at"]:
            d["indexed_at"] = meta.get("indexed_at", 0)
    return sorted(by_source.values(), key=lambda x: x["indexed_at"], reverse=True)


def delete_document(source: str) -> bool:
    """ลบ chunks ทั้งหมดของ source"""
    col = _get_collection()
    if col is None:
        return False
    try:
        col.delete(where={"source": source})
        logger.info(f"[Documents] deleted {source}")
        return True
    except Exception as e:
        logger.warning(f"[Documents] delete failed: {e}")
        return False


def format_for_context(items: list[dict], max_chars: int = 2000) -> str:
    """แปลง retrieved chunks เป็น context string พร้อม citation markers"""
    if not items:
        return ""
    lines = ["📄 **เอกสารที่เกี่ยวข้อง:**", ""]
    used = 0
    for i, it in enumerate(items, 1):
        snippet = it["text"][:600]
        block = f"[{i}] _(จาก: {it['source']}, score: {it['score']})_\n{snippet}"
        if used + len(block) > max_chars:
            break
        lines.append(block)
        lines.append("")
        used += len(block)
    return "\n".join(lines).rstrip()
