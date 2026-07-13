"""Gemini quota fallback ห้ามปนเปื้อนคำตอบจริง (เจอจริงจากภาพหน้าจอ 2026-07-13)

เดิม (routers/chat.py): เมื่อ Gemini quota หมด/ใช้ไม่ได้ โค้ด yield ข้อความ
"⚠️ Gemini quota หมด — กำลังลอง local model..." เป็น `chunk` ปกติ แล้วบวกเข้า
full_response ตรงๆ → ข้อความเตือนนี้:
  1. ติดอยู่หน้าคำตอบจริงที่ผู้ใช้เห็นในบับเบิล (ดูไม่เป็นมืออาชีพ)
  2. ถูก save ลง DB ปนกับคำตอบจริง (save_message)
  3. เข้า remember()/teach()/auto-learn lesson (ปนเปื้อน episodic memory)

Harnet (โปรเจกต์พี่น้อง ~/Desktop/harnet) ไม่มีปัญหานี้เพราะไม่มี auto-fallback
เลย — error จะแยกเป็น SSE `error` event ต่างหาก ไม่ปนกับเนื้อหาคำตอบ

Fix: ui เก็บ auto-fallback ไว้ (มีประโยชน์กว่า harnet) แต่ข้อความแจ้งเตือนต้อง
แยกออกจาก `chunk`/`full_response` เป็น SSE event `provider_fallback` ต่างหาก
(pattern เดียวกับ active_learning/reflection ที่มีอยู่แล้ว) — frontend เลือกจะ
แสดงเป็น badge เล็กๆ แยกจากบับเบิลคำตอบแทน
"""
import json
import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

os.environ["UI_PASSWORD"] = ""
import server  # noqa: E402
from utils.llm import GeminiQuotaExhausted  # noqa: E402

client = TestClient(server.app)

_BODY = {
    "provider": "gemini",
    "assistant": "ฟ้า",
    "prompt": "สวัสดีครับ",
    "session_id": "test_gemini_fallback",
}


def _events_of(resp_text: str) -> list[dict]:
    out = []
    for line in resp_text.splitlines():
        if not line.startswith("data: "):
            continue
        try:
            out.append(json.loads(line[6:]))
        except json.JSONDecodeError:
            continue
    return out


def _quota_then_answer():
    """side_effect ของ stream_response: ครั้งแรก raise quota, ครั้งสอง yield คำตอบจริง"""
    calls = {"n": 0}

    def _fn(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise GeminiQuotaExhausted("429 limit exceeded")
        return iter(["สวัสดี", "ครับ"])
    return _fn


class TestGeminiQuotaFallbackNotice:
    def test_fallback_notice_not_mixed_into_chunks(self):
        """ข้อความเตือน quota ห้ามอยู่ใน chunk event เดียวกับคำตอบจริง"""
        with patch("routers.chat.stream_response", side_effect=_quota_then_answer()), \
             patch("routers.chat.save_message", return_value=1), \
             patch("reasoning.router.route",
                   return_value=MagicMock(provider="ollama", model="", reason="test")), \
             patch("reasoning.classifier.needs_internet", return_value=False):
            resp = client.post("/api/chat", json=_BODY)
            assert resp.status_code == 200
            events = _events_of(resp.text)

            chunk_text = "".join(e.get("chunk", "") for e in events)
            assert "quota" not in chunk_text.lower(), \
                f"ข้อความเตือน quota ต้องไม่ปนใน chunk แต่เจอ: {chunk_text!r}"
            assert chunk_text == "สวัสดีครับ"

    def test_fallback_emits_dedicated_event(self):
        """ต้องมี SSE event แยกต่างหากบอกว่า fallback ไป provider ไหนเพราะอะไร"""
        with patch("routers.chat.stream_response", side_effect=_quota_then_answer()), \
             patch("routers.chat.save_message", return_value=1), \
             patch("reasoning.router.route",
                   return_value=MagicMock(provider="ollama", model="", reason="test")), \
             patch("reasoning.classifier.needs_internet", return_value=False):
            resp = client.post("/api/chat", json=_BODY)
            events = _events_of(resp.text)

            fallback_events = [e["provider_fallback"] for e in events if "provider_fallback" in e]
            assert fallback_events, "ต้องมี event key 'provider_fallback' อย่างน้อย 1 อัน"
            assert fallback_events[0]["reason"] == "quota"
            assert fallback_events[0]["to"] == "ollama"

    def test_saved_message_excludes_fallback_notice(self):
        """ข้อความที่ save ลง DB ต้องเป็นคำตอบจริงล้วนๆ ไม่มี banner ปน"""
        with patch("routers.chat.stream_response", side_effect=_quota_then_answer()), \
             patch("routers.chat.save_message", return_value=1) as mock_save, \
             patch("reasoning.router.route",
                   return_value=MagicMock(provider="ollama", model="", reason="test")), \
             patch("reasoning.classifier.needs_internet", return_value=False):
            resp = client.post("/api/chat", json=_BODY)
            _ = resp.text

            asst_saves = [c for c in mock_save.call_args_list if c.args[1] == "assistant"]
            assert asst_saves, "ต้องมีการ save assistant message"
            assert asst_saves[0].args[2] == "สวัสดีครับ", \
                f"ข้อความ save ต้องไม่มี banner ปน แต่ได้: {asst_saves[0].args[2]!r}"
