"""reader.db ต้องอยู่ในซอง backup — และต้องมีแหล่ง path เดียว

ทำไมถึงหลุดมาได้ (ตรวจจริง 2026-09-01):
  `run_db_backup()` ตั้ง default paths ไว้ตั้งแต่ 2026-07-12 ตอนที่ยังมีแค่
  chat_history + cache 2 ใบ · `reader.db` เกิดทีหลัง (08-09) พร้อม path literal
  ของตัวเองใน routers/reader.py และไม่มีใครเชื่อมสองที่นี้เข้าหากัน
  ⇒ ซองที่ได้เก็บ embed_cache/response_cache ที่ **สร้างใหม่ได้ฟรี**
     แต่ไม่เก็บ reader.db 125 MB ที่ **สร้างใหม่ไม่ได้**

🔑 ที่ทำให้ไม่มีใครรู้: เทส backup ทุกตัวที่มีอยู่ (test_db_backup_job.py /
   test_db_backup_health.py) ส่ง `db_paths=` เข้าไปเองทุกเคส ⇒ **รายการ default
   ไม่เคยถูกเดินผ่านเลยสักเทสเดียว** — บั๊กจึงไม่มีทางถูกจับโดยโครงสร้าง
   เทสในไฟล์นี้จึงเรียกโดย *ไม่* ส่ง db_paths เป็นหลัก
"""
import os
import sqlite3
import subprocess
import tarfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _seed(path, table="t", rows=1):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(f"CREATE TABLE {table} (x INTEGER)")
    for i in range(rows):
        conn.execute(f"INSERT INTO {table} VALUES ({i})")
    conn.commit()
    conn.close()


def _archive_names(dest):
    archives = list(dest.glob("db_backup_*.tar.gz"))
    assert len(archives) == 1, f"คาดว่าได้ 1 archive ได้ {archives}"
    with tarfile.open(archives[0]) as tf:
        return {os.path.basename(n) for n in tf.getnames()}


# ── 1. รายการ default ต้องมี reader.db ────────────────────────────────────────

def test_default_paths_เก็บ_reader_db_ด้วย(tmp_path, monkeypatch):
    """เส้นที่ prod เดินจริง: scheduler เรียก run_db_backup() เปล่าๆ ไม่ส่ง db_paths"""
    import utils.db_backup as m

    chat = str(tmp_path / "chat_history.db")
    reader = str(tmp_path / "data" / "reader.db")
    _seed(chat)
    _seed(reader, table="books")
    monkeypatch.setattr(m, "DB_PATH", chat)
    monkeypatch.setattr(m, "READER_DB_PATH", reader)
    monkeypatch.setattr(m, "EMBED_CACHE_DB", str(tmp_path / "data" / "embed_cache.db"))
    monkeypatch.setattr(m, "RESPONSE_CACHE_DB", str(tmp_path / "data" / "response_cache.db"))

    dest = tmp_path / "backups"
    m.run_db_backup(dest=str(dest))

    assert "reader.db" in _archive_names(dest), (
        "reader.db หายจากซอง — ใบเดียวในระบบที่สร้างใหม่ไม่ได้")


def test_db_หลักยังเป็นใบชี้ขาดลำดับแรก():
    """paths[0] คือใบที่ _verify_snapshot ตรวจ — การเพิ่ม reader ห้ามแย่งที่นั่ง

    ถ้า reader.db ขึ้นมาเป็นตัวแรก ตัวตรวจจะเลิกดู chat_history ทั้งที่นั่นคือ
    ใบที่เคยผลิต archive 989 ไบต์เมื่อ 2026-07-12

    ⚠️ ผูกกับ *บทบาท* (คือ DB_PATH) ไม่ใช่ชื่อไฟล์ — conftest override DB_PATH
       เป็น hybrid_ai_test.db เทสที่เช็ค 'chat_history.db' ตรงๆ จะแดงมั่ว
    """
    import core.config as cfg
    from utils.db_backup import _default_db_paths

    assert _default_db_paths()[0] == cfg.DB_PATH


