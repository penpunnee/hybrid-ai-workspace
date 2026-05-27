"""Tests สำหรับ utils/context_budget.py — score filter + token-budget trim"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from utils.context_budget import approx_tokens, filter_by_score, trim_to_budget, stats


# ── approx_tokens: 4 chars ≈ 1 token, ขั้นต่ำ 1 ถ้ามี text ──
@pytest.mark.parametrize("text,expected", [
    ("", 0),
    ("a", 1),        # max(1, 0)
    ("abcd", 1),
    ("abcdefgh", 2),
])
def test_approx_tokens(text, expected):
    assert approx_tokens(text) == expected


# ── filter_by_score: เก็บ score >= min_score; ไม่มี score → default 1.0 ──
def test_filter_by_score_drops_below_threshold():
    items = [{"score": 0.5}, {"score": 0.1}, {"score": 0.3}]
    kept = filter_by_score(items, min_score=0.3)
    assert [it["score"] for it in kept] == [0.5, 0.3]


def test_filter_by_score_missing_score_kept_as_one():
    items = [{"text": "x"}]  # ไม่มี score → default 1.0 → ผ่าน
    assert filter_by_score(items, min_score=0.9) == items


def test_filter_by_score_empty():
    assert filter_by_score([]) == []


# ── trim_to_budget: sort score desc แล้วตัดเมื่อ tokens เกิน budget ──
def test_trim_sorts_by_score_desc():
    items = [{"text": "a", "score": 0.2}, {"text": "b", "score": 0.9}]
    out = trim_to_budget(items, max_tokens=1000)
    assert [it["score"] for it in out] == [0.9, 0.2]


def test_trim_stops_when_budget_exceeded():
    # text 40 chars → ~10 tokens ต่อ item; budget 15 → ได้แค่ตัวแรก
    items = [
        {"text": "x" * 40, "score": 0.9},
        {"text": "y" * 40, "score": 0.5},
    ]
    out = trim_to_budget(items, max_tokens=15)
    assert len(out) == 1 and out[0]["score"] == 0.9


def test_trim_keeps_first_item_even_if_over_budget():
    """item แรกต้องถูกเก็บเสมอ แม้ใหญ่เกิน budget (กัน context ว่าง)"""
    items = [{"text": "z" * 400, "score": 0.9}]  # ~100 tokens
    out = trim_to_budget(items, max_tokens=10)
    assert len(out) == 1


def test_trim_reads_alternate_text_keys():
    items = [{"content": "hello world here", "score": 0.8}]
    out = trim_to_budget(items, max_tokens=1000)
    assert len(out) == 1


def test_trim_empty():
    assert trim_to_budget([]) == []


# ── stats: savings summary ──
def test_stats_savings_pct():
    before = [{"text": "x" * 40}, {"text": "y" * 40}]  # ~20 tokens
    after = [{"text": "x" * 40}]                         # ~10 tokens
    s = stats(before, after)
    assert s["items_before"] == 2 and s["items_after"] == 1
    assert s["savings_pct"] == 50.0
