"""Memory Store — ChromaDB operations พร้อม metadata ครบ

รองรับทั้ง entry ใหม่ (มี metadata) และเก่า (fallback ค่า default)
"""
import uuid
import logging
from datetime import datetime
from .dualvec import key_hits, merge_max, sync_key
from .lexical import passes_lexical
from .schema import MemoryEntry

logger = logging.getLogger(__name__)

# พื้นความเกี่ยวข้องร่วมกับ utils/memory.py — import มาใช้ตัวเดียวกัน ไม่ประกาศซ้ำ
# เพราะถ้าแยกกันไว้ วันหนึ่งจะแก้ที่เดียวแล้วลืมอีกที่ (ที่มาของเลขดูใน utils/memory.py)
def _recall_min_score() -> float:
    from utils.memory import RECALL_MIN_SCORE

    return RECALL_MIN_SCORE


def _get_chroma_client():
    try:
        from utils.memory import _get_client
        return _get_client()
    except Exception as e:
        logger.warning(f"ChromaDB client unavailable: {e}")
        return None


def _get_collection(client, name: str):
    try:
        from utils.memory import get_or_create_collection
        return get_or_create_collection(client, name)
    except Exception as e:
        logger.error(f"Cannot get collection '{name}': {e}")
        return None


def save_entry(entry: MemoryEntry, collection_name: str | None = None) -> bool:
    """บันทึก MemoryEntry พร้อม metadata ลง ChromaDB"""
    client = _get_chroma_client()
    if client is None:
        return False

    col_name = collection_name or f"memory_{resolve_slug(entry.assistant)}"
    col = _get_collection(client, col_name)
    if col is None:
        return False

    doc_id = f"mem_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"
    meta = entry.to_metadata()
    meta["timestamp"] = entry.created_at  # backward compat

    try:
        col.upsert(ids=[doc_id], documents=[entry.content], metadatas=[meta])
        logger.debug(f"Saved memory [{entry.type}] confidence={entry.confidence:.2f} source={entry.source}")
        # vector ที่สอง (ข้อ 17) — ล้มได้โดยไม่ทำให้การบันทึกหลักล้มตาม
        sync_key(client, col_name, doc_id, entry.content, metadata=meta)
        return True
    except Exception as e:
        logger.error(f"save_entry failed: {e}")
        return False


def _ids_or_placeholder(res: dict, n: int) -> list:
    """ids จากผล query — สร้าง placeholder ถ้าไม่มี/ไม่ครบ

    โค้ด dual-vector ใช้ id เป็นตัวเชื่อมกับฝั่งกุญแจ ถ้าปล่อยให้ ids ว่างแล้ว zip
    ต่อไปเลย ผลลัพธ์จะกลายเป็นว่างทั้งชุด **เงียบๆ** ทั้งที่ query สำเร็จ —
    รูปแบบ "ล้มเหลวที่หน้าตาเหมือนสำเร็จ" ที่ไล่แก้มาทั้ง audit
    placeholder จะไม่แมตช์กับกุญแจใดๆ = เสียแค่ประโยชน์ของ vector ที่สอง ไม่เสียผลหลัก
    """
    ids = (res.get("ids") or [[]])[0]
    if len(ids) == n:
        return list(ids)
    return [f"_noid_{i}" for i in range(n)]


