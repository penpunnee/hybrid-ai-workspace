"""สำรอง SQLite databases จากในแอป (APScheduler 03:30 — core/scheduler.py)

ทำไมต้องมี in-app ทั้งที่มี scripts/db_backup.sh: ตั้ง DSM Task Scheduler
จาก SSH ไม่ได้ (sudo บน NAS จำกัดแค่ docker) — job ในแอปจบได้เองไม่พึ่ง GUI
และใน container path DB ชัดเจนเสมอ (/app/chat_history.db = ตัวจริงผ่าน mount)

วิธี: sqlite3 backup API (online snapshot — consistent แม้แอปกำลังเขียน, WAL-safe)
→ tar.gz ที่ DB_BACKUP_DEST (default ./db_backups → /app/db_backups ใน container,
mount กลับ host ผ่าน docker-compose) เก็บ DB_BACKUP_RETAIN วัน

⚠️ "เขียนไฟล์สำเร็จ" ≠ "มี backup" — 2026-07-12 บน prod เกิด archive ขนาด 989 ไบต์
ที่รายงานสำเร็จเหมือนรอบปกติทุกประการ (ตัวจริง 146 KB) เพราะไปหยิบ DB ผิดใบ
ตอนนั้นแก้ที่ "เลือกไฟล์ให้ถูก" ซึ่งเป็นสาเหตุ แต่ไม่ได้แก้ที่อาการ — คือการที่
backup เปล่ายังผ่านออกไปได้โดยไม่มีใครรู้ ตอนนี้กันด้วย _verify_snapshot()
"""
import glob
import logging
import os
import sqlite3
import tarfile
import tempfile
import time
from datetime import datetime

from core.config import DB_PATH, EMBED_CACHE_DB, RESPONSE_CACHE_DB

logger = logging.getLogger(__name__)

DB_BACKUP_DEST = os.getenv("DB_BACKUP_DEST", "./db_backups")
DB_BACKUP_RETAIN_DAYS = int(os.getenv("DB_BACKUP_RETAIN", "7"))

# DB ตัวชี้ขาด = **ตัวแรกใน db_paths ที่ผู้เรียกขอมา** (default = DB_PATH)
# cache ที่เหลือ regenerate เอาใหม่ได้ จึงไม่นับ — เตือนผิดตัวบ่อยๆ คือทางที่ทำให้
# คนเลิกฟังเสียงเตือน ซึ่งแย่กว่าไม่มีเสียงเตือน
#
# ยึดจากอาร์กิวเมนต์ ไม่ใช่ค่าคงที่ที่อ่าน env ตอน import — เพราะ DB_PATH ถูก
# override ได้ (conftest ตั้งเป็น hybrid_ai_test.db) แล้วตัวตรวจจะไปเทียบชื่อผิดใบ
# โดยไม่มีใครรู้ ที่สำคัญกว่า: ตรวจ "ใบที่ขอมา" ทำให้จับเคส DB หลักหายจาก mount ได้
# (ขอมา 3 ใบ ได้กลับ 2 ใบที่เป็น cache ล้วน = archive ที่กู้ระบบไม่ได้)


class BackupUnhealthy(RuntimeError):
    """archive ถูกเขียนแล้วแต่เนื้อในไม่ผ่านการตรวจ — path อยู่ที่ .archive

    ตั้งใจให้เป็น exception ไม่ใช่ค่า return เพื่อไม่ไปแก้ความหมายของค่าที่
    ผู้เรียกเดิมอ่านอยู่ (str | None) — การเพิ่มความหมายให้ค่าเดิมเคยทำให้
    ผู้เรียกที่เคยถูกกลายเป็นตัวทำลายมาแล้ว
    """

    def __init__(self, message: str, archive: str | None = None):
        super().__init__(message)
        self.archive = archive


def _snapshot(src_path: str, dst_path: str) -> None:
    src = sqlite3.connect(src_path)
    dst = sqlite3.connect(dst_path)
    try:
        with dst:
            src.backup(dst)
    finally:
        src.close()
        dst.close()


