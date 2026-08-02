"""Test: sync_skills_to_search ต้องลบ skill ที่หายไปจาก skills_db ออกจาก index ด้วย

บั๊กจริง (2026-08-02): ชื่อว่า sync แต่ `add_skills_from_db()` มีแต่ upsert
ไม่เคยลบ → ลบ skill ออกจาก skills_db.json แล้วมันยังค้างอยู่ใน ChromaDB ตลอดไป
และยังถูกดึงเข้า context ต่อ (เจอตอนล้าง Dream skills 60 อัน: ไฟล์เหลือ 52
แต่ search index ยังมี 128)
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from unittest.mock import MagicMock
import utils.skills_search as ss


def test_sync_removes_skills_deleted_from_db(monkeypatch):
    col = MagicMock()
    # index เดิมมี 3 ตัว แต่ db เหลือ 2 → ต้องลบตัวที่หายไป
    col.get.return_value = {"ids": ["skill_a", "skill_b", "skill_ghost"]}
    search = MagicMock()
    search.available = True
    search.collection = col
    # ผูกเมธอดจริงเข้ากับ mock — ต้องผูก _skill_id ด้วย ไม่งั้น self._skill_id
    # จะคืน MagicMock แทน string ทำให้ set เทียบไม่ตรงแล้วลบหมดทุกตัว
    search._skill_id = ss.SkillsSearch._skill_id
    real = ss.SkillsSearch.sync_from_db
    search.sync_from_db = lambda db: real(search, db)
    monkeypatch.setattr(ss, "get_skills_search", lambda: search)

    ss.sync_skills_to_search({"a": {"summary": "x"}, "b": {"summary": "y"}})

    deleted = [c.kwargs.get("ids") for c in col.delete.call_args_list]
    assert deleted, "ต้องเรียก delete สำหรับ id ที่หายไปจาก db"
    assert "skill_ghost" in deleted[0]
    assert "skill_a" not in deleted[0], "ตัวที่ยังอยู่ใน db ห้ามถูกลบ"
