"""ก้อน 9 (audit 2026-09-24 MEDIUM) — orchestrator 2 จุด

1. Gemini adapter: ครบ max_steps แล้ว tool result ของ step สุดท้ายค้างใน `_pending` ไม่เคยถูกส่ง → `synthesize()`
   ส่งข้อความสั่งสรุปแทน ⇒ history = model(function_call) → user(text) โดยไม่มี function_response คั่น
   (API ตอบ 400 "function call turn comes immediately after a user turn or after a function response turn"
   · pydantic-ai #3692) และข้อมูลที่เพิ่งได้มาไม่ถึงโมเดล · SDK 2.10 เองประกอบเทิร์นตอบ tool เป็น
   `Content(role='user', parts=func_response_parts)` ล้วน (`models.py` AFC) ⇒ ส่ง function responses ล้วน +
   config ต่อคำขอ (แทนที่ทั้งก้อน `chats.py`) ที่ `tool_config=NONE` และคำสั่งสรุปอยู่ใน system_instruction
2. Ollama ReAct: guard "ไม่มีข้อมูลจริง" เดิมทำงานเฉพาะครบ max_steps · `Answer:` ที่ step ใดก็ yield ตรง ·
   tool ที่รายงานล้ม/ว่างโดยไม่ขึ้นต้น ❌ (`Memory error:` `Vault error:` `ไม่พบ…` — agents/tools.py) นับเป็นได้ข้อมูล
วัด prod 08-18→09-28: Gemini 10 run / LM Studio 18 run ไม่เคยถึง max_steps · Ollama agent มีแต่ probe ⇒ ทั้งคู่แฝง
"""
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agents.orchestrator as orch
from google.genai import types as genai_types


# ── 1. Gemini synthesize ─────────────────────────────────────────────────────
def _part(function_call=None, text=None):
    p = MagicMock(); p.function_call = function_call; p.text = text
    return p


def _chunk(parts):
    ch = MagicMock(); cand = MagicMock(); cand.content.parts = parts; ch.candidates = [cand]
    return ch


def _fc(name="web_search"):
    fc = MagicMock(); fc.name = name; fc.args = {"query": "ราคาทอง"}
    return fc


def _run_gemini(stream_side, max_steps=1, tool_result="ราคาทองวันนี้ 41,500 บาท"):
    import contextlib
    fake_chat = MagicMock()
    fake_chat.send_message_stream.side_effect = stream_side
    fake_client = MagicMock()
    fake_client.chats.create.return_value = fake_chat
    with contextlib.ExitStack() as st:
        for cm in (patch("google.genai.Client", return_value=fake_client),
                   patch.object(orch, "GEMINI_API_KEY", "k"),
                   patch.object(orch, "execute_tool", return_value=tool_result),
                   patch.object(orch, "get_gemini_tools", return_value=[]),
                   patch.object(orch.time, "sleep", return_value=None)):
            st.enter_context(cm)
        out = list(orch._run_agent_gemini([{"role": "system", "content": "SYS"}, {"role": "user", "content": "ราคาทอง"}],
                                          "gemini-x", max_steps=max_steps))
    return out, fake_client


def test_gemini_ครบ_max_steps_ต้องส่ง_function_response_ก่อนสรุป():
    sent = []

    def side(message, config=None):
        sent.append((message, config))
        if len(sent) == 1:
            return iter([_chunk([_part(function_call=_fc())])])
        return iter([_chunk([_part(text="41,500 บาท")])])

    out, _ = _run_gemini(side, max_steps=1)
    assert len(sent) == 2, sent
    msg, cfg = sent[1]
    assert isinstance(msg, list) and msg, f"ข้อความสรุปต้องเป็น function responses ไม่ใช่ข้อความ ({msg!r})"
    frs = [p.function_response for p in msg if getattr(p, "function_response", None)]
    assert len(frs) == len(msg) == 1, "เทิร์นตอบ tool ต้องมีแต่ function_response (แบบเดียวกับที่ SDK ประกอบเอง)"
    assert frs[0].name == "web_search" and "41,500" in str(frs[0].response)
    assert "41,500 บาท" in "".join(p for k, p in out if k == "chunk")


