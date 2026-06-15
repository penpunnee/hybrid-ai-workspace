"""Option B — Gemini ใช้ Google Search grounding ในตัว (real Google) สำหรับคำถาม real-time

ทำไม: Custom Search API (key/CX) ยัง 403 ใช้ไม่ได้ → คำถาม real-time บนโมเดล Gemini
ให้ใช้ google_search tool ที่ฝังใน Gemini เลย (เป็น Google จริง ไม่ต้องมี key/CX/DDG)
ใช้เฉพาะ Gemini — provider อื่น (local/Claude/Kimi) ยังพึ่ง DDG เหมือนเดิม
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import llm


class _FakeChunk:
    def __init__(self, text):
        self.text = text


class _FakeModels:
    def __init__(self, sink):
        self._sink = sink

    def generate_content_stream(self, model, contents, config):
        self._sink["config"] = config
        return iter([_FakeChunk("ok")])


class _FakeClient:
    def __init__(self, sink):
        self.models = _FakeModels(sink)


def test_web_grounding_enables_google_search(monkeypatch):
    """web_grounding=True → config มี google_search tool (ไม่มี code_execution)"""
    sink = {}
    monkeypatch.setattr(llm, "gemini_client", _FakeClient(sink))
    out = "".join(llm._stream_gemini(
        [{"role": "user", "content": "ราคาทองวันนี้"}], web_grounding=True))
    assert out == "ok"
    tools = sink["config"].tools or []
    assert any(getattr(t, "google_search", None) is not None for t in tools), \
        "ต้องเปิด google_search tool"
    assert not any(getattr(t, "code_execution", None) is not None for t in tools), \
        "grounding ไม่ควรเปิด code_execution (เฉพาะ agent_mode)"


def test_no_grounding_no_tools(monkeypatch):
    """ปกติ (ไม่ ground ไม่ agent) → ไม่มี tools"""
    sink = {}
    monkeypatch.setattr(llm, "gemini_client", _FakeClient(sink))
    out = "".join(llm._stream_gemini(
        [{"role": "user", "content": "สวัสดี"}]))
    assert out == "ok"
    assert not sink["config"].tools


def test_stream_response_threads_web_grounding(monkeypatch):
    """stream_response(provider='gemini', web_grounding=True) ต้องส่งต่อให้ _stream_gemini"""
    captured = {}

    def fake_gemini(messages, image_b64="", image_mime="", agent_mode=False,
                    model="", thinking=None, effort="", web_grounding=False):
        captured["web_grounding"] = web_grounding
        yield "x"

    monkeypatch.setattr(llm, "_stream_gemini", fake_gemini)
    list(llm.stream_response([{"role": "user", "content": "ราคาทอง"}],
                             provider="gemini", web_grounding=True))
    assert captured["web_grounding"] is True
