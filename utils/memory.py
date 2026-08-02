import os
import re
import socket
import logging
import threading
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Configure logging for memory system
logger = logging.getLogger(__name__)

def _detect_chroma_host() -> tuple:
    """Auto-detect CHROMA_HOST and PORT"""
    if os.getenv("CHROMA_HOST"):
        return os.getenv("CHROMA_HOST"), int(os.getenv("CHROMA_PORT", "8000"))
    candidates = [
        ("chromadb", 8000),
        ("192.168.51.49", 8000),
        ("chroma.pawinhome.com", 443),
    ]
    for host, port in candidates:
        try:
            s = socket.create_connection((host, port), timeout=2)
            s.close()
            return host, port
        except Exception as e:
            logger.debug(f"ChromaDB host probe failed for {host}:{port}: {e}")
            continue
    return "localhost", 8000

CHROMA_HOST, CHROMA_PORT = _detect_chroma_host()

# ChromaDB default embedding function (MiniLM) มองอักษรไทยเป็น UNK ทั้งหมด →
# ทุกประโยคไทยได้ vector เดียวกัน (cosine score = 1.000 ทุกคู่ไม่ว่าคนละเรื่องแค่ไหน)
# → semantic recall ภาษาไทยเป็น noise ล้วนมาตั้งแต่ day 1 (พิสูจน์แล้วในโปรเจกต์ JARVIS
# 2026-07-08, ดู wiki concepts/thai-embedding-chromadb.md) แก้ด้วย Ollama multilingual
# model ผ่าน EMBEDDING_MODEL — ปล่อยว่าง (default) = ปิด/ใช้ default MiniLM เดิม
# (ตาม convention ของโปรเจกต์นี้ที่ฟีเจอร์ optional เป็น opt-in ด้วย env ว่าง — ตั้งเป็น
# "paraphrase-multilingual" ใน .env เพื่อเปิดใช้จริง หลัง migrate ข้อมูลเก่าแล้วเท่านั้น)
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "")

# พื้นความเกี่ยวข้องขั้นต่ำของ recall (cosine similarity) — **ไม่ใช่เลขที่เดา**
# มาจาก ground truth 50 คู่ที่คนมาร์ค จากคำถามจริงบน prod 25 ข้อ (backlog ข้อ 12,
# `scripts/recall_groundtruth.py`):
#     0.40 → P=0.62 R=1.00 F1=0.77
#     0.55 → P=0.89 R=0.89 F1=0.89   ← เลือกตัวนี้
#     0.60 → P=0.94 R=0.89 F1=0.91   (F1 สูงกว่านิดเดียว)
#     0.80 → P=1.00 R=0.17 F1=0.29
# เลือก 0.55 แทน 0.60 เพราะเอียงไปทาง recall โดยตั้งใจ — "AI ลืมสิ่งที่เคยคุย"
# ผู้ใช้รู้สึกแย่กว่ามี context เกินมาชิ้นหนึ่ง · ทนทานต่อการมาร์คผิด: พลิก label
# ที่ไม่มั่นใจครบ 64 กรณีแล้ว เกณฑ์ที่ดีที่สุดอยู่ในช่วง 0.525-0.65 เสมอ
# ⚠️ อย่าเอาเลขนี้ไปใช้กับ `user_facts` — คนละลักษณะข้อความ (ประโยคสั้น) ดู backlog ข้อ 16
RECALL_MIN_SCORE = float(os.getenv("RECALL_MIN_SCORE", "0.55"))

_client = None
_collections = {}
_lock = threading.Lock()
_embedding_function = None
_embedding_function_attempted = False
_ef_lock = threading.Lock()


def _ollama_native_url() -> str:
    """OLLAMA_BASE_URL ของโปรเจกต์นี้เป็น OpenAI-compat endpoint (ลงท้าย /v1) —
    chromadb OllamaEmbeddingFunction ต้องการ native Ollama API base แทน"""
    base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    return base[:-len("/v1")] if base.endswith("/v1") else base


