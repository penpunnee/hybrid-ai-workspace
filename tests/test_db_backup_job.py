"""utils/db_backup.py — in-app backup job (APScheduler 03:30)

ทำไมต้องมี in-app: ตั้ง DSM Task Scheduler จาก SSH ไม่ได้ (sudo จำกัดแค่ docker)
→ ฝัง job ในแอปแทน. ใน container path DB ชัดเจนเสมอ (/app/chat_history.db คือ
ตัวจริงผ่าน volume mount) — ไม่มีปัญหา layout host แบบ scripts/db_backup.sh
"""
import os
import sqlite3
import tarfile
import time

import pytest

from utils.db_backup import run_db_backup


def _seed_db(path, marker="t"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(f"CREATE TABLE {marker} (x INTEGER)")
    conn.execute(f"INSERT INTO {marker} VALUES (1)")
    conn.commit()
    conn.close()


def test_creates_archive_with_given_dbs(tmp_path):
    db1 = str(tmp_path / "chat_history.db")
    db2 = str(tmp_path / "embed_cache.db")
    _seed_db(db1)
    _seed_db(db2)
    dest = str(tmp_path / "backups")

    archive = run_db_backup(dest=dest, db_paths=[db1, db2])

    assert archive is not None and os.path.isfile(archive)
    with tarfile.open(archive) as tf:
        names = {os.path.basename(n) for n in tf.getnames()}
    assert {"chat_history.db", "embed_cache.db"} <= names


def test_backup_is_valid_sqlite_snapshot(tmp_path):
    db = str(tmp_path / "chat_history.db")
    _seed_db(db, marker="messages")
    dest = str(tmp_path / "backups")

    archive = run_db_backup(dest=dest, db_paths=[db])

    extract = tmp_path / "extract"
    with tarfile.open(archive) as tf:
        tf.extractall(extract)
    conn = sqlite3.connect(extract / "chat_history.db")
    rows = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    conn.close()
    assert rows == 1


def test_returns_none_when_no_dbs_exist(tmp_path):
    dest = str(tmp_path / "backups")
    assert run_db_backup(dest=dest, db_paths=[str(tmp_path / "nope.db")]) is None


def test_skips_missing_but_backs_up_existing(tmp_path):
    db = str(tmp_path / "chat_history.db")
    _seed_db(db)
    dest = str(tmp_path / "backups")

    archive = run_db_backup(
        dest=dest, db_paths=[db, str(tmp_path / "missing.db")])

    with tarfile.open(archive) as tf:
        names = {os.path.basename(n) for n in tf.getnames()}
    assert names == {"chat_history.db"}


def test_retention_deletes_old_archives(tmp_path):
    db = str(tmp_path / "chat_history.db")
    _seed_db(db)
    dest = tmp_path / "backups"
    dest.mkdir()
    old = dest / "db_backup_20200101_000000.tar.gz"
    old.write_bytes(b"old")
    stale = time.time() - 8 * 86400
    os.utime(old, (stale, stale))

    run_db_backup(dest=str(dest), db_paths=[db], retain_days=7)

    assert not old.exists(), "archive เก่ากว่า retain_days ต้องถูกลบ"
    assert list(dest.glob("db_backup_*.tar.gz")), "ต้องมี archive ใหม่แทน"


def test_scheduler_registers_nightly_job():
    from core import scheduler as sched_mod
    job = None
    try:
        sched_mod.start_scheduler()
        job = sched_mod.scheduler.get_job("db_backup_nightly")
    finally:
        try:
            sched_mod.scheduler.shutdown(wait=False)
        except Exception:
            pass
    assert job is not None, "start_scheduler ต้องลงทะเบียน job db_backup_nightly"
    trigger = str(job.trigger)
    assert "hour='3'" in trigger and "minute='30'" in trigger
