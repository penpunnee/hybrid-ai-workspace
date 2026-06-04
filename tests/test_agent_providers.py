"""Tests for provider-aware agent orchestrator

หลักการ:
- run_agent รับ provider param เพื่อเลือก backend
- Gemini path ใช้ google.genai SDK
- LM Studio path ใช้ OpenAI client (เดิม)
- ถ้า provider ไม่พร้อม (ไม่มี key/URL) → yield error event ทันที ไม่ crash
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch, MagicMock


def _collect(gen):
    """เก็บ generator output เป็น list"""
    return list(gen)


class TestRunAgentProviderRouting:
    def test_gemini_provider_uses_gemini_path(self):
        with patch("agents.orchestrator._run_agent_gemini") as mock_gemini:
            mock_gemini.return_value = iter([("chunk", "ok")])
            from agents.orchestrator import run_agent
            results = _collect(run_agent(
                [{"role": "user", "content": "ping NAS"}],
                provider="gemini",
            ))
        mock_gemini.assert_called_once()

    def test_lmstudio_provider_uses_lmstudio_path(self):
        with patch("agents.orchestrator._run_agent_lmstudio") as mock_lm:
            mock_lm.return_value = iter([("chunk", "ok")])
            from agents.orchestrator import run_agent
            results = _collect(run_agent(
                [{"role": "user", "content": "ping NAS"}],
                provider="lmstudio",
            ))
        mock_lm.assert_called_once()

    def test_unknown_provider_yields_error(self):
        from agents.orchestrator import run_agent
        results = _collect(run_agent(
            [{"role": "user", "content": "hi"}],
            provider="unknown_xyz",
        ))
        types = [r[0] for r in results]
        assert "event" in types
        events = [r[1] for r in results if r[0] == "event"]
        assert any(e.get("type") == "error" for e in events)

    def test_gemini_unavailable_yields_error(self):
        with patch("agents.orchestrator.GEMINI_API_KEY", ""):
            from agents.orchestrator import run_agent
            results = _collect(run_agent(
                [{"role": "user", "content": "hi"}],
                provider="gemini",
            ))
        events = [r[1] for r in results if r[0] == "event"]
        assert any(e.get("type") == "error" for e in events)

    def test_lmstudio_unavailable_yields_error(self):
        with patch("agents.orchestrator.LMSTUDIO_BASE_URL", ""):
            from agents.orchestrator import run_agent
            results = _collect(run_agent(
                [{"role": "user", "content": "hi"}],
                provider="lmstudio",
            ))
        events = [r[1] for r in results if r[0] == "event"]
        assert any(e.get("type") == "error" for e in events)


class TestGetGeminiTools:
    def test_gemini_tools_schema_generated_from_registry(self):
        from agents.tools import get_gemini_tools
        tools = get_gemini_tools()
        assert isinstance(tools, list)
        assert len(tools) > 0
        first = tools[0]
        assert hasattr(first, "name") or isinstance(first, dict)
