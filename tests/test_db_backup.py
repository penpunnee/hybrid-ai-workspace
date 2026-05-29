"""Smoke test สำหรับ scripts/db_backup.sh — สำรอง SQLite (chat_history.db + caches)

รัน script จริงผ่าน subprocess บน temp dir → ยืนยันว่าได้ archive + มี db ครบ
"""
import os
import sqlite3
import subprocess
import sys
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
