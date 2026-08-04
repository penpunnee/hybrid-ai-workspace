"""`skills_db.json` ต้องทนการเขียนพร้อมกัน **ข้ามโปรเซส** ไม่ใช่แค่ข้ามเธรด

ต่อจาก `test_skills_db_concurrency.py` ซึ่งปิดฝั่ง "หลายเธรดในแอปเดียว" ด้วย `_db_lock`
(`threading.RLock`) — RLock เป็นของในโปรเซสเดียว **คนละโปรเซสไม่เห็นกันเลย**

ผู้เขียนไฟล์เดียวกันจากคนละโปรเซสที่มีจริงบน prod:

| ใคร | เขียนตอนไหน |
|---|---|
| `ai-backend-1` (แอป) | ตลอดเวลา — เส้นแชท, dream cycle (APScheduler), `/api/skills/*` |
| `scripts/clean_skills_db.py` | ตอนคนสั่งเอง — **รันใน container เดียวกัน** (`docker exec`) จึงเห็นไฟล์เดียวกัน |

สองอาการที่วัดได้ในไฟล์นี้:

1. **lost update ข้ามโปรเซส** — `set_skill_entry()` จากหลายโปรเซสพร้อมกัน รายการหาย
2. **สคริปต์เขียนทับของที่แอปเพิ่งเขียน** — สคริปต์อ่าน db ตอน T0 แล้วใช้เวลาไล่ `.md`
   ทุกไฟล์ก่อนเขียนคืนตอน T1 · อะไรที่แอปเขียนระหว่าง T0→T1 หายเงียบ
   (สคริปต์ยังเขียนด้วย `open(db,"w")` = truncate = ไม่ atomic ด้วย — บั๊กคู่แฝดของ
   ตัวที่ `_save_skills_db()` แก้ไปแล้วเมื่อ 2026-08-04 แต่สคริปต์ไม่ได้ถูกแก้ตาม)

⚠️ เทสนี้ต้องใช้ **subprocess จริง** — `threading` พิสูจน์ข้อนี้ไม่ได้เลย เพราะ RLock
ที่มีอยู่แล้วจะทำให้เขียวโดยไม่ได้ทดสอบสิ่งที่ตั้งใจ
"""
import json
import os
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import utils.skills as skills

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# สคริปต์ที่ subprocess รัน — ชี้ SKILLS_DB_PATH ไปไฟล์ทดสอบ แล้วเขียนผ่าน API จริง
_WRITER = """
import sys
sys.path.insert(0, {repo!r})
import utils.skills as s
s.SKILLS_DB_PATH = {db!r}
for i in range({n}):
    key = "หัวข้อทดสอบของโปรเซส {w} หมายเลข %d" % i
    s.set_skill_entry(key, {{"summary": "เนื้อหาทดสอบที่ยาวพอจะผ่านเกณฑ์ %d" % i}})
"""


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    p = tmp_path / "skills_db.json"
    p.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(skills, "SKILLS_DB_PATH", str(p))
    return p


def _expected_keys(n_proc: int, per_proc: int) -> set:
    return {f"หัวข้อทดสอบของโปรเซส {w} หมายเลข {i}"
            for w in range(n_proc) for i in range(per_proc)}


