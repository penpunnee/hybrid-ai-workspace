"""Tests สำหรับ utils/embed.py — cosine, pack/unpack, two-tier cache, rerank

Mock LM Studio client (`embed._client.embeddings`) ทั้งหมด — ไม่แตะ network จริง.
sqlite cache ชี้ temp file ต่อ test, ล้าง lru_cache ก่อนทุกเทสต์.
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import utils.embed as embed


class FakeEmbeddings:
    """แทน _client.embeddings — บันทึก call + คืน vector ตาม mapping"""

    def __init__(self, mapping=None, fail=False):
        self.calls = []          # list ของ input ที่ถูกส่งเข้ามา (แต่ละครั้ง)
        self.mapping = mapping or {}
        self.fail = fail

    def create(self, model, input):
        self.calls.append(list(input))
        if self.fail:
            raise RuntimeError("lmstudio down")
        data = [SimpleNamespace(embedding=self.mapping.get(t, [float(len(t)), 1.0, 0.0]))
                for t in input]
        return SimpleNamespace(data=data)


@pytest.fixture
def fake_client(monkeypatch, tmp_path):
    """ชี้ sqlite cache → temp, reset conn, ล้าง LRU, ติดตั้ง fake embeddings"""
    monkeypatch.setattr(embed, "_CACHE_DB", str(tmp_path / "embed_cache.db"))
    monkeypatch.setattr(embed, "_CACHE_ENABLED", True)
    monkeypatch.setattr(embed, "_cache_conn", None)
    embed._embed_one_cached.cache_clear()
    fe = FakeEmbeddings()
    monkeypatch.setattr(embed._client, "embeddings", fe)
    yield fe
    embed._embed_one_cached.cache_clear()


# ── cosine_similarity (pure math) ─────────────────────────────────────────────
def test_cosine_identical_vectors_is_one():
    assert embed.cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_cosine_orthogonal_is_zero():
    assert embed.cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_opposite_is_negative_one():
    assert embed.cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


@pytest.mark.parametrize("a,b", [
    ([], [1.0]),
    ([1.0], []),
    ([1.0, 2.0], [1.0]),       # ความยาวไม่เท่ากัน
    ([0.0, 0.0], [1.0, 1.0]),  # zero vector
])
def test_cosine_bad_input_returns_zero(a, b):
    assert embed.cosine_similarity(a, b) == 0.0


# ── pack/unpack roundtrip ─────────────────────────────────────────────────────
def test_pack_unpack_roundtrip():
    vec = [0.5, -1.25, 3.0, 0.0]
    blob = embed._pack(vec)
    assert isinstance(blob, bytes)
    out = embed._unpack(blob, len(vec))
    assert out == pytest.approx(vec)


def test_cache_key_deterministic_and_differs():
    assert embed._cache_key("hello") == embed._cache_key("hello")
    assert embed._cache_key("hello") != embed._cache_key("world")


# ── embed_query: cold → client; warm → cache (no client) ──────────────────────
def test_embed_query_cold_calls_client(fake_client):
    vec = embed.embed_query("foo")
    assert vec == [3.0, 1.0, 0.0]      # len("foo")=3
    assert len(fake_client.calls) == 1


def test_embed_query_lru_warm_skips_client(fake_client):
    embed.embed_query("foo")
    embed.embed_query("foo")           # LRU hit
    assert len(fake_client.calls) == 1


def test_embed_query_sqlite_warm_skips_client(fake_client):
    embed.embed_query("bar")
    embed._embed_one_cached.cache_clear()   # ทิ้ง LRU แต่ sqlite ยังอยู่
    embed.embed_query("bar")                # sqlite hit
    assert len(fake_client.calls) == 1


def test_embed_query_failure_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(embed, "_CACHE_DB", str(tmp_path / "c.db"))
    monkeypatch.setattr(embed, "_cache_conn", None)
    embed._embed_one_cached.cache_clear()
    monkeypatch.setattr(embed._client, "embeddings", FakeEmbeddings(fail=True))
    assert embed.embed_query("x") == []


# ── embed_texts: batch + partial cache ────────────────────────────────────────
def test_embed_texts_filters_empty(fake_client):
    out = embed.embed_texts(["", "  ", "ok"])
    assert len(out) == 1
    assert fake_client.calls == [["ok"]]      # ส่งเฉพาะ non-empty


def test_embed_texts_partial_cache_only_fetches_misses(fake_client):
    embed.embed_query("a")                    # warm "a" ลง sqlite
    fake_client.calls.clear()
    out = embed.embed_texts(["a", "bb"])       # "a" hit, "bb" miss
    assert len(out) == 2
    assert fake_client.calls == [["bb"]]


def test_embed_texts_batch_failure_returns_cached_only(fake_client):
    embed.embed_query("a")
    fake_client.calls.clear()
    fake_client.fail = True
    out = embed.embed_texts(["a", "new"])      # batch ล้ม → คืนเฉพาะ "a" ที่ cache ไว้
    assert out == [[1.0, 1.0, 0.0]]            # len("a")=1


# ── rerank_by_similarity ──────────────────────────────────────────────────────
def test_rerank_orders_by_similarity(fake_client):
    # query vec ใกล้ item "match" มากกว่า "other"
    fake_client.mapping = {
        "q": [1.0, 0.0],
        "match": [1.0, 0.0],
        "other": [0.0, 1.0],
    }
    items = [{"body": "other"}, {"body": "match"}]
    out = embed.rerank_by_similarity("q", items, text_keys=("body",), top_k=2)
    assert [it["body"] for it in out] == ["match", "other"]
    assert out[0]["_rerank_score"] >= out[1]["_rerank_score"]


def test_rerank_top_k_limits(fake_client):
    items = [{"body": f"i{i}"} for i in range(5)]
    out = embed.rerank_by_similarity("q", items, text_keys=("body",), top_k=2)
    assert len(out) == 2


def test_rerank_min_score_filters(fake_client):
    fake_client.mapping = {"q": [1.0, 0.0], "a": [1.0, 0.0], "b": [0.0, 1.0]}
    items = [{"body": "a"}, {"body": "b"}]
    out = embed.rerank_by_similarity("q", items, text_keys=("body",), top_k=5, min_score=0.5)
    assert [it["body"] for it in out] == ["a"]      # "b" score 0 ถูกตัด


def test_rerank_embed_fail_fallback_to_original(monkeypatch, tmp_path):
    monkeypatch.setattr(embed, "_CACHE_DB", str(tmp_path / "c.db"))
    monkeypatch.setattr(embed, "_cache_conn", None)
    embed._embed_one_cached.cache_clear()
    monkeypatch.setattr(embed._client, "embeddings", FakeEmbeddings(fail=True))
    items = [{"body": "a"}, {"body": "b"}, {"body": "c"}]
    out = embed.rerank_by_similarity("q", items, text_keys=("body",), top_k=2)
    assert out == items[:2]                          # fallback ไม่ rerank


def test_rerank_empty_items_returns_empty(fake_client):
    assert embed.rerank_by_similarity("q", []) == []


# ── Ollama fallback เมื่อ LM Studio ล่ม/ติด token ─────────────────────────────
def test_embed_falls_back_to_ollama(monkeypatch, tmp_path):
    monkeypatch.setattr(embed, "_CACHE_DB", str(tmp_path / "c.db"))
    monkeypatch.setattr(embed, "_cache_conn", None)
    embed.reset_metrics()
    # LM Studio fail (เช่น ติด token), Ollama ตอบได้
    monkeypatch.setattr(embed._client, "embeddings", FakeEmbeddings(fail=True))
    monkeypatch.setattr(embed._ollama_client, "embeddings",
                        FakeEmbeddings(mapping={"x": [9.0, 9.0]}))
    vec = embed.embed_query("x")
    assert vec == [9.0, 9.0]                     # ได้ vector จาก Ollama
    assert embed.cache_stats()["ollama_fallback"] >= 1


def test_embed_both_down_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(embed, "_CACHE_DB", str(tmp_path / "c.db"))
    monkeypatch.setattr(embed, "_cache_conn", None)
    embed.reset_metrics()
    monkeypatch.setattr(embed._client, "embeddings", FakeEmbeddings(fail=True))
    monkeypatch.setattr(embed._ollama_client, "embeddings", FakeEmbeddings(fail=True))
    assert embed.embed_query("x") == []          # ทั้งคู่ล่ม → [] (pipeline ไม่พัง)