def test_gemini_synth_config_ห้ามเรียก_tool_และคงค่าเดิม():
    sent = []

    def side(message, config=None):
        sent.append(config)
        if len(sent) == 1:
            return iter([_chunk([_part(function_call=_fc())])])
        return iter([_chunk([_part(text="ok")])])

    _, client = _run_gemini(side, max_steps=1)
    base = client.chats.create.call_args.kwargs["config"]
    cfg = sent[1]
    assert cfg is not None, "synth ต้องส่ง config ต่อคำขอ (chats.py: config แทนที่ config ของ chat ทั้งก้อน)"
    assert cfg.tool_config.function_calling_config.mode == genai_types.FunctionCallingConfigMode.NONE
    assert cfg.temperature == base.temperature
    assert cfg.system_instruction.startswith(base.system_instruction), "system prompt เดิมต้องอยู่ครบ"
    assert orch._FORCE_SYNTH_PROMPT in cfg.system_instruction
    assert sent[0] is None, "step ปกติต้องไม่ส่ง config (ใช้ของ chat)"


def test_gemini_ตอบใน_step_แรก_ไม่เรียก_synthesize():
    sent = []

    def side(message, config=None):
        sent.append(message)
        return iter([_chunk([_part(text="สวัสดี")])])

    out, _ = _run_gemini(side, max_steps=4)
    assert len(sent) == 1
    assert "สวัสดี" in "".join(p for k, p in out if k == "chunk")


# ── 2. Ollama ReAct guard ────────────────────────────────────────────────────
class _FakeOllama:
    def __init__(self, contents):
        self.contents, self.calls = list(contents), 0
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kw):
        c = self.contents[min(self.calls, len(self.contents) - 1)]
        self.calls += 1
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=c))])


def _run_ollama(monkeypatch, contents, tool_result, max_steps=4):
    import openai
    fake = _FakeOllama(contents)
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: fake)
    monkeypatch.setattr(orch, "execute_tool", lambda name, args: tool_result)
    out = list(orch._run_agent_ollama([{"role": "user", "content": "ราคาทองวันนี้"}], "llama3", max_steps))
    return "".join(p for k, p in out if k == "chunk"), fake


ACTION = 'Thought: ต้องค้น\nAction: {"tool": "web_search", "args": {"query": "ราคาทอง"}}'
FAKE_ANSWER = "Answer: ราคาทองวันนี้ ~$1,825 (Source: Google Search)"


@pytest.mark.parametrize("bad_result", [
    "❌ web_search ล้ม: timeout",
    "Memory error: ChromaDB down",
    "Vault error: path missing",
    "Skills error: x",
    "ไม่พบโน้ตที่เกี่ยวข้องใน vault",
    "ไม่พบ entity ที่ตรงกับ 'ทอง'",
    "   ",
])
def test_ollama_tool_ไม่ได้ข้อมูล_แล้วตอบ_ต้องไม่ปล่อยคำตอบแต่ง(monkeypatch, bad_result):
    text, _ = _run_ollama(monkeypatch, [ACTION, FAKE_ANSWER], bad_result)
    assert "1,825" not in text, f"คำตอบที่แต่งหลัง tool ไม่ได้ข้อมูลหลุดออกไป ({text!r})"
    assert "ไม่ได้ข้อมูลจริง" in text


def test_ollama_plain_หลัง_tool_ล้ม_ก็ต้องถูกกัน(monkeypatch):
    text, _ = _run_ollama(monkeypatch, [ACTION, "ราคาทองวันนี้ประมาณ 1,825 ดอลลาร์"], "❌ timeout")
    assert "1,825" not in text


def test_ollama_tool_ได้ข้อมูลจริง_ตอบได้ตามปกติ(monkeypatch):
    text, _ = _run_ollama(monkeypatch, [ACTION, "Answer: 41,500 บาท"], "ทองคำแท่ง ขายออก 41,500 บาท (สมาคมค้าทองคำ)")
    assert text == "41,500 บาท"


def test_ollama_ตอบตรงใน_step_แรก_ไม่ต้องมี_tool(monkeypatch):
    text, _ = _run_ollama(monkeypatch, ["Answer: 2"], "unused")
    assert text == "2"


def test_ollama_ครบ_max_steps_นับ_Memory_error_ว่าไม่ได้ข้อมูล(monkeypatch):
    text, fake = _run_ollama(monkeypatch, [ACTION], "Memory error: down", max_steps=2)
    assert "ไม่ได้ข้อมูลจริง" in text
    assert fake.calls == 2, "ไม่ได้ข้อมูลเลย = ห้ามเรียก LLM สรุปเพิ่ม"


def test_is_informative():
    ok = orch._is_informative
    assert ok("41,500 บาท") and ok("ไม่มีข้อมูลเพิ่ม แต่ราคา 41,500")
    for bad in ("", "  ", "❌ x", "Memory error: x", "Vault error: y", "Skills error: z", "ไม่พบโน้ต", "ไม่พบ entity"):
        assert not ok(bad), bad
