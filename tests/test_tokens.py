"""Tests สำหรับ utils/tokens.py — approx token counting + context limits"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from utils.tokens import count_tokens_approx, get_context_limit, get_token_status


# ── count_tokens_approx: total chars // 3 ──
def test_count_tokens_sums_content_chars_div3():
    msgs = [{"content": "abcdef"}, {"content": "xyz"}]  # 9 chars
    assert count_tokens_approx(msgs) == 3


def test_count_tokens_ignores_missing_content():
    assert count_tokens_approx([{"role": "user"}]) == 0


def test_count_tokens_empty_list():
    assert count_tokens_approx([]) == 0


# ── get_context_limit: known model → limit, unknown → 8192 default ──
@pytest.mark.parametrize("model,expected", [
    ("llama3", 4096),
    ("llama3.2", 128000),
    ("gemini-2.5-flash", 1048576),
])
def test_get_context_limit_known(model, expected):
    assert get_context_limit(model) == expected


def test_get_context_limit_unknown_defaults_8192():
    assert get_context_limit("some-random-model") == 8192


# ── get_token_status: (color, message) ตาม pct ──
@pytest.mark.parametrize("used,limit,color", [
    (50, 100, "normal"),    # 0.50
    (60, 100, "warning"),   # 0.60 boundary → warning
    (84, 100, "warning"),   # 0.84
    (85, 100, "error"),     # 0.85 boundary → error
    (99, 100, "error"),
])
def test_get_token_status_color(used, limit, color):
    c, msg = get_token_status(used, limit)
    assert c == color
    assert "tokens" in msg


def test_get_token_status_zero_limit_is_normal():
    c, _ = get_token_status(0, 0)
    assert c == "normal"
