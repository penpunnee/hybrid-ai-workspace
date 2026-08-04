"""เขียน `skills_db.json` ไม่สำเร็จต้องดัง — ห้ามรายงานว่าบันทึกแล้ว

`_save_skills_db()` เดิม `except Exception` แล้ว `logger.warning` เฉยๆ ไม่คืนอะไรเลย
→ ดิสก์เต็ม / สิทธิ์ไม่พอ / `os.replace()` ข้าม filesystem ไม่ได้ = **เขียนไม่ลงแต่เงียบ**
แล้วผู้เรียกทุกคนเดินต่อเหมือนสำเร็จ:

- `save_skill()` คืน `True`
- `set_skill_entry()` คืนปกติ → `skills_extract` ตอบ `db_updated: true`
- `scripts/clean_skills_db.py --apply` พิมพ์ "ลบ N · resync M" แล้ว **exit 0**

⚠️ ข้อสุดท้ายเป็น **regression ที่เกิดจาก PR นี้เอง** — ก่อนหน้านี้สคริปต์เขียนด้วย
`open(db,"w")` + `json.dump()` ซึ่งโยน exception ออกมาเป็น traceback = ดังอยู่แล้ว
การย้ายมาใช้ `_save_skills_db()` (ถูกต้องเรื่อง atomic + lock) เผลอทำให้ **ความล้มเหลว
ที่เคยดังกลายเป็นเงียบ** · บทเรียนเดียวกับ `save_mem` ที่ตอบ ok:True ทั้งที่ ChromaDB ล่ม
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import utils.skills as skills

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    p = tmp_path / "skills_db.json"
    p.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(skills, "SKILLS_DB_PATH", str(p))
    return p


@pytest.fixture
def broken_write(monkeypatch):
    """จำลองดิสก์เต็ม/สิทธิ์ไม่พอ ณ จังหวะสลับไฟล์จริง"""
    def boom(*a, **kw):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(os, "replace", boom)


def test_set_skill_entry_ต้องโยน_error_เมื่อเขียนไม่ลง(db_path, broken_write):
    with pytest.raises(skills.SkillsDbError):
        skills.set_skill_entry("หัวข้อที่เขียนไม่ลง", {"summary": "เนื้อหาที่ยาวพอจะผ่านเกณฑ์"})

    assert json.loads(db_path.read_text(encoding="utf-8")) == {}


def test_save_skill_ต้องคืน_False_เมื่อเขียนไม่ลง(db_path, broken_write):
    """สัญญาเป็น bool อยู่แล้ว — ต้องไม่คืน True ทั้งที่ไฟล์ไม่เปลี่ยน"""
    assert skills.save_skill("หัวข้อทดสอบที่ดีพอ",
                             "เนื้อหาที่ยาวพอจะผ่านเกณฑ์คุณภาพขั้นต่ำ", sync=False) is False


def test_สคริปต์ต้อง_exit_1_เมื่อเขียนไม่ลง(db_path, tmp_path):
    """เดิมเขียนด้วย open(w) = พังแล้วมี traceback · ห้ามถอยหลังเป็น 'เงียบแล้วจบ 0'"""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    db_path.write_text(json.dumps({"กำพร้าไม่มีไฟล์": {"summary": "ควรถูกลบ", "source": "x.md"}},
                                  ensure_ascii=False), encoding="utf-8")

    # ทำให้ os.replace ล้มเหลวในโปรเซสของสคริปต์ ผ่าน sitecustomize ที่ PYTHONPATH หยิบไป
    inject = tmp_path / "inject"
    inject.mkdir()
    (inject / "sitecustomize.py").write_text(
        "import os\n"
        "def _boom(*a, **kw):\n"
        "    raise OSError(28, 'No space left on device')\n"
        "os.replace = _boom\n",
        encoding="utf-8")

    env = dict(os.environ, PYTHONPATH=str(inject))
    p = subprocess.run(
        [sys.executable, os.path.join(REPO, "scripts", "clean_skills_db.py"),
         "--apply", "--db", str(db_path), "--skills-dir", str(skills_dir)],
        capture_output=True, text=True, timeout=120, env=env)

    assert p.returncode == 1, (
        f"สคริปต์จบด้วย {p.returncode} ทั้งที่เขียนไม่ลง\n"
        f"stdout: {p.stdout[-400:]}\nstderr: {p.stderr[-400:]}")
    assert "เขียน skills_db ไม่สำเร็จ" in (p.stdout + p.stderr), (
        f"ไม่มีข้อความบอกสาเหตุ\nstdout: {p.stdout[-400:]}\nstderr: {p.stderr[-400:]}")
