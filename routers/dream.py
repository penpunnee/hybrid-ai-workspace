import logging
import os
from fastapi import APIRouter, Request

from core.state import dream_lock
from utils.dream import run_dream_cycle, get_latest_report, list_reports

router = APIRouter(prefix="/api/dream", tags=["dream"])
logger = logging.getLogger(__name__)

_DREAM_TIMEOUT = int(os.getenv("DREAM_TIMEOUT", "600"))  # 10 นาที default


def _default_dream_provider() -> str:
    """ให้ router ตัดสินใจ — single source of truth"""
    return "auto"


@router.post("")
async def trigger_dream(request: Request):
    """Trigger dream cycle — ป้องกัน concurrent run ด้วย lock"""
    if dream_lock.locked():
        return {"ok": False, "error": "Dream Cycle กำลังรันอยู่แล้ว กรุณารอให้เสร็จก่อน"}

    try:
        data = await request.json()
    except Exception:
        data = {}
    provider = data.get("provider", _default_dream_provider()) if isinstance(data, dict) else _default_dream_provider()
    hours = data.get("hours", 24) if isinstance(data, dict) else 24

    from concurrent.futures import ThreadPoolExecutor
    async with dream_lock:
        with ThreadPoolExecutor(max_workers=1) as ex:
            try:
                result = ex.submit(run_dream_cycle, provider, hours).result(timeout=_DREAM_TIMEOUT)
            except TimeoutError:
                logger.error(f"Dream cycle timed out after {_DREAM_TIMEOUT}s")
                return {"ok": False, "error": {"code": "DREAM_TIMEOUT", "message": f"Dream Cycle ใช้เวลานานเกิน {_DREAM_TIMEOUT//60} นาที"}}
            except Exception as e:
                logger.error(f"Dream cycle error: {e}")
                return {"ok": False, "error": {"code": "DREAM_ERROR", "message": str(e)}}

    return {"ok": True, "report": result}


@router.get("/report")
def dream_report():
    return get_latest_report()


@router.get("/history")
def dream_history(limit: int = 10):
    return {"reports": list_reports(limit)}
