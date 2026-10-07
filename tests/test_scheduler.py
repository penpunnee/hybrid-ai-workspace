"""core/scheduler.py — CronTrigger ต้องผูก timezone Asia/Bangkok ตรงๆ

บั๊กจริง (เจอ 2026-07-13 ตรวจ Dream Cycle บน prod): `BackgroundScheduler(timezone="Asia/Bangkok")`
ไม่ inject timezone เข้า `CronTrigger(...)` ที่สร้างแยกไว้ก่อน add_job() เอง — CronTrigger
ที่ไม่ระบุ timezone จะ fallback เป็น OS-local (container ไม่ตั้ง TZ = UTC) ทำให้ยิงเพี้ยนไป
7 ชม. (Dream ตั้งใจตี 2 บางกอก กลายเป็นยิงจริงตี 9 บางกอก/ตี 2 UTC)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apscheduler.triggers.cron import CronTrigger

import core.scheduler as scheduler_mod


def test_start_scheduler_registers_jobs_with_bangkok_timezone():
    scheduler_mod.start_scheduler()
    try:
        dream_job = scheduler_mod.scheduler.get_job("dream_nightly")
        backup_job = scheduler_mod.scheduler.get_job("db_backup_nightly")
        assert dream_job is not None and backup_job is not None

        assert str(dream_job.trigger.timezone) == "Asia/Bangkok", (
            f"dream_nightly ต้องผูก Asia/Bangkok ตรงๆ ไม่ใช่ fallback OS-local "
            f"(ได้ {dream_job.trigger.timezone})"
        )
        assert str(backup_job.trigger.timezone) == "Asia/Bangkok", (
            f"db_backup_nightly ต้องผูก Asia/Bangkok ตรงๆ (ได้ {backup_job.trigger.timezone})"
        )
    finally:
        scheduler_mod.scheduler.remove_all_jobs()
        if scheduler_mod.scheduler.running:
            scheduler_mod.scheduler.shutdown(wait=False)


def test_crontrigger_without_explicit_timezone_falls_back_to_os_local(monkeypatch):
    """เอกสารไว้ว่าทำไม CronTrigger(hour=2, minute=0) เฉยๆ (ไม่มี timezone=) ถึงอันตราย —
    บังคับ OS-local เป็น UTC ชัดเจน (เครื่อง dev อยู่ไทยเฉยๆ tz ก็ Asia/Bangkok พอดี ทำให้
    เทสนี้ pass มั่วได้ถ้าไม่บังคับ) แล้วพิสูจน์ว่า CronTrigger ไม่ inherit
    BackgroundScheduler(timezone=...) เอง — ต้องผูก timezone= ตรงๆ เท่านั้น"""
    import time
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    try:
        naive = CronTrigger(hour=2, minute=0)
        explicit = CronTrigger(hour=2, minute=0, timezone="Asia/Bangkok")
        assert str(naive.timezone) == "UTC", (
            f"คาดว่า fallback เป็น OS-local (UTC ที่บังคับไว้) ได้ {naive.timezone} แทน — "
            "ถ้า apscheduler เปลี่ยนพฤติกรรมไป inherit scheduler timezone เองแล้ว "
            "อัปเดตคอมเมนต์ใน core/scheduler.py ได้ (ไม่ต้องผูก timezone= ตรงๆ อีกต่อไป)"
        )
        assert str(explicit.timezone) == "Asia/Bangkok"
    finally:
        time.tzset()  # คืน TZ ระบบเดิมหลัง monkeypatch ลบ env var


def test_งานรายคืนทนการยิงช้าได้_1_ชั่วโมง():
    """A1 (ปอยเคาะ 10-07): ค่าปริยาย `misfire_grace_time` ของ APScheduler = 1 วิ ⇒ ถ้า thread ของ
    scheduler ช้ากว่ากำหนดเกิน 1 วิ (NAS พัก · CPU เต็ม) รอบนั้น**ถูกข้ามเงียบ** — Dream ใช้ <10 วิ
    และ backup 03:30 อยู่ห่างไป 1.5 ชม. ⇒ ยอมให้ช้าได้ 1 ชม.

    ⚠️ ไม่ครอบเคสคอนเทนเนอร์ดับตอนถึงเวลา (job store อยู่ในหน่วยความจำ · บูตใหม่คำนวณรอบถัดไป
    จากเวลาปัจจุบัน) — นั่นคืองานเปิด A2 ใน docs/session-log/open-work.md"""
    scheduler_mod.start_scheduler()
    try:
        for job_id in ("dream_nightly", "db_backup_nightly"):
            job = scheduler_mod.scheduler.get_job(job_id)
            assert job is not None, f"ไม่เจอ job {job_id}"
            assert job.misfire_grace_time is not None and job.misfire_grace_time >= 3600, (
                f"{job_id}.misfire_grace_time = {job.misfire_grace_time} — ช้าเกินค่านี้แล้วรอบถูกข้ามเงียบ"
            )
            assert job.coalesce is True, f"{job_id} ต้อง coalesce (ช้าหลายรอบ = ยิงรอบเดียว)"
    finally:
        scheduler_mod.scheduler.remove_all_jobs()
        if scheduler_mod.scheduler.running:
            scheduler_mod.scheduler.shutdown(wait=False)
