"""agents/orchestrator.py ต้องใช้ค่าจาก config ถึง client/request จริง (ก้อน 4 · 2026-09-23)

เดิมไฟล์นี้อ่าน env เอง 11 จุด — ทุกชื่อมีเจ้าของอยู่แล้ว (`core/config.py`) จึงเปลี่ยนเป็น
import ค่า · เทสนี้ยืนยันว่าค่า *ถึงปลายทาง* (constructor ของ client + body ของ request)
ไม่ใช่แค่อยู่ในโมดูล — ใช้ค่าที่ต่างจาก default ทุกตัว ⇒ hardcode default กลับมาจะแดง
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agents.orchestrator as orch  # noqa: E402


class _FakeOpenAI:
    instances: list = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls: list[dict] = []
        _FakeOpenAI.instances.append(self)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        msg = SimpleNamespace(content="Answer: ok", tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")])


def _install(monkeypatch):
    import openai

    _FakeOpenAI.instances = []
    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)


def test_ollama_agent_ใช้ค่าจาก_config(monkeypatch):
    _install(monkeypatch)
    monkeypatch.setattr(orch, "OLLAMA_BASE_URL", "http://fake-ollama:1/v1")
    monkeypatch.setattr(orch, "OLLAMA_TIMEOUT", 77)
    monkeypatch.setattr(orch, "OLLAMA_NUM_CTX", 1234)

    out = list(orch._run_agent_ollama([{"role": "user", "content": "hi"}], "m", max_steps=1))
    assert ("chunk", "ok") in out or any(k == "chunk" for k, _ in out)

    (client,) = _FakeOpenAI.instances
    assert client.kwargs["base_url"] == "http://fake-ollama:1/v1"
    assert client.kwargs["timeout"] == 77
    assert client.calls, "ไม่ได้ยิง request เลย — เทสนี้ไม่ได้ตรวจอะไร"
    for call in client.calls:
        assert call["extra_body"]["options"]["num_ctx"] == 1234


def test_lmstudio_agent_ใช้ค่าจาก_config(monkeypatch):
    _install(monkeypatch)
    monkeypatch.setattr(orch, "LMSTUDIO_BASE_URL", "http://fake-lms:2/v1")
    monkeypatch.setattr(orch, "LMSTUDIO_API_KEY", "sk-fake")
    monkeypatch.setattr(orch, "LMSTUDIO_TIMEOUT", 55)

    list(orch._run_agent_lmstudio([{"role": "user", "content": "hi"}], "m", max_steps=1))

    (client,) = _FakeOpenAI.instances
    assert client.kwargs == {"base_url": "http://fake-lms:2/v1", "api_key": "sk-fake", "timeout": 55}


def test_ค่าของ_orchestrator_คือตัวเดียวกับ_config():
    """ไม่ใช่แค่ "เท่ากัน" (ซึ่งเป็นจริงได้โดยบังเอิญเพราะอ่าน env ชุดเดียวกัน) —
    ต้องไม่มี `os.getenv` ดิบในไฟล์ (ตรวจโดย test_env_registry) และชื่อต้อง import มาจริง"""
    import ast
    import pathlib

    src = (pathlib.Path(orch.__file__)).read_text()
    imported = {a.asname or a.name for n in ast.walk(ast.parse(src))
                if isinstance(n, ast.ImportFrom) and n.module == "core.config" for a in n.names}
    for name in ("GEMINI_API_KEY", "LMSTUDIO_BASE_URL", "LMSTUDIO_API_KEY", "LMSTUDIO_TIMEOUT",
                 "OLLAMA_BASE_URL", "OLLAMA_MODEL", "OLLAMA_TIMEOUT", "OLLAMA_NUM_CTX"):
        assert name in imported, f"{name} ไม่ได้ import จาก core.config"


def test_ollama_agent_ครบ_max_steps_แล้วสรุป_ก็ใช้ค่าจาก_config(monkeypatch):
    """เส้น "ครบ max_steps → บังคับสรุป" เป็นการเรียก LLM อีกครั้งแยกจากในลูป
    (mutation O4: hardcode num_ctx เฉพาะตรงนั้นแล้วเทสข้างบนยังเขียว — เพราะ fake
    ตอบ `Answer:` ตั้งแต่ก้าวแรก ไม่เคยเดินถึงเส้นนี้)"""
    _install(monkeypatch)
    # ⚠️ ไม่ใส่ "args": {...} — `_ACTION_RE` แบบ non-greedy หยุดที่ `}` ตัวแรก ⇒ Action ที่มี
    #    args ซ้อน parse พังเสมอ (บั๊กเดิม เจอ 2026-09-23 · ยังไม่แก้ — นอกขอบเขตก้อน 4)
    replies = iter(['Action: {"tool": "fake_tool"}', "Answer: สรุปแล้ว"])

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        msg = SimpleNamespace(content=next(replies), tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")])

    monkeypatch.setattr(_FakeOpenAI, "_create", _create)
    monkeypatch.setattr(orch, "execute_tool", lambda name, args: "ผลปลอม")
    monkeypatch.setattr(orch, "OLLAMA_NUM_CTX", 2345)

    out = list(orch._run_agent_ollama([{"role": "user", "content": "hi"}], "m", max_steps=1))

    assert ("event", {"type": "max_steps_reached"}) in out, "ไม่ได้เดินถึงเส้นบังคับสรุป"
    assert ("chunk", "สรุปแล้ว") in out
    (client,) = _FakeOpenAI.instances
    assert len(client.calls) == 2
    assert [c["extra_body"]["options"]["num_ctx"] for c in client.calls] == [2345, 2345]