def test_เขียนจากหลายโปรเซสพร้อมกันต้องไม่มีรายการหาย(db_path):
    """`threading.RLock` ไม่ข้ามโปรเซส — ต้องมี file lock (flock) ถึงจะกันได้"""
    n_proc, per_proc = 6, 20
    procs = [
        subprocess.Popen(
            [sys.executable, "-c",
             _WRITER.format(repo=REPO, db=str(db_path), n=per_proc, w=w)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for w in range(n_proc)
    ]
    for p in procs:
        out, err = p.communicate(timeout=180)
        assert p.returncode == 0, err.decode()[-500:]

    saved = json.loads(db_path.read_text(encoding="utf-8"))
    missing = sorted(_expected_keys(n_proc, per_proc) - set(saved))
    assert not missing, (
        f"หายไป {len(missing)}/{n_proc * per_proc} รายการ (lost update ข้ามโปรเซส) "
        f"— ตัวอย่าง {missing[:3]}")


def test_clean_skills_db_ต้องรอ_lock_ไม่เขียนทับของที่แอปเพิ่งเขียน(db_path, tmp_path):
    """สคริปต์ maintenance ต้องแย่ง lock ตัวเดียวกับแอป ไม่ใช่เขียนสวนเข้าไป

    วัดแบบตัดตัวแปรเวลาออก: **ยึด lock ค้างไว้ก่อน** แล้วปล่อยสคริปต์วิ่ง
    - ถ้าสคริปต์เคารพ lock → มันต้องยังไม่จบตอนที่เรายังถืออยู่
    - ระหว่างนั้นเราเขียนรายการใหม่ → พอปล่อย lock สคริปต์ต้องอ่าน**ของใหม่**แล้วค่อยเขียน
      รายการนั้นจึงต้องรอด · ถ้าสคริปต์อ่านไปตั้งแต่ก่อนเราเขียน มันจะทับหาย
    """
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    skills.set_skill_entry("รายการเดิมที่ต้องอยู่รอด",
                           {"summary": "เนื้อหาเดิมที่ยาวพอจะผ่านเกณฑ์คุณภาพ"})

    proc_holder = {}

    def run_script():
        proc_holder["p"] = subprocess.Popen(
            [sys.executable, os.path.join(REPO, "scripts", "clean_skills_db.py"),
             "--apply", "--db", str(db_path), "--skills-dir", str(skills_dir)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        proc_holder["out"] = proc_holder["p"].communicate(timeout=180)

    with skills._db_transaction():          # ยึด lock ค้างไว้
        t = threading.Thread(target=run_script)
        t.start()
        time.sleep(2.0)                     # ให้สคริปต์สตาร์ทและไปติดที่ lock
        assert proc_holder.get("p") is not None
        assert proc_holder["p"].poll() is None, (
            "สคริปต์ทำงานจนจบทั้งที่ lock ถูกถืออยู่ — มันไม่ได้แย่ง lock กับแอปเลย")

        # แอปเขียนรายการใหม่ระหว่างที่ยังถือ lock
        db = skills._load_skills_db()
        db["รายการใหม่ที่แอปเพิ่งเขียน"] = {"summary": "เนื้อหาใหม่ที่ยาวพอจะผ่านเกณฑ์"}
        skills._save_skills_db(db)

    t.join(timeout=180)
    assert proc_holder["p"].returncode == 0, proc_holder["out"][1].decode()[-500:]

    saved = json.loads(db_path.read_text(encoding="utf-8"))
    assert "รายการใหม่ที่แอปเพิ่งเขียน" in saved, (
        "สคริปต์เขียนทับรายการที่แอปเพิ่งเขียน (lost update ข้ามโปรเซส)")
    assert "รายการเดิมที่ต้องอยู่รอด" in saved


def test_ไฟล์ต้องอ่านได้ตลอดเวลาแม้ระหว่างที่สคริปต์เขียน(db_path, tmp_path):
    """สคริปต์เขียนด้วย `open(db,"w")` = truncate ก่อนเขียนเนื้อ

    ใครอ่านจังหวะนั้นได้ JSON พัง → `_load_skills_db()` กลืน exception แล้วคืน `{}`
    = คลังว่างเปล่าชั่วคราวโดยไม่มีใครรู้ · db ใหญ่พอให้ช่วง truncate กว้างจนจับได้จริง
    """
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    big = {f"หัวข้อทดสอบขนาดใหญ่หมายเลข {i}":
           {"summary": "เนื้อหาที่ยาวพอจะผ่านเกณฑ์คุณภาพขั้นต่ำของ skill " * 6}
           for i in range(3000)}
    db_path.write_text(json.dumps(big, ensure_ascii=False, indent=2), encoding="utf-8")

    stop = threading.Event()
    bad: list[str] = []

    def reader():
        while not stop.is_set():
            try:
                raw = db_path.read_text(encoding="utf-8")
            except FileNotFoundError:
                bad.append("ไฟล์หายไประหว่างเขียน")
                continue
            if not raw:
                bad.append("อ่านได้ไฟล์เปล่า")
                continue
            try:
                json.loads(raw)
            except json.JSONDecodeError:
                bad.append(f"JSON พัง ({len(raw)} ไบต์)")

    r = threading.Thread(target=reader, daemon=True)
    r.start()
    try:
        p = subprocess.run(
            [sys.executable, os.path.join(REPO, "scripts", "clean_skills_db.py"),
             "--apply", "--db", str(db_path), "--skills-dir", str(skills_dir)],
            capture_output=True, timeout=300)
        assert p.returncode == 0, p.stderr.decode()[-500:]
    finally:
        stop.set()
        r.join(timeout=10)

    assert not bad, f"อ่านเจอสถานะพัง {len(bad)} ครั้ง — ตัวอย่าง {bad[:3]}"
