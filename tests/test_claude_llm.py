"""Tests สำหรับ Claude (Anthropic) provider ใน utils/llm.py

Mock anthropic_client.messages.stream — ไม่แตะ network. ตรวจ message conversion,
prompt caching (cache_control), vision, adaptive thinking opt-in, error classify, dispatch.
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import utils.llm as llm


# ── fake Anthropic client ─────────────────────────────────────────────────────
class _FakeStream:
    def __init__(self, texts):
        self._texts = texts

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    @property
    def text_stream(self):
        yield from self._texts

    def get_final_message(self):
        return SimpleNamespace(usage=SimpleNamespace(
            input_tokens=10, output_tokens=5,
            cache_creation_input_tokens=0, cache_read_input_tokens=8,
        ))


class _FakeMessages:
    def __init__(self, texts=("Hello", " world"), raise_exc=None):
        self.captured = None
        self._texts = texts
        self._raise = raise_exc

    def stream(self, **kwargs):
        self.captured = kwargs
        if self._raise is not None:
            raise self._raise
        return _FakeStream(self._texts)


class _FakeClient:
    def __init__(self, **kw):
        self.messages = _FakeMessages(**kw)


@pytest.fixture
def fake_claude(monkeypatch):
    client = _FakeClient()
    monkeypatch.setattr(llm, "anthropic_client", client)
    monkeypatch.setattr(llm, "CLAUDE_THINKING", "off")
    monkeypatch.setattr(llm, "CLAUDE_MODEL", "claude-opus-4-8")
    return client


# ── unconfigured ──────────────────────────────────────────────────────────────
def test_unconfigured_no_key(monkeypatch):
    monkeypatch.setattr(llm, "anthropic_client", None)
    out = list(llm._stream_claude([{"role": "user", "content": "hi"}]))
    assert "ANTHROPIC_API_KEY" in out[0]


def test_unconfigured_no_sdk(monkeypatch):
    monkeypatch.setattr(llm, "anthropic_client", None)
    monkeypatch.setattr(llm, "anthropic", None)
    out = list(llm._stream_claude([{"role": "user", "content": "hi"}]))
    assert "pip install anthropic" in out[0]


# ── streaming + message conversion ────────────────────────────────────────────
def test_stream_yields_text(fake_claude):
    out = "".join(llm._stream_claude([{"role": "user", "content": "hi"}]))
    assert out == "Hello world"


def test_system_becomes_cached_block(fake_claude):
    list(llm._stream_claude([
        {"role": "system", "content": "You are helpful"},
        {"role": "user", "content": "hi"},
    ]))
    sys_block = fake_claude.messages.captured["system"]
    assert sys_block[0]["text"] == "You are helpful"
    assert sys_block[0]["cache_control"] == {"type": "ephemeral"}


def test_system_excluded_from_messages_and_roles_mapped(fake_claude):
    list(llm._stream_claude([
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "q2"},
    ]))
    msgs = fake_claude.messages.captured["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert all(m["content"] for m in msgs)


def test_no_system_omits_system_kwarg(fake_claude):
    list(llm._stream_claude([{"role": "user", "content": "hi"}]))
    assert "system" not in fake_claude.messages.captured


def test_vision_adds_image_block(fake_claude):
    list(llm._stream_claude(
        [{"role": "user", "content": "what is this"}],
        image_b64="BASE64DATA", image_mime="image/png",
    ))
    content = fake_claude.messages.captured["messages"][-1]["content"]
    assert content[0] == {"type": "text", "text": "what is this"}
    assert content[1]["type"] == "image"
    assert content[1]["source"]["data"] == "BASE64DATA"
    assert content[1]["source"]["media_type"] == "image/png"


def test_first_message_forced_to_user(fake_claude):
    # ประวัติเริ่มด้วย assistant → ต้อง insert user นำหน้า (Claude requirement)
    list(llm._stream_claude([{"role": "assistant", "content": "a"}]))
    assert fake_claude.messages.captured["messages"][0]["role"] == "user"


def test_max_tokens_passed(fake_claude, monkeypatch):
    monkeypatch.setattr(llm, "CLAUDE_MAX_TOKENS", 1234)
    list(llm._stream_claude([{"role": "user", "content": "hi"}]))
    assert fake_claude.messages.captured["max_tokens"] == 1234


# ── adaptive thinking opt-in ──────────────────────────────────────────────────
def test_default_no_thinking(fake_claude):
    list(llm._stream_claude([{"role": "user", "content": "hi"}]))
    assert "thinking" not in fake_claude.messages.captured


def test_adaptive_thinking_kwargs(fake_claude, monkeypatch):
    monkeypatch.setattr(llm, "CLAUDE_THINKING", "adaptive")
    monkeypatch.setattr(llm, "CLAUDE_EFFORT", "high")
    list(llm._stream_claude([{"role": "user", "content": "hi"}]))
    cap = fake_claude.messages.captured
    assert cap["thinking"] == {"type": "adaptive"}
    assert cap["output_config"] == {"effort": "high"}


# ── error classification (typed exceptions) ───────────────────────────────────
class _AuthErr(Exception):
    pass


class _RateErr(Exception):
    pass


class _StatusErr(Exception):
    def __init__(self, msg, status_code=503):
        super().__init__(msg)
        self.status_code = status_code


@pytest.fixture
def fake_exc_module(monkeypatch):
    monkeypatch.setattr(llm, "anthropic", SimpleNamespace(
        AuthenticationError=_AuthErr,
        RateLimitError=_RateErr,
        APIStatusError=_StatusErr,
    ))


def _run_with_raise(monkeypatch, exc):
    monkeypatch.setattr(llm, "anthropic_client", _FakeClient(raise_exc=exc))
    monkeypatch.setattr(llm, "CLAUDE_THINKING", "off")
    return "".join(llm._stream_claude([{"role": "user", "content": "hi"}]))


def test_error_auth(monkeypatch, fake_exc_module):
    out = _run_with_raise(monkeypatch, _AuthErr("bad key"))
    assert "ANTHROPIC_API_KEY ไม่ถูกต้อง" in out


def test_error_rate_limit(monkeypatch, fake_exc_module):
    out = _run_with_raise(monkeypatch, _RateErr("429"))
    assert "rate limit" in out


def test_error_server_5xx(monkeypatch, fake_exc_module):
    out = _run_with_raise(monkeypatch, _StatusErr("boom", status_code=503))
    assert "server error" in out and "503" in out


def test_error_generic(monkeypatch, fake_exc_module):
    out = _run_with_raise(monkeypatch, RuntimeError("weird"))
    assert out.startswith("❌ Claude error")


# ── dispatch via stream_response ──────────────────────────────────────────────
def test_dispatch_routes_to_claude(fake_claude):
    out = "".join(llm.stream_response([{"role": "user", "content": "hi"}], provider="claude"))
    assert out == "Hello world"


def test_dispatch_claude_with_image_not_gemini(fake_claude):
    # provider=claude + image ต้องไป Claude (ไม่ตกไป gemini catch-all)
    out = "".join(llm.stream_response(
        [{"role": "user", "content": "hi"}], provider="claude",
        image_b64="X", image_mime="image/jpeg",
    ))
    assert out == "Hello world"
    assert fake_claude.messages.captured["messages"][-1]["content"][1]["type"] == "image"
