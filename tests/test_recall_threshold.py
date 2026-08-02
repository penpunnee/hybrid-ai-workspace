"""Tests สำหรับพื้นความเกี่ยวข้องของ recall (backlog ข้อ 3 + 4)

เกณฑ์ 0.55 **ไม่ได้เดา** — มาจาก ground truth 50 คู่ที่คนมาร์ค จากคำถามจริงบน prod
25 ข้อ (`scripts/recall_groundtruth.py`, ข้อ 12):

    เกณฑ์ 0.40 → P=0.62 R=1.00 F1=0.77
    เกณฑ์ 0.55 → P=0.89 R=0.89 F1=0.89
    เกณฑ์ 0.60 → P=0.94 R=0.89 F1=0.91
    เกณฑ์ 0.80 → P=1.00 R=0.17 F1=0.29

เลือก 0.55 ไม่ใช่ 0.57/0.60 ที่ F1 สูงกว่าเล็กน้อย เพราะเอียงไปทาง recall โดยตั้งใจ:
"AI ลืมสิ่งที่เคยคุย" ผู้ใช้รู้สึกแย่กว่าการมี context เกินมาหนึ่งชิ้น · ทดสอบความ
ทนทานแล้ว (พลิก label ที่ไม่มั่นใจครบ 64 กรณี) เกณฑ์ที่ดีที่สุดอยู่ในช่วง 0.525-0.65 เสมอ
"""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))



def _fake_collection(docs_with_dist):
    col = MagicMock()
    col.count.return_value = len(docs_with_dist)
    col.query.return_value = {
        "ids": [[f"id{i}" for i in range(len(docs_with_dist))]],
        "documents": [[d for d, _ in docs_with_dist]],
        "metadatas": [[{"confidence": 0.9, "verified": False, "timestamp": ""}
                       for _ in docs_with_dist]],
        "distances": [[dist for _, dist in docs_with_dist]],
    }
    return col


class TestUtilsMemoryThreshold:
    """`utils/memory.py` — 3 ฟังก์ชันนี้เดิม query แล้วคืน top-N โดยไม่เคยดู distances เลย"""

    def test_search_memory_drops_irrelevant(self):
        import utils.memory as um

        col = _fake_collection([("เกี่ยวจริง", 0.30), ("ไม่เกี่ยว", 0.70)])
        with patch.object(um, "_get_collection", return_value=col):
            out = um.search_memory("kwan", "คำถาม")

        assert "เกี่ยวจริง" in out
        assert "ไม่เกี่ยว" not in out, "score 0.30 ต่ำกว่าพื้น 0.55 ต้องถูกตัด"

    def test_search_memory_returns_empty_when_all_irrelevant(self):
        import utils.memory as um

        col = _fake_collection([("ไม่เกี่ยวเลย", 0.95)])
        with patch.object(um, "_get_collection", return_value=col):
            assert um.search_memory("kwan", "คำถาม") == ""

    def test_get_lessons_drops_irrelevant(self):
        import utils.memory as um

        col = _fake_collection([("บทเรียนที่เกี่ยว", 0.20), ("บทเรียนที่ไม่เกี่ยว", 0.80)])
        with patch.object(um, "_get_client", return_value=MagicMock()), \
             patch.object(um, "get_or_create_collection", return_value=col):
            out = um.get_lessons("คำถาม")

        assert "บทเรียนที่เกี่ยว" in out
        assert "บทเรียนที่ไม่เกี่ยว" not in out

    def test_get_lessons_without_query_is_unfiltered(self):
        """เรียกแบบไม่มี query = ขอดูทั้งคลัง ไม่ใช่การค้น — ไม่มีคะแนนให้กรอง"""
        import utils.memory as um

        col = MagicMock()
        col.count.return_value = 2
        col.get.return_value = {"documents": ["บทเรียน ก", "บทเรียน ข"]}
        with patch.object(um, "_get_client", return_value=MagicMock()), \
             patch.object(um, "get_or_create_collection", return_value=col):
            out = um.get_lessons("")

        assert "บทเรียน ก" in out and "บทเรียน ข" in out

    def test_search_long_term_memory_drops_irrelevant(self):
        import utils.memory as um

        col = _fake_collection([("ธีมที่เกี่ยว", 0.10), ("ธีมที่ไม่เกี่ยว", 0.90)])
        with patch.object(um, "_get_client", return_value=MagicMock()), \
             patch.object(um, "get_or_create_collection", return_value=col):
            out = um.search_long_term_memory("คำถาม")

        assert "ธีมที่เกี่ยว" in out
        assert "ธีมที่ไม่เกี่ยว" not in out


