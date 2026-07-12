"""Tests สำหรับ utils/chunking.py — semantic-aware document chunker"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.chunking import chunk_text, chunk_stats, Chunk


def test_empty_text_returns_no_chunks():
    assert chunk_text("") == []
    assert chunk_text("   \n  ") == []


def test_short_text_single_chunk():
    chunks = chunk_text("hello world", source="doc.txt")
    assert len(chunks) == 1
    c = chunks[0]
    assert c.text == "hello world"
    assert c.index == 0
    assert c.source == "doc.txt"


def test_long_text_splits_into_multiple_chunks():
    text = "Sentence one here. Sentence two here. Sentence three here. Sentence four here."
    chunks = chunk_text(text, chunk_size=25, overlap=5)
    assert len(chunks) >= 2
    # invariant: ทุก chunk ต้องไม่เกิน chunk_size
    assert all(len(c.text) <= 25 for c in chunks)
    # index เรียงต่อเนื่อง 0,1,2,...
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_metadata_is_copied_into_each_chunk():
    text = "para one body.\n\npara two body.\n\npara three body."
    chunks = chunk_text(text, chunk_size=20, metadata={"doc_id": 7})
    assert chunks  # มี chunk
    assert all(c.metadata.get("doc_id") == 7 for c in chunks)
    # ต้องเป็น copy — แก้ของ chunk แรกไม่กระทบตัวอื่น
    chunks[0].metadata["doc_id"] = 999
    assert chunks[-1].metadata["doc_id"] == 7


def test_chunk_to_dict_roundtrip():
    c = chunk_text("hello", source="s")[0]
    d = c.to_dict()
    assert d["text"] == "hello" and d["source"] == "s" and "start" in d


def test_chunk_stats_empty():
    assert chunk_stats([]) == {"count": 0}


def test_chunk_stats_aggregates():
    chunks = [
        Chunk(text="aa", index=0, source="s"),     # 2
        Chunk(text="bbbb", index=1, source="s"),   # 4
    ]
    s = chunk_stats(chunks)
    assert s == {"count": 2, "min": 2, "max": 4, "avg": 3, "total": 6}
