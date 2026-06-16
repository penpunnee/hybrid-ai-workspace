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


class TestGeminiToolResponseTurn:
    """Regression: หลัง agent เรียก tool แล้ววนรอบ 2 ต้องส่ง tool-response เป็น
    list[Part] — ไม่ใช่ types.Content (chat.send_message รับ Content ตรงๆ ไม่ได้
    → 'Message must be a valid part type ... got types.Content')
    """

    def _fc_response(self, name="web_search", args=None):
        fc = MagicMock()
        fc.name = name
        fc.args = args or {"query": "x"}
        part = MagicMock()
        part.function_call = fc
        resp = MagicMock()
        cand = MagicMock()
        cand.content.parts = [part]
        resp.candidates = [cand]
        return resp

    def _text_response(self, text="done"):
        part = MagicMock()
        part.function_call = None
        resp = MagicMock()
        cand = MagicMock()
        cand.content.parts = [part]
        resp.candidates = [cand]
        resp.text = text
        return resp

    def test_tool_response_turn_sent_as_parts_not_content(self):
        from google.genai import types as genai_types

        sent = []
        responses = [self._fc_response(), self._text_response()]

        fake_chat = MagicMock()
        fake_chat.send_message.side_effect = lambda message: (
            sent.append(message) or responses[len(sent) - 1]
        )
        fake_client = MagicMock()
        fake_client.chats.create.return_value = fake_chat

        with patch("google.genai.Client", return_value=fake_client), \
             patch("agents.orchestrator.GEMINI_API_KEY", "fake-key"), \
             patch("agents.orchestrator.execute_tool", return_value="tool result"), \
             patch("agents.orchestrator.get_gemini_tools", return_value=[]):
            from agents.orchestrator import _run_agent_gemini
            _collect(_run_agent_gemini(
                [{"role": "user", "content": "ping NAS"}],
                "gemini-2.5-flash", max_steps=4,
            ))

        assert len(sent) >= 2, "ต้องมี send รอบ 2 (หลังรัน tool)"
        assert sent[0] == "ping NAS"                    # รอบแรก = user string
        second = sent[1]                                 # รอบ tool-response
        assert not isinstance(second, genai_types.Content), \
            "tool-response turn ต้องเป็น parts/list ไม่ใช่ types.Content"
        assert isinstance(second, list) and len(second) > 0
