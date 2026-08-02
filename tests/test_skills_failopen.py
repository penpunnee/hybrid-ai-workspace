"""Tests สำหรับ `utils.skills.search_skills()` — ChromaDB ล่มต้องคืนว่าง ไม่ใช่เทคลัง

ทำไมสำคัญ: `search_skills()` ถูกเรียกทุกเทิร์นใน `routers/chat.py` (volatile block)
เดิมมี fail-open 2 เส้น — `search.available == False` และ `except Exception` —
ทั้งคู่ `return get_all_skills()` = ยัด **ทั้งคลัง** เข้า context แทนที่จะคืนว่าง

วัดบน prod 2026-08-03: 22 รายการ = **7,455 chars ≈ 1,863 tokens ต่อเทิร์น**
(ตัวเลข 48 ในบันทึกเก่าล้าสมัยตั้งแต่ปิดข้อ 18) และ context ไม่มี cap ยกเว้นเส้น ollama
ที่ตัดที่ 2,000 chars → บนเส้นนั้นการเทคลังยัง**เบียด home tool ข้อมูลจริง + citations ตกท้าย**

ทิศที่ถูกคือ conservative: ไม่รู้ → ไม่ฉีด · ความรู้ยังเข้าทาง `load_skills_relevant()`
(อ่าน .md จากดิสก์ตรงๆ ไม่ผ่าน ChromaDB) ซึ่งเป็นคนละเส้นและไม่ได้พังไปด้วย
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import utils.skills as skills


@pytest.fixture
def loaded_db(monkeypatch):
    """คลัง skill ที่ 'ใหญ่พอจะสังเกตได้' ถ้าหลุดออกมาทั้งก้อน"""
    db = {f"topic-{i}": {"summary": f"เนื้อหาของ skill {i}"} for i in range(20)}
    monkeypatch.setattr(skills, "_load_skills_db", lambda: db)
    return db


class _FakeSearch:
    def __init__(self, available=True, results=None, raises=False):
        self.available = available
        self._results = results or []
        self._raises = raises

    def search(self, query, n_results=3):
        if self._raises:
            raise RuntimeError("chroma down")
        return self._results


def _patch_search(monkeypatch, fake):
    """แทน utils.skills_search.get_skills_search ที่ search_skills import ตอนเรียก"""
    import utils.skills_search as ss
    monkeypatch.setattr(ss, "get_skills_search", lambda: fake)


def test_returns_empty_when_search_unavailable(monkeypatch, loaded_db):
    _patch_search(monkeypatch, _FakeSearch(available=False))
    out = skills.search_skills("อะไรก็ได้")
    assert out == "", f"fail-open: คืนมา {len(out)} chars แทนที่จะเป็นค่าว่าง"


def test_returns_empty_when_search_raises(monkeypatch, loaded_db):
    _patch_search(monkeypatch, _FakeSearch(raises=True))
    out = skills.search_skills("อะไรก็ได้")
    assert out == "", f"fail-open: คืนมา {len(out)} chars แทนที่จะเป็นค่าว่าง"


def test_failopen_does_not_leak_whole_db(monkeypatch, loaded_db):
    """เจาะจงกว่า assert ว่าว่าง — ต้องไม่มีหัวข้อไหนของคลังโผล่ออกมาเลย"""
    for fake in (_FakeSearch(available=False), _FakeSearch(raises=True)):
        _patch_search(monkeypatch, fake)
        out = skills.search_skills("อะไรก็ได้")
        assert "topic-0" not in out and "[ความรู้ที่สะสมไว้]" not in out


def test_normal_path_still_returns_top_results(monkeypatch, loaded_db):
    _patch_search(monkeypatch, _FakeSearch(results=[
        {"topic": "deploy", "summary": "วิธี deploy", "category": "ops"},
        {"topic": "network", "summary": "ผังเน็ตบ้าน"},
    ]))
    out = skills.search_skills("deploy ยังไง")
    assert "[ความรู้ที่เกี่ยวข้องกับคำถาม]" in out
    assert "deploy" in out and "network" in out
    assert "หมวดหมู่: ops" in out
    assert "topic-0" not in out          # ไม่ปน entry อื่นจากคลัง


def test_no_results_returns_empty(monkeypatch, loaded_db):
    _patch_search(monkeypatch, _FakeSearch(results=[]))
    assert skills.search_skills("ไม่มีอะไรตรง") == ""


def test_agent_skill_search_tool_does_not_dump_db(monkeypatch, loaded_db):
    """tool `skill_search` ของ agent ใช้ฟังก์ชันเดียวกัน — ต้องไม่เทคลังใส่โมเดลเช่นกัน"""
    _patch_search(monkeypatch, _FakeSearch(available=False))
    from agents.tools import execute_tool
    out = execute_tool("skill_search", {"query": "อะไรก็ได้"})
    assert "topic-0" not in str(out)