def _get_embedding_function():
    """คืน OllamaEmbeddingFunction (multilingual, รองรับไทยจริง) singleton —
    คืน None ถ้าปิดด้วย EMBEDDING_MODEL="" หรือสร้างไม่สำเร็จ (เช่นไม่มีแพ็กเกจ
    `ollama`) แล้วปล่อยให้ collection ต่อ fallback ไปใช้ default embedder ของ chroma"""
    global _embedding_function, _embedding_function_attempted
    if not EMBEDDING_MODEL:
        return None
    with _ef_lock:
        if not _embedding_function_attempted:
            _embedding_function_attempted = True
            try:
                from chromadb.utils.embedding_functions import OllamaEmbeddingFunction
                url = _ollama_native_url()
                _embedding_function = OllamaEmbeddingFunction(url=url, model_name=EMBEDDING_MODEL)
                logger.info(f"Embedding function ready: Ollama '{EMBEDDING_MODEL}' @ {url}")
            except Exception as e:
                logger.warning(
                    f"Embedding function init failed (EMBEDDING_MODEL={EMBEDDING_MODEL}): {e} "
                    "— falling back to ChromaDB default embedder (ภาษาไทยจะ recall ไม่ได้)"
                )
        return _embedding_function


def get_or_create_collection(client, name: str, **kwargs):
    """wrapper รอบ client.get_or_create_collection ที่ inject embedding_function
    ไทย-multilingual อัตโนมัติถ้าพร้อมใช้งาน — ทุกจุดที่สร้าง/ดึง collection ควรผ่านนี่
    แทนเรียก client ตรงๆ กันหลุดไปใช้ default MiniLM"""
    ef = _get_embedding_function()
    if ef is not None:
        kwargs.setdefault("embedding_function", ef)
    kwargs.setdefault("metadata", {"hnsw:space": "cosine"})
    return client.get_or_create_collection(name, **kwargs)


def get_collection(client, name: str, **kwargs):
    """wrapper รอบ client.get_collection ที่ inject embedding_function เดียวกับ
    get_or_create_collection ด้านบน"""
    ef = _get_embedding_function()
    if ef is not None:
        kwargs.setdefault("embedding_function", ef)
    return client.get_collection(name, **kwargs)


def _safe_slug(name: str) -> str:
    """แปลงชื่อ assistant → ชื่อ ChromaDB collection ที่ถูกต้อง [a-zA-Z0-9._-]"""
    # ตัด emoji และ non-ASCII ออก แล้ว sanitize
    ascii_only = name.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", ascii_only.lower()).strip("_")
    return slug or "default"


def _get_client():
    global _client
    with _lock:
        if _client is None:
            try:
                import chromadb
                from chromadb.config import Settings
                ssl = CHROMA_PORT == 443
                _client = chromadb.HttpClient(
                    host=CHROMA_HOST,
                    port=CHROMA_PORT,
                    ssl=ssl,
                    settings=Settings(anonymized_telemetry=False),
                )
                _client.heartbeat()
                logger.info(f"ChromaDB connected to {CHROMA_HOST}:{CHROMA_PORT}")
            except Exception as e:
                logger.error(f"ChromaDB connection error: {str(e)}")
                _client = None
        return _client


def _get_collection(assistant_name: str):
    client = _get_client()
    if client is None:
        return None
    try:
        from memory.store import resolve_slug
        slug = resolve_slug(assistant_name)
    except Exception:
        slug = _safe_slug(assistant_name)
    with _lock:
        if slug not in _collections:
            try:
                _collections[slug] = get_or_create_collection(client, f"memory_{slug}")
            except Exception as e:
                logger.warning(f"Failed to get or create collection for {slug}: {e}")
                return None
        return _collections[slug]


def save_memory(assistant_name: str, user_msg: str, ai_msg: str) -> bool:
    """บันทึกบทสนทนาสำคัญลง ChromaDB"""
    col = _get_collection(assistant_name)
    if col is None:
        logger.error(f"Memory save failed: Collection not available for {assistant_name}")
        return False
    try:
        doc_id = f"{assistant_name}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        document = f"User: {user_msg}\nAssistant: {ai_msg}"
        col.add(
            documents=[document],
            ids=[doc_id],
            metadatas=[{
                "assistant": assistant_name,
                "timestamp": datetime.now().isoformat(),
                "user_msg": user_msg[:200],
            }]
        )
        return True
    except Exception as e:
        logger.error(f"Memory save error for {assistant_name}: {str(e)}")
        return False


def _relevant_docs(results: dict, min_score: float | None = None) -> list:
    """คัดเฉพาะ doc ที่ score ผ่านพื้น — ตัวกลางของทุกจุดที่ query ในโมดูลนี้

    เดิมทั้ง 3 ฟังก์ชันคืน top-N เสมอโดยไม่เคยอ่าน `distances` เลย → ของที่ไม่เกี่ยว
    ถูกฉีดเข้า prompt ทุกครั้งที่คลังไม่ว่าง (backlog ข้อ 3)

    ถ้า chroma ไม่ส่ง distances มา (บาง path/เวอร์ชัน) → คืนทุก doc ตามเดิม
    ดีกว่าตัดทิ้งหมดเพราะอ่านคะแนนไม่ได้
    """
    docs = (results.get("documents") or [[]])[0]
    dists = (results.get("distances") or [[]])[0]
    if not docs:
        return []
    if not dists or len(dists) != len(docs):
        return list(docs)
    floor = RECALL_MIN_SCORE if min_score is None else min_score
    return [d for d, dist in zip(docs, dists) if (1 - dist) >= floor]


