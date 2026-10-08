"""skills_db.json ในรอบสำรอง 03:30 (utils/db_backup.py · devlog 2026-10-08 ต่อ 150)

ทำไม: ก่อนหน้านี้ไฟล์นี้ไม่อยู่ในชุดสำรองตัวไหนเลย ทั้งที่แอปใช้งานจริง (สกิล 22 ตัวบน prod)
และสร้างใหม่จาก .md ได้ไม่ครบ (summary/metadata ที่ resync ไม่ได้สร้าง)

กติกาที่ปอยเคาะ:
- อยู่ในซอง tar.gz คืนเดียวกับ sqlite ⇒ เก็บรุ่นตามกติกา 7 วันเดิม
- JSON เสีย/หาไม่เจอ = ห้ามเอาของเสียเข้าซอง + ห้ามลบรุ่นเก่า + ห้ามยิง heartbeat สำเร็จ
  (ยิง /fail ให้ Healthchecks เตือนทันที) · ชื่อซอง **ไม่ต่อ** `_UNHEALTHY` เพราะ sqlite ในซองยังดี
"""
import json
import logging
import os
import tarfile
import time
from unittest.mock import patch

import pytest

import utils.db_backup as m
from utils.db_backup import BackupUnhealthy, SkillsDbNotBackedUp, run_db_backup

from tests.test_db_backup_job import _seed_db

_GOOD = {"deploy-cheatsheet": {"summary": "สรุป", "path": "skills/deploy-cheatsheet.md"}}


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


def _members(archive) -> dict[str, bytes]:
    with tarfile.open(archive) as tf:
        return {os.path.basename(i.name): tf.extractfile(i).read()
                for i in tf.getmembers() if i.isfile()}


def _stale_good_archive(dest):
    """ซองเก่าเกิน 7 วันที่ 'ยังดีอยู่' — retention ปกติจะลบทิ้ง"""
    dest.mkdir(exist_ok=True)
    good = dest / "db_backup_20200101_000000.tar.gz"
    good.write_bytes("ซองเก่าที่มีสกิลดี".encode())
    stale = time.time() - 30 * 86400
    os.utime(good, (stale, stale))
    return good


def _setup(tmp_path):
    chat = str(tmp_path / "data" / "chat_history.db")
    _seed_db(chat)
    skills = str(tmp_path / "data" / "skills_db.json")
    return chat, skills


# ─── ⓐ ทางที่ prod เดินจริง: scheduler เรียก run_db_backup() เปล่าๆ ─────────────

def test_ทางprod_ไม่ส่งอาร์กิวเมนต์_ซองมี_skills_db_ไบต์ตรงต้นฉบับ(tmp_path, monkeypatch):
    chat, skills = _setup(tmp_path)
    _write_json(skills, _GOOD)
    monkeypatch.setattr(m, "DB_PATH", chat)
    monkeypatch.setattr(m, "READER_DB_PATH", str(tmp_path / "data" / "reader.db"))
    monkeypatch.setattr(m, "EMBED_CACHE_DB", str(tmp_path / "data" / "embed_cache.db"))
    monkeypatch.setattr(m, "RESPONSE_CACHE_DB", str(tmp_path / "data" / "response_cache.db"))
    monkeypatch.setattr(m, "SKILLS_DB_PATH", skills)

    archive = run_db_backup(dest=str(tmp_path / "backups"))

    got = _members(archive)
    assert "skills_db.json" in got, "skills_db.json ต้องอยู่ในซองรายคืน"
    with open(skills, "rb") as f:
        assert got["skills_db.json"] == f.read()


def test_รายการ_json_default_อ่านค่าตอนเรียก_ไม่ใช่ตอน_import(monkeypatch, tmp_path):
    monkeypatch.setattr(m, "SKILLS_DB_PATH", str(tmp_path / "x" / "skills_db.json"))
    assert m._default_json_paths() == [str(tmp_path / "x" / "skills_db.json")]


def test_ผู้เรียกส่ง_db_paths_เอง_ไม่ดึง_skills_db_จริงเข้ามาเงียบๆ(tmp_path, monkeypatch):
    """กันเทส/สคริปต์ที่ระบุชุด sqlite เองไปหยิบ skills_db ของเครื่องเข้ามา (หรือล้มเพราะหาไม่เจอ)"""
    chat, _ = _setup(tmp_path)
    monkeypatch.setattr(m, "SKILLS_DB_PATH", str(tmp_path / "ไม่มีไฟล์นี้.json"))
    archive = run_db_backup(dest=str(tmp_path / "backups"), db_paths=[chat])
    assert set(_members(archive)) == {"chat_history.db"}


