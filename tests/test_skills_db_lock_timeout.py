"""รอ `flock` ต้องมีเพดาน — ไม่งั้นโปรเซสที่ค้างถือ lock ลากแอปทั้งตัว

**ทำไมต้องมีเพดานทั้งที่ file lock ปกติรอไม่จำกัด:** ตั้งแต่ PR #23 เส้นที่เขียน
`skills_db.json` ย้ายไปอยู่ใน `run_in_threadpool` (threadpool มี 40 slot) ถ้ามีโปรเซส
ค้างถือ lock ไว้ คำขอที่เขียน skills จะกองรอจนกิน slot หมด = **อาการเดียวกับที่ PR #23
เพิ่งไล่ปิดไป** แค่เปลี่ยนสาเหตุจาก "งาน sync บน event loop" เป็น "รอ lock ไม่จำกัด"

**ทิศที่เลือก (user ตัดสินใจ 2026-08-04): fail-fast + ส่งเสียงดัง** — เพราะเส้นสำรองมีจริง
ผู้ใช้กดบันทึกใหม่ได้ แต่แอปที่ค้างทั้งตัวไม่มีทางออก · ทิศเดียวกับ `_handle_unscorable_results`
(ดู vault `wiki/concepts/failure-mode-direction.md`)

⚠️ ผู้ถือ lock ต้องเป็น **คนละโปรเซส** — ถ้าใช้เธรดในโปรเซสเดียวกัน มันจะไปติดที่ `_db_lock`
(RLock) ก่อนถึง `flock` ด้วยซ้ำ เทสจะวัดคนละอย่างกับที่ตั้งใจ
"""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import utils.skills as skills

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# โปรเซสที่ยึด lock ค้างไว้ — พิมพ์ LOCKED แล้ว flush ให้พ่อรู้ว่ายึดได้แล้วจริง
_HOLDER = """
import sys, time
sys.path.insert(0, {repo!r})
import utils.skills as s
s.SKILLS_DB_PATH = {db!r}
with s._db_transaction():
    print("LOCKED", flush=True)
    time.sleep({hold})
"""


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    p = tmp_path / "skills_db.json"
    p.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(skills, "SKILLS_DB_PATH", str(p))
    return p


@pytest.fixture
def lock_holder(db_path):
    """สตาร์ตโปรเซสที่ถือ lock ไว้ แล้วรอจนมันยืนยันว่ายึดได้จริง"""
    procs = []

    def start(hold: float = 30.0):
        p = subprocess.Popen(
            [sys.executable, "-c", _HOLDER.format(repo=REPO, db=str(db_path), hold=hold)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        procs.append(p)
        line = p.stdout.readline()
        assert line.strip() == "LOCKED", f"โปรเซสยึด lock ไม่สำเร็จ: {line!r} {p.stderr.read()[:300]}"
        return p

    yield start
    for p in procs:
        p.kill()
        p.wait(timeout=30)


def test_รอเกินเพดานต้องโยน_error_ไม่ค้างรอต่อ(db_path, lock_holder):
    lock_holder(hold=30.0)

    t0 = time.perf_counter()
    with pytest.raises(skills.SkillsDbLocked):
        with skills._db_transaction(timeout=1.0):
            pass
    elapsed = time.perf_counter() - t0

    assert 0.9 <= elapsed < 4.0, (
        f"ใช้เวลา {elapsed:.2f}s — เพดาน 1.0s ควรเลิกรอราวๆ นั้น "
        "(เร็วเกิน = ไม่ได้รอจริง · ช้าเกิน = เพดานไม่ทำงาน)")


def test_ทางเขียนของแอปต้องรายงานความล้มเหลว_ไม่กลืนเงียบ(db_path, lock_holder, monkeypatch):
    """`set_skill_entry()` ต้องปล่อย error ออกมา ไม่ใช่ทำเหมือนบันทึกสำเร็จ"""
    monkeypatch.setattr(skills, "SKILLS_DB_LOCK_TIMEOUT", 1.0)
    lock_holder(hold=30.0)

    with pytest.raises(skills.SkillsDbLocked):
        skills.set_skill_entry("หัวข้อที่บันทึกไม่ลง", {"summary": "เนื้อหาที่ยาวพอจะผ่านเกณฑ์"})

    # ต้องไม่มีอะไรถูกเขียนลงไปครึ่งๆ กลางๆ
    assert json.loads(db_path.read_text(encoding="utf-8")) == {}


def test_save_skill_ต้องคืน_False_เมื่อ_lock_ไม่ว่าง(db_path, lock_holder, monkeypatch):
    """`save_skill()` มีสัญญาเป็น bool อยู่แล้ว — คืน False + log ERROR ไม่ให้ exception หลุด

    ผู้เรียกคือ `auto_extract_skills()` กับ dream cycle ซึ่งวนหลายรายการ
    ปล่อย exception หลุดจะทำให้ทั้งชุดพัง ทั้งที่รายการอื่นยังบันทึกได้
    """
    monkeypatch.setattr(skills, "SKILLS_DB_LOCK_TIMEOUT", 1.0)
    lock_holder(hold=30.0)

    assert skills.save_skill("หัวข้อทดสอบที่ดีพอ",
                             "เนื้อหาที่ยาวพอจะผ่านเกณฑ์คุณภาพขั้นต่ำ", sync=False) is False


def test_lock_ว่างต้องทำงานปกติไม่รอเปล่า(db_path):
    """กัน 'เขียวเพราะทุกอย่างพัง' — เส้นปกติต้องไม่ถูกเพดานทำให้ช้าลง"""
    t0 = time.perf_counter()
    skills.set_skill_entry("หัวข้อปกติที่บันทึกได้", {"summary": "เนื้อหาที่ยาวพอจะผ่านเกณฑ์"})
    elapsed = time.perf_counter() - t0

    assert elapsed < 0.5, f"เส้นที่ไม่มีใครแย่ง lock ใช้เวลา {elapsed:.2f}s"
    assert "หัวข้อปกติที่บันทึกได้" in json.loads(db_path.read_text(encoding="utf-8"))


def test_สคริปต์ต้องออกด้วยรหัสไม่ศูนย์เมื่อยึด_lock_ไม่ได้(db_path, lock_holder, tmp_path):
    """งาน maintenance ที่ทำไม่สำเร็จต้องดัง — ไม่ใช่จบ 0 แล้วคนคิดว่าล้างแล้ว"""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    lock_holder(hold=30.0)

    p = subprocess.run(
        [sys.executable, os.path.join(REPO, "scripts", "clean_skills_db.py"),
         "--apply", "--db", str(db_path), "--skills-dir", str(skills_dir),
         "--lock-timeout", "1"],
        capture_output=True, text=True, timeout=120)

    # ⚠️ ห้าม assert แค่ `returncode != 0` + คำว่า "lock" ในเอาต์พุต — argparse ที่ไม่รู้จัก
    # `--lock-timeout` ก็ออก 2 พร้อมข้อความ "unrecognized arguments: --lock-timeout"
    # ทำให้เทสเขียวโดยไม่ได้ทดสอบอะไรเลย (เจอจริงตอนเขียนเทสนี้)
    assert p.returncode == 1, (
        f"ควรออกด้วย 1 (ยึด lock ไม่ได้) แต่ได้ {p.returncode}\n"
        f"stdout: {p.stdout[-300:]}\nstderr: {p.stderr[-300:]}")
    assert "ยึด lock ของ skills_db ไม่ได้" in (p.stdout + p.stderr), (
        f"ไม่มีข้อความบอกสาเหตุ\nstdout: {p.stdout[-300:]}\nstderr: {p.stderr[-300:]}")