def test_ครบทั้ง_4_ใบไม่มีตกหล่น():
    """กลุ่มควบคุม — กันการ 'แก้' ด้วยการสลับ cache ออกไปแทนที่จะเพิ่ม reader"""
    import core.config as cfg
    from utils.db_backup import _default_db_paths

    assert _default_db_paths() == [
        cfg.DB_PATH, cfg.READER_DB_PATH, cfg.EMBED_CACHE_DB, cfg.RESPONSE_CACHE_DB]


# ── 2. แหล่ง path เดียว (กันดริฟต์แบบ voice.py) ───────────────────────────────

def test_reader_ใช้_path_ตัวเดียวกับ_backup():
    """ตอน env ไม่ได้ตั้ง สองฝั่งต้องชี้ไฟล์เดียวกัน"""
    import core.config
    import routers.reader

    assert routers.reader._DB == core.config.READER_DB_PATH


def test_reader_ต้องไม่มี_default_เป็นของตัวเอง():
    """ตรวจ *ซอร์ส* ไม่ใช่ค่า — ค่าเท่ากันวันนี้ไม่ได้แปลว่าพรุ่งนี้ยังเท่ากัน

    บทเรียน utils/voice.py: default 2 ที่ที่ไม่ตรงกันเงียบๆ ตั้งแต่ 369f18e
    ทั้งที่คอมเมนต์เขียนว่า 'ให้ default ตรงกับ core/config.py'

    🔑 ตรึงที่ "ชื่อไฟล์ default ห้ามโผล่ในไฟล์นี้" ไม่ใช่ "ห้ามเรียก getenv" —
       เกณฑ์แบบหลังเคยเขียนไว้แล้วมันบังคับให้ reader รับค่าสำเร็จรูปจาก config
       ซึ่ง**ทำลายการแยก DB ในเทส** (reload ไม่เห็น env ใหม่) การห้ามผิดข้อ
       เปลี่ยนบั๊กหนึ่งเป็นอีกบั๊กหนึ่งที่แย่กว่า
    """
    src = open(os.path.join(_ROOT, "routers", "reader.py"), encoding="utf-8").read()
    code = "\n".join(
        line for line in src.splitlines() if not line.lstrip().startswith("#"))
    assert "reader.db" not in code, (
        "routers/reader.py เขียนชื่อไฟล์ default เอง — ต้องใช้ "
        "core.config.READER_DB_DEFAULT ที่เดียว")


def test_เทสต้องแยก_db_ออกจากของจริงได้จริง(tmp_path, monkeypatch):
    """ตัวกันซ้ำของสิ่งที่เพิ่งพลาด 2026-09-01

    tests/test_reader_api.py แยก DB ด้วย setenv + importlib.reload(routers.reader)
    ตอนย้าย path ไป core.config รอบแรก reload เลิกเห็น env ใหม่เงียบๆ ⇒ เทสทั้งชุด
    ไปเขียนทับ data/reader.db ตัวจริงบนเครื่อง dev **โดยเทสที่รันเดี่ยวยังเขียว**
    (เจอเพราะรันชุดเต็ม + มีกลุ่มควบคุมบนโค้ดเดิม)
    """
    import importlib

    import routers.reader as R

    monkeypatch.setenv("READER_DB_PATH", str(tmp_path / "iso.db"))
    importlib.reload(R)
    try:
        assert R._DB == str(tmp_path / "iso.db"), (
            "reload แล้วไม่เห็น READER_DB_PATH ใหม่ — เทสจะไปเขียน DB ตัวจริง")
    finally:
        monkeypatch.undo()
        importlib.reload(R)


# ── 3. ratchet: DB ใหม่ใน config ต้องเข้าซองอัตโนมัติ ─────────────────────────