# ─── ⓑ ⓔ JSON เสีย → ไม่เข้าซอง · ไม่ลบรุ่นเก่า · raise (ไม่ยิง heartbeat) ────────

@pytest.mark.parametrize("content", [
    '{"deploy-cheatsheet": {"summary": "ตัดครึ่ง'.encode(),   # เขียนค้างกลางทาง
    b"",                                             # ไฟล์ว่าง
    b"[]",                                           # parse ได้แต่ไม่ใช่ dict
    b"null",
    b'"x"',
], ids=["ตัดครึ่ง", "ว่าง", "list", "null", "string"])
def test_json_เสีย_ไม่เข้าซอง_ไม่ลบรุ่นเก่า_raise(tmp_path, content, caplog):
    chat, skills = _setup(tmp_path)
    os.makedirs(os.path.dirname(skills), exist_ok=True)
    with open(skills, "wb") as f:
        f.write(content)
    dest = tmp_path / "backups"
    good = _stale_good_archive(dest)

    with caplog.at_level(logging.ERROR, logger="utils.db_backup"):
        with pytest.raises(SkillsDbNotBackedUp) as exc:
            run_db_backup(dest=str(dest), db_paths=[chat], json_paths=[skills], retain_days=7)

    assert isinstance(exc.value, BackupUnhealthy)
    archive = exc.value.archive
    assert archive and os.path.isfile(archive)
    assert "_UNHEALTHY" not in os.path.basename(archive), "sqlite ในซองยังดี — ห้ามติดป้ายเสีย"
    assert set(_members(archive)) == {"chat_history.db"}, "ไฟล์ JSON เสียต้องไม่เข้าซอง"
    assert good.exists(), "รอบที่สกิลสำรองไม่ได้ ห้ามลบซองเก่าที่มีสกิลดี"
    assert any(r.levelno >= logging.ERROR and "skills_db.json" in r.getMessage()
               for r in caplog.records)


# ─── ⓓ หาไม่เจอ = เหมือน JSON เสีย (แอปใช้จริง ไม่ใช่ใบรอง) ─────────────────────

def test_หา_skills_db_ไม่เจอ_ได้ซอง_sqlite_ไม่ลบรุ่นเก่า_raise(tmp_path, caplog):
    chat, skills = _setup(tmp_path)
    dest = tmp_path / "backups"
    good = _stale_good_archive(dest)

    with caplog.at_level(logging.ERROR, logger="utils.db_backup"):
        with pytest.raises(SkillsDbNotBackedUp) as exc:
            run_db_backup(dest=str(dest), db_paths=[chat], json_paths=[skills], retain_days=7)

    assert set(_members(exc.value.archive)) == {"chat_history.db"}
    assert good.exists()
    assert any(r.levelno >= logging.ERROR and "skills_db.json" in r.getMessage()
               for r in caplog.records)


# ─── ⓒ backup มือ (10-08) ห้ามโดน retention ─────────────────────────────────────

def test_backup_มือของ_skills_db_ไม่โดน_retention(tmp_path):
    chat, skills = _setup(tmp_path)
    _write_json(skills, _GOOD)
    dest = tmp_path / "backups"
    dest.mkdir()
    manual = dest / "skills_db.json.pre-dirmount-20261008-1417"
    manual.write_text("{}")
    stale = time.time() - 365 * 86400
    os.utime(manual, (stale, stale))

    run_db_backup(dest=str(dest), db_paths=[chat], json_paths=[skills], retain_days=7)

    assert manual.exists()


# ─── ของที่เก็บ = ไบต์ชุดเดียวกับที่ตรวจแล้ว (ไม่อ่านซ้ำ) ───────────────────────

def test_ไฟล์ถูกเขียนทับหลังตรวจ_ซองยังเก็บไบต์ชุดที่ตรวจผ่าน(tmp_path, monkeypatch):
    """จำลองคนเขียนแทรกระหว่าง 'ตรวจ' กับ 'เก็บ' — ถ้าโค้ดอ่าน/ก๊อปไฟล์ซ้ำหลังตรวจ
    ซองจะได้ของเสียที่ไม่เคยผ่านการตรวจ"""
    chat, skills = _setup(tmp_path)
    _write_json(skills, _GOOD)
    with open(skills, "rb") as f:
        original = f.read()

    real = m._parse_skills_json

    def parse_then_clobber(data):
        result = real(data)
        with open(skills, "wb") as f:
            f.write('{"ตัดครึ่ง'.encode())
        return result

    monkeypatch.setattr(m, "_parse_skills_json", parse_then_clobber)
    archive = run_db_backup(dest=str(tmp_path / "backups"), db_paths=[chat], json_paths=[skills])

    assert _members(archive)["skills_db.json"] == original


