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


# ── home/network tools (wired จาก utils.home_tools → ปิด hallucination ใน agent) ─
def test_home_tools_registered():
    # ping/disk/docker/wol ต้องอยู่ใน registry → Agent mode รันจริงได้ แสดงผลดิบ
    for name in ("nas_disk", "nas_docker", "ping_network", "ping_device", "wol_pc"):
        assert name in tools.TOOL_REGISTRY


def test_ping_network_tool_formats_real_results(monkeypatch):
    import utils.home_tools as ht
    monkeypatch.setattr(ht, "ping_device",
                        lambda ip: {"ip": ip, "online": True, "latency_ms": 1.2, "port": 80})
    out = tools._t_ping_network()
    assert "Router" in out and "NAS" in out and "PC" in out
    assert "🟢" in out


def test_ping_device_tool_offline(monkeypatch):
    import utils.home_tools as ht
    monkeypatch.setattr(ht, "ping_device",
                        lambda ip: {"ip": ip, "online": False, "latency_ms": None})
    out = tools._t_ping_device("192.168.1.50")
    assert "🔴" in out and "192.168.1.50" in out


def test_nas_disk_tool_formats_volumes(monkeypatch):
    import utils.home_tools as ht
    monkeypatch.setattr(ht, "nas_disk_usage",
                        lambda: {"ok": True, "nas_ip": "192.168.51.49",
                                 "volumes": [{"path": "/volume1", "used_gb": 100.0,
                                              "total_gb": 200.0, "free_gb": 100.0,
                                              "percent": 50.0, "status": "normal"}]})
    out = tools._t_nas_disk()
    assert "/volume1" in out and "50.0%" in out


def test_nas_disk_tool_surfaces_error(monkeypatch):
    import utils.home_tools as ht
    monkeypatch.setattr(ht, "nas_disk_usage",
                        lambda: {"error": "ยังไม่ตั้งค่า NAS_USER"})
    out = tools._t_nas_disk()
    assert out.startswith("❌") and "NAS_USER" in out


def test_nas_docker_tool_formats_containers(monkeypatch):
    import utils.home_tools as ht
    monkeypatch.setattr(ht, "nas_docker_status",
                        lambda: {"ok": True, "nas_ip": "192.168.51.49",
                                 "containers": [{"name": "ai-backend-1", "status": "running",
                                                 "running": True, "image": "x"}]})
    out = tools._t_nas_docker()
    assert "ai-backend-1" in out and "🟢" in out


def test_wol_tool(monkeypatch):
    import utils.home_tools as ht
    monkeypatch.setattr(ht, "wol_pc",
                        lambda: {"ok": True, "ip": "x", "message": "ส่ง WoL แล้ว"})
    out = tools._t_wol_pc()
    assert "✅" in out


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


def _run(messages, provider="lmstudio", **kw):
    return list(orch.run_agent(messages, provider=provider, **kw))


def _patch_lmstudio(monkeypatch, fake_client):
    """patch OpenAI constructor ใน _run_agent_lmstudio และตั้ง LMSTUDIO_BASE_URL"""
    monkeypatch.setattr(orch, "LMSTUDIO_BASE_URL", "http://fake:1234/v1")
    import openai
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: fake_client)


def test_agent_direct_answer_no_tools(monkeypatch):
    _patch_lmstudio(monkeypatch, FakeClient([_resp(_msg(content="คำตอบตรงๆ"))]))
    events = _run([{"role": "system", "content": "base"}])
    kinds = [e[1]["type"] for e in events if e[0] == "event"]
    chunks = [e[1] for e in events if e[0] == "chunk"]
    assert "answering" in kinds
    assert chunks == ["คำตอบตรงๆ"]


def test_agent_injects_system_hint(monkeypatch):
    _patch_lmstudio(monkeypatch, FakeClient([_resp(_msg(content="x"))]))
    messages = [{"role": "system", "content": "base"}]
    _run(messages)
    assert "[Agent Mode]" in messages[0]["content"]


def test_agent_inserts_system_when_missing(monkeypatch):
    _patch_lmstudio(monkeypatch, FakeClient([_resp(_msg(content="x"))]))
    messages = [{"role": "user", "content": "hi"}]
    _run(messages)
    assert messages[0]["role"] == "system"


