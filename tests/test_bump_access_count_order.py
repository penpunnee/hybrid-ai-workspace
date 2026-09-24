"""`bump_access_count` ต้องจับคู่ metadata กับ id ที่ ChromaDB *คืนมา* ไม่ใช่ที่เราขอ

ที่มา (audit 2026-09-24 ข้อ 4): `col.get(ids=[...])` คืนรายการเรียงตาม row id ภายใน
(ลำดับ insert — `chromadb/segment/impl/metadata/sqlite.py` `.orderby(embeddings_t.id)`
และวัดจริงบน prod server 1.0.0: ขอ `[e,c,a]` ได้ `[a,c,e]`) เอกสาร Chroma ไม่รับประกัน
ลำดับเลย รับประกันแค่ว่า `ids[i]` คู่กับ `metadatas[i]` *ในคำตอบเดียวกัน*

โค้ดเดิม zip metadata ที่ได้กับ `doc_ids` ที่ขอ (ลำดับหลัง rank) แล้ว `update(ids=doc_ids)`
⇒ metadata ทั้งก้อน (created_at/confidence/access_count/…) สลับข้าม memory ทุกเทิร์นที่
recall ≥ 2 รายการ · บน prod 24/30 รายการ created_at ไม่ตรงกับเวลาที่ฝังใน id แล้ว

เทสเดิม `test_search_entries_bumps_access_count` fake `get()` คืนแต่ `metadatas` ไม่มี `ids`
จึงจับไม่ได้ — fake ที่นี่คืน ids สลับลำดับเหมือน prod และตรวจ *การจับคู่* ไม่ใช่แค่ "ถูกเรียก"
"""

from types import SimpleNamespace

import pytest

from memory import store


class _InsertionOrderCol:
    """Chroma ปลอมที่คืนผล get() เรียงตามลำดับ insert เสมอ (เหมือนของจริง)"""

    def __init__(self, rows: dict[str, dict]):
        self._rows = rows                      # insertion order = ลำดับ dict
        self.updates: list[tuple[list[str], list[dict]]] = []

    def get(self, ids=None, **k):
        want = set(ids or [])
        out_ids = [i for i in self._rows if i in want]
        return {"ids": out_ids, "metadatas": [dict(self._rows[i]) for i in out_ids]}

    def update(self, ids=None, metadatas=None, **k):
        self.updates.append((list(ids), [dict(m) for m in metadatas]))
        for i, m in zip(ids, metadatas):
            self._rows[i] = dict(m)


@pytest.fixture()
def col(monkeypatch):
    rows = {
        "a": {"tag": "a", "created_at": "2026-05-27T04:53:54", "access_count": 0},
        "b": {"tag": "b", "created_at": "2026-06-11T05:02:15", "access_count": 3},
        "c": {"tag": "c", "created_at": "2026-06-19T10:53:10", "access_count": 1},
    }
    c = _InsertionOrderCol(rows)
    client = SimpleNamespace(get_collection=lambda name: c)
    monkeypatch.setattr(store, "_get_chroma_client", lambda: client)
    monkeypatch.setattr("utils.memory.get_collection", lambda client, name: c)
    return c


def test_ขอสลับลำดับแล้ว_metadata_ต้องไม่สลับข้ามตัว(col):
    store.bump_access_count("kwan", ["c", "a"])     # ลำดับหลัง rank ≠ ลำดับ insert

    assert col.updates, "ต้องมีการ update"
    ids, metas = col.updates[0]
    for i, m in zip(ids, metas):
        assert m["tag"] == i, f"metadata ของ {m['tag']!r} ถูกเขียนทับลง id {i!r}"
    # ค่าเดิมของแต่ละตัวต้องยังอยู่กับเจ้าของ แค่ access_count +1
    assert col._rows["a"]["created_at"] == "2026-05-27T04:53:54"
    assert col._rows["c"]["created_at"] == "2026-06-19T10:53:10"
    assert col._rows["a"]["access_count"] == 1
    assert col._rows["c"]["access_count"] == 2
    assert col._rows["b"]["access_count"] == 3, "ตัวที่ไม่ได้ขอต้องไม่ถูกแตะ"


def test_id_ที่ไม่มีใน_collection_ต้องไม่ทำให้ตัวอื่นเพี้ยน(col):
    """ขอ 3 ได้กลับ 2 — ถ้า zip กับที่ขอ จะเลื่อนคู่ทั้งแถว"""
    store.bump_access_count("kwan", ["c", "ghost", "a"])

    ids, metas = col.updates[0]
    assert "ghost" not in ids
    for i, m in zip(ids, metas):
        assert m["tag"] == i
    assert col._rows["a"]["access_count"] == 1
    assert col._rows["c"]["access_count"] == 2


def test_ขอตัวเดียว_ยังทำงานเหมือนเดิม(col):
    """กลุ่มควบคุม — เคสที่โค้ดเดิมก็ถูกอยู่แล้ว ต้องไม่พังจากการแก้"""
    store.bump_access_count("kwan", ["b"])
    assert col._rows["b"]["access_count"] == 4
    assert "last_accessed" in col._rows["b"]
