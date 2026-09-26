"""full-sync ของ skills index ต้องไม่ลบ skill ที่เพิ่งบันทึกระหว่าง sync (audit 2026-09-24 MEDIUM)

`sync_from_db(db)` = upsert + **ลบ id ที่ไม่มีใน db ที่ส่งมา** · ผู้เรียก 4 จุด (`save_skill` · dream · accept_proposal ·
admin) ส่ง snapshot ที่อ่านไว้*ก่อน* → writer ที่บันทึกระหว่างช่องนี้ถูกลบออกจาก `skills_collection` ทั้งที่ไฟล์มี
วัด prod 09-26: embed 22 skill = 0.56s warm / **6.73s cold** > `SKILLS_DB_LOCK_TIMEOUT` 5s ⇒ ย้าย sync ทั้งก้อนเข้า lock
ไม่ได้ (writer จะได้ SkillsDbLocked = บันทึกหาย) → แก้ที่ `sync_from_db`: reload+ลบ stale ใต้ lock (ms) · upsert นอก lock ·
`save_skill` upsert รายการเดียว (1 embed แทน 22 · ไม่มีขั้นลบ)
"""
import json
import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils.skills as sk
import utils.skills_search as ss


@pytest.fixture
def db_file(tmp_path, monkeypatch):
    p = tmp_path / "skills_db.json"
    monkeypatch.setattr(sk, "SKILLS_DB_PATH", str(p))
    return p


def _search_with(col):
    search = MagicMock()
    search.available = True
    search.collection = col
    search._skill_id = ss.SkillsSearch._skill_id
    search.add_skills_from_db = lambda db: ss.SkillsSearch.add_skills_from_db(search, db)
    search.add_skill = lambda **kw: ss.SkillsSearch.add_skill(search, **kw)
    search.sync_from_db = lambda db: ss.SkillsSearch.sync_from_db(search, db)
    return search


def test_skill_ที่บันทึกหลัง_snapshot_ต้องไม่ถูกลบ(db_file):
    """ลำดับจริง: caller อ่าน db (snapshot ไม่มี `new`) → writer save ไฟล์ + upsert `skill_new` → caller sync ด้วย snapshot เก่า"""
    db_file.write_text(json.dumps({"old": {"summary": "x"}, "new": {"summary": "เพิ่งบันทึก"}}), encoding="utf-8")
    col = MagicMock()
    col.get.return_value = {"ids": ["skill_old", "skill_new", "skill_ghost"]}
    search = _search_with(col)
    search.sync_from_db({"old": {"summary": "x"}})          # snapshot เก่า ไม่มี new
    deleted = [i for c in col.delete.call_args_list for i in c.kwargs.get("ids", [])]
    assert "skill_ghost" in deleted, "ของที่ไม่มีทั้งใน snapshot และไฟล์ ยังต้องถูกลบ"
    assert "skill_new" not in deleted, f"skill ที่อยู่ในไฟล์แล้วห้ามถูกลบเพราะ snapshot เก่า ({deleted})"


def test_ลบ_stale_ต้องอยู่ใต้_lock_แต่_upsert_ต้องอยู่นอก_lock(db_file):
    db_file.write_text(json.dumps({"a": {"summary": "x"}}), encoding="utf-8")
    col = MagicMock()
    col.get.return_value = {"ids": ["skill_a", "skill_ghost"]}
    depth_at = {}
    col.delete.side_effect = lambda **kw: depth_at.setdefault("delete", sk._db_depth)
    col.upsert.side_effect = lambda **kw: depth_at.setdefault("upsert", sk._db_depth)
    search = _search_with(col)
    search.sync_from_db({"a": {"summary": "x"}})
    assert depth_at.get("delete", 0) > 0, "ขั้นลบต้องถือ _db_transaction (กัน writer แทรกระหว่าง reload กับ delete)"
    assert depth_at.get("upsert", 1) == 0, "ขั้น upsert (embed ผ่าน Ollama 0.6-6.7s) ห้ามถือ lock — writer จะชน timeout 5s"


def test_save_skill_ต้อง_upsert_รายการเดียว_ไม่เรียก_full_sync(db_file, monkeypatch):
    db_file.write_text("{}", encoding="utf-8")
    search = MagicMock()
    search.available = True
    search.sync_from_db.side_effect = AssertionError("save_skill ห้ามเรียก full sync (22 embed + ขั้นลบ) ต่อการบันทึก 1 รายการ")
    monkeypatch.setattr(ss, "get_skills_search", lambda: search)
    ok = sk.save_skill("docker compose restart policy", "ใช้ restart: always กับ backend-watchdog กันคอนเทนเนอร์หาย", source="t")
    assert ok is True
    assert search.add_skill.call_count == 1
    assert search.add_skill.call_args.kwargs["topic"] == "docker compose restart policy"
    assert json.loads(db_file.read_text(encoding="utf-8"))["docker compose restart policy"]["source"] == "t"


def test_เทสเดิม_ยังจริง_ลบของที่ไม่มีทั้งสองที่(db_file, monkeypatch):
    """กลุ่มควบคุมของ test_skills_sync_delete: ไฟล์ว่าง + snapshot {a,b} → ghost ต้องถูกลบ · a/b ไม่ถูกลบ"""
    db_file.write_text("{}", encoding="utf-8")
    col = MagicMock()
    col.get.return_value = {"ids": ["skill_a", "skill_b", "skill_ghost"]}
    search = _search_with(col)
    monkeypatch.setattr(ss, "get_skills_search", lambda: search)
    ss.sync_skills_to_search({"a": {"summary": "x"}, "b": {"summary": "y"}})
    deleted = [i for c in col.delete.call_args_list for i in c.kwargs.get("ids", [])]
    assert deleted == ["skill_ghost"], deleted
