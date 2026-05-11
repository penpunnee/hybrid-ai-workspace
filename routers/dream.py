import logging
from fastapi import APIRouter, Request

from core.state import dream_lock
from utils.dream import run_dream_cycle, get_latest_report, list_reports

router = APIRouter(prefix="/api/dream", tags=["dream"])
logger = logging.getLogger(__name__)


@router.post("")
async def trigger_dream(request: Request):
    """Trigger dream cycle — ป้องกัน concurrent run ด้วย lock"""
    if dream_lock.locked():
        return {"ok": False, "error": "Dream Cycle กำลังรันอยู่แล้ว กรุณารอให้เสร็จก่อน"}

    try:
        data = await request.json()
    except Exception:
        data = {}
    provider = data.get("provider", "ollama") if isinstance(data, dict) else "ollama"
    hours = data.get("hours", 24) if isinstance(data, dict) else 24

    from concurrent.futures import ThreadPoolExecutor
    async with dream_lock:
        with ThreadPoolExecutor(max_workers=1) as ex:
            try:
                result = ex.submit(run_dream_cycle, provider, hours).result(timeout=300)
            except TimeoutError:
                logger.error("Dream cycle timed out after 300s")
                return {"ok": False, "error": {"code": "DREAM_TIMEOUT", "message": "Dream Cycle ใช้เวลานานเกิน 5 นาที"}}
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
