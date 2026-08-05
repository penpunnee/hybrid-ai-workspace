"""ตรวจว่า archive ที่ได้ "มีข้อมูลจริง" ไม่ใช่แค่ "เขียนไฟล์สำเร็จ"

ทำไม: 2026-07-12 บน prod เกิด backup ที่รายงานสำเร็จแต่ว่างเปล่าจริง —
/volume1/homes/pawin/db_backups/db_backup_20260712_175306.tar.gz = **989 ไบต์**
แล้วรอบที่ถูกต้อง 2 ชม.ถัดมา = 146,676 ไบต์ ทั้งสองรอบขึ้น ✅ เหมือนกันเป๊ะ
สิ่งเดียวที่จับได้คือมีคนบังเอิญมองขนาดไฟล์

เทสเดิมทุกเคสใน test_db_backup_job.py เรียก _seed_db() ที่ INSERT แถวจริงเสมอ
→ เส้น "DB ว่าง" ไม่เคยถูกเดินผ่านเลย เทสจึงผ่านฟรีมาตลอด
"""
import os
import time
import sqlite3
import tarfile

import pytest

from utils.db_backup import BackupUnhealthy, run_db_backup


def _seed_db(path, marker="messages", rows=1):
    conn = sqlite3.connect(path)
    conn.execute(f"CREATE TABLE {marker} (x INTEGER)")
    for i in range(rows):
        conn.execute(f"INSERT INTO {marker} VALUES ({i})")
    conn.commit()
    conn.close()


def test_empty_critical_db_raises_but_still_writes_archive(tmp_path):
    """DB หลักเป็นไฟล์เปล่า → ต้องดังขึ้นมา ไม่ใช่ขึ้น ✅ เงียบๆ

    เลือก "เขียน archive ไว้ก่อน แล้วค่อยโวย" เพราะ backup ที่น่าสงสัย
    ยังมีค่ามากกว่าไม่มี backup เลย — แต่ต้องไม่ถูกนับว่าสำเร็จ
    """
    db = str(tmp_path / "chat_history.db")
    open(db, "wb").close()  # 0 ไบต์ — เคสที่ sqlite3 .backup คืน DB ว่างที่ valid
    dest = tmp_path / "backups"

    with pytest.raises(BackupUnhealthy) as exc:
        run_db_backup(dest=str(dest), db_paths=[db])

    archives = list(dest.glob("db_backup_*.tar.gz"))
    assert len(archives) == 1, "archive ต้องยังถูกเขียนไว้"
    assert exc.value.archive == str(archives[0])
    assert "chat_history.db" in str(exc.value)


def test_critical_db_with_schema_but_no_rows_is_unhealthy(tmp_path):
    """มีตารางแต่ไม่มีแถว — DB ที่ valid แต่ไม่มีอะไรให้กู้"""
    db = str(tmp_path / "chat_history.db")
    _seed_db(db, rows=0)
    dest = tmp_path / "backups"

    with pytest.raises(BackupUnhealthy):
        run_db_backup(dest=str(dest), db_paths=[db])


def test_healthy_backup_does_not_raise(tmp_path):
    """กลุ่มควบคุม — ถ้าเคสนี้แดงแปลว่าตัวตรวจเข้มเกินไป"""
    db = str(tmp_path / "chat_history.db")
    _seed_db(db, rows=3)
    dest = tmp_path / "backups"

    archive = run_db_backup(dest=str(dest), db_paths=[db])

    assert archive and os.path.isfile(archive)


def test_empty_cache_db_alone_is_not_fatal(tmp_path):
    """cache ว่างไม่ใช่เรื่องใหญ่ (regenerate ได้) — ห้ามโวยผิดตัว

    ถ้าเทสนี้แดง แปลว่าตัวตรวจไปตรวจ db ทุกใบแทนที่จะตรวจใบสำคัญ
    แล้วจะกลายเป็นเสียงเตือนที่คนเลิกฟัง
    """
    chat = str(tmp_path / "chat_history.db")
    cache = str(tmp_path / "embed_cache.db")
    _seed_db(chat, rows=2)
    open(cache, "wb").close()
    dest = tmp_path / "backups"

    archive = run_db_backup(dest=str(dest), db_paths=[chat, cache])

    assert archive and os.path.isfile(archive)
    with tarfile.open(archive) as tf:
        names = {os.path.basename(n) for n in tf.getnames()}
    assert names == {"chat_history.db", "embed_cache.db"}


def test_unhealthy_run_does_not_delete_old_good_archives(tmp_path):
    """รอบที่ได้ของเสีย ห้ามรัน retention — ไม่งั้น "พังชั่วคราว" กลายเป็น "พังถาวร"

    ถ้า DB หลักหายไปจาก mount แล้ว job ยังเดินทุกคืน retention 7 วันจะกิน
    backup ที่ยังดีอยู่ทีละใบจนหมดเกลี้ยงภายในสัปดาห์เดียว โดยที่ทุกรอบ
    "รันสำเร็จ" — ของเก่าต้องรอดจนกว่าจะมี backup ใหม่ที่ใช้ได้จริงมาแทน
    """
    db = str(tmp_path / "chat_history.db")
    open(db, "wb").close()
    dest = tmp_path / "backups"
    dest.mkdir()
    good = dest / "db_backup_20200101_000000.tar.gz"
    good.write_bytes("backup ที่ยังดีอยู่".encode())
    stale = time.time() - 30 * 86400
    os.utime(good, (stale, stale))

    with pytest.raises(BackupUnhealthy):
        run_db_backup(dest=str(dest), db_paths=[db], retain_days=7)

    assert good.exists(), "archive เก่าที่ยังดีต้องไม่ถูกลบในรอบที่ backup ล้มเหลว"


