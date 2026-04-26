import os
import socket
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

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
        except Exception:
            continue
    return "localhost", 8000

CHROMA_HOST, CHROMA_PORT = _detect_chroma_host()

_client = None
_collections = {}


def _get_client():
    global _client
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
        except Exception:
            _client = None
    return _client


def _get_collection(assistant_name: str):
    client = _get_client()
    if client is None:
        return None
    slug = assistant_name.lower().replace(" ", "_")
    if slug not in _collections:
        try:
            _collections[slug] = client.get_or_create_collection(
                name=f"memory_{slug}",
                metadata={"hnsw:space": "cosine"},
            )
        except Exception:
            return None
    return _collections[slug]


def save_memory(assistant_name: str, user_msg: str, ai_msg: str) -> bool:
    """บันทึกบทสนทนาสำคัญลง ChromaDB"""
    col = _get_collection(assistant_name)
    if col is None:
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
    except Exception:
        return False


def search_memory(assistant_name: str, query: str, n_results: int = 3) -> str:
    """ค้นหา memory ที่เกี่ยวข้องกับ query"""
    col = _get_collection(assistant_name)
    if col is None:
        return ""
    try:
        count = col.count()
        if count == 0:
            return ""
        results = col.query(
            query_texts=[query],
            n_results=min(n_results, count),
        )
        docs = results.get("documents", [[]])[0]
        if not docs:
            return ""
        memory_text = "\n---\n".join(docs)
        return f"[ความจำจากการสนทนาก่อนหน้า]\n{memory_text}"
    except Exception:
        return ""


def save_lesson(topic: str, lesson: str) -> bool:
    """บันทึกบทเรียนที่ AI เรียนรู้จากการสนทนา"""
    client = _get_client()
    if client is None:
        return False
    try:
        col = client.get_or_create_collection("lessons", metadata={"hnsw:space": "cosine"})
        doc_id = f"lesson_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        col.add(
            documents=[f"[บทเรียน: {topic}]\n{lesson}"],
            ids=[doc_id],
            metadatas=[{"topic": topic, "timestamp": datetime.now().isoformat()}]
        )
        return True
    except Exception:
        return False


def save_preference(key: str, value: str) -> bool:
    """บันทึก preference ของพี่ปอย"""
    client = _get_client()
    if client is None:
        return False
    try:
        col = client.get_or_create_collection("preferences", metadata={"hnsw:space": "cosine"})
        col.upsert(
            documents=[f"[preference: {key}]\n{value}"],
            ids=[f"pref_{key}"],
            metadatas=[{"key": key, "timestamp": datetime.now().isoformat()}]
        )
        return True
    except Exception:
        return False


def get_lessons(query: str = "", n_results: int = 3) -> str:
    """ดึงบทเรียนที่เกี่ยวข้อง"""
    client = _get_client()
    if client is None:
        return ""
    try:
        col = client.get_or_create_collection("lessons", metadata={"hnsw:space": "cosine"})
        count = col.count()
        if count == 0:
            return ""
        if query:
            results = col.query(query_texts=[query], n_results=min(n_results, count))
            docs = results.get("documents", [[]])[0]
        else:
            results = col.get()
            docs = results.get("documents", [])[:n_results]
        return "\n---\n".join(docs) if docs else ""
    except Exception:
        return ""


def get_preferences() -> str:
    """ดึง preferences ทั้งหมดของพี่ปอย"""
    client = _get_client()
    if client is None:
        return ""
    try:
        col = client.get_or_create_collection("preferences", metadata={"hnsw:space": "cosine"})
        results = col.get()
        docs = results.get("documents", [])
        return "\n".join(docs) if docs else ""
    except Exception:
        return ""


def search_long_term_memory(query: str, n_results: int = 3) -> str:
    """ค้นหาจาก long_term_memory (ความจำที่ผ่าน Dream Cycle แล้ว)"""
    client = _get_client()
    if client is None:
        return ""
    try:
        col = client.get_or_create_collection("long_term_memory", metadata={"hnsw:space": "cosine"})
        count = col.count()
        if count == 0:
            return ""
        results = col.query(query_texts=[query], n_results=min(n_results, count))
        docs = results.get("documents", [[]])[0]
        if not docs:
            return ""
        return "\n---\n".join(docs)
    except Exception:
        return ""


def get_memory_stats() -> dict:
    """ดูจำนวน entries ใน collections ทั้งหมด"""
    client = _get_client()
    if client is None:
        return {"available": False}
    stats = {"available": True, "collections": {}}
    collection_names = ["lessons", "preferences", "long_term_memory"]
    try:
        for name, cfg in _collections.items():
            try:
                stats["collections"][f"memory_{name}"] = cfg.count()
            except Exception:
                stats["collections"][f"memory_{name}"] = 0
        for cname in collection_names:
            try:
                col = client.get_or_create_collection(cname, metadata={"hnsw:space": "cosine"})
                stats["collections"][cname] = col.count()
            except Exception:
                stats["collections"][cname] = 0
        stats["total"] = sum(stats["collections"].values())
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
    try:
        all_cols = list(_collections.values())
        for col in all_cols:
            try:
                results = col.get(include=["metadatas"])
                ids_to_delete = [
                    results["ids"][i]
                    for i, meta in enumerate(results.get("metadatas", []))
                    if meta and meta.get("timestamp", "9999") < cutoff
                ]
                if ids_to_delete:
                    col.delete(ids=ids_to_delete)
                    deleted_total += len(ids_to_delete)
                    detail[col.name] = len(ids_to_delete)
            except Exception:
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
    except Exception:
        return False
