"""Tests สำหรับ utils/retrieval_cache.py — per-session cache hit/miss/TTL/evict

Mock embed_query → คุม vector ได้; cosine จริง. รีเซ็ต _cache ทุกเทสต์.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import utils.retrieval_cache as rc


@pytest.fixture
def clean_cache(monkeypatch):
    """ล้าง _cache + map prompt→vec ผ่าน embed_query ปลอม"""
    rc._cache.clear()
    vecs = {
        "weather today": [1.0, 0.0, 0.0],
        "weather now": [1.0, 0.0, 0.0],      # เหมือน → cosine 1
        "stock price": [0.0, 1.0, 0.0],      # ตั้งฉาก → cosine 0
    }
    monkeypatch.setattr(rc, "embed_query", lambda p: vecs.get(p, []))
    yield
    rc._cache.clear()


def test_store_then_hit_similar_prompt(clean_cache):
    rc.store("s1", "weather today", [{"id": 1}], [{"c": 1}])
    hit = rc.get_cached("s1", "weather now")
    assert hit is not None
    assert hit["similarity"] == pytest.approx(1.0)
    assert hit["chunks"] == [{"id": 1}]
    assert hit["citations"] == [{"c": 1}]
    assert hit["source_prompt"] == "weather today"


def test_miss_when_dissimilar(clean_cache):
    rc.store("s1", "weather today", [{"id": 1}])
    assert rc.get_cached("s1", "stock price") is None


def test_miss_when_no_entry(clean_cache):
    assert rc.get_cached("nope", "weather today") is None


def test_empty_session_or_prompt_guarded(clean_cache):
    assert rc.get_cached("", "weather today") is None
    assert rc.get_cached("s1", "") is None
    rc.store("", "weather today", [{"id": 1}])     # ไม่ควรเก็บ
    assert rc._cache == {}


def test_store_skips_when_embed_fails(clean_cache):
    rc.store("s1", "unknown-prompt", [{"id": 1}])   # embed_query → []
    assert "s1" not in rc._cache


def test_ttl_expiry_returns_none_and_evicts(clean_cache):
    rc.store("s1", "weather today", [{"id": 1}])
    rc._cache["s1"].ts = time.time() - (rc._TTL + 1)   # ทำให้หมดอายุ
    assert rc.get_cached("s1", "weather now") is None
    assert "s1" not in rc._cache


def test_invalidate_clears_session(clean_cache):
    rc.store("s1", "weather today", [{"id": 1}])
    rc.invalidate("s1")
    assert "s1" not in rc._cache


def test_eviction_caps_sessions(monkeypatch, clean_cache):
    # หลังแก้: insert ก่อน → _evict_old → cache ไม่เกิน _MAX_SESSIONS เป๊ะ
    monkeypatch.setattr(rc, "_MAX_SESSIONS", 2)
    monkeypatch.setattr(rc, "embed_query", lambda p: [1.0, 0.0, 0.0])
    for i in range(5):
        rc.store(f"s{i}", "weather today", [{"id": i}])
    assert len(rc._cache) == rc._MAX_SESSIONS
    assert "s0" not in rc._cache       # เก่าสุดถูก evict
    assert "s4" in rc._cache           # ใหม่สุดอยู่


def test_threshold_override(clean_cache):
    # cosine ของ 2 prompt นี้ = 1.0 อยู่แล้ว; ตั้ง threshold สูงเกินไป → ยังผ่าน
    rc.store("s1", "weather today", [{"id": 1}])
    assert rc.get_cached("s1", "weather now", threshold=0.99) is not None
    # ตั้ง threshold = 1.1 (เกิน max ที่เป็นไปได้) → miss
    rc.store("s1", "weather today", [{"id": 1}])
    assert rc.get_cached("s1", "weather now", threshold=1.1) is None


def test_stats_shape(clean_cache):
    rc.store("s1", "weather today", [{"id": 1}])
    s = rc.stats()
    assert s["sessions"] == 1
    assert s["ttl_seconds"] == rc._TTL
    assert "threshold" in s and "max_sessions" in s
