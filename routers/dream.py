import logging
import os
from fastapi import APIRouter, Request, HTTPException
from starlette.concurrency import run_in_threadpool

from core.state import dream_lock
from utils.dream import run_dream_cycle, get_latest_report, list_reports
from utils.http_limits import json_body_capped, MAX_BODY_BYTES

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
        data = await json_body_capped(request, MAX_BODY_BYTES)
    except HTTPException as e:
        # **เฉพาะ 413** ที่ต้องทะลุออกไป — `except Exception` กว้างๆ จะกลืนเพดานที่เพิ่งใส่
        # ⚠️ ห้าม re-raise ทั้งก้อน: `json_body_capped()` โยน **400** เมื่อ parse ไม่ได้
        # ซึ่งเป็นเคสที่เส้นนี้ตั้งใจให้ทนได้ (body ไม่บังคับ) — รูปแบบเดียวกับ memory/cleanup
        if e.status_code == 413:
            raise
        data = {}
    except Exception:
        data = {}
    provider = data.get("provider", _default_dream_provider()) if isinstance(data, dict) else _default_dream_provider()
    hours = data.get("hours", 24) if isinstance(data, dict) else 24

    # ⚠️ `.result(timeout=...)` เป็น call แบบบล็อก — เรียกตรงๆ ใน async def จะแช่
    # event loop ได้ถึง _DREAM_TIMEOUT (10 นาที) = ทั้งแอปหยุดตอบ · ต้องรอผ่าน threadpool
    from concurrent.futures import ThreadPoolExecutor
    async with dream_lock:
        ex = ThreadPoolExecutor(max_workers=1)
        fut = ex.submit(run_dream_cycle, provider, hours)
        try:
            result = await run_in_threadpool(fut.result, timeout=_DREAM_TIMEOUT)
        except TimeoutError:
            logger.error(f"Dream cycle timed out after {_DREAM_TIMEOUT}s")
            return {"ok": False, "error": {"code": "DREAM_TIMEOUT", "message": f"Dream Cycle ใช้เวลานานเกิน {_DREAM_TIMEOUT//60} นาที"}}
        except Exception as e:
            logger.error(f"Dream cycle error: {e}")
            return {"ok": False, "error": {"code": "DREAM_ERROR", "message": str(e)}}
        finally:
            # wait=False เสมอ — `with ThreadPoolExecutor` เดิม shutdown(wait=True) ตอนออก
            # ซึ่งบนเส้น timeout แปลว่ากลับไปแช่ event loop รอ dream ที่เพิ่งบอกว่าไม่รอ
            ex.shutdown(wait=False)

    return {"ok": True, "report": result}


@router.get("/report")
def dream_report():
    return get_latest_report()


@router.get("/history")
def dream_history(limit: int = 10):
    return {"reports": list_reports(limit)}
