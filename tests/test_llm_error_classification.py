"""utils/llm.py ต้องจัดประเภท error ด้วยชนิด exception/status code ก่อน แล้วค่อย substring (audit 2026-09-24 MEDIUM)

เดิม `"model" in err` = "ไม่พบโมเดล ให้ ollama pull" — แต่ข้อความ OOM จริงของ Ollama คือ
`model requires more system memory (11.3 GiB) than is available (9.2 GiB)` (issue bolt.diy #558) ⇒ ตกสาขาผิด
· openai SDK 2.44: `APITimeoutError` (str = "Request timed out.") ไม่มีคำว่า timeout → ไม่เข้าสาขา retry
· `APITimeoutError` สืบทอด `APIConnectionError` (`_exceptions.py:111`) ⇒ ต้องเช็ค timeout ก่อน connection
· Kimi: `"invalid" in err` จับ 400 "invalid request" เป็น "API key ไม่ถูกต้อง"
"""
import os
import sys
from types import SimpleNamespace

import httpx
import openai
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils.llm as llm
from google.genai import errors as genai_errors

REQ = httpx.Request("POST", "http://local/v1/chat/completions")


def _status(cls, status, msg):
    return cls(msg, response=httpx.Response(status, request=REQ), body=None)


def _mk_stream(texts):
    return [SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=t))]) for t in texts]


class _Fake:
    def __init__(self, behaviors):
        self.b, self.calls = behaviors, 0
    def create(self, **kw):
        b = self.b[min(self.calls, len(self.b) - 1)]
        self.calls += 1
        if isinstance(b, Exception):
            raise b
        return _mk_stream(b)


def _patch(monkeypatch, client_attr, behaviors):
    fake = _Fake(behaviors)
    monkeypatch.setattr(getattr(llm, client_attr), "chat", SimpleNamespace(completions=fake))
    monkeypatch.setattr(llm.time, "sleep", lambda *a, **k: None)
    return fake


MSGS = [{"role": "user", "content": "hi"}]
OOM = "model requires more system memory (11.3 GiB) than is available (9.2 GiB)"


# ── Ollama ────────────────────────────────────────────────────────────────────
def test_ollama_OOM_ต้องบอกว่า_RAM_ไม่พอ_ไม่ใช่_ollama_pull_และไม่_retry(monkeypatch):
    fake = _patch(monkeypatch, "ollama_client", [_status(openai.InternalServerError, 500, OOM)])
    out = "".join(llm._stream_ollama(MSGS))
    assert "ollama pull" not in out and "ไม่พบ" not in out, out
    assert "RAM" in out or "หน่วยความจำ" in out, out
    assert fake.calls == 1, "OOM เป็น deterministic — retry ไม่ช่วย"


def test_ollama_404_จาก_SDK_คือไม่พบโมเดล(monkeypatch):
    fake = _patch(monkeypatch, "ollama_client", [_status(openai.NotFoundError, 404, "model 'x' not found, try pulling it first")])
    out = "".join(llm._stream_ollama(MSGS))
    assert "ollama pull" in out
    assert fake.calls == 1


def test_ollama_APITimeoutError_ต้อง_retry(monkeypatch):
    fake = _patch(monkeypatch, "ollama_client", [openai.APITimeoutError(request=REQ), ["ok"]])
    out = "".join(llm._stream_ollama(MSGS))
    assert "ok" in out, out
    assert fake.calls == 2, "str(APITimeoutError)='Request timed out.' ไม่มีคำว่า timeout → เดิมไม่ retry"


def test_ollama_APITimeoutError_หมด_retry_ต้องบอกว่า_timeout(monkeypatch):
    _patch(monkeypatch, "ollama_client", [openai.APITimeoutError(request=REQ)])
    out = "".join(llm._stream_ollama(MSGS))
    assert "timeout" in out.lower() and "เชื่อมต่อ" not in out, out


# ── LM Studio ─────────────────────────────────────────────────────────────────
def test_lmstudio_OOM_ต้องไม่กลายเป็น_ไม่พบ_model(monkeypatch):
    _patch(monkeypatch, "lmstudio_client", [_status(openai.InternalServerError, 500, "Model loading aborted: insufficient system resources")])
    out = "".join(llm._stream_lmstudio(MSGS, model="m"))
    assert "ไม่พบ model" not in out, out
    assert "RAM" in out, out


