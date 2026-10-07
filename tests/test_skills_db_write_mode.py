"""เขียน `skills_db.json` ใหม่ต้องได้ **0644** เสมอ (2026-10-07 · devlog [ต่อ 147]–[148])

`_save_skills_db()` เขียนลงไฟล์จาก `tempfile.mkstemp` (สร้างเป็น 0600 เสมอ) แล้ว `os.replace` ทับ
⇒ ถ้าไม่ตั้งสิทธิ์ ไฟล์จริงกลายเป็น 0600 ของ root (คอนเทนเนอร์รันเป็น root) · user `pawin` บน NAS อ่านไม่ได้
ก่อนหน้านี้ไม่เคยเกิดเพราะ mount ไฟล์เดี่ยวทำให้ `os.replace` ล้ม (EBUSY) ทุกครั้ง

⛔ ห้ามแก้เป็น "ลอกสิทธิ์ไฟล์เดิม" — วัดบน prod 2026-10-07: ไฟล์ที่มี Synology ACL host เห็น 777
แต่**ในคอนเทนเนอร์เห็น 0111** (`skills_db.json` · `reader.db` · dream report) ⇒ ลอกมา = 0111 อ่านไม่ได้
ส่วนไฟล์ที่คอนเทนเนอร์สร้างเองใน data/ (`embed_cache.db`) = 644 ทั้งสองฝั่ง ⇒ ใช้ 0644 ตายตัว
"""
import os
import stat
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import utils.skills as skills


def _mode(p) -> int:
    return stat.S_IMODE(os.stat(p).st_mode)


@pytest.mark.parametrize("old_mode", [0o600, 0o111, 0o777, 0o640])
def test_สิทธิ์หลังเขียน_เป็น_0644(tmp_path, monkeypatch, old_mode):
    """0o111 = ที่คอนเทนเนอร์เห็นไฟล์ ACL ของ Synology จริง — ห้ามลอกตาม"""
    p = tmp_path / "skills_db.json"
    p.write_text("{}", encoding="utf-8")
    os.chmod(p, old_mode)
    monkeypatch.setattr(skills, "SKILLS_DB_PATH", str(p))

    skills._save_skills_db({"x": {}})

    got = _mode(p)
    os.chmod(p, 0o644 | got)  # ให้อ่านได้แม้ regress เป็น 0111 — ตรวจเนื้อหาก่อน แล้วค่อยตรวจสิทธิ์จากค่าที่จดไว้
    assert '"x"' in p.read_text(encoding="utf-8"), "ต้องเขียนลงจริง (ไม่งั้นเทสนี้ไม่ได้ตรวจอะไร)"
    assert got == 0o644, f"ไฟล์เดิม {oct(old_mode)} → หลังเขียนได้ {oct(got)}"


def test_ไฟล์ใหม่ที่ยังไม่เคยมี_ได้_0644(tmp_path, monkeypatch):
    p = tmp_path / "skills_db.json"
    monkeypatch.setattr(skills, "SKILLS_DB_PATH", str(p))

    skills._save_skills_db({"x": {}})

    assert _mode(p) == 0o644, oct(_mode(p))


def test_ไม่ทิ้งไฟล์ชั่วคราวไว้(tmp_path, monkeypatch):
    p = tmp_path / "skills_db.json"
    p.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(skills, "SKILLS_DB_PATH", str(p))

    skills._save_skills_db({"x": {}})

    assert sorted(f.name for f in tmp_path.iterdir() if f.name.endswith(".tmp")) == []
