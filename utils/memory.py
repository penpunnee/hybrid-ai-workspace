import os
import socket
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

def _detect_chroma_host() -> str:
    """Auto-detect CHROMA_HOST: env > chromadb container (NAS) > NAS LAN IP"""
    if os.getenv("CHROMA_HOST"):
        return os.getenv("CHROMA_HOST")
    for host in ["chromadb", "192.168.51.49", "localhost"]:
        try:
            s = socket.create_connection((host, int(os.getenv("CHROMA_PORT", "8000"))), timeout=1)
            s.close()
            return host
        except Exception:
            continue
    return "localhost"

CHROMA_HOST = _detect_chroma_host()
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))

_client = None
_collections = {}


def _get_client():
    global _client
    if _client is None:
        try:
            import chromadb
            from chromadb.config import Settings
            _client = chromadb.HttpClient(
                host=CHROMA_HOST,
                port=CHROMA_PORT,
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
