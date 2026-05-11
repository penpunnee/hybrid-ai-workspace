import logging
import os
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(timezone="Asia/Bangkok")


def _scheduled_dream():
    from utils.dream import run_dream_cycle
    from utils.notify import send_line_notify
    provider = "gemini" if os.getenv("GEMINI_API_KEY") else "ollama"
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    logger.info(f"[Scheduler] Dream Cycle ({ts}) provider={provider}")
    try:
        run_dream_cycle(provider=provider)
        logger.info("[Scheduler] Dream Cycle เสร็จ")
    except Exception as e:
        logger.error(f"[Scheduler] Dream error: {e}")
        try:
            send_line_notify(f"⚠️ Dream Cycle ล้มเหลว ({ts})\nError: {e}")
        except Exception:
            pass


def start_scheduler():
    scheduler.add_job(
        _scheduled_dream,
        CronTrigger(hour=2, minute=0),
        id="dream_nightly",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("[Scheduler] ตั้ง Dream รันทุกคืนตี 2 แล้ว")
