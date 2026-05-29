"""Tests สำหรับ utils/documents.py — index/retrieve/list/delete + format

Mock _get_collection → FakeCollection (ไม่แตะ ChromaDB จริง).
Mock embed_texts / rerank_by_similarity ที่ documents เรียกจาก utils.embed.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import utils.documents as docs
import utils.embed as embed


class FakeCollection:
    def __init__(self):
        self.records = {}          # id -> (doc, meta, embedding)
        self.deleted = []          # where clauses ที่ถูกลบ
        self.query_result = {"documents": [[]], "metadatas": [[]], "distances": [[]]}

    def upsert(self, ids, documents, metadatas, embeddings=None):
        for i, (id_, doc, meta) in enumerate(zip(ids, documents, metadatas)):
            self.records[id_] = (doc, meta, embeddings[i] if embeddings else None)

    def delete(self, where=None):
        self.deleted.append(where)
        if where and "source" in where:
            for k in [k for k, (d, m, e) in self.records.items()
                      if m.get("source") == where["source"]]:
                self.records.pop(k)

    def query(self, query_texts, n_results, where=None):
        return self.query_result

    def get(self, include=None):
        return {"metadatas": [m for (d, m, e) in self.records.values()]}


@pytest.fixture
def fake_col(monkeypatch):
    col = FakeCollection()
    monkeypatch.setattr(docs, "_get_collection", lambda: col)
    # rerank = identity (top_k) เพื่อ deterministic; embed_texts = vector ต่อ chunk
    monkeypatch.setattr(embed, "rerank_by_similarity",
                        lambda q, items, text_keys=(), top_k=5, min_score=0.0: items[:top_k])
    monkeypatch.setattr(embed, "embed_texts", lambda texts: [[0.1, 0.2, 0.3] for _ in texts])
    return col


# ── _doc_id ───────────────────────────────────────────────────────────────────
def test_doc_id_deterministic():
    assert docs._doc_id("file.txt", 0) == docs._doc_id("file.txt", 0)
    assert docs._doc_id("file.txt", 0) != docs._doc_id("file.txt", 1)
    assert docs._doc_id("a.txt", 0) != docs._doc_id("b.txt", 0)


# ── index_document ────────────────────────────────────────────────────────────
def test_index_document_success(fake_col):
    content = "ประโยคแรก. " * 80   # ยาวพอให้แตกหลาย chunk
    res = docs.index_document(content, source="doc1.txt", chunk_size=200, overlap=20)
    assert res["ok"] is True
    assert res["chunks_count"] >= 1
    assert len(fake_col.records) == res["chunks_count"]
    # embedding ถูกแนบ (จาก embed_texts ที่เรา mock)
    any_rec = next(iter(fake_col.records.values()))
    assert any_rec[2] == [0.1, 0.2, 0.3]


def test_index_document_no_collection(monkeypatch):
    monkeypatch.setattr(docs, "_get_collection", lambda: None)
    res = docs.index_document("content", source="x")
    assert res["ok"] is False
    assert "unavailable" in res["error"]


def test_index_document_empty_content(fake_col):
    res = docs.index_document("", source="x")
    assert res["ok"] is False


def test_index_reindex_deletes_old_first(fake_col):
    docs.index_document("hello world content here", source="doc1.txt", chunk_size=200)
    docs.index_document("new content replaces old", source="doc1.txt", chunk_size=200)
    # delete(where={"source":...}) ถูกเรียกก่อน upsert รอบสอง
    assert {"source": "doc1.txt"} in fake_col.deleted


# ── retrieve_chunks ───────────────────────────────────────────────────────────
def test_retrieve_empty_query(fake_col):
    assert docs.retrieve_chunks("   ") == []


def test_retrieve_no_collection(monkeypatch):
    monkeypatch.setattr(docs, "_get_collection", lambda: None)
    assert docs.retrieve_chunks("q") == []


def test_retrieve_returns_scored_items(fake_col):
    fake_col.query_result = {
        "documents": [["chunk A", "chunk B", "chunk C"]],
        "metadatas": [[
            {"source": "d.txt", "chunk_index": 0, "start": 0, "end": 5},
            {"source": "d.txt", "chunk_index": 1, "start": 5, "end": 10},
            {"source": "d.txt", "chunk_index": 2, "start": 10, "end": 15},
        ]],
        "distances": [[0.1, 0.2, 0.95]],   # scores: 0.9, 0.8, 0.05
    }
    out = docs.retrieve_chunks("query", top_k=5)
    # score 0.05 ถูกตัดโดย budget filter (min 0.3)
    scores = [it["score"] for it in out]
    assert all(s >= 0.3 for s in scores)
    assert "chunk C" not in [it["text"] for it in out]


def test_retrieve_source_filter_passes_where(fake_col, monkeypatch):
    captured = {}
    def fake_query(query_texts, n_results, where=None):
        captured["where"] = where
        return {"documents": [[]], "metadatas": [[]], "distances": [[]]}
    fake_col.query = fake_query
    docs.retrieve_chunks("q", source_filter="only.txt")
    assert captured["where"] == {"source": "only.txt"}


# ── list_documents ────────────────────────────────────────────────────────────
def test_list_documents_groups_by_source(fake_col):
    fake_col.records = {
        "a": ("t", {"source": "d1", "indexed_at": 100}, None),
        "b": ("t", {"source": "d1", "indexed_at": 200}, None),
        "c": ("t", {"source": "d2", "indexed_at": 150}, None),
    }
    out = docs.list_documents()
    by = {d["source"]: d for d in out}
    assert by["d1"]["chunks_count"] == 2
    assert by["d1"]["indexed_at"] == 200      # ใช้ค่าล่าสุด
    assert by["d2"]["chunks_count"] == 1


# ── delete_document ───────────────────────────────────────────────────────────
def test_delete_document(fake_col):
    fake_col.records = {"a": ("t", {"source": "d1"}, None)}
    assert docs.delete_document("d1") is True
    assert "a" not in fake_col.records


def test_delete_document_no_collection(monkeypatch):
    monkeypatch.setattr(docs, "_get_collection", lambda: None)
    assert docs.delete_document("d1") is False


# ── format_for_context ────────────────────────────────────────────────────────
def test_format_empty_returns_empty():
    assert docs.format_for_context([]) == ""


def test_format_includes_citation_markers():
    items = [
        {"text": "เนื้อหา 1", "source": "a.txt", "score": 0.9},
        {"text": "เนื้อหา 2", "source": "b.txt", "score": 0.8},
    ]
    out = docs.format_for_context(items)
    assert "[1]" in out and "[2]" in out
    assert "a.txt" in out and "b.txt" in out


def test_format_respects_max_chars():
    items = [{"text": "x" * 500, "source": f"f{i}.txt", "score": 0.9} for i in range(10)]
    out = docs.format_for_context(items, max_chars=700)
    # ตัดเมื่อเกิน budget — ไม่ครบ 10 บล็อก
    assert out.count("_(จาก:") < 10
