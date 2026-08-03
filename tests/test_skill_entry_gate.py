"""Tests: เกณฑ์ "ทางเข้า" ของ skill ต้องเป็นตัวเดียวกับเกณฑ์ "ทางออก" (backlog ข้อ 20)

ข้อ 9 ล้างขยะเก่าออกแล้ว แต่ทางเข้ายังเปิดโล่ง — `_is_meaningful_skill()` ถูกใช้
เฉพาะตอน**ลบ** (`cleanup_junk_skills`) และใน `auto_extract_skills` เท่านั้น
ส่วนทางเข้าอีก 3 เส้นเขียนได้อิสระ: `save_skill()` (dream promotion เรียกตรง),
`accept_proposal()` (skill-discovery), `POST /api/skills/extract`

ทำไมถึงสำคัญกว่าที่คิด — ไฟล์ที่ pipeline สร้างลงไปที่ `${NAS_DATA_PATH}/skills` บน prod
**ไม่เคยผ่านสายตา `test_skills_freshness.py`** เพราะเทสนั้นอ่านได้แค่ไฟล์ที่ commit เข้า git
ยืนยันแล้ว: `ได-เลย.md` / `openclaw-*.md` ที่เคยเจอ **ไม่เคยมีอยู่ใน git history เลย**
→ เทสย้อนหลังจับไม่ได้ตามนิยาม · gate ตอนเขียนคือด่านเดียวที่ครอบของบน prod ได้
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import utils.skills as skills
import utils.skill_discovery as sd
from utils.skills import _is_meaningful_skill

# ตัวอย่างของที่ `cleanup_junk_skills()` ลบทิ้ง = ของที่ต้องสร้างไม่ได้ตั้งแต่แรก
JUNK = [
    ("ได้เลยครับ", "ได้เลยครับ เดี๋ยวจัดการให้ทันทีเลยนะครับผม"),   # ตอบรับ ไม่ใช่ความรู้
    ("ok", "สั้นไป"),                                              # topic สั้น + summary สั้น
    ("การ deploy", "สั้น"),                                        # summary ไม่ถึง 20 ตัว
    ("http://localhost:8080", "หน้าเว็บของแอปอยู่ที่ที่อยู่นี้นะครับ"),  # URL ไม่ใช่หัวข้อ
]

GOOD = ("deploy ขึ้น NAS", "push ขึ้น main แล้ว ssh เข้า NAS สั่ง git reset --hard + docker restart ai-backend-1")


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """แยก skills_db.json + skills dir ออกจากของจริง"""
    db_path = tmp_path / "skills_db.json"
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    monkeypatch.setattr(skills, "SKILLS_DB_PATH", str(db_path))
    monkeypatch.setattr(sd, "_SKILLS_DB", str(db_path))
    monkeypatch.setattr(sd, "_SKILLS_DIR", str(skills_dir))
    return db_path, skills_dir


def _read_db(db_path):
    if not os.path.exists(db_path):
        return {}
    with open(db_path, encoding="utf-8") as f:
        return json.load(f)


# ── save_skill() — chokepoint ของ skills_db (dream promotion เรียกเส้นนี้) ────
@pytest.mark.parametrize("topic,summary", JUNK)
def test_save_skill_rejects_junk(isolated_db, topic, summary):
    db_path, _ = isolated_db
    assert skills.save_skill(topic, summary, sync=False) is False
    assert topic not in _read_db(db_path)


def test_save_skill_accepts_real_knowledge(isolated_db):
    db_path, _ = isolated_db
    assert skills.save_skill(*GOOD, sync=False) is True
    assert GOOD[0] in _read_db(db_path)


# ── accept_proposal() — เส้นของ skill-discovery ──────────────────────────────
def _stage(proposal_id, topic, summary):
    sd._proposals_cache[proposal_id] = sd.SkillProposal(
        id=proposal_id, topic=topic, summary=summary,
        examples=["ตัวอย่างคำถาม"], cluster_size=3, detected_at="2026-08-03T00:00:00",
    )


@pytest.mark.parametrize("topic,summary", JUNK)
def test_accept_proposal_rejects_junk(isolated_db, topic, summary):
    db_path, skills_dir = isolated_db
    _stage("p-junk", topic, summary)
    res = sd.accept_proposal("p-junk")
    assert res["ok"] is False
    assert os.listdir(skills_dir) == [], "เขียนไฟล์ .md ทั้งที่ไม่ผ่านเกณฑ์"
    assert _read_db(db_path) == {}


def test_accept_proposal_accepts_real_knowledge(isolated_db):
    db_path, skills_dir = isolated_db
    _stage("p-ok", *GOOD)
    res = sd.accept_proposal("p-ok")
    assert res["ok"] is True
    assert len(os.listdir(skills_dir)) == 1
    assert GOOD[0] in _read_db(db_path)


def test_accept_proposal_gates_custom_content_too(isolated_db):
    """ผู้เรียกส่ง topic/content เองก็ต้องผ่านเกณฑ์เดียวกัน — ไม่ใช่ทางลัด"""
    _, skills_dir = isolated_db
    _stage("p-custom", *GOOD)
    res = sd.accept_proposal("p-custom", custom_topic="ได้เลยครับ",
                             custom_content="ได้เลยครับ เดี๋ยวจัดการให้เลยนะครับ")
    assert res["ok"] is False
    assert os.listdir(skills_dir) == []


# ── invariant: เกณฑ์เข้า == เกณฑ์ออก ────────────────────────────────────────
def test_nothing_that_survives_entry_would_be_removed_by_cleanup(isolated_db):
    """คุณสมบัติที่ต้องจริงเสมอ: ของที่เข้าได้ ต้องไม่ถูก cleanup ลบ

    ถ้าสองเกณฑ์แยกกันเมื่อไหร่ ระบบจะกลับไปวนลูป 'สร้าง → ล้าง → สร้างใหม่' เหมือนข้อ 9
    """
    db_path, _ = isolated_db
    for topic, summary in JUNK + [GOOD]:
        skills.save_skill(topic, summary, sync=False)

    before = set(_read_db(db_path))
    monkey_db = _read_db(db_path)
    kept = {t: d for t, d in monkey_db.items()
            if _is_meaningful_skill(t, d.get("summary", ""))}
    assert set(kept) == before, (
        f"cleanup จะลบของที่ผ่านทางเข้ามาได้: {before - set(kept)}"
    )
    assert before == {GOOD[0]}
