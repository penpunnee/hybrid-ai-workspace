"""Tests สำหรับ utils/response_cache.py — semantic Q&A cache (sqlite)

ชี้ DB → temp ต่อ test, reset _conn, mock embed_query. cosine จริง.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import utils.response_cache as resp


@pytest.fixture
def db(monkeypatch, tmp_path):
    monkeypatch.setattr(resp, "_DB_PATH", str(tmp_path / "response_cache.db"))
    monkeypatch.setattr(resp, "_ENABLED", True)
    monkeypatch.setattr(resp, "_conn", None)
    vecs = {
        "how to cook rice": [1.0, 0.0, 0.0],
        "how do i cook rice": [1.0, 0.0, 0.0],   # cosine 1 กับอันบน
        "what is the weather": [0.0, 1.0, 0.0],  # ตั้งฉาก
    }
    monkeypatch.setattr(resp, "embed_query", lambda p: vecs.get(p, []))
    yield
    if resp._conn is not None:
        resp._conn.close()
        resp._conn = None


def test_save_then_lookup_hit(db):
    assert resp.save("kwan", "how to cook rice", "ต้มน้ำก่อน", model="llama3") is True
    hit = resp.lookup("kwan", "how do i cook rice")
    assert hit is not None
    assert hit["response"] == "ต้มน้ำก่อน"
    assert hit["model"] == "llama3"
    assert hit["similarity"] == pytest.approx(1.0)
    assert hit["source_prompt"] == "how to cook rice"


def test_lookup_miss_below_threshold(db):
    resp.save("kwan", "how to cook rice", "ต้มน้ำก่อน")
    assert resp.lookup("kwan", "what is the weather") is None


def test_lookup_respects_assistant_scope(db):
    resp.save("kwan", "how to cook rice", "answer")
    assert resp.lookup("fah", "how do i cook rice") is None


def test_save_rejects_empty(db):
    assert resp.save("kwan", "   ", "ans") is False
    assert resp.save("kwan", "how to cook rice", "  ") is False


def test_save_skips_when_embed_fails(db):
    assert resp.save("kwan", "no-vec-prompt", "ans") is False


def test_ttl_cutoff_excludes_old(db):
    resp.save("kwan", "how to cook rice", "ans")
    old = time.time() - (resp._TTL_DAYS * 86400 + 100)
    resp._conn.execute("UPDATE response_cache SET created_at=?", (old,))
    assert resp.lookup("kwan", "how do i cook rice") is None


def test_hit_count_increments(db):
    resp.save("kwan", "how to cook rice", "ans")
    resp.lookup("kwan", "how do i cook rice")
    resp.lookup("kwan", "how do i cook rice")
    n = resp._conn.execute("SELECT hit_count FROM response_cache").fetchone()[0]
    assert n == 2


def test_eviction_over_max(monkeypatch, db):
    monkeypatch.setattr(resp, "_MAX_ENTRIES", 3)
    monkeypatch.setattr(resp, "embed_query", lambda p: [1.0, 0.0, 0.0])
    for i in range(6):
        resp.save("kwan", f"prompt number {i}", f"ans {i}")
    n = resp._conn.execute("SELECT COUNT(*) FROM response_cache").fetchone()[0]
    assert n <= 3


def test_delete_for_message(db):
    resp.save("kwan", "how to cook rice", "ans")
    assert resp.delete_for_message("kwan", "how to cook rice") is True
    assert resp.lookup("kwan", "how do i cook rice") is None


def test_stats_shape(db):
    resp.save("kwan", "how to cook rice", "ans")
    s = resp.stats()
    assert s["enabled"] is True
    assert s["entries"] == 1
    assert s["by_assistant"] == {"kwan": 1}
    assert "threshold" in s and "ttl_days" in s


def test_disabled_mode(monkeypatch, tmp_path):
    monkeypatch.setattr(resp, "_DB_PATH", str(tmp_path / "x.db"))
    monkeypatch.setattr(resp, "_ENABLED", False)
    monkeypatch.setattr(resp, "_conn", None)
    assert resp.save("kwan", "p", "a") is False
    assert resp.lookup("kwan", "p") is None
    assert resp.stats() == {"enabled": False}