def search_memory(assistant_name: str, query: str, n_results: int = 3) -> str:
    """ค้นหา memory ที่เกี่ยวข้องกับ query"""
    col = _get_collection(assistant_name)
    if col is None:
        logger.warning(f"Memory search failed: Collection not available for {assistant_name}")
        return ""
    try:
        count = col.count()
        if count == 0:
            return ""
        results = col.query(
            query_texts=[query],
            n_results=min(n_results, count),
        )
        docs = _relevant_docs(results)
        if not docs:
            return ""
        memory_text = "\n---\n".join(docs)
        return f"[ความจำจากการสนทนาก่อนหน้า]\n{memory_text}"
    except Exception as e:
        logger.error(f"Memory search error for {assistant_name}: {str(e)}")
        return ""


def save_lesson(topic: str, lesson: str) -> bool:
    """บันทึกบทเรียนที่ AI เรียนรู้จากการสนทนา"""
    client = _get_client()
    if client is None:
        return False
    try:
        col = get_or_create_collection(client, "lessons")
        doc_id = f"lesson_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        col.add(
            documents=[f"[บทเรียน: {topic}]\n{lesson}"],
            ids=[doc_id],
            metadatas=[{"topic": topic, "timestamp": datetime.now().isoformat()}]
        )
        return True
    except Exception as e:
        logger.warning(f"save_lesson failed for topic '{topic}': {e}")
        return False


def save_preference(key: str, value: str) -> bool:
    """บันทึก preference ของพี่ปอย"""
    client = _get_client()
    if client is None:
        return False
    try:
        col = get_or_create_collection(client, "preferences")
        col.upsert(
            documents=[f"[preference: {key}]\n{value}"],
            ids=[f"pref_{key}"],
            metadatas=[{"key": key, "timestamp": datetime.now().isoformat()}]
        )
        return True
    except Exception as e:
        logger.warning(f"save_preference failed for key '{key}': {e}")
        return False


def get_lessons(query: str = "", n_results: int = 3) -> str:
    """ดึงบทเรียนที่เกี่ยวข้อง"""
    client = _get_client()
    if client is None:
        return ""
    try:
        col = get_or_create_collection(client, "lessons")
        count = col.count()
        if count == 0:
            return ""
        if query:
            results = col.query(query_texts=[query], n_results=min(n_results, count))
            # มี query = การค้น → กรองความเกี่ยวข้อง
            docs = _relevant_docs(results)
        else:
            results = col.get()
            docs = results.get("documents", [])[:n_results]
        return "\n---\n".join(docs) if docs else ""
    except Exception as e:
        logger.warning(f"get_lessons failed: {e}")
        return ""


def get_preferences() -> str:
    """ดึง preferences ทั้งหมดของพี่ปอย"""
    client = _get_client()
    if client is None:
        return ""
    try:
        col = get_or_create_collection(client, "preferences")
        results = col.get()
        docs = results.get("documents", [])
        return "\n".join(docs) if docs else ""
    except Exception as e:
        logger.warning(f"get_preferences failed: {e}")
        return ""


def search_long_term_memory(query: str, n_results: int = 3) -> str:
    """ค้นหาจาก long_term_memory (ความจำที่ผ่าน Dream Cycle แล้ว)"""
    client = _get_client()
    if client is None:
        return ""
    try:
        col = get_or_create_collection(client, "long_term_memory")
        count = col.count()
        if count == 0:
            return ""
        results = col.query(query_texts=[query], n_results=min(n_results, count))
        docs = _relevant_docs(results)
        if not docs:
            return ""
        return "\n---\n".join(docs)
    except Exception as e:
        logger.warning(f"search_long_term_memory failed for query '{query[:50]}': {e}")
        return ""


