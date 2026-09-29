"""งานที่ไม่ต้อง embed ต้องไม่ล้มเพราะ EF conflict + collection ที่อ่านไม่ได้ต้องถูกรายงาน (`unreadable`) — ขั้น 5A 09-29

chromadb 1.5.9: ส่ง EF ชื่อต่างจากที่ persist → `ValueError(... Embedding function conflict ...)` (collection_configuration.py:781-798)
แต่ EF ชื่อ "default" (= ไม่ส่ง) ถูกข้ามการตรวจ (:791) · get/delete ไม่เรียก `_embed` · update embed เฉพาะเมื่อส่ง documents
⇒ cleanup / Dream Light / decay / prune / delete ตัวหลักใน dualvec ใช้ `get_collection_noembed` (client.get_collection(name))
เดิมทุกจุด `except Exception` → warning/debug แล้ว `continue` = "อ่านไม่ได้" หน้าตาเหมือน "ไม่มีอะไรต้องทำ"
(log prod ก.ค.–ส.ค. 269 ครั้ง · Dream Light ข้าม collection ทุกคืน)

ชื่อฟิลด์ `unreadable` (ไม่ใช่ `skipped` — ชื่อนั้นใช้แล้ว 2 ความหมาย: report "no memories in window" · decay นับ verified/no-meta)
"""
import logging
import os
import sys
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils.dream as dream
import utils.memory as um
import memory.dualvec as dv

OLD = (datetime.now() - timedelta(days=90)).isoformat()


class _Col:
    def __init__(self, ids, metas, docs=None):
        self.ids, self.metas = list(ids), list(metas)
        self.docs = docs or [f"doc {i}" for i in ids]
        self.deleted, self.updated = [], []

    def get(self, **k):
        return {"ids": self.ids, "metadatas": self.metas, "documents": self.docs}

    def delete(self, ids=None, **k):
        self.deleted.extend(ids or [])

    def update(self, ids=None, metadatas=None, documents=None, **k):
        assert documents is None, "decay ต้อง update แค่ metadata"
        self.updated.extend(ids or [])

    def count(self):
        return len(self.ids)

    def query(self, **k):
        return {"ids": [[]], "distances": [[]]}


class _Client:
    """ส่ง EF มา = โยน conflict เหมือน chromadb จริง · ชื่อใน `broken` = อ่านไม่ได้จริง (ไม่ขึ้นกับ EF)"""

    def __init__(self, cols: dict, broken=()):
        self.cols, self.broken, self.calls = cols, set(broken), []

    def list_collections(self):
        return [SimpleNamespace(name=n) for n in [*self.cols, *self.broken]]

    def get_collection(self, name, embedding_function=None, **k):
        self.calls.append((name, embedding_function is not None))
        if name in self.broken:
            raise RuntimeError("chroma 500 อ่าน collection นี้ไม่ได้")
        if embedding_function is not None:
            raise ValueError("Embedding function conflict: new: ollama vs persisted: default")
        return self.cols[name]


@pytest.fixture(autouse=True)
def _real_ef(monkeypatch):
    """ไม่ patch = EF เป็น None ในเครื่องเทส → wrapper ไม่ส่ง EF → conflict ไม่เกิด = เทสผ่านฟรี"""
    monkeypatch.setattr(um, "_get_embedding_function", lambda: object())


def _meta(**kw):
    return {"timestamp": OLD, "created_at": OLD, "last_accessed": OLD, "confidence": 0.1, "access_count": 0, **kw}


def test_กลุ่มควบคุม_wrapper_เดิมโยน_conflict_จริง():
    c = _Client({"memory_kwan": _Col(["a"], [_meta()])})
    with pytest.raises(ValueError, match="conflict"):
        um.get_collection(c, "memory_kwan")


def test_cleanup_ลบได้แม้_EF_conflict_และรายงาน_unreadable(monkeypatch, caplog):
    col = _Col(["old1"], [_meta()])
    c = _Client({"memory_kwan": col}, broken=["memory_ghost"])
    monkeypatch.setattr(um, "_get_client", lambda: c)
    monkeypatch.setattr(dv, "delete_keys", lambda *a, **k: True)
    with caplog.at_level(logging.ERROR):
        res = um.cleanup_old_memories(days=30)
    assert col.deleted == ["old1"] and res["deleted"] == 1
    assert list(res["unreadable"]) == ["memory_ghost"] and "500" in res["unreadable"]["memory_ghost"]
    assert any("memory_ghost" in r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR)


def test_light_sleep_อ่านได้แม้_EF_conflict_และเก็บ_unreadable(monkeypatch):
    now = datetime.now().isoformat()
    c = _Client({"memory_kwan": _Col(["m1"], [{"timestamp": now, "assistant": "k"}])}, broken=["memory_ghost"])
    monkeypatch.setattr(dream, "_get_client", lambda: c)
    unreadable: dict = {}
    got = dream.light_sleep(hours=24, unreadable=unreadable)
    assert [m["id"] for m in got] == ["m1"]
    assert list(unreadable) == ["memory_ghost"]


def test_decay_อัปเดตได้แม้_EF_conflict(monkeypatch):
    col = _Col(["d1"], [_meta(confidence=0.7)])
    c = _Client({"memory_kwan": col}, broken=["memory_ghost"])
    monkeypatch.setattr(dream, "_get_client", lambda: c)
    res = dream.memory_decay()
    assert col.updated == ["d1"] and res["decayed"] == 1
    assert list(res["unreadable"]) == ["memory_ghost"]


def test_prune_ลบได้แม้_EF_conflict(monkeypatch):
    col = _Col(["dead"], [_meta()])
    c = _Client({"memory_kwan": col}, broken=["memory_ghost"])
    monkeypatch.setattr(dream, "_get_client", lambda: c)
    monkeypatch.setattr(dv, "delete_keys", lambda *a, **k: True)
    res = dream.memory_prune(cap=500, max_age_days=30)
    assert col.deleted == ["dead"] and res["pruned"] == 1
    assert list(res["unreadable"]) == ["memory_ghost"]


def test_delete_with_keys_ลบตัวหลักได้แม้_EF_conflict(monkeypatch):
    col = _Col(["x"], [{}])
    c = _Client({"memory_kwan": col})
    monkeypatch.setattr(dv, "delete_keys", lambda *a, **k: True)
    dv.delete_with_keys(c, "memory_kwan", ["x"])
    assert col.deleted == ["x"]


def test_กลุ่มควบคุม_key_hits_ยังส่ง_EF(monkeypatch):
    """dualvec.py:131 ใช้ query_texts = ต้อง embed → ห้ามเปลี่ยนเป็น noembed (user สั่งห้ามแก้)"""
    c = _Client({"memory_kwan__keys": _Col(["k"], [{}])})
    dv.key_hits(c, "memory_kwan", "คำค้น")
    assert c.calls and c.calls[0] == ("memory_kwan__keys", True)


def test_dream_report_มี_unreadable_ของ_light(monkeypatch):
    def fake_light(hours=24, unreadable=None):
        unreadable["memory_ghost"] = "อ่านไม่ได้"
        return []
    monkeypatch.setattr(dream, "light_sleep", fake_light)
    monkeypatch.setattr(dream, "_save_report", lambda r: None, raising=False)
    report = dream.run_dream_cycle(hours=24)
    assert report["phase1_light"]["unreadable"] == {"memory_ghost": "อ่านไม่ได้"}
