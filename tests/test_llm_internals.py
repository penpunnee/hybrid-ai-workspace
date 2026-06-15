"""Tests สำหรับ utils/llm.py internals — retry, error-mapping, health check

ครอบส่วนที่ test_llm_routing.py ยังไม่แตะ:
  - _stream_ollama: retry + exponential backoff + error classification
  - _stream_gemini: map error → GeminiQuotaExhausted / GeminiUnavailable
  - check_ollama_health: connection / model-not-found / ok (+ cache bypass)
"""
import os
import sys
import json
import urllib.request
import urllib.error
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import utils.llm as llm
from utils.llm import GeminiQuotaExhausted, GeminiUnavailable


# ── helpers ──────────────────────────────────────────────────────────────────
def _mk_stream(texts):
    """fake OpenAI-style stream: chunk.choices[0].delta.content"""
    return [SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=t))])
            for t in texts]


class _FakeCompletions:
    """create() เล่นตาม behaviors ทีละครั้ง (Exception=raise, list=stream)"""
    def __init__(self, behaviors):
        self._behaviors = behaviors
        self._i = 0

    def create(self, **kwargs):
        b = self._behaviors[min(self._i, len(self._behaviors) - 1)]
        self._i += 1
        if isinstance(b, Exception):
            raise b
        return _mk_stream(b)


def _patch_ollama(monkeypatch, behaviors):
    monkeypatch.setattr(llm.ollama_client, "chat",
                        SimpleNamespace(completions=_FakeCompletions(behaviors)))
    monkeypatch.setattr(llm.time, "sleep", lambda *a, **k: None)  # ไม่หน่วงจริง


# ── _stream_ollama ────────────────────────────────────────────────────────────
def test_ollama_success_yields_content(monkeypatch):
    _patch_ollama(monkeypatch, [["hello", " world"]])
    out = "".join(llm._stream_ollama([{"role": "user", "content": "hi"}]))
    assert out == "hello world"


def test_ollama_model_not_found_no_retry(monkeypatch):
    _patch_ollama(monkeypatch, [Exception("model 'llama3' not found")])
    out = "".join(llm._stream_ollama([{"role": "user", "content": "hi"}]))
    assert "ไม่พบ" in out or "ollama pull" in out


def test_ollama_connection_retries_then_succeeds(monkeypatch):
    _patch_ollama(monkeypatch, [ConnectionError("connection refused"), ["recovered"]])
    out = "".join(llm._stream_ollama([{"role": "user", "content": "hi"}]))
    assert "ลองใหม่" in out         # แจ้ง retry ครั้งแรก
    assert "recovered" in out        # สำเร็จหลัง retry


def test_ollama_connection_all_retries_fail(monkeypatch):
    _patch_ollama(monkeypatch, [ConnectionError("connection refused")])
    out = "".join(llm._stream_ollama([{"role": "user", "content": "hi"}]))
    assert "ครั้งแล้ว" in out        # "ลอง N ครั้งแล้ว"
    assert "ollama serve" in out


# ── _stream_gemini error mapping ──────────────────────────────────────────────
class _FakeModels:
    def __init__(self, exc):
        self._exc = exc

    def generate_content_stream(self, **k):
        raise self._exc


def _patch_gemini(monkeypatch, exc):
    monkeypatch.setattr(llm, "gemini_client", SimpleNamespace(models=_FakeModels(exc)))


def test_gemini_quota_maps_to_quota_exhausted(monkeypatch):
    _patch_gemini(monkeypatch, Exception("429 RESOURCE_EXHAUSTED: quota"))
    with pytest.raises(GeminiQuotaExhausted):
        list(llm._stream_gemini([{"role": "user", "content": "hi"}]))


def test_gemini_invalid_key_maps_to_unavailable(monkeypatch):
    _patch_gemini(monkeypatch, Exception("API_KEY_INVALID: bad key"))
    with pytest.raises(GeminiUnavailable):
        list(llm._stream_gemini([{"role": "user", "content": "hi"}]))


