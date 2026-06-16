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


class TestGeminiAgentStreamingAndTools:
    """A+C+F สำหรับ Gemini agent (ใช้ send_message_stream):
    - A: stream คำตอบสุดท้ายเป็นหลาย chunk
    - Content-fix (regression): tool-response turn เป็น list[Part] ไม่ใช่ types.Content
    - F: retry/backoff เมื่อเจอ error ชั่วคราว (503/overloaded); error อื่นเด้งทันที
    """

    def _part(self, function_call=None, text=None):
        p = MagicMock(); p.function_call = function_call; p.text = text
        return p

    def _chunk(self, parts):
        ch = MagicMock(); cand = MagicMock()
        cand.content.parts = parts
        ch.candidates = [cand]
        return ch

    def _fc(self, name="web_search", args=None):
        fc = MagicMock(); fc.name = name; fc.args = args or {"query": "x"}
        return fc

    def _run(self, fake_chat):
        import contextlib
        fake_client = MagicMock()
        fake_client.chats.create.return_value = fake_chat
        with contextlib.ExitStack() as st:
            for cm in (
                patch("google.genai.Client", return_value=fake_client),
                patch("agents.orchestrator.GEMINI_API_KEY", "fake-key"),
                patch("agents.orchestrator.execute_tool", return_value="tool result"),
                patch("agents.orchestrator.get_gemini_tools", return_value=[]),
                patch("agents.orchestrator.time.sleep", return_value=None),
            ):
                st.enter_context(cm)
            from agents.orchestrator import _run_agent_gemini
            return _collect(_run_agent_gemini(
                [{"role": "user", "content": "ping NAS"}],
                "gemini-2.5-flash", max_steps=4,
            ))

    def test_streams_final_answer_and_tool_response_is_parts(self):
        from google.genai import types as genai_types
        sent = []

        def stream_side(message):
            sent.append(message)
            if len(sent) == 1:                       # step 1 → function call
                return iter([self._chunk([self._part(function_call=self._fc())])])
            return iter([                            # step 2 → คำตอบ stream 2 chunk
                self._chunk([self._part(text="โต")]),
                self._chunk([self._part(text="เกียว")]),
            ])

        fake_chat = MagicMock()
        fake_chat.send_message_stream.side_effect = stream_side

        results = self._run(fake_chat)
        chunks = [p for k, p in results if k == "chunk"]
        events = [p for k, p in results if k == "event"]

        # A: คำตอบมาเป็นหลาย chunk แยกกัน (ไม่ใช่ก้อนเดียว)
        assert "โต" in chunks and "เกียว" in chunks
        assert any(e.get("type") == "tool_call" for e in events)
        # Content-fix: turn ที่ 2 = list[Part] ไม่ใช่ types.Content
        assert len(sent) >= 2
        assert not isinstance(sent[1], genai_types.Content)
        assert isinstance(sent[1], list) and len(sent[1]) > 0
        assert not any("valid part type" in c for c in chunks)

    def test_retries_transient_error_then_succeeds(self):
        sent = []

        def stream_side(message):
            sent.append(message)
            if len(sent) == 1:
                raise Exception("503 UNAVAILABLE — model experiencing high demand")
            return iter([self._chunk([self._part(text="คำตอบหลัง retry")])])

        fake_chat = MagicMock()
        fake_chat.send_message_stream.side_effect = stream_side

        results = self._run(fake_chat)
        text = "".join(p for k, p in results if k == "chunk")
        assert "คำตอบหลัง retry" in text          # F: retry สำเร็จ
        assert "agent error" not in text.lower()
        assert len(sent) == 2                        # เรียกซ้ำ 1 รอบ

    def test_non_retryable_error_surfaces_immediately(self):
        sent = []

        def stream_side(message):
            sent.append(message)
            raise Exception("400 INVALID_ARGUMENT — bad request")

        fake_chat = MagicMock()
        fake_chat.send_message_stream.side_effect = stream_side

        results = self._run(fake_chat)
        text = "".join(p for k, p in results if k == "chunk")
        assert "Gemini agent error" in text          # ไม่ retry
        assert len(sent) == 1
