"""Tests for User Facts shared memory

หลักการ: user_taught memory (จำไว้ว่า / prefer / note) ต้องบันทึกลง
user_facts collection (shared) ไม่ใช่ memory_{slug} (per-assistant)
และ recall() ต้องดึง user_facts ได้ทุก assistant ไม่ว่าจะสอนจาก assistant ไหน
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch, MagicMock, call
from memory.teach import process_teaching
from memory.store import search_user_facts
from memory.operations import recall


class TestTeachSavesToUserFacts:
    def test_fact_saves_to_user_facts_collection(self):
        saved = {}

        def mock_save(entry, collection_name=None):
            saved["collection"] = collection_name
            saved["content"] = entry.content
            return True

        with patch("memory.teach.save_entry", side_effect=mock_save):
            process_teaching("kwan", "จำไว้ว่า ปอยชอบ dark mode")

        assert saved["collection"] == "user_facts"

    def test_preference_saves_to_user_facts_collection(self):
        saved = {}

        def mock_save(entry, collection_name=None):
            saved["collection"] = collection_name
            return True

        with patch("memory.teach.save_entry", side_effect=mock_save):
            process_teaching("fa", "prefer ตอบกระชับ ไม่ใช้ bullet เยอะ")

        assert saved["collection"] == "user_facts"

    def test_correction_saves_to_user_facts_collection(self):
        saved = {}

        def mock_save(entry, collection_name=None):
            saved["collection"] = collection_name
            return True

        with patch("memory.teach.save_entry", side_effect=mock_save):
            process_teaching("kwan", "ที่ถูกต้องคือ port 8000 ไม่ใช่ 8080", "ตอบผิด")

        assert saved["collection"] == "user_facts"

    def test_regular_remember_still_uses_slug_collection(self):
        from memory.operations import remember

        saved = {}

        def mock_save(entry, collection_name=None):
            saved["collection"] = collection_name
            return True

        with patch("memory.operations.save_entry", side_effect=mock_save):
            remember("kwan", "คำถาม", "คำตอบ")

        assert saved["collection"] is None  # default → memory_{slug}


class TestSearchUserFacts:
    def test_search_user_facts_queries_correct_collection(self):
        mock_client = MagicMock()
        mock_col = MagicMock()
        mock_client.get_collection.return_value = mock_col
        mock_col.query.return_value = {
            "documents": [["ปอยชอบ dark mode"]],
            "metadatas": [[{"confidence": 0.95, "verified": True, "type": "fact", "source": "user_taught"}]],
            "distances": [[0.05]],
        }

        with patch("memory.store._get_chroma_client", return_value=mock_client):
            results = search_user_facts("dark mode")

        mock_client.get_collection.assert_called_with("user_facts")
        assert len(results) == 1
        assert "dark mode" in results[0]["content"]

    def test_search_user_facts_returns_empty_when_collection_missing(self):
        mock_client = MagicMock()
        mock_client.get_collection.side_effect = Exception("not found")

        with patch("memory.store._get_chroma_client", return_value=mock_client):
            results = search_user_facts("anything")

        assert results == []

    def test_low_score_entry_is_filtered_out(self):
        """distance=0.5 → score=0.5 < threshold 0.6 → ต้องไม่คืนผล"""
        mock_client = MagicMock()
        mock_col = MagicMock()
        mock_client.get_collection.return_value = mock_col
        mock_col.query.return_value = {
            "documents": [["ข้อมูลที่ไม่เกี่ยวข้อง"]],
            "metadatas": [[{"confidence": 0.95, "type": "fact", "source": "user_taught"}]],
            "distances": [[0.5]],  # score = 1 - 0.5 = 0.5 < 0.6
        }

        with patch("memory.store._get_chroma_client", return_value=mock_client):
            results = search_user_facts("คำถามไม่เกี่ยว")

        assert results == []

    def test_high_score_entry_passes_filter(self):
        """distance=0.3 → score=0.7 >= threshold 0.6 → ต้องคืนผล"""
        mock_client = MagicMock()
        mock_col = MagicMock()
        mock_client.get_collection.return_value = mock_col
        mock_col.query.return_value = {
            "documents": [["ปอยชอบ dark mode"]],
            "metadatas": [[{"confidence": 0.95, "type": "fact", "source": "user_taught"}]],
            "distances": [[0.3]],  # score = 1 - 0.3 = 0.7 >= 0.6
        }

        with patch("memory.store._get_chroma_client", return_value=mock_client):
            results = search_user_facts("dark mode preference")

        assert len(results) == 1
        assert results[0]["score"] == 0.7


class TestRecallIncludesUserFacts:
    def test_recall_for_any_assistant_includes_user_facts(self):
        with (
            patch("memory.operations.working_memory") as mock_wm,
            patch("memory.operations.search_entries", return_value=[]),
            patch("memory.operations.search_long_term", return_value=[]),
            patch("memory.operations.search_user_facts") as mock_uf,
        ):
            mock_wm.get_context_text.return_value = ""
            mock_uf.return_value = [
                {"content": "ปอยชอบ dark mode", "confidence": 0.95, "verified": True}
            ]

            result = recall("fa", "dark mode preference")

        mock_uf.assert_called_once_with("dark mode preference", n_results=5)
        assert "ปอยชอบ dark mode" in result

    def test_user_facts_labelled_distinctly_in_recall(self):
        with (
            patch("memory.operations.working_memory") as mock_wm,
            patch("memory.operations.search_entries", return_value=[]),
            patch("memory.operations.search_long_term", return_value=[]),
            patch("memory.operations.search_user_facts") as mock_uf,
        ):
            mock_wm.get_context_text.return_value = ""
            mock_uf.return_value = [
                {"content": "prefer กระชับ", "confidence": 0.95, "verified": True}
            ]

            result = recall("kwan", "style")

        assert "[ข้อมูลของคุณ]" in result
