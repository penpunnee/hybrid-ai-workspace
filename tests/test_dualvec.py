"""Tests for memory/dualvec.py — index 2 vector ต่อ 1 memory (backlog ข้อ 17)

ที่มา: embedding เป็นค่าเฉลี่ยของทั้งข้อความ → เก็บ "คำถาม+คำตอบ" เป็นก้อนเดียวแล้ว
ค้นด้วยคำถาม คำตอบที่ยาวกว่ากลบสัญญาณทิ้ง (วัดจริง: หัวข้ออย่างเดียว 0.913 → doc เต็ม 0.490)

⚠️ ทางที่ดูน่าจะใช่ — "index แค่กุญแจ" — **ตกไปแล้ว**: ทดสอบกับ ground truth 50 คู่
ได้ P=0.75 R=0.83 แย่กว่าเดิม เพราะ 3 เคสที่คำถามใหม่ไม่ตรงกับคำถามเดิมแต่ตรงกับ
*เนื้อคำตอบ* · ต้องเก็บทั้งสองแล้วเอา max (P=0.86 R=1.00)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.dualvec import key_text, keys_collection, merge_max


class TestKeyText:
    def test_extracts_question_from_qa_doc(self):
        assert key_text("Q: NAS ที่บ้านรุ่นอะไร\nA: เป็น Synology ครับ ยาวมาก...") == "NAS ที่บ้านรุ่นอะไร"

    def test_extracts_topic_from_lesson_doc(self):
        doc = "[บทเรียน: หาข้อมูลการสร้างหน้า ui แชทบอท]\nบทเรียนนี้แนะนำการเลือก Tech Stack"
        assert key_text(doc) == "หาข้อมูลการสร้างหน้า ui แชทบอท"

    def test_plain_fact_uses_identifier_stripped_form(self):
        """fact สั้นไม่มีโครง Q/A — ตัวที่กดคะแนนคือ 'ตัวระบุ' ไม่ใช่ความยาว

        วัดจริง: "Synology รุ่นไหน" ↔ "NAS ที่บ้านคือ Synology DS923+" = 0.578
        แต่ถอด DS923+ ออกแล้วได้ 0.791
        """
        k = key_text("NAS ที่บ้านคือ Synology DS923+")
        assert k is not None
        assert "DS923+" not in k
        assert "Synology" in k

    def test_returns_none_when_key_adds_nothing(self):
        """ข้อความที่ไม่มีทั้งโครง Q/A และตัวระบุ → กุญแจจะเหมือนเดิมเป๊ะ ไม่ต้องเก็บซ้ำ"""
        assert key_text("เราเตอร์ที่บ้านคือยี่ห้อเอซุส") is None

    def test_returns_none_for_blank(self):
        assert key_text("") is None
        assert key_text(None) is None

    def test_key_never_becomes_too_short_to_be_useful(self):
        """ถอดตัวระบุแล้วเหลือเศษ = กุญแจไร้ความหมาย ห้ามเก็บ"""
        assert key_text("DS923+ 192.168.51.49") is None

    def test_question_wins_over_identifier_stripping(self):
        """doc ที่มีทั้งโครง Q/A และตัวระบุ → ใช้คำถาม (สัญญาณแรงกว่ามาก)"""
        assert key_text("Q: NAS รุ่นอะไร\nA: Synology DS923+") == "NAS รุ่นอะไร"


class TestKeysCollection:
    def test_name_is_derived_and_stable(self):
        assert keys_collection("lessons") == "lessons__keys"
        assert keys_collection("memory_kwan") == "memory_kwan__keys"

    def test_does_not_double_suffix(self):
        assert keys_collection("lessons__keys") == "lessons__keys"


class TestMergeMax:
    def test_key_score_lifts_primary_hit(self):
        primary = [{"id": "a", "content": "doc a", "score": 0.49}]
        out = merge_max(primary, {"a": 0.91})
        assert out[0]["score"] == 0.91

    def test_primary_score_wins_when_higher(self):
        primary = [{"id": "a", "content": "doc a", "score": 0.80}]
        out = merge_max(primary, {"a": 0.20})
        assert out[0]["score"] == 0.80

    def test_key_only_hit_is_added(self):
        """เจอจากฝั่งกุญแจอย่างเดียว = เคสที่ dilution กลบจนหลุด top-N ของฝั่งเต็ม"""
        primary = [{"id": "a", "content": "doc a", "score": 0.70}]
        out = merge_max(primary, {"b": 0.88}, key_docs={"b": "doc b"})
        ids = [r["id"] for r in out]
        assert "b" in ids
        assert next(r for r in out if r["id"] == "b")["score"] == 0.88

    def test_key_only_hit_without_content_is_skipped(self):
        """ไม่มีเนื้อให้ฉีดเข้า context = เพิ่มเข้าไปก็ไร้ประโยชน์"""
        primary = [{"id": "a", "content": "doc a", "score": 0.70}]
        out = merge_max(primary, {"b": 0.88})
        assert [r["id"] for r in out] == ["a"]

    def test_result_is_sorted_by_score(self):
        primary = [{"id": "a", "content": "a", "score": 0.4},
                   {"id": "b", "content": "b", "score": 0.6}]
        out = merge_max(primary, {"a": 0.95})
        assert [r["id"] for r in out] == ["a", "b"]

    def test_no_duplicates(self):
        primary = [{"id": "a", "content": "a", "score": 0.4}]
        out = merge_max(primary, {"a": 0.95}, key_docs={"a": "a"})
        assert len(out) == 1

    def test_empty_inputs(self):
        assert merge_max([], {}) == []
        assert merge_max([{"id": "a", "content": "a", "score": 0.5}], {})[0]["score"] == 0.5


class TestStoreWiring:
    """ต่อสายเข้า memory/store.py — เขียนกุญแจตอน save, เอา max ตอน search"""

    def test_save_entry_writes_key(self):
        from unittest.mock import MagicMock, patch

        import memory.store as ms
        from memory.schema import MemoryEntry

        entry = MemoryEntry(content="Q: NAS ที่บ้านรุ่นอะไร\nA: Synology ครับ",
                            assistant="kwan", type="event")
        seen = {}
        with patch.object(ms, "_get_chroma_client", return_value=MagicMock()), \
             patch.object(ms, "_get_collection", return_value=MagicMock()), \
             patch.object(ms, "sync_key",
                          side_effect=lambda c, n, i, d, metadata=None: seen.update(col=n, doc=d)):
            ms.save_entry(entry)

        assert seen["col"] == "memory_kwan"
        assert seen["doc"] == entry.content

    def test_search_entries_lifts_score_from_key_hit(self):
        """หัวใจของข้อ 17 — doc ที่ถูก dilution กลบ ต้องกลับมาผ่านเกณฑ์ได้"""
        from unittest.mock import MagicMock, patch

        import memory.store as ms

        col = MagicMock()
        col.query.return_value = {
            "ids": [["a"]],
            "documents": [["Q: หาข้อมูลการสร้างหน้า ui แชทบอท\nA: ยาวมาก..."]],
            "metadatas": [[{"confidence": 0.9, "verified": False}]],
            "distances": [[0.51]],          # score 0.49 — ต่ำกว่าเกณฑ์ 0.55
        }
        with patch.object(ms, "_get_chroma_client", return_value=MagicMock()), \
             patch("utils.memory.get_collection", return_value=col), \
             patch.object(ms, "bump_access_count"), \
             patch.object(ms, "key_hits", return_value=({"a": 0.91}, {"a": "คีย์"})):
            out = ms.search_entries("kwan", "หาข้อมูลการสร้างหน้า ui แชทบอท")

        assert len(out) == 1, "เดิม doc นี้ถูกตัดทิ้งเพราะ 0.49 < 0.55"
        assert out[0]["score"] == 0.91

    def test_search_entries_still_filters_true_noise(self):
        """max ต้องไม่กลายเป็นประตูหลังให้ของไม่เกี่ยวหลุดเข้ามา"""
        from unittest.mock import MagicMock, patch

        import memory.store as ms

        col = MagicMock()
        col.query.return_value = {
            "ids": [["a"]],
            "documents": [["Q: เรื่องอื่นสิ้นเชิง\nA: ..."]],
            "metadatas": [[{"confidence": 0.99, "verified": True}]],
            "distances": [[0.80]],
        }
        with patch.object(ms, "_get_chroma_client", return_value=MagicMock()), \
             patch("utils.memory.get_collection", return_value=col), \
             patch.object(ms, "bump_access_count"), \
             patch.object(ms, "key_hits", return_value=({"a": 0.22}, {})):
            out = ms.search_entries("kwan", "คำถาม")

        assert out == []

    def test_search_entries_works_without_keys_collection(self):
        """ยังไม่ backfill = ต้องทำงานเหมือนเดิมเป๊ะ ไม่ใช่พัง"""
        from unittest.mock import MagicMock, patch

        import memory.store as ms

        col = MagicMock()
        col.query.return_value = {
            "ids": [["a"]],
            "documents": [["Q: อะไรสักอย่าง\nA: ..."]],
            "metadatas": [[{"confidence": 0.9, "verified": False}]],
            "distances": [[0.20]],
        }
        with patch.object(ms, "_get_chroma_client", return_value=MagicMock()), \
             patch("utils.memory.get_collection", return_value=col), \
             patch.object(ms, "bump_access_count"), \
             patch.object(ms, "key_hits", return_value=({}, {})):
            out = ms.search_entries("kwan", "คำถาม")

        assert len(out) == 1 and out[0]["score"] == 0.8

    def test_key_only_hit_survives_ranking(self):
        """รายการที่มาจากฝั่งกุญแจอย่างเดียวไม่มี field verified/confidence

        `_rank_results` อ่าน x["verified"] ตรงๆ → KeyError ทำให้ทั้ง search พัง
        (เส้นนี้เกิดเฉพาะตอน dilution กดจนหลุด top-N ของฝั่งเต็ม = เคสที่ตั้งใจจะกู้พอดี)
        """
        from unittest.mock import MagicMock, patch

        import memory.store as ms

        col = MagicMock()
        col.query.return_value = {
            "ids": [["a"]],
            "documents": [["Q: เรื่องอื่น\nA: ..."]],
            "metadatas": [[{"confidence": 0.9, "verified": False}]],
            "distances": [[0.90]],
        }
        with patch.object(ms, "_get_chroma_client", return_value=MagicMock()), \
             patch("utils.memory.get_collection", return_value=col), \
             patch.object(ms, "bump_access_count"), \
             patch.object(ms, "key_hits", return_value=({"zz": 0.93}, {"zz": "เนื้อจากกุญแจ"})):
            out = ms.search_entries("kwan", "คำถาม")

        assert [r["id"] for r in out] == ["zz"]
        assert out[0]["content"] == "เนื้อจากกุญแจ"


class TestLessonsWiring:
    def test_save_lesson_writes_key(self):
        from unittest.mock import MagicMock, patch

        import utils.memory as um

        seen = {}
        with patch.object(um, "_get_client", return_value=MagicMock()), \
             patch.object(um, "get_or_create_collection", return_value=MagicMock()), \
             patch("memory.dualvec.sync_key",
                   side_effect=lambda c, n, i, d, metadata=None: seen.update(col=n, doc=d)):
            assert um.save_lesson("หัวข้อทดสอบยาวพอ", "เนื้อบทเรียน") is True

        assert seen["col"] == "lessons"
        assert seen["doc"].startswith("[บทเรียน: หัวข้อทดสอบยาวพอ]")

    def test_get_lessons_lifts_diluted_lesson(self):
        """เคสจริงที่วัดได้: บทเรียนของคำถามนั้นเองได้ 0.490 เพราะเนื้อกลบหัวข้อ"""
        from unittest.mock import MagicMock, patch

        import utils.memory as um

        col = MagicMock()
        col.count.return_value = 1
        col.query.return_value = {
            "ids": [["L1"]],
            "documents": [["[บทเรียน: หาข้อมูลการสร้างหน้า ui แชทบอท]\nเนื้อยาว..."]],
            "distances": [[0.51]],          # 0.49 — ต่ำกว่าพื้น
        }
        with patch.object(um, "_get_client", return_value=MagicMock()), \
             patch.object(um, "get_or_create_collection", return_value=col), \
             patch("memory.dualvec.key_hits", return_value=({"L1": 0.91}, {"L1": "คีย์"})):
            out = um.get_lessons("หาข้อมูลการสร้างหน้า ui แชทบอท")

        assert "เนื้อยาว" in out, "ต้องได้บทเรียนเต็มคืนมา ไม่ใช่แค่ข้อความกุญแจ"

    def test_get_lessons_still_drops_noise(self):
        from unittest.mock import MagicMock, patch

        import utils.memory as um

        col = MagicMock()
        col.count.return_value = 1
        col.query.return_value = {
            "ids": [["L1"]],
            "documents": [["[บทเรียน: เรื่องอื่น]\nเนื้อ"]],
            "distances": [[0.85]],
        }
        with patch.object(um, "_get_client", return_value=MagicMock()), \
             patch.object(um, "get_or_create_collection", return_value=col), \
             patch("memory.dualvec.key_hits", return_value=({"L1": 0.20}, {})):
            assert um.get_lessons("คำถามคนละเรื่อง") == ""


class TestDeletionStaysInSync:
    def test_clean_episodic_deletes_keys_too(self):
        """กุญแจค้างหลังลบตัวหลัก = orphan ที่ยัง recall ขึ้นมาได้ทั้งที่ของจริงหายแล้ว"""
        from unittest.mock import MagicMock, patch

        from scripts.clean_episodic import delete_with_keys

        client, col = MagicMock(), MagicMock()
        client.get_collection.return_value = col
        with patch("memory.dualvec.delete_keys") as mock_dk:
            delete_with_keys(client, "memory_kwan", ["x", "y"])

        col.delete.assert_called_once_with(ids=["x", "y"])
        mock_dk.assert_called_once()
        assert mock_dk.call_args[0][2] == ["x", "y"]

    def test_no_ids_is_a_noop(self):
        from unittest.mock import MagicMock, patch

        from scripts.clean_episodic import delete_with_keys

        client = MagicMock()
        with patch("memory.dualvec.delete_keys") as mock_dk:
            delete_with_keys(client, "memory_kwan", [])
        client.get_collection.assert_not_called()
        mock_dk.assert_not_called()


class TestUserFactsWiring:
    """ต่อ dual-vector ให้ครบทุกเส้น — บทเรียนซ้ำของ audit นี้คือ 'แก้ 3 ใน 4 จุดแล้วคิดว่าจบ'"""

    def test_search_user_facts_uses_key_vector(self):
        from unittest.mock import MagicMock, patch

        import memory.store as ms

        col = MagicMock()
        col.query.return_value = {
            "ids": [["f1"]],
            "documents": [["เราเตอร์ที่บ้านคือ ASUS RT-BE92U"]],
            "metadatas": [[{"confidence": 0.95, "verified": True, "type": "fact",
                            "source": "user_taught"}]],
            "distances": [[0.45]],          # 0.55 — ต่ำกว่าเกณฑ์ 0.6 ของ user_facts
        }
        with patch.object(ms, "_get_chroma_client", return_value=MagicMock()), \
             patch("utils.memory.get_collection", return_value=col), \
             patch.object(ms, "key_hits", return_value=({"f1": 0.72}, {})):
            out = ms.search_user_facts("เราเตอร์ที่บ้านยี่ห้ออะไร")

        assert len(out) == 1
        assert out[0]["score"] == 0.72

    def test_search_user_facts_still_rejects_noise(self):
        from unittest.mock import MagicMock, patch

        import memory.store as ms

        col = MagicMock()
        col.query.return_value = {
            "ids": [["f1"]],
            "documents": [["เราเตอร์ที่บ้านคือ ASUS RT-BE92U"]],
            "metadatas": [[{"confidence": 0.95, "verified": True}]],
            "distances": [[0.90]],
        }
        with patch.object(ms, "_get_chroma_client", return_value=MagicMock()), \
             patch("utils.memory.get_collection", return_value=col), \
             patch.object(ms, "key_hits", return_value=({"f1": 0.17}, {})):
            assert ms.search_user_facts("อาหารเย็นกินอะไรดี") == []