def list_lessons(n: int = 50) -> list:
    """ดึง lessons ทั้งหมดพร้อม metadata"""
    client = _get_client()
    if client is None:
        return []
    try:
        col = get_or_create_collection(client, "lessons")
        results = col.get(include=["documents", "metadatas"])
        docs = results.get("documents", [])
        metas = results.get("metadatas", [])
        ids = results.get("ids", [])
        items = []
        for i, doc in enumerate(docs[:n]):
            meta = metas[i] if i < len(metas) else {}
            items.append({
                "id": ids[i] if i < len(ids) else f"lesson_{i}",
                "topic": meta.get("topic", ""),
                "content": doc,
                "timestamp": meta.get("timestamp", ""),
            })
        items.sort(key=lambda x: x["timestamp"], reverse=True)
        return items
    except Exception as e:
        logger.warning(f"list_lessons failed: {e}")
        return []


def list_preferences() -> list:
    """ดึง preferences ทั้งหมดพร้อม metadata"""
    client = _get_client()
    if client is None:
        return []
    try:
        col = get_or_create_collection(client, "preferences")
        results = col.get(include=["documents", "metadatas"])
        docs = results.get("documents", [])
        metas = results.get("metadatas", [])
        ids = results.get("ids", [])
        items = []
        for i, doc in enumerate(docs):
            meta = metas[i] if i < len(metas) else {}
            items.append({
                "id": ids[i] if i < len(ids) else f"pref_{i}",
                "key": meta.get("key", ids[i] if i < len(ids) else ""),
                "content": doc,
                "timestamp": meta.get("timestamp", ""),
            })
        return items
    except Exception as e:
        logger.warning(f"list_preferences failed: {e}")
        return []


def delete_lesson(doc_id: str) -> bool:
    """ลบ lesson ตาม doc_id"""
    client = _get_client()
    if client is None:
        return False
    try:
        col = get_or_create_collection(client, "lessons")
        col.delete(ids=[doc_id])
        return True
    except Exception as e:
        logger.warning(f"delete_lesson failed for id '{doc_id}': {e}")
        return False


def delete_preference(doc_id: str) -> bool:
    """ลบ preference ตาม doc_id/key"""
    client = _get_client()
    if client is None:
        return False
    try:
        col = get_or_create_collection(client, "preferences")
        col.delete(ids=[doc_id])
        return True
    except Exception as e:
        logger.warning(f"delete_preference failed for id '{doc_id}': {e}")
        return False


def get_memory_stats() -> dict:
    """ดูจำนวน entries ใน collections ทั้งหมด"""
    client = _get_client()
    if client is None:
        return {"available": False}
    stats = {"available": True, "collections": {}}
    try:
        all_collections = client.list_collections()
        for col_info in all_collections:
            name = col_info.name if hasattr(col_info, "name") else str(col_info)
            try:
                col = get_collection(client, name)
                stats["collections"][name] = col.count()
            except Exception as e:
                logger.warning(f"get_memory_stats: failed to get count for collection '{name}': {e}")
                stats["collections"][name] = 0
        stats["total"] = sum(stats["collections"].values())
        stats["long_term"] = stats["collections"].get("long_term_memory", 0)
        stats["lessons"] = stats["collections"].get("lessons", 0)
    except Exception as e:
        stats["error"] = str(e)
    return stats


def cleanup_old_memories(days: int = 30) -> dict:
    """ลบ memory ที่เก่ากว่า N วัน จาก short-term collections"""
    from datetime import timedelta
    client = _get_client()
    if client is None:
        return {"ok": False, "error": "ChromaDB ไม่พร้อม"}
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    deleted_total = 0
    detail = {}
    skip_collections = {"long_term_memory", "preferences"}
    try:
        all_collections = client.list_collections()
        for col_info in all_collections:
            name = col_info.name if hasattr(col_info, "name") else str(col_info)
            if name in skip_collections:
                continue
            try:
                col = get_collection(client, name)
                results = col.get(include=["metadatas"])
                ids_to_delete = [
                    results["ids"][i]
                    for i, meta in enumerate(results.get("metadatas", []))
                    if meta and meta.get("timestamp", "9999") < cutoff
                ]
                if ids_to_delete:
                    col.delete(ids=ids_to_delete)
                    deleted_total += len(ids_to_delete)
                    detail[name] = len(ids_to_delete)
            except Exception as e:
                logger.warning(f"cleanup_old_memories: failed to process collection '{name}': {e}")
                continue
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "deleted": deleted_total, "detail": detail, "cutoff_days": days}


def is_memory_available() -> bool:
    """ตรวจสอบว่า ChromaDB พร้อมใช้งานไหม"""
    client = _get_client()
    if client is None:
        return False
    try:
        client.heartbeat()
        return True
    except Exception as e:
        logger.warning(f"ChromaDB heartbeat failed: {e}")
        return False
