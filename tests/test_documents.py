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

    def query(self, n_results, query_texts=None, query_embeddings=None, where=None):
        self.last_query_kwargs = {
            "query_texts": query_texts, "query_embeddings": query_embeddings, "where": where,
        }
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


# ── index_document embed-failure poisons collection dimension (พบจาก audit 2026-08-01) ──
# collection "documents" ถูกเซ็ตมิติจาก vector ตัวแรกที่เขียนจริง (LM Studio
# nomic-embed-text, 768-dim) ถ้า embed_texts() ล้มระหว่างอัปโหลด (LM Studio ล่ม
# ชั่วคราว) โค้ดเดิม fallback ให้ ChromaDB auto-embed ด้วย default embedder
# (MiniLM 384-dim) แล้ว upsert ไปเลย — ถ้าเป็นเอกสารแรกของ collection ที่ว่างเปล่า
# จะ "ปักหมุด" มิติ collection เป็น 384 ถาวร ทำให้เอกสารที่ embed สำเร็จ (768-dim)
# ในอนาคตเขียนไม่ได้อีกเลย ต้อง fail ตรงๆ แทนเขียนด้วยมิติที่ไม่ตรงกัน
def test_index_document_embed_failure_does_not_write_mismatched_vectors(fake_col, monkeypatch):
    monkeypatch.setattr(embed, "embed_texts",
                        lambda texts: (_ for _ in ()).throw(Exception("LM Studio down")))
    res = docs.index_document("hello world content here", source="doc1.txt", chunk_size=200)
    assert res["ok"] is False
    assert "embed" in res["error"].lower()
    # ต้องไม่มีการ upsert ใดๆ เกิดขึ้นเลย (กัน collection ถูกปักมิติผิดถาวร)
    assert fake_col.records == {}


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
    def fake_query(n_results, query_texts=None, query_embeddings=None, where=None):
        captured["where"] = where
        return {"documents": [[]], "metadatas": [[]], "distances": [[]]}
    fake_col.query = fake_query
    docs.retrieve_chunks("q", source_filter="only.txt")
    assert captured["where"] == {"source": "only.txt"}


# ── retrieve_chunks embedding dimension bug (เจอจริง 2026-07-13 ทดสอบ upload PDF scan) ──
# index_document() ใส่ vector explicit ผ่าน embed_texts() (LM Studio nomic-embed-text,
# 768-dim) แต่ retrieve_chunks() เดิมส่ง query_texts เฉยๆ → ChromaDB auto-embed ด้วย
# default embedder (MiniLM 384-dim) มิติไม่ตรง → query พังเงียบๆ ทุกครั้ง (คืน [] เสมอ)
def test_retrieve_uses_query_embeddings_when_embed_succeeds(fake_col):
    """ต้อง embed query ด้วยฟังก์ชันเดียวกับตอน insert ไม่ใช่ปล่อยให้ ChromaDB
    auto-embed ด้วย default embedder (มิติไม่ตรงกับที่ persist ไว้)"""
    docs.retrieve_chunks("คำถาม", top_k=3)
    assert fake_col.last_query_kwargs["query_embeddings"] == [[0.1, 0.2, 0.3]]
    assert fake_col.last_query_kwargs["query_texts"] is None


def test_retrieve_falls_back_to_query_texts_when_embed_raises(fake_col, monkeypatch):
    """embed_texts โยน exception (เช่น LM Studio ล่ม) → fallback ไป query_texts
    เหมือนเดิม ดีกว่า query ไม่ได้เลย"""
    monkeypatch.setattr(embed, "embed_texts", lambda texts: (_ for _ in ()).throw(Exception("LM Studio down")))
    docs.retrieve_chunks("คำถาม", top_k=3)
    assert fake_col.last_query_kwargs["query_texts"] == ["คำถาม"]
    assert fake_col.last_query_kwargs["query_embeddings"] is None


def test_retrieve_falls_back_to_query_texts_when_embed_returns_empty(fake_col, monkeypatch):
    """embed_texts คืน [] ตามสัญญา (ไม่ throw) เมื่อ embed ไม่สำเร็จ — ต้อง fallback เหมือนกัน"""
    monkeypatch.setattr(embed, "embed_texts", lambda texts: [])
    docs.retrieve_chunks("คำถาม", top_k=3)
    assert fake_col.last_query_kwargs["query_texts"] == ["คำถาม"]
    assert fake_col.last_query_kwargs["query_embeddings"] is None


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
