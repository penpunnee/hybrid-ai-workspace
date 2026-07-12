"""สำรอง SQLite databases จากในแอป (APScheduler 03:30 — core/scheduler.py)

ทำไมต้องมี in-app ทั้งที่มี scripts/db_backup.sh: ตั้ง DSM Task Scheduler
จาก SSH ไม่ได้ (sudo บน NAS จำกัดแค่ docker) — job ในแอปจบได้เองไม่พึ่ง GUI
และใน container path DB ชัดเจนเสมอ (/app/chat_history.db = ตัวจริงผ่าน mount)

วิธี: sqlite3 backup API (online snapshot — consistent แม้แอปกำลังเขียน, WAL-safe)
→ tar.gz ที่ DB_BACKUP_DEST (default ./db_backups → /app/db_backups ใน container,
mount กลับ host ผ่าน docker-compose) เก็บ DB_BACKUP_RETAIN วัน
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


def _snapshot(src_path: str, dst_path: str) -> None:
    src = sqlite3.connect(src_path)
    dst = sqlite3.connect(dst_path)
    try:
        with dst:
            src.backup(dst)
    finally:
        src.close()
        dst.close()


def run_db_backup(dest: str | None = None,
                  db_paths: list[str] | None = None,
                  retain_days: int | None = None) -> str | None:
    """สำรอง DB ทั้งหมดที่มีอยู่จริง → คืน path ของ archive (None ถ้าไม่มีอะไรให้สำรอง)"""
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
        with tarfile.open(archive, "w:gz") as tf:
            for name in sorted(os.listdir(work)):
                tf.add(os.path.join(work, name), arcname=name)

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
