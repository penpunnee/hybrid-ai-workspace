"""ฝั่ง `__keys` ต้องเคารพ `min_confidence`/`verified_only` และใช้ metadata *ของตัวหลัก* (audit 2026-09-24 MEDIUM)

เดิม `merge_max()` ฉีดรายการที่เจอจากกุญแจอย่างเดียวด้วย `confidence=0.7 verified=False` ตายตัว
⇒ memory ที่ Dream ลด confidence เหลือ 0.3 (หรือถูกลบตัวหลักไปแล้ว = กุญแจกำพร้า) โผล่กลับมาเป็น "🟡 probable"
"""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import memory.store as ms


def _col(primary_meta_for_k):
    col = MagicMock()
    col.query.return_value = {            # ตัวหลักไม่เจอ k (dilution) — เจอแต่ a
        "ids": [["a"]], "documents": [["doc a"]],
        "metadatas": [[{"confidence": 0.9, "verified": True}]], "distances": [[0.2]],
    }
    if primary_meta_for_k is None:        # ตัวหลักถูกลบไปแล้ว (กุญแจกำพร้า)
        col.get.return_value = {"ids": [], "documents": [], "metadatas": []}
    else:
        col.get.return_value = {"ids": ["k"], "documents": ["doc k"], "metadatas": [primary_meta_for_k]}
    return col


def _search(col, **kw):
    with patch.object(ms, "_get_chroma_client", return_value=MagicMock()), \
         patch("utils.memory.get_collection", return_value=col), \
         patch.object(ms, "bump_access_count"), \
         patch.object(ms, "key_hits", return_value=({"k": 0.95}, {"k": "คีย์ของ k"})):
        return ms.search_entries("kwan", "คำถาม", **kw)


def test_key_only_ต่ำกว่า_min_confidence_ต้องถูกตัด():
    out = _search(_col({"confidence": 0.3, "verified": False}), min_confidence=0.5)
    assert [r["id"] for r in out] == ["a"], [r["id"] for r in out]


def test_key_only_ไม่_verified_ต้องถูกตัดเมื่อ_verified_only():
    out = _search(_col({"confidence": 0.9, "verified": False}), verified_only=True)
    assert [r["id"] for r in out] == ["a"]


def test_key_only_ผ่านเกณฑ์_ต้องได้_confidence_จากตัวหลัก_ไม่ใช่_0_7():
    out = _search(_col({"confidence": 0.3, "verified": False}), min_confidence=0.0)
    k = next(r for r in out if r["id"] == "k")
    assert k["confidence"] == 0.3, "ค่าตายตัว 0.7 ทำให้ memory ที่ถูกลดขั้นโชว์เป็น probable"
    assert k["content"] == "doc k", "เนื้อควรเป็น doc เต็มของตัวหลัก ไม่ใช่ข้อความกุญแจ"


def test_กุญแจกำพร้า_ต้องไม่ถูกฉีด():
    out = _search(_col(None))
    assert [r["id"] for r in out] == ["a"], "ตัวหลักถูกลบแล้ว กุญแจที่ค้างต้องไม่พาเนื้อกลับมา"


def test_ตัวหลักคืน_ids_ไม่ครบ_ต้อง_zip_กับ_ids_ที่คืนมา_ไม่ใช่ที่ขอ():
    """กติกาก้อน 2: ผล `col.get(ids=…)` เรียงตาม insert และตัดตัวที่ไม่มีทิ้ง — zip กับ ids ที่ขอ
    = doc ของ k2 ไปติดอยู่ใต้ k1 (กุญแจกำพร้า) แล้ว k2 ตัวจริงหาย"""
    col = MagicMock()
    col.query.return_value = {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}
    col.get.return_value = {"ids": ["k2"], "documents": ["doc k2"], "metadatas": [{"confidence": 0.9, "verified": True}]}
    with patch.object(ms, "_get_chroma_client", return_value=MagicMock()), \
         patch("utils.memory.get_collection", return_value=col), \
         patch.object(ms, "bump_access_count"), \
         patch.object(ms, "key_hits", return_value=({"k1": 0.95, "k2": 0.90}, {"k1": "คีย์ k1", "k2": "คีย์ k2"})):
        out = ms.search_entries("kwan", "คำถาม")
    by_id = {r["id"]: r for r in out}
    assert "k1" not in by_id, f"k1 ไม่มีตัวหลักแล้ว ต้องไม่โผล่ ({by_id})"
    assert by_id["k2"]["content"] == "doc k2"