def _count_rows(path: str) -> int | None:
    """นับแถวรวมทุกตารางใน snapshot — คืน None ถ้า DB เสียหาย/อ่านไม่ได้

    นับรวมทุกตารางแทนที่จะเจาะจงชื่อ 'messages' เพื่อไม่ผูกกับ schema
    (schema เปลี่ยนแล้วตัวตรวจต้องไม่กลายเป็นตัวเตือนผิดพลาดเงียบๆ)
    """
    try:
        conn = sqlite3.connect(path)
    except sqlite3.Error:
        return None
    try:
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            return None
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'")]
        return sum(conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                   for t in tables)
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def _verify_snapshot(work: str, critical_name: str) -> str | None:
    """ตรวจ snapshot ของ DB หลัก — คืนข้อความปัญหา หรือ None ถ้าผ่าน"""
    snap = os.path.join(work, critical_name)
    if not os.path.isfile(snap):
        return (f"ไม่มี {critical_name} ใน archive — สำรองได้แต่ไฟล์รอง "
                f"ซึ่งกู้ระบบกลับไม่ได้")

    rows = _count_rows(snap)
    if rows is None:
        return f"{critical_name} ใน archive อ่านไม่ได้/integrity_check ไม่ผ่าน"
    if rows == 0:
        return (f"{critical_name} ใน archive ว่างเปล่า (0 แถวทุกตาราง) — "
                f"ตรงกับอาการ backup 989 ไบต์ เมื่อ 2026-07-12")
    return None


def run_db_backup(dest: str | None = None,
                  db_paths: list[str] | None = None,
                  retain_days: int | None = None) -> str | None:
    """สำรอง DB ทั้งหมดที่มีอยู่จริง → คืน path ของ archive (None ถ้าไม่มีอะไรให้สำรอง)

    raise BackupUnhealthy ถ้า archive เขียนสำเร็จแต่เนื้อในใช้กู้ไม่ได้
    (archive ยังถูกเก็บไว้ — ของน่าสงสัยมีค่ากว่าไม่มีอะไรเลย แต่ห้ามนับว่าสำเร็จ)
    """
    dest = dest or DB_BACKUP_DEST
    retain = DB_BACKUP_RETAIN_DAYS if retain_days is None else retain_days
    paths = db_paths if db_paths is not None else [
        DB_PATH, EMBED_CACHE_DB, RESPONSE_CACHE_DB]

    existing = [p for p in paths if os.path.isfile(p)]
    if not existing:
        logger.warning("[db_backup] ไม่พบ database ให้สำรอง: %s", paths)
        return None

    os.makedirs(dest, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive = os.path.join(dest, f"db_backup_{ts}.tar.gz")

    with tempfile.TemporaryDirectory() as work:
        for p in existing:
            _snapshot(p, os.path.join(work, os.path.basename(p)))
        problem = _verify_snapshot(work, os.path.basename(paths[0]))
        with tarfile.open(archive, "w:gz") as tf:
            for name in sorted(os.listdir(work)):
                tf.add(os.path.join(work, name), arcname=name)

    if problem:
        # ⚠️ ไม่แตะ retention เด็ดขาด — รอบนี้ได้ของเสีย การลบของเก่าตามอายุ
        # จะทำลาย backup ที่ยังดีอยู่ทิ้งไปด้วย (พังชั่วคราว → พังถาวร)
        logger.error("[db_backup] archive ไม่ผ่านการตรวจ: %s → %s", problem, archive)
        raise BackupUnhealthy(problem, archive=archive)

    cutoff = time.time() - retain * 86400
    for old in glob.glob(os.path.join(dest, "db_backup_*.tar.gz")):
        if old != archive and os.path.getmtime(old) < cutoff:
            try:
                os.remove(old)
            except OSError:
                pass

    logger.info("[db_backup] สำรอง %d db → %s (%.1f KB)",
                len(existing), archive, os.path.getsize(archive) / 1024)
    return archive