class TestStoreThreshold:
    """`memory/store.py` — คำนวณ score อยู่แล้วแต่ไม่มีพื้นขั้นต่ำ (ข้อ 4)"""

    def test_search_entries_drops_low_score_even_when_confidence_high(self):
        import memory.store as ms

        col = MagicMock()
        col.query.return_value = {
            "ids": [["a", "b"]],
            "documents": [["เกี่ยวจริง", "มั่นใจสูงแต่ไม่เกี่ยว"]],
            "metadatas": [[{"confidence": 0.5, "verified": False},
                           {"confidence": 0.99, "verified": True}]],
            "distances": [[0.30, 0.80]],
        }
        with patch.object(ms, "_get_chroma_client", return_value=MagicMock()), \
             patch("utils.memory.get_collection", return_value=col), \
             patch.object(ms, "bump_access_count"):
            out = ms.search_entries("kwan", "คำถาม")

        contents = [r["content"] for r in out]
        assert "เกี่ยวจริง" in contents
        assert "มั่นใจสูงแต่ไม่เกี่ยว" not in contents, \
            "confidence สูงต้องไม่ช่วยให้ของที่ไม่เกี่ยวหลุดขึ้นมา"

    def test_search_long_term_drops_low_score(self):
        import memory.store as ms

        col = MagicMock()
        col.query.return_value = {
            "documents": [["ธีมที่เกี่ยว", "ธีมที่ไม่เกี่ยว"]],
            "metadatas": [[{"confidence": 0.9}, {"confidence": 0.9}]],
            "distances": [[0.20, 0.90]],
        }
        with patch.object(ms, "_get_chroma_client", return_value=MagicMock()), \
             patch("utils.memory.get_collection", return_value=col):
            out = ms.search_long_term("คำถาม")

        contents = [r["content"] for r in out]
        assert contents == ["ธีมที่เกี่ยว"]


class TestThresholdValueIsShared:
    def test_all_call_sites_use_one_constant(self):
        """เกณฑ์เดียวกันต้องมาจากที่เดียว — ไม่งั้นแก้ทีหลังจะหลุดบางจุด

        `store.py` ต้อง *อ่านจาก* `utils.memory` ไม่ใช่ประกาศค่าของตัวเองซ้ำ
        (ประกาศซ้ำ = สิ่งที่เทสนี้ตั้งใจจะกัน ไม่ใช่สิ่งที่ต้องการ)
        """
        import memory.store as ms
        import utils.memory as um

        assert ms._recall_min_score() == um.RECALL_MIN_SCORE
        assert 0.5 <= um.RECALL_MIN_SCORE <= 0.65, "ช่วงที่ ground truth รองรับ"

    def test_env_override(self, monkeypatch):
        """ปรับได้โดยไม่ต้องแก้โค้ด — จะได้ทดลองกับข้อมูลจริงในอนาคต"""
        monkeypatch.setenv("RECALL_MIN_SCORE", "0.42")
        import importlib

        import utils.memory as um
        importlib.reload(um)
        assert um.RECALL_MIN_SCORE == 0.42
        monkeypatch.delenv("RECALL_MIN_SCORE")
        importlib.reload(um)
