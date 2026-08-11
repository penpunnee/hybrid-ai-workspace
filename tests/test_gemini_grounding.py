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
                    model="", thinking=None, effort="", web_grounding=False,
                    sources_sink=None, usage_sink=None):
        captured["web_grounding"] = web_grounding
        yield "x"

    monkeypatch.setattr(llm, "_stream_gemini", fake_gemini)
    list(llm.stream_response([{"role": "user", "content": "ราคาทอง"}],
                             provider="gemini", web_grounding=True))
    assert captured["web_grounding"] is True


# ── grounding sources → citations (พบจาก audit 2026-08-02) ────────────────────
# _stream_gemini เปิด google_search tool จริง แต่ไม่เคยดึง grounding_metadata
# ออกมาเป็น citation เลย → เส้นทางที่แม่นที่สุด (Gemini) กลับเป็นตัวเดียวที่ผู้ใช้
# ตรวจสอบแหล่งที่มาไม่ได้ (โมเดล local ที่ยืม gemini_web_search กลับมี citation)
# ฟังก์ชัน _extract_grounding_sources() มีอยู่แล้ว แค่ยังไม่ถูกต่อสายเข้า stream
class _FakeWeb:
    def __init__(self, uri, title):
        self.uri, self.title = uri, title


class _FakeGroundingChunk:
    def __init__(self, uri, title):
        self.web = _FakeWeb(uri, title)


class _FakeGroundingMeta:
    def __init__(self, pairs):
        self.grounding_chunks = [_FakeGroundingChunk(u, t) for u, t in pairs]


class _FakeCandidate:
    def __init__(self, pairs):
        self.grounding_metadata = _FakeGroundingMeta(pairs)


class _ChunkWithGrounding:
    """chunk สุดท้ายของ Gemini stream ที่แนบ grounding_metadata มาด้วย"""
    def __init__(self, text, pairs=None):
        self.text = text
        self.candidates = [_FakeCandidate(pairs)] if pairs else []


class _GroundedModels:
    def __init__(self, sink):
        self._sink = sink

    def generate_content_stream(self, model, contents, config):
        self._sink["config"] = config
        return iter([
            _ChunkWithGrounding("ราคาทอง "),
            _ChunkWithGrounding("64,200 บาท", pairs=[
                ("https://example.com/gold", "ราคาทองวันนี้"),
                ("https://kapook.com/gold", "Kapook Gold"),
            ]),
        ])


class _GroundedClient:
    def __init__(self, sink):
        self.models = _GroundedModels(sink)


def test_grounding_sources_collected_into_sink(monkeypatch):
    """web_grounding=True + ส่ง sources_sink → ต้องได้แหล่งอ้างอิงจริงกลับมา
    (ไม่งั้น UI โชว์ citation ไม่ได้ ผู้ใช้ตรวจสอบที่มาของตัวเลขไม่ได้)"""
    sink = {}
    sources: list[dict] = []
    monkeypatch.setattr(llm, "gemini_client", _GroundedClient(sink))
    out = "".join(llm._stream_gemini(
        [{"role": "user", "content": "ราคาทองวันนี้"}],
        web_grounding=True, sources_sink=sources))
    assert "64,200" in out
    assert len(sources) == 2, f"ควรได้ 2 แหล่ง ได้ {sources}"
    assert sources[0]["href"] == "https://example.com/gold"
    assert sources[0]["title"] == "ราคาทองวันนี้"


def test_grounding_sink_optional_no_crash(monkeypatch):
    """ไม่ส่ง sources_sink → ต้องทำงานปกติ ไม่พัง (backward compatible)"""
    sink = {}
    monkeypatch.setattr(llm, "gemini_client", _GroundedClient(sink))
    out = "".join(llm._stream_gemini(
        [{"role": "user", "content": "ราคาทองวันนี้"}], web_grounding=True))
    assert "64,200" in out