def test_lmstudio_404_คือไม่พบ_model(monkeypatch):
    _patch(monkeypatch, "lmstudio_client", [_status(openai.NotFoundError, 404, "no such model")])
    out = "".join(llm._stream_lmstudio(MSGS, model="m"))
    assert "ไม่พบ model" in out, out


def test_lmstudio_APIConnectionError_ต้อง_raise_ให้_cascade(monkeypatch):
    _patch(monkeypatch, "lmstudio_client", [openai.APIConnectionError(request=REQ)])
    with pytest.raises(llm.LMStudioUnavailable):
        list(llm._stream_lmstudio(MSGS, model="m"))


# ── Kimi ──────────────────────────────────────────────────────────────────────
@pytest.fixture
def _kimi(monkeypatch):
    monkeypatch.setattr(llm, "kimi_client", SimpleNamespace(chat=None))


def test_kimi_400_invalid_request_ไม่ใช่_API_key_ผิด(monkeypatch, _kimi):
    _patch(monkeypatch, "kimi_client", [_status(openai.BadRequestError, 400, "invalid request: messages[0] is empty")])
    out = "".join(llm._stream_kimi(MSGS))
    assert "MOONSHOT_API_KEY" not in out, out


def test_kimi_401_คือ_API_key_ผิด(monkeypatch, _kimi):
    _patch(monkeypatch, "kimi_client", [_status(openai.AuthenticationError, 401, "Unauthorized")])
    out = "".join(llm._stream_kimi(MSGS))
    assert "MOONSHOT_API_KEY" in out


def test_kimi_429_คือ_rate_limit(monkeypatch, _kimi):
    _patch(monkeypatch, "kimi_client", [_status(openai.RateLimitError, 429, "Too Many Requests")])
    out = "".join(llm._stream_kimi(MSGS))
    assert "rate limit" in out


# ── Gemini (google-genai APIError.code) ───────────────────────────────────────
class _FakeModels:
    def __init__(self, exc):
        self.exc = exc
    def generate_content_stream(self, **kw):
        raise self.exc


def _gemini(monkeypatch, exc):
    monkeypatch.setattr(llm, "gemini_client", SimpleNamespace(models=_FakeModels(exc)))
    monkeypatch.setattr(llm.time, "sleep", lambda *a, **k: None)


def test_gemini_code_401_คือ_key_ผิด(monkeypatch):
    _gemini(monkeypatch, genai_errors.APIError(401, {"error": {"status": "UNAUTHENTICATED", "message": "bad"}}))
    with pytest.raises(llm.GeminiUnavailable) as ei:
        list(llm._stream_gemini(MSGS))
    assert "key" in str(ei.value).lower()


def test_gemini_code_429_คือ_quota(monkeypatch):
    _gemini(monkeypatch, genai_errors.APIError(429, {"error": {"status": "RESOURCE_EXHAUSTED", "message": "q"}}))
    with pytest.raises(llm.GeminiQuotaExhausted):
        list(llm._stream_gemini(MSGS))


def test_gemini_ข้อความมี_401_แต่_code_ไม่ใช่_ต้องไม่ใช่_key_ผิด(monkeypatch):
    """เดิม '401' in err — ข้อความ error ที่บังเอิญมีเลข 401 (เช่น request id) กลายเป็น "API key invalid"""
    _gemini(monkeypatch, genai_errors.APIError(500, {"error": {"status": "INTERNAL", "message": "trace 401aa (internal)"}}))
    with pytest.raises(llm.GeminiUnavailable) as ei:
        list(llm._stream_gemini(MSGS))
    assert "key invalid" not in str(ei.value).lower()


def test_400_ของ_SDK_ที่ข้อความมี_not_found_ต้องไม่กลายเป็นไม่พบโมเดล(monkeypatch):
    """status จาก SDK ชี้ขาดแล้ว — ห้ามให้ substring เดาต่อ (400 'tool not found' ≠ ไม่พบโมเดล)"""
    fake = _patch(monkeypatch, "ollama_client", [_status(openai.BadRequestError, 400, "function 'x' not found in tools")])
    out = "".join(llm._stream_ollama(MSGS))
    assert "ollama pull" not in out, out
    assert fake.calls == 1
