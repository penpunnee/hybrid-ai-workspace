"""Tests สำหรับ scripts/eval_kwan.py — eval gate logic (verdict parse + aggregate + judge)

ทดสอบส่วน logic ล้วน (ไม่แตะ network): _parse_verdict, _aggregate, _judge (mock judge)
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import pytest

import eval_kwan as ek


# ── _parse_verdict ────────────────────────────────────────────────────────────
def test_parse_verdict_clean():
    assert ek._parse_verdict('{"winner":"A","reason":"ดีกว่า"}')["winner"] == "A"


def test_parse_verdict_noise_and_think():
    out = ek._parse_verdict('<think>คิด...</think> สรุป: {"winner":"B","reason":"ครบกว่า"} จบ')
    assert out["winner"] == "B"


def test_parse_verdict_tie_and_invalid():
    assert ek._parse_verdict('{"winner":"tie"}')["winner"] == "tie"
    assert ek._parse_verdict("ไม่มี json")["winner"] == "tie"        # fallback
    assert ek._parse_verdict('{"winner":"X"}')["winner"] == "tie"     # ค่าแปลก → tie


# ── _aggregate ────────────────────────────────────────────────────────────────
def _mk(winners):
    return [{"q": "x", "winner": w} for w in winners]


def test_aggregate_candidate_passes():
    # candidate ชนะ 10 แพ้ 3 เสมอ 3 → win_rate 0.769 ≥ 0.55 → PASS
    res = _mk(["candidate"] * 10 + ["baseline"] * 3 + ["tie"] * 3)
    agg = ek._aggregate(res, threshold=0.55)
    assert agg["win_rate"] == pytest.approx(10 / 13, abs=0.01)
    assert agg["passed"] is True
    assert agg["inconclusive"] is False


def test_aggregate_candidate_fails_when_worse():
    res = _mk(["candidate"] * 4 + ["baseline"] * 10 + ["tie"] * 2)
    agg = ek._aggregate(res, threshold=0.55)
    assert agg["passed"] is False          # win_rate ~0.29 < 0.55


def test_aggregate_boundary_at_threshold():
    res = _mk(["candidate"] * 6 + ["baseline"] * 4)   # 0.6
    assert ek._aggregate(res, threshold=0.6)["passed"] is True
    assert ek._aggregate(res, threshold=0.61)["passed"] is False


def test_aggregate_inconclusive_when_too_few_decisive():
    # เสมอเกือบหมด → decisive < min_games → inconclusive → ไม่ผ่าน
    res = _mk(["tie"] * 14 + ["candidate"] * 2)
    agg = ek._aggregate(res, threshold=0.55, min_games=8)
    assert agg["inconclusive"] is True
    assert agg["passed"] is False


def test_aggregate_no_decisive():
    agg = ek._aggregate(_mk(["tie"] * 5), threshold=0.55)
    assert agg["win_rate"] is None and agg["passed"] is False


# ── _judge (mock judge client) ────────────────────────────────────────────────
class _FakeJudge:
    def __init__(self, text):
        self._text = text
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self._text)])


def test_judge_returns_winner():
    assert ek._judge(_FakeJudge('{"winner":"A"}'), "m", "q", "a", "b") == "A"
    assert ek._judge(_FakeJudge('{"winner":"B","reason":"x"}'), "m", "q", "a", "b") == "B"
    assert ek._judge(_FakeJudge("garbage"), "m", "q", "a", "b") == "tie"


def test_eval_questions_exist():
    assert len(ek.EVAL_QUESTIONS) >= 12      # ชุดข้อสอบต้องมีพอควร + หลากหลาย
