"""Tests สำหรับ utils/query_rewrite.py — rule-based helpers + LLM rewrite + cache

Mock _client.chat.completions.create. ล้าง lru cache ทุกเทสต์.
"""
import os
import sys
from datetime import datetime
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import utils.query_rewrite as qr


def _fake_client(content=None, raises=False):
    def create(**kwargs):
        if raises:
            raise RuntimeError("lmstudio down")
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


@pytest.fixture(autouse=True)
def clear_cache():
    qr.clear_cache()
    yield
    qr.clear_cache()


# ── rule-based helpers ────────────────────────────────────────────────────────
def test_inject_time_context_english():
    out = qr._inject_time_context("weather today")
    assert datetime.now().strftime("%Y-%m-%d") in out


def test_inject_time_context_thai_spaced():
    # "วันนี้" ต้องถูกเติมวันที่ (แก้บั๊ก \b + วรรณยุกต์ ้ ที่เคยทำให้ไม่ match)
    out = qr._inject_time_context("ขออากาศ วันนี้")
    assert datetime.now().strftime("%d") in out


def test_inject_time_context_thai_glued():
    # ไทยติดกันไม่มีช่องว่าง ("อากาศวันนี้") ก็ต้อง inject ได้ (ไม่พึ่ง word boundary)
    out = qr._inject_time_context("อากาศวันนี้")
    assert datetime.now().strftime("%d") in out


def test_inject_time_context_noop_when_no_time_word():
    assert qr._inject_time_context("stock price") == "stock price"


def test_extract_keywords_drops_stopwords_and_short():
    kw = qr._extract_keywords_rule("what is the weather in bangkok")
    assert "weather" in kw and "bangkok" in kw
    assert "the" not in kw and "is" not in kw


def test_extract_keywords_dedup_and_cap():
    kw = qr._extract_keywords_rule("alpha beta gamma delta epsilon zeta eta", max_n=3)
    assert len(kw) == 3


# ── _parse_llm_json ───────────────────────────────────────────────────────────
def test_parse_json_extracts_from_noise():
    data = qr._parse_llm_json('สวัสดี here: {"rewritten": "x", "keywords": ["a"]} จบ')
    assert data["rewritten"] == "x"


def test_parse_json_invalid_returns_none():
    assert qr._parse_llm_json("no json here") is None
    assert qr._parse_llm_json("{broken json") is None


# ── _should_rewrite ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("q,expected", [
    ("", False),
    ("abc", False),       # < 4
    ("hello world", True),
    ("x" * 501, False),   # ยาวเกิน
])
def test_should_rewrite(q, expected):
    assert qr._should_rewrite(q) is expected


# ── RewriteResult.all_queries ─────────────────────────────────────────────────
def test_all_queries_dedup_and_strip():
    r = qr.RewriteResult(original="o", rewritten="main", sub_queries=["main", " sub ", ""])
    assert r.all_queries == ["main", "sub"]


# ── rewrite_query — fallback & LLM paths ──────────────────────────────────────
def test_rewrite_empty_query():
    r = qr.rewrite_query("")
    assert r.original == "" and r.rewritten == ""


def test_rewrite_disabled_uses_fallback(monkeypatch):
    monkeypatch.setattr(qr, "_REWRITE_ENABLED", False)
    r = qr.rewrite_query("weather today")
    assert r.used_llm is False
    assert datetime.now().strftime("%Y-%m-%d") in r.rewritten   # time injected


def test_rewrite_llm_success(monkeypatch):
    monkeypatch.setattr(qr, "_REWRITE_ENABLED", True)
    payload = '{"rewritten": "weather in bangkok now", "sub_queries": ["temp", "rain", "wind", "extra"], "keywords": ["a","b","c","d","e","f","g"]}'
    monkeypatch.setattr(qr, "_client", _fake_client(content=payload))
    r = qr.rewrite_query("weather")
    assert r.used_llm is True
    assert r.rewritten == "weather in bangkok now"
    assert len(r.sub_queries) == 3      # capped 3
    assert len(r.keywords) == 6         # capped 6


def test_rewrite_llm_non_json_falls_back(monkeypatch):
    monkeypatch.setattr(qr, "_REWRITE_ENABLED", True)
    monkeypatch.setattr(qr, "_client", _fake_client(content="sorry I cannot"))
    r = qr.rewrite_query("weather forecast please")
    assert r.used_llm is False          # fallback


def test_rewrite_llm_raises_falls_back(monkeypatch):
    monkeypatch.setattr(qr, "_REWRITE_ENABLED", True)
    monkeypatch.setattr(qr, "_client", _fake_client(raises=True))
    r = qr.rewrite_query("weather forecast please")
    assert r.used_llm is False


def test_rewrite_result_caches(monkeypatch):
    monkeypatch.setattr(qr, "_REWRITE_ENABLED", True)
    calls = {"n": 0}

    def create(**kwargs):
        calls["n"] += 1
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content='{"rewritten":"r","sub_queries":[],"keywords":[]}'))])

    monkeypatch.setattr(qr, "_client",
                        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    qr.rewrite_query("same query here")
    qr.rewrite_query("same query here")
    assert calls["n"] == 1               # ครั้งที่ 2 มาจาก lru cache
