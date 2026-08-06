"""Shared in-memory state สำหรับทั้งระบบ"""
import asyncio
import logging

logger = logging.getLogger(__name__)

# ── Share link store ──────────────────────────────────────────────────────────
_share_store: dict = {}
_SHARE_STORE_LIMIT = 500


def share_store_set(token: str, data: dict):
    if len(_share_store) >= _SHARE_STORE_LIMIT:
        oldest = next(iter(_share_store))
        del _share_store[oldest]
        logger.debug(f"share_store evicted oldest entry (limit={_SHARE_STORE_LIMIT})")
    _share_store[token] = data


def share_store_get(token: str) -> dict | None:
    return _share_store.get(token)


def share_store_delete_by_session(assistant: str, session_id: str) -> list[str]:
    """ถอด share token ของ session นั้นออกจาก in-memory store — คืนรายการ token ที่ถอด

    ⚠️ ต้องเรียกคู่กับการลบแถวใน `share_links` เสมอ — `get_shared_data()` อ่าน store นี้
    **ก่อน** DB แล้วยังเติม cache กลับจาก DB ด้วย ⇒ ลบแต่ DB = token ที่ถูก cache ไว้แล้ว
    ยังตอบ `ok:true` ต่อไปจนกว่าโปรเซสจะรีสตาร์ท (ลบที่ดูเหมือนลบแต่ไม่ได้ลบ)
    """
    hits = [
        t for t, d in _share_store.items()
        if isinstance(d, dict) and d.get("assistant") == assistant and d.get("session_id") == session_id
    ]
    for t in hits:
        del _share_store[t]
    return hits


# ── Dream Cycle lock — ป้องกัน concurrent run ────────────────────────────────
dream_lock = asyncio.Lock()
