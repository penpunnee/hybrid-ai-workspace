"""Feedback API — thumbs up/down + stats

Endpoints:
  POST /api/feedback              — บันทึก rating
  GET  /api/feedback/stats        — สถิติรวม
  GET  /api/feedback/{message_id} — ดู feedback ของ message
"""
import logging
from fastapi import APIRouter, Request, HTTPException

from utils.feedback import (
    save_feedback, get_feedback, get_stats, list_low_rated_messages,
)

router = APIRouter(prefix="/api/feedback", tags=["feedback"])
logger = logging.getLogger(__name__)


@router.post("")
async def submit(request: Request):
    """รับ {assistant, session_id, message_id, rating, comment?}"""
    data = await request.json()
    try:
        message_id = int(data.get("message_id"))
    except (TypeError, ValueError):
        raise HTTPException(400, "message_id required (integer)")

    result = save_feedback(
        assistant=str(data.get("assistant", "")).strip(),
        session_id=str(data.get("session_id", "default")),
        message_id=message_id,
        rating=str(data.get("rating", "")).strip(),
        comment=str(data.get("comment", "")).strip(),
    )
    if not result.get("ok"):
        raise HTTPException(400, result.get("error") or "save failed")
    return result


@router.get("/stats")
def stats(assistant: str = ""):
    return get_stats(assistant or None)


@router.get("/low-rated")
def low_rated(assistant: str = "", limit: int = 20):
    return {"items": list_low_rated_messages(assistant or None, limit=limit)}


@router.get("/{message_id}")
def get_one(message_id: int):
    fb = get_feedback(message_id)
    if not fb:
        raise HTTPException(404, "no feedback")
    return fb
