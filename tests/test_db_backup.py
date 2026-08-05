"""Smoke test สำหรับ scripts/db_backup.sh — สำรอง SQLite (chat_history.db + caches)

รัน script จริงผ่าน subprocess บน temp dir → ยืนยันว่าได้ archive + มี db ครบ
"""
import os
import sqlite3
import subprocess
import tarfile

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPT = os.path.join(_ROOT, "scripts", "db_backup.sh")


def _seed_db(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.execute("INSERT INTO t VALUES (1)")
    conn.commit()
    conn.close()


@pytest.fixture
def ui_dir(tmp_path):
    ui = tmp_path / "ui"
    for name in ("chat_history.db", "data/embed_cache.db", "data/response_cache.db"):
        _seed_db(str(ui / name))
    return ui


def _run(ui, dest, retain="7"):
    return subprocess.run(
        ["bash", _SCRIPT],
        env={**os.environ, "UI_DIR": str(ui), "DB_BACKUP_DEST": str(dest),
             "DB_BACKUP_RETAIN": retain},
        capture_output=True, text=True,
    )


def test_backup_creates_archive_with_all_dbs(ui_dir, tmp_path):
    dest = tmp_path / "backups"
    r = _run(ui_dir, dest)
    assert r.returncode == 0, r.stderr
    archives = list(dest.glob("db_backup_*.tar.gz"))
    assert len(archives) == 1
    with tarfile.open(archives[0]) as tf:
        names = {os.path.basename(n) for n in tf.getnames()}
    assert {"chat_history.db", "embed_cache.db", "response_cache.db"} <= names


def test_backup_fails_when_no_dbs(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    r = _run(empty, tmp_path / "backups")
    assert r.returncode == 1
    assert "ไม่พบ database" in (r.stdout + r.stderr)


def test_backup_prefers_data_layout_over_stale_root_db(tmp_path):
    # prod (NAS): DB จริงอยู่ data/chat_history.db — root chat_history.db เป็นไฟล์ค้างเก่า
    # เจอจริง 2026-07-12: script หยิบตัว root (12KB เม.ย.) แทนตัวจริง (933KB) → backup เปล่า
    ui = tmp_path / "ui"
    _seed_db(str(ui / "chat_history.db"))
    real = str(ui / "data" / "chat_history.db")
    _seed_db(real)
    conn = sqlite3.connect(real)
    conn.execute("CREATE TABLE real_marker (x INTEGER)")
    conn.commit()
    conn.close()

    dest = tmp_path / "backups"
    r = _run(ui, dest)
    assert r.returncode == 0, r.stderr

    archive = next(dest.glob("db_backup_*.tar.gz"))
    extract = tmp_path / "extract"
    with tarfile.open(archive) as tf:
        tf.extractall(extract)
    conn = sqlite3.connect(extract / "chat_history.db")
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "real_marker" in tables, "ต้อง backup ตัว data/ (DB จริง) ไม่ใช่ตัว root ที่ค้างเก่า"


def test_backup_still_runs_with_only_chat_history(tmp_path):
    # cache dbs หาย แต่ chat_history (สำคัญสุด) ยังอยู่ → ต้อง backup ได้
    ui = tmp_path / "ui"
    _seed_db(str(ui / "chat_history.db"))
    dest = tmp_path / "backups"
    r = _run(ui, dest)
    assert r.returncode == 0, r.stderr
    archive = next(dest.glob("db_backup_*.tar.gz"))
    with tarfile.open(archive) as tf:
        names = {os.path.basename(n) for n in tf.getnames()}
    assert "chat_history.db" in names


def _seed_empty(path):
    """ไฟล์ 0 ไบต์ — sqlite3 .backup จะสร้าง DB ว่างที่ valid ออกมา"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").close()


def test_empty_critical_db_must_not_report_success(tmp_path):
    """เส้นนี้แหละที่เคยผลิต archive 989 ไบต์บน prod เมื่อ 2026-07-12

    ตอนนั้นแก้ให้ "เลือกไฟล์ถูกใบ" (test_backup_prefers_data_layout_over_stale_root_db)
    แต่ไม่ได้แก้ให้ "รู้ตัวว่าใบที่เลือกมาว่างเปล่า" — สคริปต์ยังขึ้น ✅ เหมือนเดิม
    ตัว in-app job ปิดช่องนี้ไปแล้ว (PR #29) เส้น host ยังเปิดอยู่
    """
    ui = tmp_path / "ui"
    _seed_empty(str(ui / "data" / "chat_history.db"))
    dest = tmp_path / "backups"

    r = _run(ui, dest)

    assert r.returncode != 0, "DB หลักว่างเปล่าต้องไม่ exit 0"
    assert "ว่างเปล่า" in (r.stdout + r.stderr)


def test_unhealthy_archive_is_named_unhealthy(tmp_path):
    ui = tmp_path / "ui"
    _seed_empty(str(ui / "data" / "chat_history.db"))
    dest = tmp_path / "backups"

    _run(ui, dest)

    names = [p.name for p in dest.glob("db_backup_*.tar.gz")]
    assert names and all("_UNHEALTHY" in n for n in names), names


def test_unhealthy_run_keeps_old_archives(tmp_path):
    """รอบที่พังต้องไม่ลบของเก่า — เหมือนฝั่ง in-app"""
    ui = tmp_path / "ui"
    _seed_empty(str(ui / "data" / "chat_history.db"))
    dest = tmp_path / "backups"
    dest.mkdir()
    old = dest / "db_backup_20200101_000000.tar.gz"
    old.write_bytes(b"old-good")
    stale = os.path.getmtime(old) - 60 * 86400
    os.utime(old, (stale, stale))

    _run(ui, dest, retain="7")

    assert old.exists(), "archive เก่าต้องรอดเมื่อรอบนี้ล้มเหลว"


def test_healthy_backup_still_exits_zero(tmp_path, ui_dir):
    """กลุ่มควบคุม — ตัวตรวจต้องไม่ทำให้เส้นปกติพัง"""
    dest = tmp_path / "backups"
    r = _run(ui_dir, dest)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not list(dest.glob("*_UNHEALTHY*"))
