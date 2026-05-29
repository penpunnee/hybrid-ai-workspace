"""Tests สำหรับ agents/tools.py + agents/orchestrator.py

tools: pure tool fns + registry + execute_tool dispatch.
orchestrator: run_agent loop (mock LM Studio client + execute_tool).
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import agents.tools as tools
import agents.orchestrator as orch


# ══════════════════════════════ tools.py ══════════════════════════════════════

def test_calculator_valid():
    assert tools._t_calculator("(2+3)*4") == "(2+3)*4 = 20"


def test_calculator_power():
    assert "225" in tools._t_calculator("15**2")


def test_calculator_rejects_unsafe():
    out = tools._t_calculator("__import__('os').system('ls')")
    assert "ไม่ปลอดภัย" in out


def test_calculator_handles_error():
    out = tools._t_calculator("1/0")
    assert out.startswith("❌")


def test_current_time_returns_date_string():
    out = tools._t_current_time("Asia/Bangkok")
    assert any(c.isdigit() for c in out)


# ── registry / schema ─────────────────────────────────────────────────────────
def test_registry_entries_well_formed():
    for name, spec in tools.TOOL_REGISTRY.items():
        assert "description" in spec
        assert "parameters" in spec and spec["parameters"]["type"] == "object"
        assert callable(spec["fn"])


def test_get_openai_tools_format():
    schema = tools.get_openai_tools()
    assert all(t["type"] == "function" for t in schema)
    names = {t["function"]["name"] for t in schema}
    assert names == set(tools.TOOL_REGISTRY.keys())


def test_list_tools_matches_registry():
    assert set(tools.list_tools()) == set(tools.TOOL_REGISTRY.keys())


# ── execute_tool dispatch ─────────────────────────────────────────────────────
def test_execute_tool_unknown():
    assert "ไม่รู้จัก tool" in tools.execute_tool("nonexistent", {})


def test_execute_tool_runs_calculator():
    assert tools.execute_tool("calculator", {"expression": "6*7"}) == "6*7 = 42"


def test_execute_tool_bad_args_typeerror():
    # calculator ต้องการ expression — ส่ง arg ผิดชื่อ → TypeError → ข้อความ "argument ผิด"
    out = tools.execute_tool("calculator", {"wrong_arg": "x"})
    assert "argument ผิด" in out


def test_execute_tool_clamps_length(monkeypatch):
    monkeypatch.setitem(tools.TOOL_REGISTRY, "bignoise",
                        {"description": "x", "parameters": {"type": "object", "properties": {}},
                         "fn": lambda: "y" * 10000})
    out = tools.execute_tool("bignoise", {})
    assert len(out) == 5000


# ══════════════════════════════ orchestrator.py ═══════════════════════════════

def _msg(content="", tool_calls=None):
    return SimpleNamespace(content=content, tool_calls=tool_calls)


def _resp(msg):
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def _tool_call(cid, name, arguments):
    return SimpleNamespace(id=cid, function=SimpleNamespace(name=name, arguments=arguments))


def _stream_chunk(text):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text))])


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    @property
    def chat(self):
        return SimpleNamespace(completions=SimpleNamespace(create=self._create))


def _run(messages, **kw):
    return list(orch.run_agent(messages, **kw))


def test_agent_direct_answer_no_tools(monkeypatch):
    monkeypatch.setattr(orch, "_client", FakeClient([_resp(_msg(content="คำตอบตรงๆ"))]))
    events = _run([{"role": "system", "content": "base"}])
    kinds = [e[1]["type"] for e in events if e[0] == "event"]
    chunks = [e[1] for e in events if e[0] == "chunk"]
    assert "answering" in kinds
    assert chunks == ["คำตอบตรงๆ"]


def test_agent_injects_system_hint(monkeypatch):
    monkeypatch.setattr(orch, "_client", FakeClient([_resp(_msg(content="x"))]))
    messages = [{"role": "system", "content": "base"}]
    _run(messages)
    assert "[Agent Mode]" in messages[0]["content"]


def test_agent_inserts_system_when_missing(monkeypatch):
    monkeypatch.setattr(orch, "_client", FakeClient([_resp(_msg(content="x"))]))
    messages = [{"role": "user", "content": "hi"}]
    _run(messages)
    assert messages[0]["role"] == "system"


def test_agent_tool_call_then_answer(monkeypatch):
    monkeypatch.setattr(orch, "_client", FakeClient([
        _resp(_msg(tool_calls=[_tool_call("c1", "calculator", '{"expression": "2+2"}')])),
        _resp(_msg(content="ได้ 4")),
    ]))
    monkeypatch.setattr(orch, "execute_tool", lambda name, args: "2+2 = 4")
    events = _run([{"role": "system", "content": "base"}])

    tool_calls = [e[1] for e in events if e[0] == "event" and e[1]["type"] == "tool_call"]
    tool_results = [e[1] for e in events if e[0] == "event" and e[1]["type"] == "tool_result"]
    chunks = [e[1] for e in events if e[0] == "chunk"]

    assert tool_calls[0]["name"] == "calculator"
    assert tool_calls[0]["args"] == {"expression": "2+2"}
    assert tool_results[0]["length"] == len("2+2 = 4")
    assert chunks == ["ได้ 4"]


def test_agent_llm_error_yields_error_event(monkeypatch):
    monkeypatch.setattr(orch, "_client", FakeClient([RuntimeError("boom")]))
    events = _run([{"role": "system", "content": "base"}])
    kinds = [e[1]["type"] for e in events if e[0] == "event"]
    chunks = [e[1] for e in events if e[0] == "chunk"]
    assert "error" in kinds
    assert chunks[0].startswith("❌ Agent error")


def test_agent_bad_tool_arguments_default_empty(monkeypatch):
    # arguments เป็น JSON เสีย → args = {} (ไม่ crash)
    monkeypatch.setattr(orch, "_client", FakeClient([
        _resp(_msg(tool_calls=[_tool_call("c1", "current_time", "{not json")])),
        _resp(_msg(content="done")),
    ]))
    captured = {}
    monkeypatch.setattr(orch, "execute_tool", lambda name, args: captured.update(args=args) or "ok")
    _run([{"role": "system", "content": "base"}])
    assert captured["args"] == {}


def test_agent_max_steps_forces_synthesis(monkeypatch):
    # ทุก step คืน tool_call → ไม่จบ → ครบ max_steps → synthesis stream
    monkeypatch.setattr(orch, "_client", FakeClient([
        _resp(_msg(tool_calls=[_tool_call("c1", "calculator", '{"expression":"1+1"}')])),
        [_stream_chunk("สรุป"), _stream_chunk("คำตอบ")],   # final stream (stream=True)
    ]))
    monkeypatch.setattr(orch, "execute_tool", lambda name, args: "1+1 = 2")
    events = _run([{"role": "system", "content": "base"}], max_steps=1)
    kinds = [e[1]["type"] for e in events if e[0] == "event"]
    chunks = "".join(e[1] for e in events if e[0] == "chunk")
    assert "max_steps_reached" in kinds
    assert chunks == "สรุปคำตอบ"
