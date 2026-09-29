"""delete_keys ต้องไม่ทิ้งกุญแจกำพร้าเงียบๆ เมื่อ EF conflict — ต่อจากขั้น 5A (2026-09-29)

เดิม: เปิด collection เงาด้วย wrapper ที่ส่ง EF → conflict = ValueError → `except Exception` ตีความว่า "ไม่มีเงา" → คืน True
⇒ ตัวหลักถูกลบ กุญแจค้าง (กุญแจกำพร้าฉีดกลับเข้า context ได้ = ของที่ลบแล้วโผล่กลับ · เกิดจริง 07-13)
แก้: `get_collection_noembed` (delete ไม่ embed) · "ไม่มีเงา" = `chromadb.errors.NotFoundError` เท่านั้น (ลองบน prod แล้ว:
collection ที่ไม่มี → NotFoundError "Collection [...] does not exist") · error อื่น = ลบไม่สำเร็จ (คืน False + log)
"""
import logging
import os
import sys
from types import SimpleNamespace

import pytest
from chromadb.errors import NotFoundError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import memory.dualvec as dv
import utils.memory as um


class _Col:
    def __init__(self, fail_delete=False):
        self.deleted, self.fail_delete = [], fail_delete

    def delete(self, ids=None, **k):
        if self.fail_delete:
            raise RuntimeError("chroma 500 ตอนลบ")
        self.deleted.extend(ids or [])


class _Client:
    """ส่ง EF = conflict เหมือน chromadb จริง · open_error = error ตอนเปิด (ไม่ขึ้นกับ EF)"""

    def __init__(self, cols, open_error=None):
        self.cols, self.open_error = cols, open_error

    def get_collection(self, name, embedding_function=None, **k):
        if self.open_error is not None:
            raise self.open_error
        if embedding_function is not None:
            raise ValueError("Embedding function conflict: new: ollama vs persisted: default")
        if name not in self.cols:
            raise NotFoundError(f"Collection [{name}] does not exist")
        return self.cols[name]


@pytest.fixture(autouse=True)
def _real_ef(monkeypatch):
    """ไม่ patch = EF None ในเครื่องเทส → wrapper ไม่ส่ง EF → conflict ไม่เกิด = ผ่านฟรี"""
    monkeypatch.setattr(um, "_get_embedding_function", lambda: object())


def test_1_EF_conflict_ต้องลบกุญแจได้จริง():
    keys = _Col()
    c = _Client({"memory_kwan__keys": keys})
    assert dv.delete_keys(c, "memory_kwan", ["a", "b"]) is True
    assert keys.deleted == ["a", "b"], "เดิมคืน True โดยไม่ลบอะไร = กุญแจกำพร้า"


def test_2_ไม่มีเงาจริง_คืน_True_ไม่เตือน(caplog):
    with caplog.at_level(logging.WARNING, logger="memory.dualvec"):
        assert dv.delete_keys(_Client({}), "memory_new", ["x"]) is True
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_3_เปิดไม่ได้จริง_คืน_False_และ_log_ERROR(caplog):
    c = _Client({}, open_error=RuntimeError("chroma ต่อไม่ติด"))
    with caplog.at_level(logging.ERROR, logger="memory.dualvec"):
        assert dv.delete_keys(c, "memory_kwan", ["x"]) is False
    assert any("chroma ต่อไม่ติด" in r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR)


def test_4_ลบไม่สำเร็จ_คืน_False_และ_log_WARNING(caplog):
    c = _Client({"memory_kwan__keys": _Col(fail_delete=True)})
    with caplog.at_level(logging.WARNING, logger="memory.dualvec"):
        assert dv.delete_keys(c, "memory_kwan", ["x"]) is False
    assert any("500" in r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING)


def test_5_ทางรวม_delete_with_keys_ลบคู่กันไม่เหลือกำพร้า():
    main, keys = _Col(), _Col()
    c = _Client({"memory_kwan": main, "memory_kwan__keys": keys})
    dv.delete_with_keys(c, "memory_kwan", ["m1", "m2"])
    assert keys.deleted == ["m1", "m2"] and main.deleted == ["m1", "m2"]


def test_6_กลุ่มควบคุม_key_hits_ยังส่ง_EF():
    """query ต้อง embed → ห้ามใช้ noembed · fake โยน conflict เมื่อส่ง EF = key_hits คืนว่างแต่ไม่ใช่เพราะไม่ส่ง EF"""
    seen = []

    class Spy(_Client):
        def get_collection(self, name, embedding_function=None, **k):
            seen.append(embedding_function is not None)
            return SimpleNamespace(count=lambda: 0)

    dv.key_hits(Spy({}), "memory_kwan", "คำค้น")
    assert seen == [True]
