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


# ── Dream Cycle lock — ป้องกัน concurrent run ────────────────────────────────
dream_lock = asyncio.Lock()
