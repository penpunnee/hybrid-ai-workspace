"""ท่อ token จริงจาก provider → SSE done event (user ขอ 2026-08-12)

เดิม UI ประมาณ token จากตัวอักษร ~4 ตัว/token (`~191 tokens`) — provider ทุกตัว
มีตัวเลขจริงอยู่แล้วแต่ถูกทิ้ง: OpenAI-compatible (LM Studio/Ollama/Kimi) ส่งได้ผ่าน
`stream_options.include_usage` · Gemini แนบ `usage_metadata` มากับ chunk ท้าย ·
Claude มีใน final message (โค้ดเดิม log อยู่แล้วแต่ไม่ส่งต่อ)

แพทเทิร์น out-param เดียวกับ `sources_sink`: generator yield ได้แต่ str
จึงส่ง `usage_sink: dict` เข้าไปให้ provider เติม {"input_tokens", "output_tokens"}
แล้ว router แนบใน done event ให้ frontend

⚠️ กับดักที่เทสต้องตรึง:
- เปิด include_usage แล้ว chunk ท้ายมี choices=[] — โค้ดเดิม `chunk.choices[0]`
  จะ IndexError กลาง stream ทันทีที่เปิดฟีเจอร์นี้
- เซิร์ฟเวอร์เก่าที่ไม่รู้จัก stream_options ต้อง retry แบบไม่ขอ usage
  (คำตอบต้องมาก่อนตัวเลขสถิติ)
"""
import json
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
import server
import routers.chat as chatmod
import utils.llm as llm
from utils.history import save_message

client = TestClient(server.app)


def _sse_events(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        if line.startswith("data: "):
            try:
                out.append(json.loads(line[6:]))
            except Exception:
                pass
    return out


# ── wiring: /api/chat + /api/regenerate ต้องแนบ usage ใน done ──────────────

def test_chat_done_event_includes_real_usage(monkeypatch):
    def fake_stream(messages, usage_sink=None, **k):
        yield "ตอบด้วย token จริง"
        if usage_sink is not None:
            usage_sink["input_tokens"] = 12
            usage_sink["output_tokens"] = 34

    monkeypatch.setattr(chatmod, "stream_response", fake_stream)
    r = client.post("/api/chat", json={
        "session_id": "usage-test-1", "assistant": "kwan", "prompt": "นับ token ให้หน่อย",
        "provider": "ollama", "active_learning": False, "response_cache": False,
    })
    assert r.status_code == 200
    done = next(e for e in _sse_events(r.text) if e.get("done"))
    assert done.get("usage") == {"input_tokens": 12, "output_tokens": 34}, (
        f"done event ต้องแนบ usage จริงจาก provider (ได้ {done})"
    )


def test_chat_done_event_usage_absent_when_provider_silent(monkeypatch):
    def fake_stream(messages, usage_sink=None, **k):
        yield "provider เก่า ไม่มีตัวเลข"

    monkeypatch.setattr(chatmod, "stream_response", fake_stream)
    r = client.post("/api/chat", json={
        "session_id": "usage-test-2", "assistant": "kwan", "prompt": "ไม่มี usage",
        "provider": "ollama", "active_learning": False, "response_cache": False,
    })
    done = next(e for e in _sse_events(r.text) if e.get("done"))
    assert done.get("usage") is None, "provider ไม่รายงาน → usage ต้องเป็น null ให้ UI ถอยไปใช้ค่าประมาณ"


def test_regenerate_done_event_includes_real_usage(monkeypatch):
    save_message("kwan", "user", "คำถามเดิม", session_id="usage-regen-1")
    save_message("kwan", "assistant", "คำตอบเดิม", session_id="usage-regen-1")

    def fake_stream(messages, usage_sink=None, **k):
        yield "คำตอบใหม่"
        if usage_sink is not None:
            usage_sink["input_tokens"] = 5
            usage_sink["output_tokens"] = 9

    monkeypatch.setattr(chatmod, "stream_response", fake_stream)
    r = client.post("/api/regenerate", json={"assistant": "kwan", "session_id": "usage-regen-1"})
    done = next(e for e in _sse_events(r.text) if e.get("done"))
    assert done.get("usage") == {"input_tokens": 5, "output_tokens": 9}


# ── provider: OpenAI-compatible (LM Studio ตัวแทนของทั้งตระกูล) ─────────────

def _oai_chunk(text):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text))], usage=None)


_OAI_USAGE_TAIL = SimpleNamespace(  # chunk ท้ายจาก include_usage: ไม่มี choices เลย
    choices=[], usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
)


def test_lmstudio_fills_usage_sink_and_survives_empty_choices_tail(monkeypatch):
    captured_kwargs = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured_kwargs.update(kwargs)
            return iter([_oai_chunk("สวัส"), _oai_chunk("ดี"), _OAI_USAGE_TAIL])

    fake = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    monkeypatch.setattr(llm, "lmstudio_client", fake)

    sink: dict = {}
    got = "".join(llm._stream_lmstudio(
        [{"role": "user", "content": "hi"}], model="m", usage_sink=sink))
    assert got == "สวัสดี", "chunk ท้ายที่ choices ว่างต้องไม่พังและไม่ปนข้อความ"
    assert sink == {"input_tokens": 10, "output_tokens": 5}
    assert captured_kwargs.get("stream_options") == {"include_usage": True}


def test_lmstudio_retries_without_stream_options_when_server_rejects(monkeypatch):
    calls = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            if "stream_options" in kwargs:
                raise ValueError("unexpected parameter: 'stream_options'")
            return iter([_oai_chunk("ตอบได้")])

    fake = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    monkeypatch.setattr(llm, "lmstudio_client", fake)

    sink: dict = {}
    got = "".join(llm._stream_lmstudio(
        [{"role": "user", "content": "hi"}], model="m", usage_sink=sink))
    assert got == "ตอบได้", "เซิร์ฟเวอร์เก่าไม่รู้จัก stream_options → คำตอบต้องยังมา"
    assert sink == {}, "ไม่มีตัวเลขจริงก็ปล่อยว่าง (UI ถอยไปใช้ค่าประมาณ)"
    assert len(calls) == 2 and "stream_options" not in calls[1]


# ── provider: Gemini (usage_metadata มากับ chunk ท้ายๆ) ────────────────────

def test_gemini_fills_usage_sink_from_usage_metadata(monkeypatch):
    chunks = [
        SimpleNamespace(text="คำ", candidates=None, usage_metadata=None),
        SimpleNamespace(text="ตอบ", candidates=None,
                        usage_metadata=SimpleNamespace(prompt_token_count=7, candidates_token_count=3)),
    ]

    class FakeModels:
        def generate_content_stream(self, **kwargs):
            return iter(chunks)

    monkeypatch.setattr(llm, "gemini_client", SimpleNamespace(models=FakeModels()))

    sink: dict = {}
    got = "".join(llm._stream_gemini([{"role": "user", "content": "hi"}], usage_sink=sink))
    assert got == "คำตอบ"
    assert sink == {"input_tokens": 7, "output_tokens": 3}
