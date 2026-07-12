"""Tests สำหรับ scripts/auto_score.py — เฟส 3 RLAIF (Claude auto-score → training pool)

pure: parse/qualifies/state. end-to-end: run_auto_score ด้วย score_fn ที่ inject (ไม่แตะ Claude)
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import pytest

import auto_score as a
from utils.history import _get_conn


def _add(role, content, assistant="kwan", session_id="s1"):
    conn = _get_conn()
    try:
        cur = conn.execute(
            """INSERT INTO messages (assistant, role, content, provider, created_at, session_id)
               VALUES (?,?,?,?,?,?)""",
            (assistant, role, content, "ollama", "2026-01-01T00:00:00", session_id),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


@pytest.fixture
def clean_msgs():
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM messages")
        conn.commit()
    finally:
        conn.close()
    yield


# ── _parse_score ──────────────────────────────────────────────────────────────
def test_parse_score_clean():
    assert a._parse_score('{"score": 8.5, "reason": "ดี"}')["score"] == 8.5


def test_parse_score_clamps_and_noise():
    assert a._parse_score('<think>x</think> {"score": 15}')["score"] == 10.0
    assert a._parse_score('{"score": -3}')["score"] == 0.0


def test_parse_score_invalid():
    assert a._parse_score("ไม่มี json")["score"] == 0.0


def test_qualifies():
    assert a._qualifies(8.0, 7.5) is True
    assert a._qualifies(7.0, 7.5) is False


# ── state ─────────────────────────────────────────────────────────────────────
def test_state_roundtrip(tmp_path):
    p = str(tmp_path / "state.json")
    assert a._load_state(p) == 0          # ไม่มีไฟล์ → 0
    a._save_state(p, 42)
    assert a._load_state(p) == 42


# ── _fetch_unscored ───────────────────────────────────────────────────────────
def test_fetch_unscored_pairs_with_user(clean_msgs):
    _add("user", "q1")
    _add("assistant", "a1")
    conn = _get_conn()
    try:
        items = a._fetch_unscored(conn, 0, 50)
    finally:
        conn.close()
    assert len(items) == 1
    assert items[0]["answer"] == "a1" and items[0]["user"] == "q1"


def test_fetch_unscored_after_id(clean_msgs):
    _add("user", "q1"); a1 = _add("assistant", "a1")
    conn = _get_conn()
    try:
        items = a._fetch_unscored(conn, a1, 50)   # id > a1 → ไม่มี
    finally:
        conn.close()
    assert items == []


# ── run_auto_score (inject score_fn) ──────────────────────────────────────────
def test_run_auto_score_filters_good(clean_msgs, tmp_path):
    _add("user", "q1"); _add("assistant", "good answer ดีมาก")
    _add("user", "q2"); _add("assistant", "bad")
    out = str(tmp_path / "auto.jsonl")
    state = str(tmp_path / "state.json")
    score = lambda user, ans: {"score": 9.0 if "good" in ans else 3.0, "reason": ""}

    r = a.run_auto_score(threshold=7.5, limit=50, out_path=out, state_path=state, score_fn=score)
    assert r["scored"] == 2 and r["qualified"] == 1
    rows = [json.loads(l) for l in open(out, encoding="utf-8")]
    assert len(rows) == 1
    assert rows[0]["messages"][2]["content"] == "good answer ดีมาก"
    assert [m["role"] for m in rows[0]["messages"]] == ["system", "user", "assistant"]


def test_run_auto_score_skips_already_processed(clean_msgs, tmp_path):
    _add("user", "q1"); _add("assistant", "good")
    out = str(tmp_path / "auto.jsonl"); state = str(tmp_path / "state.json")
    score = lambda u, ans: {"score": 9.0, "reason": ""}
    a.run_auto_score(threshold=7.5, out_path=out, state_path=state, score_fn=score)
    r2 = a.run_auto_score(threshold=7.5, out_path=out, state_path=state, score_fn=score)
    assert r2["scored"] == 0          # รอบสองไม่มีใหม่


def test_w3_state_persists_per_item_on_crash(clean_msgs, tmp_path):
    # crash กลาง batch → item ที่ผ่านแล้ว state ถูกบันทึก → re-run ไม่ score ซ้ำ
    _add("user", "q1"); a1 = _add("assistant", "a1")
    _add("user", "q2"); _add("assistant", "a2")
    out = str(tmp_path / "auto.jsonl"); state = str(tmp_path / "state.json")
    n = {"i": 0}

    def boom(u, ans):
        n["i"] += 1
        if n["i"] == 2:
            raise RuntimeError("crash on 2nd item")
        return {"score": 9.0, "reason": ""}

    with pytest.raises(RuntimeError):
        a.run_auto_score(threshold=7.5, out_path=out, state_path=state, score_fn=boom)
    assert a._load_state(state) == a1        # item1 บันทึกแล้ว (ไม่ใช่ 0/ทั้ง batch หาย)


def test_run_auto_score_skips_orphan_assistant(clean_msgs, tmp_path):
    _add("assistant", "no preceding user")   # ไม่มี user นำหน้า
    out = str(tmp_path / "auto.jsonl"); state = str(tmp_path / "state.json")
    r = a.run_auto_score(threshold=5.0, out_path=out, state_path=state,
                         score_fn=lambda u, x: {"score": 9.0, "reason": ""})
    assert r["scored"] == 0 and r["qualified"] == 0
