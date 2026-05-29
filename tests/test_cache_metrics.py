"""Tests สำหรับ hit-rate counters (Phase G4) + bench_cache harness

ครอบ counter ของ retrieval_cache / response_cache / embed + smoke ของ bench script
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import pytest

import utils.retrieval_cache as rc
import utils.response_cache as resp
import utils.embed as embed


# ══════════════════ retrieval_cache counters ══════════════════════════════════
@pytest.fixture
def retr_env(monkeypatch):
    rc._cache.clear()
    rc.reset_metrics()
    vecs = {"a": [1.0, 0.0], "a2": [1.0, 0.0], "b": [0.0, 1.0]}
    monkeypatch.setattr(rc, "embed_query", lambda p: vecs.get(p, []))
    yield
    rc._cache.clear()
    rc.reset_metrics()


def test_retrieval_counts_hit(retr_env):
    rc.store("s1", "a", [{"x": 1}])
    rc.get_cached("s1", "a2")          # cosine 1 → hit
    s = rc.stats()
    assert s["lookups"] == 1 and s["hits"] == 1 and s["misses"] == 0
    assert s["hit_rate"] == 1.0


def test_retrieval_counts_miss(retr_env):
    rc.store("s1", "a", [{"x": 1}])
    rc.get_cached("s1", "b")           # orthogonal → miss
    s = rc.stats()
    assert s["hits"] == 0 and s["misses"] == 1
    assert s["hit_rate"] == 0.0


def test_retrieval_hit_rate_none_when_no_lookups(retr_env):
    assert rc.stats()["hit_rate"] is None


def test_retrieval_lookups_equal_hits_plus_misses(retr_env):
    rc.store("s1", "a", [{"x": 1}])
    rc.get_cached("s1", "a2")          # hit
    rc.get_cached("s1", "b")           # miss
    rc.get_cached("nope", "a")         # miss (no entry)
    s = rc.stats()
    assert s["lookups"] == s["hits"] + s["misses"]


def test_retrieval_guard_not_counted(retr_env):
    rc.get_cached("", "a")             # ไม่มี session → ไม่นับ lookup
    assert rc.stats()["lookups"] == 0


# ══════════════════ response_cache counters ═══════════════════════════════════
@pytest.fixture
def resp_env(monkeypatch, tmp_path):
    monkeypatch.setattr(resp, "_DB_PATH", str(tmp_path / "rc.db"))
    monkeypatch.setattr(resp, "_ENABLED", True)
    monkeypatch.setattr(resp, "_conn", None)
    resp.reset_metrics()
    vecs = {"q1": [1.0, 0.0], "q1b": [1.0, 0.0], "q2": [0.0, 1.0]}
    monkeypatch.setattr(resp, "embed_query", lambda p: vecs.get(p, []))
    yield
    if resp._conn is not None:
        resp._conn.close()
        resp._conn = None
    resp.reset_metrics()


def test_response_counts_hit(resp_env):
    resp.save("kwan", "q1", "ans")
    resp.lookup("kwan", "q1b")         # cosine 1 → hit
    s = resp.stats()
    assert s["lookups"] == 1 and s["runtime_hits"] == 1 and s["misses"] == 0
    assert s["hit_rate"] == 1.0


def test_response_counts_miss(resp_env):
    resp.save("kwan", "q1", "ans")
    resp.lookup("kwan", "q2")          # orthogonal → miss
    s = resp.stats()
    assert s["runtime_hits"] == 0 and s["misses"] == 1
    assert s["hit_rate"] == 0.0


def test_response_total_hits_persistent_vs_runtime(resp_env):
    # total_hits (column) นับสะสม; runtime_hits reset ได้
    resp.save("kwan", "q1", "ans")
    resp.lookup("kwan", "q1b")
    resp.lookup("kwan", "q1b")
    s = resp.stats()
    assert s["total_hits"] == 2 and s["runtime_hits"] == 2
    resp.reset_metrics()
    s2 = resp.stats()
    assert s2["runtime_hits"] == 0          # runtime reset
    assert s2["total_hits"] == 2            # persistent คงอยู่


# ══════════════════ embed counters ════════════════════════════════════════════
class FakeEmbeddings:
    def __init__(self):
        self.calls = 0

    def create(self, model, input):
        self.calls += 1
        return SimpleNamespace(data=[SimpleNamespace(embedding=[float(len(t)), 1.0]) for t in input])


@pytest.fixture
def embed_env(monkeypatch, tmp_path):
    monkeypatch.setattr(embed, "_CACHE_DB", str(tmp_path / "embed.db"))
    monkeypatch.setattr(embed, "_CACHE_ENABLED", True)
    monkeypatch.setattr(embed, "_cache_conn", None)
    embed.reset_metrics()
    fe = FakeEmbeddings()
    monkeypatch.setattr(embed._client, "embeddings", fe)
    yield fe
    embed.reset_metrics()


def test_embed_lru_hit_counted(embed_env):
    embed.embed_query("foo")           # cold: LRU miss → api
    embed.embed_query("foo")           # LRU hit
    s = embed.cache_stats()
    assert s["lru_hits"] == 1 and s["lru_misses"] == 1
    assert s["lru_hit_rate"] == 0.5
    assert s["api_calls"] == 1


def test_embed_sqlite_warm_hit(embed_env):
    embed.embed_query("bar")           # cold → api + เก็บ sqlite
    embed._embed_one_cached.cache_clear()   # ทิ้ง LRU เท่านั้น
    embed.embed_query("bar")           # LRU miss → sqlite hit (ไม่มี api ใหม่)
    s = embed.cache_stats()
    assert s["sqlite_hits"] == 1
    assert s["api_calls"] == 1         # ไม่เพิ่มเพราะมาจาก sqlite


def test_embed_hit_rate_none_when_unused(embed_env):
    assert embed.cache_stats()["lru_hit_rate"] is None


# ══════════════════ bench_cache harness ═══════════════════════════════════════
@pytest.fixture
def restore_embed_refs():
    """bench ใส่ fake embed ลง module โดยตรง → restore กันกระทบเทสต์อื่น"""
    orig_rc, orig_resp = rc.embed_query, resp.embed_query
    yield
    rc.embed_query, resp.embed_query = orig_rc, orig_resp
    rc._cache.clear(); rc.reset_metrics(); resp.reset_metrics()


def test_bench_synthetic_smoke(restore_embed_refs):
    import bench_cache
    r = bench_cache.run_synthetic(n=50, repeat=0.5, fake_embed=True)
    assert r["mode"] == "synthetic"
    assert r["queries"] == 50
    rcache = r["response_cache"]
    # repeat 0.5 + fake exact-match → ต้องมี hit จริง
    assert rcache["hits"] > 0
    assert rcache["lookups"] == rcache["hits"] + rcache["misses"]
    assert 0.0 <= rcache["hit_rate"] <= 1.0


def test_bench_synthetic_zero_repeat_no_hits(restore_embed_refs):
    import bench_cache
    r = bench_cache.run_synthetic(n=30, repeat=0.0, fake_embed=True)
    # ไม่มี repeat เลย → response cache ไม่ควร hit
    assert r["response_cache"]["hits"] == 0