def test_missing_critical_db_entirely_is_unhealthy(tmp_path):
    """ขอสำรอง 2 ใบ แต่ DB หลักหายจาก mount → ได้ archive ที่มีแต่ cache

    นี่คือเคส prod ที่อันตรายที่สุด เพราะโค้ดเดิม "ข้ามไฟล์ที่ไม่มี" อย่างเงียบๆ
    แล้วรายงานสำเร็จ — ต่างจาก test_returns_none_when_no_dbs_exist (ไม่มีอะไรเลย
    → None) ตรงที่เคสนี้ "มีของ แต่ไม่ใช่ใบที่ใช้กู้ระบบ" จึงดูเหมือนสำเร็จ
    """
    chat = str(tmp_path / "chat_history.db")  # ตั้งใจไม่สร้าง — จำลอง mount หลุด
    cache = str(tmp_path / "embed_cache.db")
    _seed_db(cache, marker="cache", rows=5)
    dest = tmp_path / "backups"

    with pytest.raises(BackupUnhealthy) as exc:
        run_db_backup(dest=str(dest), db_paths=[chat, cache])

    assert "chat_history.db" in str(exc.value)


def test_duplicate_basenames_are_refused(tmp_path):
    """สอง path คนละที่แต่ชื่อไฟล์เดียวกัน → ตัวหลังทับตัวแรกใน archive เงียบๆ

    ของเดิม `_snapshot()` ตั้งชื่อในซองด้วย basename ล้วน → ขอสำรอง 2 ใบได้กลับ 1 ใบ
    และตัวตรวจอาจไปตรวจ "ใบที่ทับ" แล้วผ่าน ทั้งที่ DB หลักที่ขอมาไม่ได้ถูกเก็บ
    (ยังไม่เคยเกิดบน prod เพราะ 3 ใบชื่อไม่ซ้ำ — แต่เป็นหลุมที่รอคนตกในอนาคต)
    """
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    _seed_db(str(a / "chat_history.db"), rows=5)
    _seed_db(str(b / "chat_history.db"), marker="อีกใบ", rows=1)

    with pytest.raises(ValueError, match="ชื่อไฟล์ซ้ำ"):
        run_db_backup(dest=str(tmp_path / "backups"),
                      db_paths=[str(a / "chat_history.db"),
                                str(b / "chat_history.db")])


def test_table_name_containing_quote_still_counts(tmp_path):
    """ชื่อตารางมี `"` ได้ตามสเปก sqlite → ต้องนับได้ ไม่ใช่ตกเป็น unhealthy

    ถ้าไม่ escape จะได้ SQL พัง → sqlite3.Error → _count_rows คืน None
    → **ตัวตรวจเตือนว่า backup เสียทั้งที่ backup ดี** = เสียงเตือนผิดที่แพงที่สุด
    """
    db = str(tmp_path / "chat_history.db")
    conn = sqlite3.connect(db)
    conn.execute('CREATE TABLE "we""ird" (x INTEGER)')
    conn.execute('INSERT INTO "we""ird" VALUES (1)')
    conn.commit()
    conn.close()

    archive = run_db_backup(dest=str(tmp_path / "backups"), db_paths=[db])

    assert archive and os.path.isfile(archive)


def test_unhealthy_archive_is_named_so_a_human_cannot_pick_it_by_mistake(tmp_path):
    """archive ที่ไม่ผ่านต้องมีชื่อที่ตะโกน ไม่ใช่หน้าตาเหมือนตัวที่ใช้ได้

    ตอนกู้ระบบจริงคนจะหยิบไฟล์ล่าสุดจากชื่อ ไม่มีใครไล่ log ย้อนหลัง
    → ชื่อคือสิ่งเดียวที่อยู่กับไฟล์ ต้องบอกความจริงด้วยตัวมันเอง
    """
    db = str(tmp_path / "chat_history.db")
    open(db, "wb").close()
    dest = tmp_path / "backups"

    with pytest.raises(BackupUnhealthy) as exc:
        run_db_backup(dest=str(dest), db_paths=[db])

    archive = os.path.basename(exc.value.archive)
    assert archive.endswith("_UNHEALTHY.tar.gz"), archive
    assert os.path.isfile(exc.value.archive)


def test_unhealthy_archives_are_still_reachable_by_retention(tmp_path):
    """ชื่อใหม่ต้องยังเข้าเงื่อนไข glob ของ retention

    ถ้าไม่เข้า มันจะกองสะสมตลอดไปโดยไม่มีใครลบ — แก้ปัญหาหนึ่งสร้างอีกปัญหา
    (retention ไม่รันในรอบที่พังอยู่แล้ว ของพวกนี้จะถูกเก็บกวาดตอนระบบกลับมาดี)
    """
    import glob as _glob
    dest = tmp_path / "backups"
    dest.mkdir()
    bad = dest / "db_backup_20200101_000000_UNHEALTHY.tar.gz"
    bad.write_bytes(b"x")
    stale = time.time() - 30 * 86400
    os.utime(bad, (stale, stale))
    assert _glob.glob(str(dest / "db_backup_*.tar.gz")), "glob ต้องเห็นไฟล์ _UNHEALTHY"

    good = str(tmp_path / "chat_history.db")
    _seed_db(good, rows=2)
    run_db_backup(dest=str(dest), db_paths=[good], retain_days=7)

    assert not bad.exists(), "รอบที่สำเร็จต้องเก็บกวาดของเสียที่เกินอายุด้วย"
