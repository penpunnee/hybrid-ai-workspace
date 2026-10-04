"""โหมด agent ต้องส่ง token จริงใน done.usage (2026-10-04 ต่อ 80)

ต่อ 78 ทำแถบ Context ให้ใช้ `done.usage` แต่ done ของ agent (`routers/chat.py`) ไม่แนบ usage เลย ·
`run_agent` ไม่มีช่องรับ · adapter ไม่ขอ `include_usage` ⇒ แถบโชว์ "ไม่รายงาน" ในเทิร์น agent
ซึ่งเสี่ยงล้น context ที่สุด (tools schema ~2.5k token + ผล tool สะสมทุก step · ต่อ 75)

agent ยิงหลายคำขอต่อเทิร์น: ขาเข้า = ของคำขอ **ล่าสุด** (ประวัติ + ผล tool สะสม = ใกล้เต็มที่สุด) ·
ขาออก = **รวม** ทุกคำขอ (เวลาที่ใช้จริงมาจากทุกรอบ)
"""
import contextlib
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import agents.orchestrator as orch
from tests.test_agents import FakeClient, _msg, _patch_lmstudio, _resp, _stream_chunk, _tool_call
from tests.test_token_usage import _sse_events, client


def _usage_tail(pt, ct):
    return SimpleNamespace(choices=[], usage=SimpleNamespace(prompt_tokens=pt, completion_tokens=ct))


class _UsageClient(FakeClient):
    """FakeClient + ชิ้นท้ายแบบ include_usage (choices ว่าง) ตามลำดับ `tails`"""
    def __init__(self, responses, tails):
        super().__init__(responses)
        self.tails = list(tails)

    def _create(self, **kwargs):
        r = super()._create(**kwargs)
        if kwargs.get("stream_options") == {"include_usage": True} and self.tails:
            return list(r) + [_usage_tail(*self.tails.pop(0))]
        return r


def test_lmstudio_agent_reports_last_input_summed_output_and_ctx(monkeypatch):
    fake = _UsageClient([
        _resp(_msg(tool_calls=[_tool_call("c1", "calculator", '{"expression": "2+2"}')])),
        _resp(_msg(content="ได้ 4")),
    ], tails=[(3000, 120), (3400, 80)])
    _patch_lmstudio(monkeypatch, fake)
    monkeypatch.setattr(orch, "execute_tool", lambda name, args: "2+2 = 4")
    monkeypatch.setattr(orch, "_lmstudio_loaded_ctx", lambda m: 16384)
    sink: dict = {}
    events = list(orch.run_agent([{"role": "system", "content": "base"}], provider="lmstudio", usage_sink=sink))
    assert [e[1] for e in events if e[0] == "chunk"] == ["ได้ 4"]
    assert all(c.get("stream_options") == {"include_usage": True} for c in fake.calls)
    assert sink == {"input_tokens": 3400, "output_tokens": 200, "context_limit": 16384}


def test_lmstudio_agent_synthesis_survives_usage_tail(monkeypatch):
    """รอบสรุป (ครบ max_steps) อ่าน `chunk.choices[0]` ตรงๆ — ชิ้นท้าย include_usage ไม่มี choices = IndexError"""
    fake = _UsageClient([
        _resp(_msg(tool_calls=[_tool_call("c1", "calculator", '{"expression":"1+1"}')])),
        [_stream_chunk("สรุป"), _stream_chunk("คำตอบ")],
    ], tails=[(2000, 50), (2600, 70)])
    _patch_lmstudio(monkeypatch, fake)
    monkeypatch.setattr(orch, "execute_tool", lambda name, args: "1+1 = 2")
    monkeypatch.setattr(orch, "_lmstudio_loaded_ctx", lambda m: None)
    sink: dict = {}
    events = list(orch.run_agent([{"role": "system", "content": "base"}], provider="lmstudio",
                                 max_steps=1, usage_sink=sink))
    assert "".join(e[1] for e in events if e[0] == "chunk") == "สรุปคำตอบ"
    assert sink == {"input_tokens": 2600, "output_tokens": 120}, "อ่าน ctx ไม่ได้ = ไม่ใส่ context_limit"


