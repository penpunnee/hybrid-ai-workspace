"""Tests for scripts/clean_skills_db.py — ล้าง entry กำพร้าใน skills_db.json (backlog ข้อ 18)

เกณฑ์ที่เลือก: **entry ต้องมีไฟล์ .md คู่กันอยู่ใน SKILLS_DIR จริง**
ไม่ใช่ "รายชื่อที่คนตรวจเลือกมา" — ด้วยเหตุผลเดียวกับที่ `clean_episodic.py` ใช้
`should_remember()` ตัวเดียวกับ gate ขาเข้า: **เกณฑ์เข้ากับเกณฑ์ออกต้องเป็นตัวเดียวกัน**
ไม่งั้นคลังจะเพี้ยนอีกในอนาคตด้วยเหตุผลใหม่ที่ไม่มีใครจำได้

หลักฐานบน prod 2026-08-03 (48 entry):
- 25 มาจาก `GUIDE.md` — ไฟล์อยู่ที่ repo root ไม่ใช่ `skills/` · ตรวจแล้ว **ซ้ำกับ
  `skills/*.md` ครบทั้ง 25 หัวข้อ ไม่มีความรู้ใหม่เลย** และเป็นฉบับ เม.ย. ที่ค่าเก่ากว่า
  (`GEMINI_MODEL=gemini-2.0-flash`, `OLLAMA_BASE_URL=http://host.docker.internal:11434`)
- 7 มาจาก `schemas.md` — **ไม่มีไฟล์นี้ในโปรเจกต์เลย** เนื้อหาเป็นเอกสารของ `skill-creator`
  (คนละระบบ): "This document defines the JSON schemas used by skill-creator"
- 16 ที่เหลือ = 1 ต่อ 1 กับ `skills/*.md` ที่ตรวจแล้วในข้อ 9
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from scripts.clean_skills_db import classify_entry, plan_cleanup, resync_summaries


@pytest.fixture
def skills_dir(tmp_path):
    d = tmp_path / "skills"
    d.mkdir()
    for name in ("deploy-cheatsheet.md", "troubleshooting.md"):
        (d / name).write_text("# หัวข้อ\n\nเนื้อหา\n", encoding="utf-8")
    return str(d)


class TestClassifyEntry:
    def test_keeps_entry_whose_md_exists(self, skills_dir):
        assert classify_entry({"source": "deploy-cheatsheet.md"}, skills_dir) == "keep"

    def test_keeps_when_source_omits_md_suffix(self, skills_dir):
        """prod เก็บทั้ง 2 แบบ: 'troubleshooting' กับ 'deploy-cheatsheet.md'"""
        assert classify_entry({"source": "troubleshooting"}, skills_dir) == "keep"

    def test_drops_entry_with_no_matching_file(self, skills_dir):
        assert classify_entry({"source": "schemas.md"}, skills_dir) == "orphan"

    def test_drops_entry_sourced_from_file_outside_skills_dir(self, skills_dir):
        """GUIDE.md อยู่ที่ repo root — ไม่ใช่ skill ที่ระบบดูแล"""
        assert classify_entry({"source": "GUIDE.md"}, skills_dir) == "orphan"

    def test_unparsable_entry_is_kept_not_dropped(self, skills_dir):
        """ความไม่แน่ใจต้องเอียงไปทาง conservative เสมอเมื่อสคริปต์ลบข้อมูล prod"""
        assert classify_entry("ไม่ใช่ dict", skills_dir) == "keep"
        assert classify_entry({}, skills_dir) == "keep"
        assert classify_entry({"source": ""}, skills_dir) == "keep"

    def test_path_traversal_in_source_is_not_treated_as_existing(self, skills_dir, tmp_path):
        """source ที่มี path ประกอบต้องไม่ไปแตะไฟล์นอก SKILLS_DIR"""
        (tmp_path / "outside.md").write_text("x", encoding="utf-8")
        assert classify_entry({"source": "../outside.md"}, skills_dir) == "orphan"


class TestPlanCleanup:
    def test_splits_keep_and_drop(self, skills_dir):
        db = {
            "A": {"source": "deploy-cheatsheet.md"},
            "B": {"source": "GUIDE.md"},
            "C": {"source": "schemas.md"},
            "D": {"source": "troubleshooting"},
        }
        keep, drop = plan_cleanup(db, skills_dir)
        assert set(keep) == {"A", "D"}
        assert set(drop) == {"B", "C"}

    def test_does_not_mutate_input(self, skills_dir):
        db = {"B": {"source": "GUIDE.md"}}
        plan_cleanup(db, skills_dir)
        assert "B" in db, "plan_cleanup ต้องไม่แก้ db ที่รับเข้ามา"

    def test_empty_db_is_safe(self, skills_dir):
        assert plan_cleanup({}, skills_dir) == ([], [])


class TestResyncSummaries:
    """`summary` เป็น snapshot ตอน ingest ไม่ใช่ pointer ไป .md — แก้ .md แล้วไม่ตามมา

    เจอจริงบน prod 2026-08-03: แก้ `GEMINI_MODEL=gemini-2.5-pro` ใน
    `skills/env-variables-reference.md` แล้ว แต่ `search_skills()` ยังฉีดค่าเก่าอยู่
    เพราะอ่านจาก `skills_db.json` คนละก๊อป — งานข้อ 9 จึงปิดครบแค่เส้น
    `load_skills_relevant()` (stable block) ส่วนเส้น semantic ยังค้าง
    """

    def test_rewrites_summary_from_current_md(self, skills_dir):
        p = os.path.join(skills_dir, "deploy-cheatsheet.md")
        with open(p, "w", encoding="utf-8") as f:
            f.write("# Deploy\n\nค่าใหม่ที่เพิ่งแก้ ยาวพอที่จะไม่ถูกมองว่าว่างเปล่า\n")
        db = {"Deploy": {"source": "deploy-cheatsheet.md", "summary": "ค่าเก่าที่ล้าสมัยแล้ว"}}

        changed = resync_summaries(db, skills_dir)

        assert changed == ["Deploy"]
        assert "ค่าใหม่ที่เพิ่งแก้" in db["Deploy"]["summary"]
        assert "ค่าเก่าที่ล้าสมัยแล้ว" not in db["Deploy"]["summary"]

    def test_reports_nothing_when_already_in_sync(self, skills_dir):
        db = {"A": {"source": "deploy-cheatsheet.md"}}
        resync_summaries(db, skills_dir)
        assert resync_summaries(db, skills_dir) == [], "รันซ้ำต้อง idempotent"

    def test_skips_entry_with_missing_file(self, skills_dir):
        db = {"X": {"source": "ไม่มีจริง.md", "summary": "เดิม"}}
        assert resync_summaries(db, skills_dir) == []
        assert db["X"]["summary"] == "เดิม", "ไฟล์หาย = ไม่แตะ ไม่ใช่เขียนทับด้วยค่าว่าง"

    def test_preserves_other_fields(self, skills_dir):
        db = {"A": {"source": "deploy-cheatsheet.md", "summary": "เก่า", "updated": "2026-01-01"}}
        resync_summaries(db, skills_dir)
        assert db["A"]["source"] == "deploy-cheatsheet.md"
        assert "updated" in db["A"]
