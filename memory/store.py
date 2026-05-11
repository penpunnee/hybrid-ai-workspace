"""Memory Store — ChromaDB operations พร้อม metadata ครบ

รองรับทั้ง entry ใหม่ (มี metadata) และเก่า (fallback ค่า default)
"""
import uuid
import logging
from datetime import datetime
from .schema import MemoryEntry

logger = logging.getLogger(__name__)


def _get_chroma_client():
    try:
        from utils.memory import _get_client
        return _get_client()
    except Exception as e:
        logger.warning(f"ChromaDB client unavailable: {e}")
        return None


def _get_collection(client, name: str):
    try:
        return client.get_or_create_collection(
            name,
            metadata={"hnsw:space": "cosine"},
        )
    except Exception as e:
        logger.error(f"Cannot get collection '{name}': {e}")
        return None


def save_entry(entry: MemoryEntry, collection_name: str | None = None) -> bool:
    """บันทึก MemoryEntry พร้อม metadata ลง ChromaDB"""
    client = _get_chroma_client()
    if client is None:
        return False

    col_name = collection_name or f"memory_{_safe_slug(entry.assistant)}"
    col = _get_collection(client, col_name)
    if col is None:
        return False

    doc_id = f"mem_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"
    meta = entry.to_metadata()
    meta["timestamp"] = entry.created_at  # backward compat

    try:
        col.upsert(ids=[doc_id], documents=[entry.content], metadatas=[meta])
        logger.debug(f"Saved memory [{entry.type}] confidence={entry.confidence:.2f} source={entry.source}")
        return True
    except Exception as e:
        logger.error(f"save_entry failed: {e}")
        return False


def search_entries(assistant: str, query: str, n_results: int = 5,
                   min_confidence: float = 0.0,
                   verified_only: bool = False) -> list[dict]:
    """ค้นหา memory พร้อม filter ตาม confidence และ verified"""
    client = _get_chroma_client()
    if client is None:
        return []

    col_name = f"memory_{_safe_slug(assistant)}"
    try:
        col = client.get_collection(col_name)
    except Exception:
        return []

    try:
        res = col.query(query_texts=[query], n_results=min(n_results * 2, 20))
    except Exception as e:
        logger.error(f"search_entries query failed: {e}")
        return []

    docs  = res.get("documents", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    dists = res.get("distances", [[]])[0]

    results = []
    for doc, meta, dist in zip(docs, metas, dists):
        confidence = meta.get("confidence", 0.7) if meta else 0.7
        verified   = meta.get("verified", False) if meta else False

        if confidence < min_confidence:
            continue
        if verified_only and not verified:
            continue

        results.append({
            "content":    doc,
            "confidence": confidence,
            "verified":   verified,
            "type":       meta.get("type", "event") if meta else "event",
            "source":     meta.get("source", "conversation") if meta else "conversation",
            "score":      round(1 - dist, 3),  # cosine similarity
            "timestamp":  meta.get("timestamp", "") if meta else "",
        })

    # เรียงตาม verified ก่อน แล้วตาม confidence
    results.sort(key=lambda x: (x["verified"], x["confidence"]), reverse=True)
    return results[:n_results]


def update_confidence(assistant: str, content_snippet: str, new_confidence: float) -> bool:
    """ปรับ confidence ของ memory ที่ match content_snippet"""
    client = _get_chroma_client()
    if client is None:
        return False
    col_name = f"memory_{_safe_slug(assistant)}"
    try:
        col = client.get_collection(col_name)
        res = col.query(query_texts=[content_snippet], n_results=1)
        ids = res.get("ids", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        if not ids:
            return False
        meta = dict(metas[0]) if metas[0] else {}
        meta["confidence"] = new_confidence
        meta["last_accessed"] = datetime.now().isoformat()
        col.update(ids=[ids[0]], metadatas=[meta])
        return True
    except Exception as e:
        logger.error(f"update_confidence failed: {e}")
        return False


def bump_access_count(assistant: str, doc_ids: list[str]) -> None:
    """เพิ่ม access_count เมื่อ memory ถูก retrieve"""
    client = _get_chroma_client()
    if client is None or not doc_ids:
        return
    col_name = f"memory_{_safe_slug(assistant)}"
    try:
        col = client.get_collection(col_name)
        res = col.get(ids=doc_ids)
        metas = res.get("metadatas", [])
        updated_metas = []
        for meta in metas:
            m = dict(meta) if meta else {}
            m["access_count"] = m.get("access_count", 0) + 1
            m["last_accessed"] = datetime.now().isoformat()
            updated_metas.append(m)
        if updated_metas:
            col.update(ids=doc_ids, metadatas=updated_metas)
    except Exception as e:
        logger.debug(f"bump_access_count failed (non-critical): {e}")


def search_long_term(query: str, n_results: int = 3) -> list[dict]:
    """ค้นหาใน long_term_memory collection (จาก Dream cycle)"""
    client = _get_chroma_client()
    if client is None:
        return []
    try:
        col = client.get_collection("long_term_memory")
        res = col.query(query_texts=[query], n_results=n_results)
        docs  = res.get("documents", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        dists = res.get("distances", [[]])[0]
        return [
            {
                "content":    doc,
                "confidence": meta.get("confidence", 0.9) if meta else 0.9,
                "verified":   True,
                "type":       "fact",
                "source":     "dream",
                "score":      round(1 - dist, 3),
            }
            for doc, meta, dist in zip(docs, metas, dists)
        ]
    except Exception as e:
        logger.debug(f"search_long_term: {e}")
        return []


def _safe_slug(name: str) -> str:
    import re
    ascii_only = name.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", ascii_only.lower()).strip("_")
    return slug or "default"
