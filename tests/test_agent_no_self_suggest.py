"""agent ต้องไม่แนะนำให้ "เปิด Agent mode" ทั้งที่อยู่ใน agent อยู่แล้ว (devlog 09-29 ต่อ 35)

ต้นเหตุ: guard `_NO_FABRICATION` ของ persona สั่ง "ดึงไม่ได้ → แนะนำให้เปิด Agent mode"
แล้ว system prompt ก้อนเดียวกันถูกส่งเข้า agent ทั้ง 3 provider · probe B2 = 18/18 คำตอบแนะนำ
⇒ ตัดประโยคนั้นเฉพาะตอนประกอบ system ของ agent · persona เดิม (แชทปกติ/เสียง/seed) ห้ามเปลี่ยน
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import agents.orchestrator as orch
from assistants.config import ASSISTANTS, SUGGEST_AGENT_MODE, _NO_FABRICATION

PERSONA = next(iter(ASSISTANTS.values()))["system_prompt"]


def test_ประโยคแนะนำอยู่ใน_guard_และ_persona_จริง():
    # ถ้าตัวนี้แดง การตัดใน agent จะกลายเป็น no-op เงียบๆ
    assert SUGGEST_AGENT_MODE in _NO_FABRICATION
    assert SUGGEST_AGENT_MODE in PERSONA


def _assert_agent_system(text: str):
    assert "Agent mode" not in text.replace("[Agent Mode]", "")
    assert "ห้ามแต่งข้อมูล" in text          # guard ที่เหลือยังอยู่ครบ
    assert "ดึงสดไม่ได้" in text


class _FakeOpenAI:
    def __init__(self, **kw):
        self.calls = []
        _FakeOpenAI.last = self
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append([dict(m) for m in kw["messages"]])
        if kw.get("stream"):
            return iter([SimpleNamespace(choices=[SimpleNamespace(
                delta=SimpleNamespace(content="ok", tool_calls=None), finish_reason="stop")])])
        msg = SimpleNamespace(content="Answer: ok", tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def _messages():
    return [{"role": "system", "content": PERSONA}, {"role": "user", "content": "ราคาทองวันนี้"}]


def test_lmstudio_agent_ไม่มีประโยคแนะนำ(monkeypatch):
    import openai
    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)
    monkeypatch.setattr(orch, "LMSTUDIO_BASE_URL", "http://fake:1234/v1")
    list(orch.run_agent(_messages(), provider="lmstudio"))
    sent = _FakeOpenAI.last.calls[0][0]
    assert sent["role"] == "system" and "[Agent Mode]" in sent["content"]
    _assert_agent_system(sent["content"])


def test_ollama_react_agent_ไม่มีประโยคแนะนำ(monkeypatch):
    import openai
    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)
    list(orch._run_agent_ollama(_messages(), "m", max_steps=1))
    sent = _FakeOpenAI.last.calls[0][0]
    assert sent["role"] == "system" and "Action:" in sent["content"]
    _assert_agent_system(sent["content"])


def test_gemini_agent_ไม่มีประโยคแนะนำ():
    fake_client = MagicMock()
    fake_chat = MagicMock()
    fake_chat.send_message_stream.return_value = iter([])
    fake_client.chats.create.return_value = fake_chat
    with patch("google.genai.Client", return_value=fake_client), \
         patch("agents.orchestrator.GEMINI_API_KEY", "fake-key"), \
         patch("agents.orchestrator.get_gemini_tools", return_value=[]), \
         patch("agents.orchestrator.time.sleep", return_value=None):
        list(orch._run_agent_gemini(_messages(), "gemini-x", max_steps=1))
    cfg = fake_client.chats.create.call_args.kwargs["config"]
    assert "[Agent Mode]" in cfg.system_instruction
    _assert_agent_system(cfg.system_instruction)
