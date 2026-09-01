import pytest
from unittest.mock import patch, MagicMock
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import memory


@pytest.fixture
def mock_client():
    """Mock _get_client() → mock ChromaDB client + collection"""
    mock_col = MagicMock()
    mock_col.count.return_value = 0

    mock_cli = MagicMock()
    mock_cli.get_or_create_collection.return_value = mock_col

    with patch("utils.memory._get_client", return_value=mock_cli):
        yield mock_cli, mock_col


@pytest.fixture
def no_client():
    """Simulate ChromaDB unavailable"""
    with patch("utils.memory._get_client", return_value=None):
        yield


class TestSaveLesson:
    def test_success(self, mock_client):
        _, col = mock_client
        assert memory.save_lesson("Python", "ใช้ list comprehension ได้") is True
        col.add.assert_called_once()

    def test_chroma_unavailable(self, no_client):
        assert memory.save_lesson("topic", "lesson") is False

    def test_chroma_error(self, mock_client):
        _, col = mock_client
        col.add.side_effect = Exception("connection reset")
        assert memory.save_lesson("topic", "lesson") is False


class TestSavePreference:
    def test_success(self, mock_client):
        _, col = mock_client
        assert memory.save_preference("language", "thai") is True
        col.upsert.assert_called_once()

    def test_chroma_unavailable(self, no_client):
        assert memory.save_preference("k", "v") is False


class TestGetLessons:
    def test_returns_empty_when_no_docs(self, mock_client):
        _, col = mock_client
        col.count.return_value = 0
        result = memory.get_lessons("test query")
        assert result == ""

    def test_returns_string_with_docs(self, mock_client):
        _, col = mock_client
        col.count.return_value = 2
        col.query.return_value = {"documents": [["lesson A", "lesson B"]]}
        result = memory.get_lessons("python", n_results=2)
        assert "lesson A" in result

    def test_chroma_unavailable(self, no_client):
        assert memory.get_lessons() == ""


class TestDeleteLesson:
    """ตั้งแต่ 2026-09-02 ลบผ่าน `memory.dualvec.delete_with_keys` (cascade เงา)
    ⇒ ใช้ `get_collection` แทน `get_or_create_collection` โดยตั้งใจ — การ "ลบ"
    ไม่ควรสร้าง collection เปล่าทิ้งไว้เป็นผลข้างเคียง"""

    def test_success(self, mock_client):
        cli, col = mock_client
        cli.get_collection.return_value = col
        assert memory.delete_lesson("doc123") is True
        # ถูกเรียก 2 ครั้ง: เงา (`lessons__keys`) แล้วตัวหลัก — fake คืน col ตัวเดียวกัน
        assert col.delete.call_args_list == [({"ids": ["doc123"]},)] * 2 or \
               col.delete.call_count == 2, col.delete.call_args_list

    def test_เงาถูกลบก่อนตัวหลัก(self, mock_client):
        """ลำดับคือกันกุญแจกำพร้าที่ recall ขึ้นมาได้ — ดู memory/dualvec.py"""
        cli, col = mock_client
        seen = []
        cli.get_collection.side_effect = lambda name, **kw: (seen.append(name), col)[1]
        memory.delete_lesson("doc123")
        assert seen == ["lessons__keys", "lessons"], seen

    def test_chroma_error(self, mock_client):
        cli, col = mock_client
        cli.get_collection.return_value = col
        col.delete.side_effect = Exception("not found")
        assert memory.delete_lesson("doc123") is False

    def test_chroma_unavailable(self, no_client):
        assert memory.delete_lesson("doc123") is False


class TestDeletePreference:
    def test_success(self, mock_client):
        _, col = mock_client
        assert memory.delete_preference("pref123") is True
        col.delete.assert_called_once_with(ids=["pref123"])

    def test_chroma_unavailable(self, no_client):
        assert memory.delete_preference("pref123") is False


class TestGetMemoryStats:
    def test_returns_dict_with_available(self, mock_client):
        mock_cli, mock_col = mock_client
        mock_col.count.return_value = 5
        mock_cli.list_collections.return_value = []
        stats = memory.get_memory_stats()
        assert isinstance(stats, dict)
        assert "available" in stats

    def test_unavailable(self, no_client):
        stats = memory.get_memory_stats()
        assert stats.get("available") is False
