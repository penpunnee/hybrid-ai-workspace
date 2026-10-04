"""เส้นแชท LM Studio ต้องข้ามช่วงคิด (`<think>`) ของ qwen3 — ต่อ 87 (2026-10-04)

วัด prod ผ่าน handler แชทจริง: "สวัสดี" คิด 2,456 token **58 วิ** (จอว่าง) แล้วตอบแค่ 325 token ·
"เช็คเครื่อข่าย" คิด 13 วิ · ส่วนคิดกิน 70–80% ของเวลารอทั้งหมด
วิธีที่ลองแล้วใช้ไม่ได้ (วัดตรงกับ LM Studio .235 · 2 รอบ × 3 คำถาม):
`chat_template_kwargs.enable_thinking=False` ยังคิด 6/6 · + `enable_thinking` ระดับบน ยังคิด 6/6 ·
`/no_think` ยังคิด 6/6 (ตรง LM Studio bug #1990)
วิธีที่ได้: ต่อข้อความ assistant ที่ปิด think ไว้แล้วท้ายคำขอ → **คิด 0 token 6/6** · คำตอบแรก 0.1–0.4 วิ ·
เนื้อคำตอบไม่มีแท็กหลุด (ตรวจ 3 คำถาม รวมโจทย์เลข)
"""
from types import SimpleNamespace

import pytest

from utils import llm

PREFILL = {"role": "assistant", "content": "<think>\n\n</think>\n\n"}


def _chunk(text, finish=None):
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=text), finish_reason=finish)], usage=None)


class _Rec:
    def __init__(self):
        self.sent = None

    def create(self, **kw):
        self.sent = kw
        return iter([_chunk("ตอบ"), _chunk("", "stop")])


@pytest.fixture()
def rec(monkeypatch):
    r = _Rec()
    monkeypatch.setattr(llm.lmstudio_client, "chat", SimpleNamespace(completions=r))
    monkeypatch.setattr(llm, "_lmstudio_loaded_ctx", lambda model: None)
    monkeypatch.setattr(llm, "_LMSTUDIO_SKIP_THINKING", True)
    return r


MSGS = [{"role": "system", "content": "ระบบ"}, {"role": "user", "content": "สวัสดี"}]


def test_qwen3_ต่อ_assistant_ที่ปิด_think_ไว้ท้ายคำขอ(rec):
    out = "".join(llm._stream_lmstudio(list(MSGS), model="qwen/qwen3.5-9b"))
    assert out == "ตอบ"
    sent = rec.sent["messages"]
    assert sent[-1] == PREFILL
    assert sent[:-1] == MSGS, "ข้อความเดิมต้องไม่ถูกแตะ"


def test_ไม่แก้_list_ของผู้เรียก(rec):
    msgs = list(MSGS)
    "".join(llm._stream_lmstudio(msgs, model="qwen/qwen3.5-9b"))
    assert msgs == MSGS


def test_โมเดลที่ไม่ใช่_qwen3_ไม่ต่อ(rec):
    # แท็ก <think> เป็นรูปแบบ chat template ของ qwen3 — โมเดลอื่นจะเห็นเป็นข้อความดิบ
    "".join(llm._stream_lmstudio(list(MSGS), model="google/gemma-4-e4b"))
    assert rec.sent["messages"] == MSGS


def test_ปิดสวิตช์แล้ว_ไม่ต่อ(rec, monkeypatch):
    monkeypatch.setattr(llm, "_LMSTUDIO_SKIP_THINKING", False)
    "".join(llm._stream_lmstudio(list(MSGS), model="qwen/qwen3.5-9b"))
    assert rec.sent["messages"] == MSGS


def test_มีรูป_รูปยังอยู่ใน_user_ล่าสุด_และ_prefill_อยู่ท้าย(rec):
    "".join(llm._stream_lmstudio(list(MSGS), model="qwen/qwen3.5-9b",
                                 image_b64="AAAA", image_mime="image/png"))
    sent = rec.sent["messages"]
    assert sent[-1] == PREFILL
    user = sent[-2]
    assert user["role"] == "user" and isinstance(user["content"], list)
    assert user["content"][1]["image_url"]["url"].startswith("data:image/png;base64,AAAA")


def test_log_บอกว่าข้ามช่วงคิด(rec, caplog):
    import logging
    with caplog.at_level(logging.INFO, logger=llm.logger.name):
        "".join(llm._stream_lmstudio(list(MSGS), model="qwen/qwen3.5-9b"))
    assert any("ข้ามคิด=ใช่" in r.getMessage() for r in caplog.records)