def test_ทุก_db_ที่ประกาศใน_config_ต้องถูก_backup():
    """ตัวล็อกไม่ให้เรื่องนี้เกิดซ้ำกับ DB ใบถัดไป

    เหตุที่ reader.db หลุดคือ 'เพิ่ม DB ใหม่แล้วไม่มีอะไรเตือน' — เทสนี้ทำให้
    การเพิ่มค่าคงที่ *_DB / *_DB_PATH ใน core/config.py แล้วไม่ใส่ในรายการ
    backup กลายเป็นเทสแดงทันที ไม่ใช่รอให้ข้อมูลหายก่อน
    """
    import core.config as cfg
    from utils.db_backup import _default_db_paths

    # 🔑 จับตาม **ค่า** (ลงท้าย .db) ไม่ใช่ตาม **ชื่อตัวแปร** — เกณฑ์ชื่อ
    #    ("_DB"/"_DB_PATH") มองไม่เห็น DB_PATH เองด้วยซ้ำ และ DB ใบใหม่ที่ตั้งชื่อ
    #    ไม่ตรงแบบ (NOTES_PATH, FOO_DATABASE) จะรอดไปเงียบๆ = ratchet ที่ไม่กันอะไร
    declared = {
        name for name in dir(cfg)
        if not name.startswith("_")
        and isinstance(getattr(cfg, name), str)
        and getattr(cfg, name).endswith(".db")
    }
    assert declared, "ไม่เจอค่าคงที่ .db เลยใน core/config.py — เทสนี้กลายเป็นเทสเปล่า"

    backed = {os.path.basename(p) for p in _default_db_paths()}
    missing = {n for n in declared
               if os.path.basename(getattr(cfg, n)) not in backed}
    assert not missing, (
        f"DB ที่ประกาศใน core/config.py แต่ไม่ได้ถูก backup: {sorted(missing)} — "
        f"ถ้าตั้งใจไม่ backup (regenerate ได้) ให้เขียนเหตุผลไว้แล้วยกเว้นในเทสนี้")


# ── 4. เส้นที่สอง: shell script ต้องไม่ตกขบวน ────────────────────────────────
# ⚠️ backup มี 2 เส้นเหมือน pipeline ค้นเว็บ — in-app (utils/db_backup.py) และ
#    scripts/db_backup.sh · แก้เส้นเดียวคือปล่อยให้อีกเส้นโกหกต่อ

def test_shell_script_เก็บ_reader_db_ด้วย(tmp_path):
    ui = tmp_path / "ui"
    for name in ("data/chat_history.db", "data/reader.db",
                 "data/embed_cache.db", "data/response_cache.db"):
        _seed(str(ui / name))
    dest = tmp_path / "backups"

    r = subprocess.run(
        ["bash", os.path.join(_ROOT, "scripts", "db_backup.sh")],
        env={**os.environ, "UI_DIR": str(ui), "DB_BACKUP_DEST": str(dest),
             "DB_BACKUP_RETAIN": "7"},
        capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "reader.db" in _archive_names(dest), r.stdout


# ── 5. ใบที่ขอแล้วหาไม่เจอ ต้องมีร่องรอย ────────────────────────────────────
# _verify_snapshot ดูแค่ paths[0] ⇒ reader.db หายจาก mount = ซองขาดใบเงียบๆ
# ซึ่งเป็นอาการเดียวกับที่เพิ่งใช้เวลา 23 วันกว่าจะเจอ

def test_ใบที่หายต้องถูก_log_เป็น_error(tmp_path, caplog):
    import logging

    from utils.db_backup import run_db_backup

    chat = str(tmp_path / "chat_history.db")
    _seed(chat)
    gone = str(tmp_path / "reader.db")  # ไม่ได้สร้าง = จำลอง mount หาย

    with caplog.at_level(logging.ERROR, logger="utils.db_backup"):
        run_db_backup(dest=str(tmp_path / "b"), db_paths=[chat, gone])

    assert any("reader.db" in r.getMessage() for r in caplog.records
               if r.levelno >= logging.ERROR), \
        "ใบที่ขอแล้วหาไม่เจอต้องดัง ไม่ใช่หายเงียบ"


def test_ครบทุกใบต้องไม่เตือน(tmp_path, caplog):
    """กลุ่มควบคุม — ตัวเตือนที่ดังตลอดเวลาคือตัวเตือนที่ไม่มีใครฟัง"""
    import logging

    from utils.db_backup import run_db_backup

    chat = str(tmp_path / "chat_history.db")
    reader = str(tmp_path / "reader.db")
    _seed(chat)
    _seed(reader)

    with caplog.at_level(logging.ERROR, logger="utils.db_backup"):
        run_db_backup(dest=str(tmp_path / "b"), db_paths=[chat, reader])

    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