def search_entries(assistant: str, query: str, n_results: int = 5,
                   min_confidence: float = 0.0,
                   verified_only: bool = False) -> list[dict]:
    """ค้นหา memory พร้อม filter ตาม confidence และ verified"""
    client = _get_chroma_client()
    if client is None:
        return []

    col_name = f"memory_{resolve_slug(assistant)}"
    try:
        from utils.memory import get_collection
        col = get_collection(client, col_name)
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
    ids   = _ids_or_placeholder(res, len(docs))

    floor = _recall_min_score()
    candidates = []
    for doc_id, doc, meta, dist in zip(ids, docs, metas, dists):
        confidence = meta.get("confidence", 0.7) if meta else 0.7
        verified   = meta.get("verified", False) if meta else False

        if confidence < min_confidence:
            continue
        if verified_only and not verified:
            continue

        candidates.append({
            "id":         doc_id,
            "content":    doc,
            "confidence": confidence,
            "verified":   verified,
            "type":       meta.get("type", "event") if meta else "event",
            "source":     meta.get("source", "conversation") if meta else "conversation",
            "score":      round(1 - dist, 3),  # cosine similarity
            "timestamp":  meta.get("timestamp", "") if meta else "",
        })

    # vector ที่สอง (ข้อ 17): เอา max ของ (doc เต็ม, กุญแจ) **ก่อน** ตัดด้วยพื้น —
    # ประเด็นทั้งหมดคือ doc ที่ถูก dilution กดจนต่ำกว่าพื้น ต้องมีโอกาสกลับมา
    ks, kdocs = key_hits(client, col_name, query, n_results=min(n_results * 2, 20))
    candidates = merge_max(candidates, ks, key_docs=kdocs)

    # พื้นความเกี่ยวข้อง — เดิมมีแต่ตัวกรอง confidence/verified แล้วเอา score ไป
    # *จัดอันดับ* อย่างเดียว ทำให้ memory ที่มั่นใจสูงแต่ไม่เกี่ยวกับคำถามยังถูก
    # surface ขึ้นมาเสมอ (backlog ข้อ 4)
    # OR-gate กับ lexical (ข้อ 16): semantic จับตัวระบุ (รุ่น/รหัส/IP) ไม่ได้
    # วัดจริง 50 คู่ — semantic อย่างเดียว R=0.89 · OR lexical R=1.00 โดย P ไม่ตก
    results = [r for r in candidates
               if r.get("score", 0.0) >= floor or passes_lexical(query, r.get("content"))]

    results = _rank_results(results, n_results)

    # Step 0: บันทึกการใช้งาน — bump access_count + refresh last_accessed
    # ของ memory ที่ถูก surface จริง (top-k) → ให้ retention policy มีข้อมูล recency/frequency
    bumped_ids = [r["id"] for r in results if r.get("id")]
    if bumped_ids:
        try:
            bump_access_count(assistant, bumped_ids)
        except Exception as e:
            logger.debug(f"bump on search skipped: {e}")

    return results


def _rank_results(results: list[dict], n_results: int) -> list[dict]:
    """จัดอันดับผลค้นหา: verified ก่อนเสมอ แล้วผสม confidence + semantic score
    (เดิมเรียง confidence ล้วน → memory มั่นใจสูงแต่ไม่เกี่ยวกับ query เด้งทับตัวที่ relevant จริง)"""
    results.sort(
        key=lambda x: (x["verified"], 0.5 * x.get("confidence", 0.0) + 0.5 * x.get("score", 0.0)),
        reverse=True,
    )
    return results[:n_results]


def update_confidence(assistant: str, content_snippet: str, new_confidence: float) -> bool:
    """ปรับ confidence ของ memory ที่ match content_snippet"""
    client = _get_chroma_client()
    if client is None:
        return False
    col_name = f"memory_{resolve_slug(assistant)}"
    try:
        from utils.memory import get_collection
        col = get_collection(client, col_name)
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
    col_name = f"memory_{resolve_slug(assistant)}"
    try:
        from utils.memory import get_collection
        col = get_collection(client, col_name)
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
        from utils.memory import get_collection
        col = get_collection(client, "long_term_memory")
        res = col.query(query_texts=[query], n_results=n_results)
        docs  = res.get("documents", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        dists = res.get("distances", [[]])[0]
        floor = _recall_min_score()
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
            # เดิมไม่มีตัวกรองเลย — ธีมจาก Dream ถูกฉีดเข้า prompt ทุกครั้งที่คลังไม่ว่าง
            # OR-gate กับ lexical (ข้อ 16) ให้ตรงกับเส้นอื่น
            if (1 - dist) >= floor or passes_lexical(query, doc)
        ]
    except Exception as e:
        logger.debug(f"search_long_term: {e}")
        return []


_USER_FACTS_MIN_SCORE = 0.6


