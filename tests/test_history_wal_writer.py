"""เส้นเขียนแชท/เสียง (save_message · save_reply) ผ่าน writer connection ค้างตัวเดียว + WAL + synchronous=NORMAL — ขั้น 2b/2c 09-29

วัดบน prod (ไฟล์ชั่วคราวใน /app · Btrfs บน RAID5 HDD 5,400 rpm) median/max ต่อ commit:
  delete+FULL (เดิม) 476/772 ms · WAL+NORMAL connection ค้าง **0.0/0.1 ms** · WAL+NORMAL เปิดใหม่ทุกครั้ง 403/675 ms
⇒ ได้ผลเฉพาะ connection ค้าง · user เคาะ NORMAL (รู้ว่าไม่มี UPS: ไฟดับ commit ช่วงท้ายอาจหาย · DB ไม่เสีย —
https://www.sqlite.org/pragma.html#pragma_synchronous) · journal_mode=WAL ถาวรในไฟล์ (https://www.sqlite.org/wal.html)
ต้องมาหลังขั้น 2a (mount โฟลเดอร์ — -wal/-shm อยู่ข้าง DB บน host · tests/test_db_path_dir_mount.py)
เส้นอื่น (truncate/pin/feedback/ลบ) ยังเปิดใหม่ทุกครั้ง — เกิดไม่บ่อย · connection ข้าม thread = lock ของเรา
"""
import os
import sqlite3
import sys
import threading

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils.history as h


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    path = str(tmp_path / "chat_history.db")
    monkeypatch.setattr(h, "DB_PATH", path)
    monkeypatch.setattr(h, "_schema_ready", False)
    yield path
    h._close_writer()


def test_หลังเขียนแล้ว_DB_เป็น_WAL_และ_writer_เป็น_NORMAL(fresh_db):
    h.save_message("kwan", "user", "q", "ollama", "s1")
    c = sqlite3.connect(fresh_db)
    try:
        assert c.execute("pragma journal_mode").fetchone()[0] == "wal"
    finally:
        c.close()
    with h._writer_lock:
        assert h._writer_conn.execute("pragma synchronous").fetchone()[0] == 1   # NORMAL


def test_เขียนหลายครั้งใช้_connection_ตัวเดียว(fresh_db, monkeypatch):
    opened = []
    real = sqlite3.connect

    def counting(path, *a, **k):
        opened.append(path)
        return real(path, *a, **k)

    monkeypatch.setattr(h.sqlite3, "connect", counting)
    uid = h.save_message("kwan", "user", "q", "ollama", "s1")
    h.save_reply("kwan", "a", "ollama", "s1", uid)
    h.save_message("kwan", "user", "q2", "ollama", "s1")
    assert opened.count(fresh_db) == 1, f"ต้องเปิด writer ครั้งเดียว (เปิด {opened.count(fresh_db)} ครั้ง)"


def test_ผู้อ่านเปิดแยกเห็นข้อมูลที่_commit_แล้วทันที(fresh_db):
    uid = h.save_message("kwan", "user", "q", "ollama", "s1")
    h.save_reply("kwan", "a", "ollama", "s1", uid)
    assert [m["content"] for m in h.load_history("kwan", "s1")] == ["q", "a"]


def test_save_reply_ยังอะตอม_ไม่บันทึกเมื่อแถว_user_หายไปแล้ว(fresh_db):
    uid = h.save_message("kwan", "user", "q", "ollama", "s1")
    assert h.truncate_from_db_id(uid)            # เส้นนี้ยังเปิด connection แยก
    assert h.save_reply("kwan", "a", "ollama", "s1", uid) == 0
    assert h.load_history("kwan", "s1") == []


def test_หลาย_thread_เขียนพร้อมกันไม่มี_error_และได้ครบ(fresh_db):
    errors = []

    def worker(n):
        try:
            for i in range(10):
                h.save_message("kwan", "user", f"{n}-{i}", "ollama", "s-par")
        except Exception as e:     # pragma: no cover - ต้องไม่เกิด
            errors.append(e)

    ts = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(10)
    assert errors == []
    assert len(h.load_history("kwan", "s-par")) == 80


def test_เปลี่ยน_DB_PATH_แล้ว_writer_เปิดไฟล์ใหม่(fresh_db, tmp_path, monkeypatch):
    h.save_message("kwan", "user", "เก่า", "ollama", "s1")
    other = str(tmp_path / "other.db")
    monkeypatch.setattr(h, "DB_PATH", other)
    monkeypatch.setattr(h, "_schema_ready", False)
    h.save_message("kwan", "user", "ใหม่", "ollama", "s1")
    c = sqlite3.connect(other)
    try:
        assert [r[0] for r in c.execute("select content from messages")] == ["ใหม่"]
    finally:
        c.close()


def test_writer_พังแล้วเขียนครั้งถัดไปเปิดใหม่ได้(fresh_db):
    h.save_message("kwan", "user", "ก่อน", "ollama", "s1")
    with h._writer_lock:
        h._writer_conn.close()                   # จำลอง connection ตาย (disk error ฯลฯ)
    with pytest.raises(sqlite3.Error):
        h.save_message("kwan", "user", "ตอนพัง", "ollama", "s1")
    h.save_message("kwan", "user", "หลัง", "ollama", "s1")
    assert [m["content"] for m in h.load_history("kwan", "s1")] == ["ก่อน", "หลัง"]


def test_backup_API_ได้ข้อมูลครบแม้ยังไม่_checkpoint(fresh_db, tmp_path):
    from utils.db_backup import _snapshot
    for i in range(5):
        h.save_message("kwan", "user", f"m{i}", "ollama", "s1")
    assert os.path.exists(fresh_db + "-wal"), "กลุ่มควบคุม: ต้องมี -wal ค้างอยู่จริง ไม่งั้นเทสนี้ไม่ได้วัดอะไร"
    dst = str(tmp_path / "snap.db")
    _snapshot(fresh_db, dst)
    c = sqlite3.connect(dst)
    try:
        assert c.execute("select count(*) from messages").fetchone()[0] == 5
    finally:
        c.close()
