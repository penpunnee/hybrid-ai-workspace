"""Tests สำหรับ utils/feedback.py — thumbs up/down store + propagate logic

ใช้ temp DB จาก conftest (DB_PATH). ปิด propagate thread เพื่อไม่แตะ ChromaDB จริง
ยกเว้นเทสต์ _propagate_impl ที่ mock memory.store + response_cache ตรงๆ
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import utils.feedback as fb
from utils.history import _get_conn


def _add_message(assistant, role, content, session_id="s1", provider="ollama"):
    conn = _get_conn()
    try:
        cur = conn.execute(
            """INSERT INTO messages (assistant, role, content, provider, created_at, session_id)
               VALUES (?,?,?,?,?,?)""",
            (assistant, role, content, provider, "2026-01-01T00:00:00", session_id),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


@pytest.fixture
def clean_db(monkeypatch):
    monkeypatch.setattr(fb, "_propagate_to_memory", lambda *a, **k: None)  # กัน thread แตะ service จริง
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM feedback")
        conn.execute("DELETE FROM messages")
        conn.commit()
    finally:
        conn.close()
    yield


# ── save_feedback validation ──────────────────────────────────────────────────
def test_save_valid_up(clean_db):
    mid = _add_message("kwan", "assistant", "answer")
    res = fb.save_feedback("kwan", "s1", mid, "up")
    assert res["ok"] is True
    assert res["rating"] == "up"
    assert res["message_id"] == mid
    assert isinstance(res["feedback_id"], int)


@pytest.mark.parametrize("rating", ["", "meh", "UPVOTE", None])
def test_save_invalid_rating(clean_db, rating):
    mid = _add_message("kwan", "assistant", "answer")
    res = fb.save_feedback("kwan", "s1", mid, rating)
    assert res["ok"] is False
    assert "rating" in res["error"]


@pytest.mark.parametrize("bad_id", [0, -5, "3"])
def test_save_invalid_message_id(clean_db, bad_id):
    res = fb.save_feedback("kwan", "s1", bad_id, "up")
    assert res["ok"] is False
    assert "message_id" in res["error"]


def test_rating_normalized_case_insensitive(clean_db):
    mid = _add_message("kwan", "assistant", "answer")
    res = fb.save_feedback("kwan", "s1", mid, " Up ")
    assert res["ok"] is True
    assert res["rating"] == "up"


def test_save_replaces_previous_rating(clean_db):
    mid = _add_message("kwan", "assistant", "answer")
    fb.save_feedback("kwan", "s1", mid, "up")
    fb.save_feedback("kwan", "s1", mid, "down")
    got = fb.get_feedback(mid)
    assert got["rating"] == "down"
    # ต้องเหลือแถวเดียวสำหรับ message นี้
    conn = _get_conn()
    try:
        n = conn.execute("SELECT COUNT(*) FROM feedback WHERE message_id=?", (mid,)).fetchone()[0]
    finally:
        conn.close()
    assert n == 1


# ── get_feedback ──────────────────────────────────────────────────────────────
def test_get_feedback_none_when_missing(clean_db):
    assert fb.get_feedback(99999) is None


def test_get_feedback_shape(clean_db):
    mid = _add_message("kwan", "assistant", "answer")
    fb.save_feedback("kwan", "s1", mid, "up", comment="ดีมาก")
    got = fb.get_feedback(mid)
    assert got["assistant"] == "kwan"
    assert got["rating"] == "up"
    assert got["comment"] == "ดีมาก"


# ── get_stats ─────────────────────────────────────────────────────────────────
def test_stats_counts_and_ratio(clean_db):
    for i in range(2):
        mid = _add_message("kwan", "assistant", f"a{i}")
        fb.save_feedback("kwan", "s1", mid, "up")
    mid = _add_message("kwan", "assistant", "bad")
    fb.save_feedback("kwan", "s1", mid, "down")

    s = fb.get_stats()
    assert s["total"] == 3
    assert s["ups"] == 2
    assert s["downs"] == 1
    assert s["ratio"] == pytest.approx(round(2 / 3, 3))
    assert len(s["recent"]) == 3


def test_stats_ratio_none_when_empty(clean_db):
    s = fb.get_stats()
    assert s["total"] == 0
    assert s["ratio"] is None


def test_stats_assistant_filter(clean_db):
    m1 = _add_message("kwan", "assistant", "a")
    fb.save_feedback("kwan", "s1", m1, "up")
    m2 = _add_message("fah", "assistant", "b")
    fb.save_feedback("fah", "s1", m2, "up")

    s = fb.get_stats(assistant="kwan")
    assert s["assistant"] == "kwan"
    assert s["ups"] == 1


# ── list_low_rated_messages ───────────────────────────────────────────────────
def test_list_low_rated(clean_db):
    good = _add_message("kwan", "assistant", "good answer")
    bad = _add_message("kwan", "assistant", "bad answer")
    fb.save_feedback("kwan", "s1", good, "up")
    fb.save_feedback("kwan", "s1", bad, "down", comment="ผิด")

    low = fb.list_low_rated_messages(assistant="kwan")
    assert len(low) == 1
    assert low[0]["message_id"] == bad
    assert low[0]["content"] == "bad answer"
    assert low[0]["comment"] == "ผิด"


# ── _propagate_impl (mock memory.store + response_cache) ──────────────────────
@pytest.fixture
def propagate_env(monkeypatch):
    """clean tables + mock downstream effects ของ _propagate_impl"""
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM feedback")
        conn.execute("DELETE FROM messages")
        conn.commit()
    finally:
        conn.close()

    calls = {"updates": [], "rc_save": [], "rc_delete": []}
    import memory.store as store
    import utils.response_cache as rc

    monkeypatch.setattr(store, "search_entries",
                        lambda a, q, n_results=2, min_confidence=0.0: [{"content": "mem fact", "confidence": 0.7}])
    monkeypatch.setattr(store, "update_confidence",
                        lambda a, content, new: calls["updates"].append((content, new)))
    monkeypatch.setattr(rc, "save",
                        lambda a, p, r, model="": calls["rc_save"].append((a, p, r, model)) or True)
    monkeypatch.setattr(rc, "delete_for_message",
                        lambda a, p: calls["rc_delete"].append((a, p)) or True)
    return calls


def test_propagate_up_boosts_and_caches(propagate_env):
    _add_message("kwan", "user", "how to cook rice")
    aid = _add_message("kwan", "assistant", "boil water")
    fb._propagate_impl("kwan", aid, "up")

    assert propagate_env["updates"], "ควรเรียก update_confidence"
    _, new_conf = propagate_env["updates"][0]
    assert new_conf == pytest.approx(0.85)            # 0.7 + 0.15
    assert propagate_env["rc_save"], "up ต้อง save response_cache"


def test_propagate_down_reduces_and_deletes(propagate_env):
    _add_message("kwan", "user", "how to cook rice")
    aid = _add_message("kwan", "assistant", "wrong answer")
    fb._propagate_impl("kwan", aid, "down")

    _, new_conf = propagate_env["updates"][0]
    assert new_conf == pytest.approx(0.45)            # 0.7 - 0.25
    assert propagate_env["rc_delete"], "down ต้องลบ response_cache"


def test_propagate_skips_when_no_prior_user_prompt(propagate_env):
    aid = _add_message("kwan", "assistant", "answer with no preceding question")
    fb._propagate_impl("kwan", aid, "up")
    assert propagate_env["updates"] == []             # ไม่มี user prompt → ไม่ propagate


def test_propagate_ignores_non_assistant_message(propagate_env):
    uid = _add_message("kwan", "user", "just a user message")
    fb._propagate_impl("kwan", uid, "up")
    assert propagate_env["updates"] == []