def test_gemini_generic_error_maps_to_unavailable(monkeypatch):
    _patch_gemini(monkeypatch, Exception("some network blip"))
    with pytest.raises(GeminiUnavailable):
        list(llm._stream_gemini([{"role": "user", "content": "hi"}]))


def test_gemini_no_client_yields_setup_hint(monkeypatch):
    monkeypatch.setattr(llm, "gemini_client", None)
    out = "".join(llm._stream_gemini([{"role": "user", "content": "hi"}]))
    assert "GEMINI_API_KEY" in out


# ── _stream_gemini transient retry + content coercion (session 2026-06-15) ────
class _FakeModelsSeq:
    """generate_content_stream ทีละ behavior: Exception=raise, list=yield chunks"""
    def __init__(self, behaviors):
        self._behaviors = list(behaviors)
        self.calls = 0

    def generate_content_stream(self, **k):
        b = self._behaviors[min(self.calls, len(self._behaviors) - 1)]
        self.calls += 1
        if isinstance(b, Exception):
            raise b
        return iter(SimpleNamespace(text=t) for t in b)


def _patch_gemini_seq(monkeypatch, behaviors):
    monkeypatch.setattr(llm.time, "sleep", lambda *a, **k: None)  # ไม่หน่วงจริง
    fake = _FakeModelsSeq(behaviors)
    monkeypatch.setattr(llm, "gemini_client", SimpleNamespace(models=fake))
    return fake


def test_gemini_transient_503_retries_then_succeeds(monkeypatch):
    # 503 UNAVAILABLE = Google ล่มชั่วคราว → ต้อง retry ไม่เด้ง fallback ทันที
    fake = _patch_gemini_seq(monkeypatch, [
        Exception("503 UNAVAILABLE: The service is currently unavailable"),
        ["recovered"],
    ])
    out = "".join(llm._stream_gemini([{"role": "user", "content": "hi"}]))
    assert "recovered" in out
    assert fake.calls == 2  # retry หนึ่งครั้งแล้วสำเร็จ


def test_gemini_transient_all_fail_maps_unavailable(monkeypatch):
    fake = _patch_gemini_seq(monkeypatch, [Exception("503 UNAVAILABLE")] * 5)
    with pytest.raises(GeminiUnavailable):
        list(llm._stream_gemini([{"role": "user", "content": "hi"}]))
    assert fake.calls >= 2  # พยายามมากกว่าหนึ่งครั้งก่อนยอมแพ้


def test_gemini_quota_not_retried(monkeypatch):
    # 429 ไม่ใช่ transient — ห้าม retry (เปลือง quota) เด้ง QuotaExhausted ทันที
    fake = _patch_gemini_seq(monkeypatch, [Exception("429 RESOURCE_EXHAUSTED")] * 5)
    with pytest.raises(GeminiQuotaExhausted):
        list(llm._stream_gemini([{"role": "user", "content": "hi"}]))
    assert fake.calls == 1


def test_gemini_nonstr_content_coerced(monkeypatch):
    # content เป็น list/dict → เคย crash ด้วย pydantic "valid part type" → ต้อง coerce เป็น str
    fake = _patch_gemini_seq(monkeypatch, [["ok"]])
    out = "".join(llm._stream_gemini([{"role": "user", "content": ["a", "b"]}]))
    assert "ok" in out


# ── _stream_gemini stable-model fallback (scrutinize Major 2) ──────────────────
class _FakeModelsRec:
    """เหมือน _FakeModelsSeq แต่จด model ที่ถูกเรียกแต่ละครั้ง"""
    def __init__(self, behaviors):
        self._behaviors = list(behaviors)
        self.calls = 0
        self.models_called = []

    def generate_content_stream(self, **k):
        self.models_called.append(k.get("model"))
        b = self._behaviors[min(self.calls, len(self._behaviors) - 1)]
        self.calls += 1
        if isinstance(b, Exception):
            raise b
        return iter(SimpleNamespace(text=t) for t in b)