def search_user_facts(query: str, n_results: int = 3,
                      min_score: float = _USER_FACTS_MIN_SCORE) -> list[dict]:
    """ค้นหาใน user_facts collection — shared ทุก Assistant (User-level memory)"""
    client = _get_chroma_client()
    if client is None:
        return []
    try:
        from utils.memory import get_collection
        col = get_collection(client, "user_facts")
        res = col.query(query_texts=[query], n_results=n_results)
        docs  = res.get("documents", [[]])[0]
        # id เป็นตัวเชื่อมกับฝั่งกุญแจ — ถ้าหายไปต้องไม่ทำให้ผลว่างทั้งชุดเงียบๆ
        ids   = _ids_or_placeholder(res, len(docs))
        metas = res.get("metadatas", [[]])[0]
        dists = res.get("distances", [[]])[0]
        candidates = [
            {
                "id":         doc_id,
                "content":    doc,
                "confidence": meta.get("confidence", 0.95) if meta else 0.95,
                "verified":   True,
                "type":       meta.get("type", "fact") if meta else "fact",
                "source":     meta.get("source", "user_taught") if meta else "user_taught",
                "score":      round(1 - dist, 3),
            }
            for doc_id, doc, meta, dist in zip(ids, docs, metas, dists)
        ]
        # vector ที่สอง (ข้อ 17) — สำหรับ fact สั้น กุญแจคือตัวมันเองที่ถอดตัวระบุออก
        # (วัดจริง: "Synology รุ่นไหน" ↔ "…Synology DS923+" 0.578 → ถอดรุ่นออกได้ 0.791)
        # ⚠️ ยังไม่พอปิดข้อ 16 — เคส "เราเตอร์ที่บ้านยี่ห้ออะไร" ได้ max 0.505 ยังต่ำกว่า 0.6
        # ต่อไว้เพื่อให้กลไกเหมือนกันทุกเส้น (บทเรียนซ้ำของ audit: แก้ 3 ใน 4 จุดแล้วคิดว่าจบ)
        ks, _ = key_hits(client, "user_facts", query, n_results=n_results * 2)
        merged = merge_max(candidates, ks)
        # OR-gate กับ lexical (ข้อ 16) — เส้นที่ปัญหาตัวระบุรุ่นรุนแรงที่สุด
        # ("เราเตอร์ที่บ้านยี่ห้ออะไร" semantic 0.447 · lexical 0.565)
        return [r for r in merged
                if r["score"] >= min_score or passes_lexical(query, r.get("content"))]
    except Exception as e:
        logger.debug(f"search_user_facts: {e}")
        return []


def list_entries(assistant: str, query: str = "", limit: int = 50) -> list[dict]:
    """List/preview episodic memory entries — สำหรับ admin cleanup (แก้ pain ที่ต้อง
    ต่อ ChromaDB ตรงเวลาลบ memory ปนเปื้อนจากการเทส). query ว่าง = ล่าสุดก่อน,
    มี query = semantic search preview (เหมือนที่โมเดลจะเห็นตอน recall จริง)"""
    client = _get_chroma_client()
    if client is None:
        return []

    col_name = f"memory_{resolve_slug(assistant)}"
    try:
        from utils.memory import get_collection
        col = get_collection(client, col_name)
    except Exception:
        return []

    try:
        if query:
            res = col.query(query_texts=[query], n_results=min(limit, 50))
            ids   = res.get("ids", [[]])[0]
            docs  = res.get("documents", [[]])[0]
            metas = res.get("metadatas", [[]])[0]
        else:
            res = col.get(limit=limit, include=["documents", "metadatas"])
            ids   = res.get("ids", [])
            docs  = res.get("documents", [])
            metas = res.get("metadatas", [])
    except Exception as e:
        logger.error(f"list_entries failed: {e}")
        return []

    items = [
        {
            "id":         doc_id,
            "content":    doc,
            "confidence": (meta or {}).get("confidence", 0.7),
            "verified":   (meta or {}).get("verified", False),
            "type":       (meta or {}).get("type", "event"),
            "source":     (meta or {}).get("source", "conversation"),
            "timestamp":  (meta or {}).get("timestamp", ""),
        }
        for doc_id, doc, meta in zip(ids, docs, metas)
    ]
    if not query:
        items.sort(key=lambda x: x["timestamp"], reverse=True)
    return items


def delete_entry(assistant: str, doc_id: str) -> bool:
    """ลบ episodic memory entry เดี่ยวตาม id"""
    client = _get_chroma_client()
    if client is None:
        return False
    col_name = f"memory_{resolve_slug(assistant)}"
    try:
        from utils.memory import get_collection
        col = get_collection(client, col_name)
        col.delete(ids=[doc_id])
        return True
    except Exception as e:
        logger.error(f"delete_entry failed for id '{doc_id}': {e}")
        return False


def _safe_slug(name: str) -> str:
    import re
    ascii_only = name.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", ascii_only.lower()).strip("_")
    return slug or "default"


def resolve_slug(name: str) -> str:
    """คืน slug ที่เสถียรจาก config["slug"] (ไม่ derive จากชื่อ display → กัน
    collection orphan เมื่อ rename). `name` อาจเป็นชื่อเต็ม ('🧡 ขวัญ (Logic)')
    หรือ slug ('kwan'). assistant ที่ไม่อยู่ใน config → fallback _safe_slug (เดิม)."""
    try:
        from assistants.config import ASSISTANTS
        for disp, cfg in ASSISTANTS.items():
            if name == disp or name == cfg.get("slug"):
                return cfg["slug"]
    except Exception:
        pass
    return _safe_slug(name)
