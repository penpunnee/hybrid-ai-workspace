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

from core.config import (
    DB_PATH,
    EMBED_CACHE_DB,
    READER_DB_PATH,
    RESPONSE_CACHE_DB,
)

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
        # ชื่อตารางใส่ " ได้ตามสเปก sqlite — ต้อง escape เป็น "" ไม่งั้น SQL พัง
        # แล้วถูกกลืนเป็น "อ่านไม่ได้" = เตือนว่า backup เสียทั้งที่ backup ดี
        return sum(conn.execute(
            'SELECT COUNT(*) FROM "{}"'.format(t.replace('"', '""'))
        ).fetchone()[0] for t in tables)
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


def _default_db_paths() -> list[str]:
    """รายการ DB ที่ job รายคืนสำรอง — **ลำดับมีความหมาย: ตัวแรกคือใบชี้ขาด**

    เรียงตาม "กู้คืนไม่ได้" ก่อน "สร้างใหม่ได้":
      1. chat_history.db — sessions/messages/feedback 👍👎/pins/shares
      2. reader.db       — เนื้อหาหนังสือ + ที่คั่นหน้า (prod 125 MB, gzip ~14 MB)
      3-4. cache         — regenerate เอาใหม่ได้ เก็บไว้เพื่อให้กู้แล้วเร็ว ไม่ใช่ตัวชี้ขาด

    🔴 อ่านค่าตอนเรียก ไม่ใช่ตอน import — conftest/monkeypatch override ค่าพวกนี้
       ถ้าผูกเป็นค่าคงที่ระดับโมดูล เทสจะไปสำรองไฟล์คนละใบกับที่ตั้งใจโดยไม่มีใครรู้

    🔴 reader.db หลุดจากรายการนี้มาตั้งแต่ 08-09 ถึง 09-01 เพราะ default เดิม
       เขียนไว้ตอนที่ยังไม่มีไฟล์นี้ และ **เทส backup ทุกตัวส่ง db_paths= เองหมด**
       ⇒ รายการ default ไม่เคยถูกเดินผ่าน · ตอนนี้ตรึงด้วย tests/test_db_backup_reader.py
       ซึ่งมี ratchet ตรวจว่า DB ใบใหม่ใน core/config.py ต้องเข้ามาที่นี่ด้วย
    """
    return [DB_PATH, READER_DB_PATH, EMBED_CACHE_DB, RESPONSE_CACHE_DB]


def run_db_backup(dest: str | None = None,
                  db_paths: list[str] | None = None,
                  retain_days: int | None = None) -> str | None:
    """สำรอง DB ทั้งหมดที่มีอยู่จริง → คืน path ของ archive (None ถ้าไม่มีอะไรให้สำรอง)

    raise BackupUnhealthy ถ้า archive เขียนสำเร็จแต่เนื้อในใช้กู้ไม่ได้
    (archive ยังถูกเก็บไว้ — ของน่าสงสัยมีค่ากว่าไม่มีอะไรเลย แต่ห้ามนับว่าสำเร็จ)
    """
    dest = dest or DB_BACKUP_DEST
    retain = DB_BACKUP_RETAIN_DAYS if retain_days is None else retain_days
    paths = db_paths if db_paths is not None else _default_db_paths()

    # ชื่อในซองคือ basename → ถ้าซ้ำกัน ตัวหลังทับตัวแรกเงียบๆ = ขอ 2 ใบได้กลับ 1 ใบ
    # และตัวตรวจอาจไปตรวจ "ใบที่ทับ" แล้วผ่าน ทั้งที่ใบที่ขอไม่ได้ถูกเก็บ
    # ปฏิเสธไปเลยดีกว่าเงียบ — ยังไม่เคยเกิดบน prod (3 ใบชื่อไม่ซ้ำ) แต่เป็นหลุมที่รออยู่
    # ⚠️ จงใจ *ไม่* เปลี่ยนวิธีตั้งชื่อในซอง — archive 7 วันที่มีอยู่ใช้ basename ล้วน
    #    การเปลี่ยนโครงชื่อจะทำให้ขั้นตอนกู้ที่คนจำไว้ใช้ไม่ได้กับของเก่า
    dupes = {n for n in (os.path.basename(p) for p in paths)
             if [os.path.basename(q) for q in paths].count(n) > 1}
    if dupes:
        raise ValueError(
            f"db_paths มีชื่อไฟล์ซ้ำกัน {sorted(dupes)} — ตัวหลังจะทับตัวแรกใน archive")

    existing = [p for p in paths if os.path.isfile(p)]
    if not existing:
        logger.warning("[db_backup] ไม่พบ database ให้สำรอง: %s", paths)
        return None

    # ⚠️ "ขอ 4 ใบ ได้ 3 ใบ" เคยผ่านไปเงียบสนิท — เป็นอาการเดียวกับที่ทำให้ reader.db
    # หายจากซองอยู่ 23 วันโดยไม่มีใครรู้ (2026-08-09 → 09-01) ต่างกันแค่ตอนนั้น
    # ไม่มีใครใส่ไว้ในรายการเลย ส่วนนี่คือใส่แล้วแต่ไฟล์หายไปจาก mount
    # ตัวตรวจ _verify_snapshot ดูแค่ paths[0] จึงจับเคสนี้ไม่ได้ — log จึงเป็นตาเดียวที่มี
    # (จงใจไม่ raise: ซองที่ขาดใบรองยังกู้ระบบได้ ห้ามทำ "ขาดบางส่วน" ให้กลายเป็น
    #  "ไม่มี backup เลย" ซึ่งเป็นการซ่อมที่ทำให้แย่ลง)
    missing = [p for p in paths if p not in existing]
    if missing:
        logger.error("[db_backup] ขอสำรอง %d ใบ แต่หาไม่เจอ %d ใบ: %s",
                     len(paths), len(missing), missing)

    os.makedirs(dest, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    with tempfile.TemporaryDirectory() as work:
        for p in existing:
            _snapshot(p, os.path.join(work, os.path.basename(p)))
        problem = _verify_snapshot(work, os.path.basename(paths[0]))

        # ชื่อไฟล์คือสิ่งเดียวที่เดินทางไปกับ archive — ตอนกู้ระบบจริงคนหยิบไฟล์
        # ล่าสุดจากชื่อ ไม่มีใครไล่ log ย้อนหลัง ชื่อจึงต้องบอกความจริงด้วยตัวมันเอง
        # ⚠️ ยังขึ้นต้น db_backup_ เหมือนเดิม เพื่อให้ glob ของ retention เห็น
        #    (ถ้าหลุด glob = กองสะสมตลอดไป แก้ปัญหาหนึ่งสร้างอีกปัญหา)
        suffix = "_UNHEALTHY" if problem else ""
        archive = os.path.join(dest, f"db_backup_{ts}{suffix}.tar.gz")

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