def test_agent_tool_call_then_answer(monkeypatch):
    _patch_lmstudio(monkeypatch, FakeClient([
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
    _patch_lmstudio(monkeypatch, FakeClient([RuntimeError("boom")]))
    events = _run([{"role": "system", "content": "base"}])
    kinds = [e[1]["type"] for e in events if e[0] == "event"]
    chunks = [e[1] for e in events if e[0] == "chunk"]
    assert "error" in kinds
    assert chunks[0].startswith("❌ LM Studio agent error")  # unified loop → provider-named


def test_agent_bad_tool_arguments_default_empty(monkeypatch):
    # arguments เป็น JSON เสีย → args = {} (ไม่ crash)
    _patch_lmstudio(monkeypatch, FakeClient([
        _resp(_msg(tool_calls=[_tool_call("c1", "current_time", "{not json")])),
        _resp(_msg(content="done")),
    ]))
    captured = {}
    monkeypatch.setattr(orch, "execute_tool", lambda name, args: captured.update(args=args) or "ok")
    _run([{"role": "system", "content": "base"}])
    assert captured["args"] == {}


def test_agent_max_steps_forces_synthesis(monkeypatch):
    # ทุก step คืน tool_call → ไม่จบ → ครบ max_steps → synthesis stream
    _patch_lmstudio(monkeypatch, FakeClient([
        _resp(_msg(tool_calls=[_tool_call("c1", "calculator", '{"expression":"1+1"}')])),
        [_stream_chunk("สรุป"), _stream_chunk("คำตอบ")],   # final stream (stream=True)
    ]))
    monkeypatch.setattr(orch, "execute_tool", lambda name, args: "1+1 = 2")
    events = _run([{"role": "system", "content": "base"}], max_steps=1)
    kinds = [e[1]["type"] for e in events if e[0] == "event"]
    chunks = "".join(e[1] for e in events if e[0] == "chunk")
    assert "max_steps_reached" in kinds
    assert chunks == "สรุปคำตอบ"


# ── [TOOL_RESULT] marker หลุดจาก chat template (cosmetic bug 2026-06-12) ────
def test_marker_filter_strips_markers_and_leading_space():
    f = orch._MarkerFilter()
    out = f.feed("[TOOL_RESULT]  \nคำตอบจริง") + f.flush()
    assert out == "คำตอบจริง"


def test_marker_filter_strips_marker_split_across_chunks():
    f = orch._MarkerFilter()
    out = f.feed("[TOOL_") + f.feed("RESULT]\nสวัสดี") + f.feed(" [END_TOOL_RESULT]ค่ะ") + f.flush()
    assert out == "สวัสดี ค่ะ"


def test_marker_filter_passthrough_normal_text():
    f = orch._MarkerFilter()
    out = f.feed("ข้อความ [ปกติ] ไม่โดนตัด") + f.flush()
    assert out == "ข้อความ [ปกติ] ไม่โดนตัด"


def test_agent_direct_answer_strips_tool_result_marker(monkeypatch):
    _patch_lmstudio(monkeypatch, FakeClient([
        _resp(_msg(content="[TOOL_RESULT]  \nคำตอบจริง")),
    ]))
    events = _run([{"role": "system", "content": "base"}])
    chunks = [e[1] for e in events if e[0] == "chunk"]
    assert chunks == ["คำตอบจริง"]


def test_agent_synthesis_stream_strips_marker_split_across_chunks(monkeypatch):
    _patch_lmstudio(monkeypatch, FakeClient([
        _resp(_msg(tool_calls=[_tool_call("c1", "calculator", '{"expression":"1+1"}')])),
        [_stream_chunk("[TOOL_"), _stream_chunk("RESULT]\nสรุป"), _stream_chunk("คำตอบ")],
    ]))
    monkeypatch.setattr(orch, "execute_tool", lambda name, args: "1+1 = 2")
    events = _run([{"role": "system", "content": "base"}], max_steps=1)
    chunks = "".join(e[1] for e in events if e[0] == "chunk")
    assert chunks == "สรุปคำตอบ"


# ── gemini agent: Part.from_text เป็น keyword-only ใน SDK ใหม่ (บั๊ก 2026-06-12) ──
def test_split_messages_for_gemini_with_history():
    pytest.importorskip("google.genai")
    # มี history คั่นกลาง → ต้องสร้าง Content/Part ได้ (SDK ใหม่ from_text บังคับ text=)
    sys_text, history, last_user = orch._split_messages_for_gemini([
        {"role": "system", "content": "base"},
        {"role": "user", "content": "คำถามเก่า"},
        {"role": "assistant", "content": "คำตอบเก่า"},
        {"role": "user", "content": "คำถามใหม่"},
    ])
    assert sys_text == "base"
    assert last_user == "คำถามใหม่"
    assert [c.role for c in history] == ["user", "model"]
    assert history[0].parts[0].text == "คำถามเก่า"


# ── orchestrator config: LM Studio token + agent hint ──────────────────────
def test_orchestrator_uses_lmstudio_api_key_from_env(monkeypatch):
    # LMSTUDIO_API_KEY ต้องถูกส่งเข้า OpenAI constructor ทุกครั้ง
    captured = {}
    import openai
    monkeypatch.setattr(orch, "LMSTUDIO_BASE_URL", "http://fake:1234/v1")
    monkeypatch.setattr(orch, "LMSTUDIO_API_KEY", "secret-token-123")

    def fake_openai(**kw):
        captured.update(kw)
        return FakeClient([_resp(_msg(content="ok"))])

    monkeypatch.setattr(openai, "OpenAI", fake_openai)
    _run([{"role": "system", "content": "base"}])
    assert captured.get("api_key") == "secret-token-123"


def test_orchestrator_api_key_defaults_to_lmstudio(monkeypatch):
    # fallback เมื่อไม่ตั้ง env = "lmstudio"
    import openai
    monkeypatch.setattr(orch, "LMSTUDIO_BASE_URL", "http://fake:1234/v1")
    monkeypatch.setattr(orch, "LMSTUDIO_API_KEY", "lmstudio")
    captured = {}

    def fake_openai(**kw):
        captured.update(kw)
        return FakeClient([_resp(_msg(content="ok"))])

    monkeypatch.setattr(openai, "OpenAI", fake_openai)
    _run([{"role": "system", "content": "base"}])
    assert captured.get("api_key") == "lmstudio"


def test_agent_hint_advertises_home_tools():
    # 🟠 MAJOR fix: โมเดลเล็กพึ่ง hint เลือก tool — ต้องโฆษณา home tools
    # ไม่งั้นถามเรื่อง network/NAS แล้วโมเดลเดาแทนเรียก tool (กุ)
    for kw in ("ping_network", "nas_disk", "nas_docker"):
        assert kw in orch.AGENT_SYSTEM_HINT