def _patch_gemini_rec(monkeypatch, behaviors, fallback="gemini-2.5-flash"):
    monkeypatch.setattr(llm.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(llm, "GEMINI_FALLBACK_MODEL", fallback)
    fake = _FakeModelsRec(behaviors)
    monkeypatch.setattr(llm, "gemini_client", SimpleNamespace(models=fake))
    return fake


def test_gemini_transient_falls_back_to_stable_model(monkeypatch):
    # preview model 503 หมด retry → สลับไป Gemini ตัวเสถียร (ไม่ถอย local) ตาม intent "อยู่กับ Gemini quota"
    fake = _patch_gemini_rec(monkeypatch, [Exception("503 UNAVAILABLE")] * 3 + [["recovered"]])
    out = "".join(llm._stream_gemini([{"role": "user", "content": "hi"}],
                                     model="gemini-3.1-flash-lite"))
    assert "recovered" in out
    assert "gemini-3.1-flash-lite" in fake.models_called   # ลองตัวที่ขอก่อน
    assert fake.models_called[-1] == "gemini-2.5-flash"    # แล้วสลับไปตัวเสถียร


def test_gemini_no_double_fallback_when_already_stable(monkeypatch):
    # ถ้าตัวที่ขอ = ตัวเสถียรอยู่แล้ว → ไม่ต้องลองซ้ำตัวเดิม
    fake = _patch_gemini_rec(monkeypatch, [Exception("503 UNAVAILABLE")] * 6)
    with pytest.raises(GeminiUnavailable):
        list(llm._stream_gemini([{"role": "user", "content": "hi"}],
                                model="gemini-2.5-flash"))
    assert fake.calls == 3                                  # 3 attempts ตัวเดียว ไม่มี chain ซ้ำ
    assert set(fake.models_called) == {"gemini-2.5-flash"}


def test_gemini_quota_no_model_fallback(monkeypatch):
    # 429 ไม่ใช่ transient → ห้ามสลับโมเดล (เปลือง quota ของอีกตัว) เด้ง QuotaExhausted ทันที
    fake = _patch_gemini_rec(monkeypatch, [Exception("429 RESOURCE_EXHAUSTED")] * 4)
    with pytest.raises(GeminiQuotaExhausted):
        list(llm._stream_gemini([{"role": "user", "content": "hi"}],
                                model="gemini-3.1-flash-lite"))
    assert fake.calls == 1
    assert fake.models_called == ["gemini-3.1-flash-lite"]


# ── check_ollama_health ───────────────────────────────────────────────────────
class _FakeResp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode()

    def read(self):
        return self._b


@pytest.fixture
def fresh_health(monkeypatch):
    """reset health cache + บังคับ OLLAMA_MODEL=llama3 ให้ deterministic"""
    monkeypatch.setattr(llm, "_health_cache", {"ok": None, "ts": 0.0, "msg": ""})
    monkeypatch.setattr(llm, "OLLAMA_MODEL", "llama3")


def test_health_ok_when_model_present(monkeypatch, fresh_health):
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: _FakeResp({"models": [{"name": "llama3:latest"}]}))
    ok, msg = llm.check_ollama_health(force=True)
    assert ok is True and msg == ""


def test_health_model_not_found(monkeypatch, fresh_health):
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: _FakeResp({"models": [{"name": "mistral:latest"}]}))
    ok, msg = llm.check_ollama_health(force=True)
    assert ok is False and "ไม่พบ" in msg


def test_health_connection_error(monkeypatch, fresh_health):
    def _boom(*a, **k):
        raise urllib.error.URLError("refused")
    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    ok, msg = llm.check_ollama_health(force=True)
    assert ok is False and "เชื่อมต่อ Ollama" in msg
