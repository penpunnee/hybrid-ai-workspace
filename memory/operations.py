"""Memory Operations — unified API สำหรับทั้งระบบ

ใช้แทน utils/memory.py ในอนาคต ตอนนี้รันควบคู่กัน
"""
import logging
from .schema import MemoryEntry
from .working import working_memory
from .store import save_entry, search_entries, search_long_term, search_user_facts
from .teach import process_teaching

logger = logging.getLogger(__name__)


def remember(assistant: str, prompt: str, response: str) -> None:
    """บันทึก interaction ลง episodic memory พร้อม metadata"""
    entry = MemoryEntry(
        content=f"Q: {prompt[:200]}\nA: {response[:400]}",
        assistant=assistant,
        type="event",
        confidence=0.7,
        source="conversation",
        verified=False,
    )
    save_entry(entry)


def recall(assistant: str, query: str, session_id: str = "",
           n_results: int = 5, min_confidence: float = 0.4) -> str:
    """
    ดึง memory ที่เกี่ยวข้องจากทุก tier:
    1. Working memory (session ปัจจุบัน)
    2. Episodic memory (ChromaDB short-term)
    3. Long-term memory (Dream consolidated)
    """
    parts = []

    # Tier 1 — Working Memory
    if session_id:
        ctx = working_memory.get_context_text(session_id, n=3)
        if ctx:
            parts.append(ctx)

    # Tier 2 — Episodic Memory (per-assistant)
    episodic = search_entries(assistant, query, n_results=n_results,
                              min_confidence=min_confidence)
    if episodic:
        lines = ["[ความทรงจำระยะสั้น]"]
        for e in episodic:
            label = MemoryEntry.confidence_label(e["confidence"])
            verified_mark = " ✓" if e["verified"] else ""
            lines.append(f"• {label}{verified_mark} {e['content'][:200]}")
        parts.append("\n".join(lines))

    # Tier 2.5 — User Facts (shared across all Assistants)
    user_facts = search_user_facts(query, n_results=n_results)
    if user_facts:
        lines = ["[ข้อมูลของคุณ]"]
        for uf in user_facts:
            lines.append(f"• ✅ {uf['content'][:200]}")
        parts.append("\n".join(lines))

    # Tier 3 — Long-term (Dream promoted)
    long_term = search_long_term(query, n_results=3)
    if long_term:
        lines = ["[ความทรงจำระยะยาว (consolidated)]"]
        for lt in long_term:
            lines.append(f"• ✅ {lt['content'][:200]}")
        parts.append("\n".join(lines))

    return "\n\n".join(parts)


def teach(assistant: str, user_text: str, ai_response: str = "") -> bool:
    """ตรวจจับและบันทึก teaching signal จาก user"""
    return process_teaching(assistant, user_text, ai_response)


def push_working(session_id: str, role: str, content: str) -> None:
    working_memory.push(session_id, role, content)


def get_memory_summary(assistant: str) -> dict:
    """สรุปสถานะ memory ทั้งหมด"""
    from .store import _get_chroma_client, _safe_slug
    client = _get_chroma_client()
    result = {"episodic": 0, "long_term": 0, "verified_facts": 0, "available": False}
    if client is None:
        return result
    try:
        col_name = f"memory_{_safe_slug(assistant)}"
        col = client.get_collection(col_name)
        all_data = col.get()
        metas = all_data.get("metadatas", [])
        result["episodic"] = len(metas)
        result["verified_facts"] = sum(1 for m in metas if m and m.get("verified"))
        result["available"] = True
    except Exception:
        pass
    try:
        lt_col = client.get_collection("long_term_memory")
        result["long_term"] = lt_col.count()
    except Exception:
        pass
    return result
