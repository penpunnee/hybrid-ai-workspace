"""LM Studio health check + /api/status fields (session 2026-06-10)

Gap: local หลักตอนนี้ = DeepSeek R1 via LM Studio แต่ /api/status เช็คเฉพาะ
check_ollama_health → status บอกสถานะ local model จริงไม่ได้ ถ้า LM Studio
ล่มจะตกไป Gemini เงียบๆ จน quota หมดโดยไม่รู้ตัว

สัญญาใหม่:
1. utils/llm.py:check_lmstudio_health() — (ok, msg) แบบเดียวกับ ollama
   - ไม่ได้ตั้ง LMSTUDIO_BASE_URL → (False, บอกว่ายังไม่ตั้งค่า)
   - /v1/models ตอบ + มี model → (True, ...)
   - /v1/models ว่าง = ไม่มี model โหลด/JIT → (False, ...)
   - connection error → (False, ...)
   - cache 30s (force=True ข้าม cache)
2. /api/status เพิ่ม lmstudio, lmstudio_message, local_provider, local_ok
"""
import json
import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

os.environ["UI_PASSWORD"] = ""
import server  # noqa: E402
import utils.llm as llm  # noqa: E402

client = TestClient(server.app)


def _reset_cache():
    llm._lm_health_cache.update({"ok": None, "ts": 0.0, "msg": ""})


def _fake_models_response(model_ids):
    resp = MagicMock()
    resp.read.return_value = json.dumps(
        {"data": [{"id": m} for m in model_ids]}
    ).encode()
    return resp


class TestCheckLMStudioHealth:
    def test_not_configured_returns_false(self, monkeypatch):
        _reset_cache()
        monkeypatch.setattr(llm, "_LMSTUDIO_BASE_URL", "")
        ok, msg = llm.check_lmstudio_health(force=True)
        assert ok is False
        assert "LMSTUDIO_BASE_URL" in msg

    def test_models_available_returns_true(self, monkeypatch):
        _reset_cache()
        monkeypatch.setattr(llm, "_LMSTUDIO_BASE_URL", "http://192.168.51.235:1234/v1")
        with patch("urllib.request.urlopen", return_value=_fake_models_response(
                ["deepseek/deepseek-r1-0528-qwen3-8b"])):
            ok, msg = llm.check_lmstudio_health(force=True)
        assert ok is True

    def test_empty_models_returns_false(self, monkeypatch):
        """/v1/models ว่าง = LM Studio รันแต่ไม่มี model ให้ใช้"""
        _reset_cache()
        monkeypatch.setattr(llm, "_LMSTUDIO_BASE_URL", "http://192.168.51.235:1234/v1")
        with patch("urllib.request.urlopen", return_value=_fake_models_response([])):
            ok, msg = llm.check_lmstudio_health(force=True)
        assert ok is False

    def test_connection_error_returns_false(self, monkeypatch):
        _reset_cache()
        monkeypatch.setattr(llm, "_LMSTUDIO_BASE_URL", "http://192.168.51.235:1234/v1")
        with patch("urllib.request.urlopen", side_effect=OSError("refused")):
            ok, msg = llm.check_lmstudio_health(force=True)
        assert ok is False

    def test_cache_skips_second_call(self, monkeypatch):
        _reset_cache()
        monkeypatch.setattr(llm, "_LMSTUDIO_BASE_URL", "http://192.168.51.235:1234/v1")
        with patch("urllib.request.urlopen", return_value=_fake_models_response(["m"])) as mock_open:
            llm.check_lmstudio_health(force=True)
            llm.check_lmstudio_health()          # ครั้งสองต้องโดน cache
        assert mock_open.call_count == 1


class TestStatusEndpointLMStudio:
    def _call_status(self, lmstudio_ok, base_url):
        with patch("routers.system.check_ollama_health", return_value=(False, "down")), \
             patch("routers.system.check_lmstudio_health", return_value=(lmstudio_ok, "")), \
             patch("routers.system.is_memory_available", return_value=True), \
             patch("routers.system.LMSTUDIO_BASE_URL", base_url):
            resp = client.get("/api/status")
        assert resp.status_code == 200
        return resp.json()

    def test_status_has_lmstudio_fields(self):
        data = self._call_status(True, "http://192.168.51.235:1234/v1")
        assert "lmstudio" in data
        assert "lmstudio_message" in data
        assert data["lmstudio"] is True

    def test_local_provider_lmstudio_when_configured(self):
        data = self._call_status(True, "http://192.168.51.235:1234/v1")
        assert data["local_provider"] == "lmstudio"
        assert data["local_ok"] is True   # lmstudio ok แม้ ollama down

    def test_local_provider_ollama_when_not_configured(self):
        data = self._call_status(False, "")
        assert data["local_provider"] == "ollama"
        assert data["local_ok"] is False  # ตาม ollama (down)
