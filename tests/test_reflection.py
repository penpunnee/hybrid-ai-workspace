"""Tests สำหรับ utils/reflection.py — critic LLM parse + safety downgrade

Mock _client.chat.completions.create. ทดสอบ pure helpers + reflect_answer logic.
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import utils.reflection as rf


def _fake_client(content=None, raises=False):
    def create(**kwargs):
        if raises:
            raise RuntimeError("lmstudio down")
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


_LONG_DRAFT = "นี่คือคำตอบที่ยาวพอสำหรับให้ critic ตรวจสอบได้ครบทุกมิติของคำถาม " * 3


# ── _parse_json ───────────────────────────────────────────────────────────────
def test_parse_json_strips_think_tags():
    data = rf._parse_json('<think>reasoning...</think> {"score": 0.8, "verdict": "ok"}')
    assert data["score"] == 0.8


def test_parse_json_invalid_returns_none():
    assert rf._parse_json("no json") is None


# ── should_reflect ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("prompt,draft,expected", [
    ("question long enough", "x" * 150, True),
    ("question long enough", "short", False),     # draft < 100
    ("hi", "x" * 150, False),                      # prompt < 5
])
def test_should_reflect(prompt, draft, expected):
    assert rf.should_reflect(prompt, draft) is expected


# ── Reflection.needs_revision property ────────────────────────────────────────
def test_needs_revision_true():
    r = rf.Reflection(verdict="needs_revision", revised="fixed answer")
    assert r.needs_revision is True


def test_needs_revision_false_when_ok():
    assert rf.Reflection(verdict="ok", revised="x").needs_revision is False


def test_needs_revision_false_when_revised_empty():
    assert rf.Reflection(verdict="needs_revision", revised="  ").needs_revision is False


# ── reflect_answer ────────────────────────────────────────────────────────────
def test_reflect_short_draft_skips_llm():
    r = rf.reflect_answer("prompt", "too short")
    assert r.used_llm is False
    assert r.verdict == "ok"


def test_reflect_good_answer_ok(monkeypatch):
    monkeypatch.setattr(rf, "_client",
                        _fake_client('{"score": 0.95, "issues": [], "verdict": "ok", "revised": ""}'))
    r = rf.reflect_answer("prompt question", _LONG_DRAFT)
    assert r.used_llm is True
    assert r.verdict == "ok"
    assert r.score == pytest.approx(0.95)


def test_reflect_needs_revision(monkeypatch):
    monkeypatch.setattr(rf, "_client", _fake_client(
        '{"score": 0.5, "issues": ["ตอบไม่ครบ"], "verdict": "needs_revision", "revised": "คำตอบที่แก้แล้ว"}'))
    r = rf.reflect_answer("prompt question", _LONG_DRAFT, threshold=0.7)
    assert r.verdict == "needs_revision"
    assert r.revised == "คำตอบที่แก้แล้ว"
    assert r.needs_revision is True


def test_reflect_downgrades_when_score_above_threshold(monkeypatch):
    # verdict ขอแก้ แต่ score >= threshold → downgrade เป็น ok + ล้าง revised
    monkeypatch.setattr(rf, "_client", _fake_client(
        '{"score": 0.85, "verdict": "needs_revision", "revised": "x"}'))
    r = rf.reflect_answer("prompt question", _LONG_DRAFT, threshold=0.7)
    assert r.verdict == "ok"
    assert r.revised == ""


def test_reflect_downgrades_when_revised_empty(monkeypatch):
    monkeypatch.setattr(rf, "_client", _fake_client(
        '{"score": 0.4, "verdict": "needs_revision", "revised": ""}'))
    r = rf.reflect_answer("prompt question", _LONG_DRAFT, threshold=0.7)
    assert r.verdict == "ok"


def test_reflect_llm_raises_safe_default(monkeypatch):
    monkeypatch.setattr(rf, "_client", _fake_client(raises=True))
    r = rf.reflect_answer("prompt question", _LONG_DRAFT)
    assert r.verdict == "ok"
    assert r.used_llm is False


def test_reflect_non_json_safe_default(monkeypatch):
    monkeypatch.setattr(rf, "_client", _fake_client("ขอโทษ ตอบไม่ได้"))
    r = rf.reflect_answer("prompt question", _LONG_DRAFT)
    assert r.verdict == "ok"


def test_reflect_bad_score_defaults_to_one(monkeypatch):
    monkeypatch.setattr(rf, "_client", _fake_client('{"score": "high", "verdict": "ok"}'))
    r = rf.reflect_answer("prompt question", _LONG_DRAFT)
    assert r.score == pytest.approx(1.0)
