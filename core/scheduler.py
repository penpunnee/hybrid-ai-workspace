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


def _scheduled_db_backup():
    """สำรอง DB แล้วยิง heartbeat **เฉพาะตอนที่สำเร็จจริง**

    การยิง heartbeat ทุกครั้งที่ job "รันจบ" จะทำให้ตัวเฝ้ายืนยันว่าระบบแข็งแรง
    แม้ในรอบที่ backup ออกมาเป็นของเปล่า — ตัวเฝ้าที่โกหกแย่กว่าไม่มีตัวเฝ้า
    เส้นเงียบทุกเส้น (ตายกลางคัน / ของเปล่า / ไม่พบ DB) ต้องไม่ยิง
    """
    from utils.db_backup import BackupUnhealthy, run_db_backup
    from utils.heartbeat import ping
    try:
        archive = run_db_backup()
        if archive:
            logger.info(f"[Scheduler] DB backup เสร็จ → {archive}")
            ping()
        else:
            logger.error("[Scheduler] DB backup ไม่พบ database ให้สำรอง — ไม่ยิง heartbeat")
    except BackupUnhealthy as e:
        logger.error(f"[Scheduler] DB backup ได้ของที่ใช้กู้ไม่ได้: {e} (เก็บไว้ที่ {e.archive})")
    except Exception as e:
        logger.error(f"[Scheduler] DB backup error: {e}")


def start_scheduler():
    # ⚠️ CronTrigger ต้องส่ง timezone ตรงๆ — BackgroundScheduler(timezone=...) ไม่ inject
    # เข้า CronTrigger ที่สร้างแยกไว้ก่อน add_job() เอง มันเลย fallback เป็น OS-local
    # (container ไม่ตั้ง TZ = UTC) ทำให้ยิงเพี้ยนไป 7 ชม. (เจอจริง 2026-07-13: Dream ยิงตี 9
    # แทนที่จะเป็นตี 2 บางกอก — ดู tests/test_scheduler.py ที่กันไม่ให้ regression กลับมา)
    scheduler.add_job(
        _scheduled_dream,
        CronTrigger(hour=2, minute=0, timezone="Asia/Bangkok"),
        id="dream_nightly",
        replace_existing=True,
    )
    # 03:30 — ก่อน chroma backup (DSM task 00:01 คนละตัว); ตั้งใน DSM ไม่ได้เพราะ
    # sudo จาก SSH จำกัดแค่ docker เลยฝัง job ในแอปแทน
    scheduler.add_job(
        _scheduled_db_backup,
        CronTrigger(hour=3, minute=30, timezone="Asia/Bangkok"),
        id="db_backup_nightly",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("[Scheduler] ตั้ง Dream ตี 2 + DB backup 03:30 แล้ว (Asia/Bangkok)")
