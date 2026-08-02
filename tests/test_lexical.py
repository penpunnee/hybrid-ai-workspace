"""Tests for memory/lexical.py — สัญญาณ lexical คู่กับ semantic (backlog ข้อ 16)

**ทำไมต้องมี:** semantic search จับตัวระบุ (รุ่น/รหัส/IP) ไม่ได้โดยธรรมชาติ —
วัดจริง สองประโยคที่ต่างกันแค่ชื่อรุ่นได้คะแนนกันเอง 0.496 · และคำถาม
"เราเตอร์ที่บ้านยี่ห้ออะไร" ↔ fact "เราเตอร์ที่บ้านคือ ASUS RT-BE92U" ได้แค่ 0.447
ทั้งที่**ซ้อนกันตรงๆ ที่คำว่า "เราเตอร์ที่บ้าน"** ซึ่งเป็นสิ่งที่ lexical จับได้ทันที

**ทำไมใช้ character n-gram:** ภาษาไทยไม่มีช่องว่างระหว่างคำ → tokenizer แบบง่ายใช้ไม่ได้
ใช้ *containment* (n-gram ของคำถามไปอยู่ใน doc กี่ส่วน) ไม่ใช่ Jaccard เพราะ doc
ยาวกว่าคำถามเสมอ Jaccard จะลงโทษฟรีๆ

**เกณฑ์ 0.50 มาจากการวัด** (ground truth 50 คู่เดิม):
    semantic 0.55 อย่างเดียว              P=0.89 R=0.89 F1=0.89
    OR lex>=0.45 / 0.50 / 0.60 / 0.70     P=0.90 R=1.00 F1=0.95  ← เท่ากันหมด
ที่ราบกว้าง 0.45-0.70 เพราะ **ค่าสูงสุดของกลุ่ม "ไม่ควรดึง" คือ 0.409** — อะไรที่สูงกว่านั้น
ไม่เพิ่ม false positive เลย (ต่างจาก dual-vector ที่จุดดีที่สุดกว้างแค่ 0.013 = overfit)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.lexical import LEXICAL_MIN_SCORE, lexical_score, passes_lexical


class TestLexicalScore:
    def test_identical_text_is_full_containment(self):
        assert lexical_score("เราเตอร์ที่บ้าน", "เราเตอร์ที่บ้าน") == 1.0

    def test_query_fully_inside_longer_doc(self):
        """หัวใจของข้อ 16 — คำถามซ้อนอยู่ใน fact แต่ semantic มองไม่เห็น"""
        s = lexical_score("เราเตอร์ที่บ้านยี่ห้ออะไร", "เราเตอร์ที่บ้านคือ ASUS RT-BE92U")
        assert s >= LEXICAL_MIN_SCORE, f"ต้องกู้เคสนี้ได้ (วัดจริงได้ 0.565) ได้ {s}"

    def test_unrelated_text_scores_zero(self):
        assert lexical_score("อาหารเย็นกินอะไรดี", "เราเตอร์ที่บ้านคือ ASUS RT-BE92U") == 0.0
        assert lexical_score("วันนี้อากาศเป็นไง", "เราเตอร์ที่บ้านคือ ASUS RT-BE92U") == 0.0

    def test_ignores_whitespace_differences(self):
        assert lexical_score("เราเตอร์ ที่ บ้าน", "เราเตอร์ที่บ้านคือเอซุส") == 1.0

    def test_containment_not_jaccard(self):
        """doc ยาวกว่าต้องไม่ถูกลงโทษ — ไม่งั้น fact ที่มีบริบทเยอะจะเสียเปรียบฟรีๆ"""
        short = lexical_score("เราเตอร์ที่บ้าน", "เราเตอร์ที่บ้าน")
        long = lexical_score("เราเตอร์ที่บ้าน", "เราเตอร์ที่บ้าน" + "ก" * 500)
        assert short == long == 1.0

    def test_short_query_does_not_crash(self):
        assert lexical_score("ก", "ข้อความอะไรสักอย่าง") == 0.0
        assert lexical_score("", "อะไรก็ได้") == 0.0
        assert lexical_score(None, None) == 0.0

    def test_score_is_bounded(self):
        for q, d in [("ทดสอบภาษาไทย", "ทดสอบภาษาไทยยาวมาก"), ("abc", "xyz")]:
            assert 0.0 <= lexical_score(q, d) <= 1.0


class TestPassesLexical:
    def test_uses_module_threshold(self):
        assert passes_lexical("เราเตอร์ที่บ้านยี่ห้ออะไร", "เราเตอร์ที่บ้านคือ ASUS RT-BE92U")
        assert not passes_lexical("อาหารเย็นกินอะไรดี", "เราเตอร์ที่บ้านคือ ASUS RT-BE92U")

    def test_threshold_sits_above_observed_noise(self):
        """0.409 = ค่าสูงสุดของคู่ 'ไม่ควรดึง' ที่วัดได้จริง — เกณฑ์ต้องสูงกว่านั้น"""
        assert LEXICAL_MIN_SCORE > 0.409

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("LEXICAL_MIN_SCORE", "0.9")
        import importlib

        import memory.lexical as ml
        importlib.reload(ml)
        assert ml.LEXICAL_MIN_SCORE == 0.9
        assert not ml.passes_lexical("เราเตอร์ที่บ้านยี่ห้ออะไร", "เราเตอร์ที่บ้านคือ ASUS")
        monkeypatch.delenv("LEXICAL_MIN_SCORE")
        importlib.reload(ml)


class TestOrGateWiring:
    """OR-gate: ผ่าน semantic **หรือ** lexical ก็พอ — ต้องต่อครบทุกเส้นค้น

    บทเรียนซ้ำของ audit นี้: แก้ 3 ใน 4 จุดแล้วคิดว่าจบ (โดนมาแล้วทั้ง Thai embedding
    3 รอบ, "query โดยไม่ดู distances" 4 โมดูล, และ dual-vector รอบที่แล้ว)
    """

    FACT = "เราเตอร์ที่บ้านคือ ASUS RT-BE92U"
    Q = "เราเตอร์ที่บ้านยี่ห้ออะไร"

    def _col(self, doc, dist):
        from unittest.mock import MagicMock

        col = MagicMock()
        col.count.return_value = 1
        col.query.return_value = {
            "ids": [["f1"]], "documents": [[doc]],
            "metadatas": [[{"confidence": 0.95, "verified": True}]],
            "distances": [[dist]],
        }
        return col

    def test_user_facts_rescued_by_lexical(self):
        """เคสที่ปิดข้อ 16 — semantic 0.447 ตกเกณฑ์ แต่ lexical 0.565 กู้ได้"""
        from unittest.mock import MagicMock, patch

        import memory.store as ms

        with patch.object(ms, "_get_chroma_client", return_value=MagicMock()), \
             patch("utils.memory.get_collection", return_value=self._col(self.FACT, 0.553)), \
             patch.object(ms, "key_hits", return_value=({}, {})):
            out = ms.search_user_facts(self.Q)

        assert len(out) == 1, "semantic 0.447 < 0.6 แต่ lexical ต้องกู้ได้"

    def test_user_facts_noise_still_rejected(self):
        from unittest.mock import MagicMock, patch

        import memory.store as ms

        with patch.object(ms, "_get_chroma_client", return_value=MagicMock()), \
             patch("utils.memory.get_collection", return_value=self._col(self.FACT, 0.90)), \
             patch.object(ms, "key_hits", return_value=({}, {})):
            assert ms.search_user_facts("อาหารเย็นกินอะไรดี") == []

    def test_search_entries_rescued_by_lexical(self):
        from unittest.mock import MagicMock, patch

        import memory.store as ms

        doc = "Q: เราเตอร์ที่บ้านยี่ห้ออะไร\nA: " + "ก" * 300
        with patch.object(ms, "_get_chroma_client", return_value=MagicMock()), \
             patch("utils.memory.get_collection", return_value=self._col(doc, 0.60)), \
             patch.object(ms, "key_hits", return_value=({}, {})), \
             patch.object(ms, "bump_access_count"):
            out = ms.search_entries("kwan", self.Q)

        assert len(out) == 1, "semantic 0.40 ตกเกณฑ์ แต่คำถามซ้อนใน doc เต็มๆ"

    def test_get_lessons_rescued_by_lexical(self):
        from unittest.mock import MagicMock, patch

        import utils.memory as um

        col = self._col("[บทเรียน: เราเตอร์ที่บ้านยี่ห้ออะไร]\n" + "ก" * 300, 0.60)
        with patch.object(um, "_get_client", return_value=MagicMock()), \
             patch.object(um, "get_or_create_collection", return_value=col), \
             patch("memory.dualvec.key_hits", return_value=({}, {})):
            assert um.get_lessons(self.Q) != ""

    def test_get_lessons_noise_still_rejected(self):
        from unittest.mock import MagicMock, patch

        import utils.memory as um

        col = self._col("[บทเรียน: เรื่องคนละโลก]\nเนื้อหาอื่น", 0.85)
        with patch.object(um, "_get_client", return_value=MagicMock()), \
             patch.object(um, "get_or_create_collection", return_value=col), \
             patch("memory.dualvec.key_hits", return_value=({}, {})):
            assert um.get_lessons("อาหารเย็นกินอะไรดี") == ""