def test_lmstudio_agent_without_sink_unchanged(monkeypatch):
    """ไม่ขอ usage = ไม่ส่ง stream_options (เส้นเดิมไม่เปลี่ยน)"""
    fake = FakeClient([_resp(_msg(content="x"))])
    _patch_lmstudio(monkeypatch, fake)
    list(orch.run_agent([{"role": "system", "content": "base"}], provider="lmstudio"))
    assert "stream_options" not in fake.calls[0]


def _gem_chunk(parts, usage=None):
    ch = MagicMock()
    cand = MagicMock()
    cand.content.parts = parts
    ch.candidates = [cand]
    ch.usage_metadata = (SimpleNamespace(prompt_token_count=usage[0], candidates_token_count=usage[1])
                         if usage else None)
    return ch


def _gem_part(function_call=None, text=None):
    p = MagicMock()
    p.function_call = function_call
    p.text = text
    return p


def test_gemini_agent_reports_usage(monkeypatch):
    fc = MagicMock()
    fc.name, fc.args = "web_search", {"query": "x"}
    sent = []

    def stream_side(message, **kw):
        sent.append(message)
        if len(sent) == 1:   # usage_metadata มาหลายชิ้นแบบสะสม — นับชุดล่าสุดของคำขอ ไม่ใช่บวกทุกชิ้น
            return iter([_gem_chunk([_gem_part(function_call=fc)], (900, 5)),
                         _gem_chunk([], (900, 10))])
        return iter([_gem_chunk([_gem_part(text="โต")]), _gem_chunk([_gem_part(text="เกียว")], (1500, 30))])

    fake_chat = MagicMock()
    fake_chat.send_message_stream.side_effect = stream_side
    fake_client = MagicMock()
    fake_client.chats.create.return_value = fake_chat
    sink: dict = {}
    with contextlib.ExitStack() as st:
        for cm in (patch("google.genai.Client", return_value=fake_client),
                   patch("agents.orchestrator.GEMINI_API_KEY", "fake-key"),
                   patch("agents.orchestrator.execute_tool", return_value="tool result"),
                   patch("agents.orchestrator.get_gemini_tools", return_value=[])):
            st.enter_context(cm)
        out = list(orch.run_agent([{"role": "user", "content": "ping"}], provider="gemini", usage_sink=sink))
    assert "".join(e[1] for e in out if e[0] == "chunk") == "โตเกียว"
    assert sink == {"input_tokens": 1500, "output_tokens": 40}


def test_gemini_agent_ignores_non_int_usage(monkeypatch):
    """MagicMock/ค่าแปลกใน usage_metadata ต้องไม่กลายเป็นตัวเลข (int(MagicMock()) == 1)"""
    sink: dict = {}
    orch._note_usage(sink, MagicMock(), MagicMock())
    assert sink == {}


def test_chat_agent_done_event_includes_usage(monkeypatch):
    def fake_run_agent(messages, usage_sink=None, **kw):
        yield ("chunk", "คำตอบ agent")
        usage_sink.update(input_tokens=7000, output_tokens=900, context_limit=16384)

    monkeypatch.setattr(orch, "run_agent", fake_run_agent)
    r = client.post("/api/chat", headers={"X-Test-Request": "1"}, json={
        "session_id": "usage-agent-1", "assistant": "kwan", "prompt": "ค้นให้หน่อย",
        "provider": "lmstudio", "tool_agent": True, "active_learning": False, "response_cache": False,
    })
    assert r.status_code == 200
    done = next(e for e in _sse_events(r.text) if e.get("done"))
    assert done.get("provider") == "agent", f"ต้องวิ่งเส้น agent จริง (ได้ {done})"
    assert done.get("usage") == {"input_tokens": 7000, "output_tokens": 900, "context_limit": 16384}


def test_chat_agent_done_usage_null_when_silent(monkeypatch):
    def fake_run_agent(messages, usage_sink=None, **kw):
        yield ("chunk", "x")

    monkeypatch.setattr(orch, "run_agent", fake_run_agent)
    r = client.post("/api/chat", headers={"X-Test-Request": "1"}, json={
        "session_id": "usage-agent-2", "assistant": "kwan", "prompt": "ค้น",
        "provider": "gemini", "tool_agent": True, "active_learning": False, "response_cache": False,
    })
    done = next(e for e in _sse_events(r.text) if e.get("done"))
    assert done.get("provider") == "agent"
    assert done.get("usage") is None
    json.dumps(done)
