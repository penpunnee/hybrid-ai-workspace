"""ChromaDB default embedding function (MiniLM) มองอักษรไทยเป็น UNK ทั้งหมด →
ทุกประโยคไทยได้ vector เดียวกัน (score=1.000 ทุกคู่) → semantic recall ภาษาไทย
เป็น noise ล้วน (พิสูจน์แล้วในโปรเจกต์ JARVIS 2026-07-08). แก้ด้วย
utils.memory._get_embedding_function() — Ollama multilingual, opt-in ผ่าน
EMBEDDING_MODEL env (ปล่อยว่าง = ปิด, คง default MiniLM เดิมไว้).
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("UI_PASSWORD", "")

import utils.memory as memory_mod


def _reset_ef_singleton(monkeypatch, model: str):
    """utils.memory._get_embedding_function() cache ผลไว้ใน module global — ต้อง
    reset ก่อนทุกเทสต์ ไม่งั้นเทสต์ก่อนหน้าค้างผล"""
    monkeypatch.setattr(memory_mod, "EMBEDDING_MODEL", model)
    monkeypatch.setattr(memory_mod, "_embedding_function", None)
    monkeypatch.setattr(memory_mod, "_embedding_function_attempted", False)


def test_disabled_by_default_returns_none(monkeypatch):
    _reset_ef_singleton(monkeypatch, "")
    assert memory_mod._get_embedding_function() is None


def test_enabled_returns_ollama_embedding_function(monkeypatch):
    _reset_ef_singleton(monkeypatch, "paraphrase-multilingual")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://192.168.51.235:11434/v1")

    calls = {}

    class _FakeOllamaEF:
        def __init__(self, url, model_name):
            calls["url"] = url
            calls["model_name"] = model_name

    monkeypatch.setattr(
        "chromadb.utils.embedding_functions.OllamaEmbeddingFunction", _FakeOllamaEF
    )

    ef = memory_mod._get_embedding_function()
    assert isinstance(ef, _FakeOllamaEF)
    # OLLAMA_BASE_URL ของโปรเจกต์นี้เป็น OpenAI-compat (/v1) — ต้อง strip ก่อนส่งให้
    # chromadb's OllamaEmbeddingFunction ซึ่งต้องการ native Ollama API base
    assert calls["url"] == "http://192.168.51.235:11434"
    assert calls["model_name"] == "paraphrase-multilingual"


def test_construction_failure_falls_back_to_none(monkeypatch):
    """ไม่มีแพ็กเกจ ollama / เหตุผลอื่น → ต้องไม่ crash แค่ fallback ไป default embedder"""
    _reset_ef_singleton(monkeypatch, "paraphrase-multilingual")

    def _boom(*a, **k):
        raise ImportError("no ollama package")

    monkeypatch.setattr(
        "chromadb.utils.embedding_functions.OllamaEmbeddingFunction", _boom
    )
    assert memory_mod._get_embedding_function() is None


def test_singleton_only_constructs_once(monkeypatch):
    _reset_ef_singleton(monkeypatch, "paraphrase-multilingual")
    calls = []

    class _FakeOllamaEF:
        def __init__(self, url, model_name):
            calls.append(1)

    monkeypatch.setattr(
        "chromadb.utils.embedding_functions.OllamaEmbeddingFunction", _FakeOllamaEF
    )
    memory_mod._get_embedding_function()
    memory_mod._get_embedding_function()
    assert len(calls) == 1


def test_native_url_strips_v1_suffix(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    assert memory_mod._ollama_native_url() == "http://localhost:11434"

    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    assert memory_mod._ollama_native_url() == "http://localhost:11434"


def test_get_or_create_collection_omits_kwarg_when_ef_disabled(monkeypatch):
    """opt-out (default) ต้องไม่ส่ง embedding_function= เลย — กัน client เก่า/fake
    ที่ signature ไม่รับ kwarg นี้พัง (ดู tests/test_memory_package.py::_fake_client)"""
    _reset_ef_singleton(monkeypatch, "")
    received = {}

    def _fake_get_or_create(name, **kwargs):
        received.update(kwargs)
        return SimpleNamespace(name=name)

    client = SimpleNamespace(get_or_create_collection=_fake_get_or_create)
    memory_mod.get_or_create_collection(client, "memory_test")
    assert "embedding_function" not in received


def test_get_or_create_collection_passes_ef_when_enabled(monkeypatch):
    _reset_ef_singleton(monkeypatch, "paraphrase-multilingual")

    class _FakeOllamaEF:
        def __init__(self, url, model_name):
            pass

    monkeypatch.setattr(
        "chromadb.utils.embedding_functions.OllamaEmbeddingFunction", _FakeOllamaEF
    )
    received = {}

    def _fake_get_or_create(name, **kwargs):
        received.update(kwargs)
        return SimpleNamespace(name=name)

    client = SimpleNamespace(get_or_create_collection=_fake_get_or_create)
    memory_mod.get_or_create_collection(client, "memory_test")
    assert isinstance(received.get("embedding_function"), _FakeOllamaEF)