# ─── scheduler: สกิลสำรองไม่ได้ → /fail ทันที · ไม่ยิงสำเร็จ ────────────────────

def _run_scheduled_backup():
    from core import scheduler as sched_mod
    sched_mod._scheduled_db_backup()


def test_scheduler_สกิลสำรองไม่ได้_ยิง_fail_ไม่ยิงสำเร็จ(monkeypatch):
    from utils import heartbeat
    monkeypatch.setattr(heartbeat, "HEARTBEAT_URL", "https://hc-ping.com/test-uuid")
    err = SkillsDbNotBackedUp("skills_db.json parse ไม่ได้", archive="/tmp/a.tar.gz")
    with patch("utils.db_backup.run_db_backup", side_effect=err), \
         patch("utils.heartbeat.ping") as ping, \
         patch("utils.heartbeat.ping_check") as ping_check:
        _run_scheduled_backup()
    ping.assert_not_called()
    ping_check.assert_called_once_with("https://hc-ping.com/test-uuid", fail=True)


def test_scheduler_chat_history_เสีย_พฤติกรรมเดิม_ไม่ยิงอะไรเลย(monkeypatch):
    """กลุ่มควบคุม — ขอบเขตงานนี้คือเคสสกิลเท่านั้น ไม่เปลี่ยนเคส DB หลักเงียบๆ"""
    from utils import heartbeat
    monkeypatch.setattr(heartbeat, "HEARTBEAT_URL", "https://hc-ping.com/test-uuid")
    err = BackupUnhealthy("chat_history.db ว่าง", archive="/tmp/a.tar.gz")
    with patch("utils.db_backup.run_db_backup", side_effect=err), \
         patch("utils.heartbeat.ping") as ping, \
         patch("utils.heartbeat.ping_check") as ping_check:
        _run_scheduled_backup()
    ping.assert_not_called()
    ping_check.assert_not_called()


def test_db_หลักเสียพร้อม_json_เสีย_ข้อความบอกทั้งสองเรื่อง(tmp_path):
    """DB หลักมาก่อน (ชื่อ _UNHEALTHY · ไม่ใช่ SkillsDbNotBackedUp) แต่ปัญหา JSON ต้องไม่หายเงียบ"""
    chat = str(tmp_path / "chat_history.db")
    open(chat, "wb").close()
    skills = str(tmp_path / "skills_db.json")
    with open(skills, "wb") as f:
        f.write(b"[]")

    with pytest.raises(BackupUnhealthy) as exc:
        run_db_backup(dest=str(tmp_path / "backups"), db_paths=[chat], json_paths=[skills])

    assert not isinstance(exc.value, SkillsDbNotBackedUp)
    assert "_UNHEALTHY" in os.path.basename(exc.value.archive)
    assert "skills_db.json" in str(exc.value)


# ─── {} = ว่าง: เก็บเข้าซองได้ (อ่านได้จริง) แต่ห้ามนับว่าสำเร็จ (ปอยเคาะ 10-08) ──────

@pytest.mark.parametrize("content", [b"{}", b" {\n}\n"], ids=["ชิด", "มีช่องว่าง"])
def test_json_ว่าง_เก็บเข้าซองได้_แต่ไม่ลบรุ่นเก่า_raise(tmp_path, content, caplog):
    """prod มี 22 สกิล — ไฟล์กลายเป็น {} คือของหาย ไม่ใช่สถานะปกติ
    ถ้าผ่านเงียบ retention 7 วันจะกินซองที่มีสกิลจริงจนหมด"""
    chat, skills = _setup(tmp_path)
    with open(skills, "wb") as f:
        f.write(content)
    dest = tmp_path / "backups"
    good = _stale_good_archive(dest)

    with caplog.at_level(logging.ERROR, logger="utils.db_backup"):
        with pytest.raises(SkillsDbNotBackedUp) as exc:
            run_db_backup(dest=str(dest), db_paths=[chat], json_paths=[skills], retain_days=7)

    got = _members(exc.value.archive)
    assert got.get("skills_db.json") == content, "ไฟล์ว่างอ่านได้ — เก็บเข้าซองตามจริง"
    assert "_UNHEALTHY" not in os.path.basename(exc.value.archive)
    assert good.exists(), "รอบที่สกิลว่าง ห้ามลบซองเก่าที่มีสกิลดี"
    assert any(r.levelno >= logging.ERROR and "skills_db.json" in r.getMessage()
               for r in caplog.records)
