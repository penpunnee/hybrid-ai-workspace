"""Plan mode (§22 ChatBox) — backend flag `plan_mode`

Major 2 fix (scrutinize 2026-06-10): เดิม frontend เติม suffix
"[ขอให้ช่วยวางแผน...]" ต่อท้าย prompt ก่อนส่ง → ถูก save_message ลง
chat_history.db ปนเปื้อน history / fine-tune export / memory

สัญญาใหม่: client ส่ง {"plan_mode": true} แทน —
1. prompt ที่บันทึกลง DB ต้องสะอาด (ไม่มี instruction ปน)
2. instruction วางแผนถูกฉีดเข้า system prompt (messages[0]) เท่านั้น
3. plan_mode ต้อง bypass semantic response cache (คำตอบ plan-style
   คนละความหมายกับคำตอบปกติของ prompt เดียวกัน)
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

os.environ["UI_PASSWORD"] = ""
import server  # noqa: E402

client = TestClient(server.app)

_PLAN_BODY = {
    "provider": "ollama",
    "assistant": "ฟ้า",
    "prompt": "ช่วยทำเว็บขายของหน่อย",
    "session_id": "test_plan_mode",
    "plan_mode": True,
}


class TestPlanMode:
    def test_plan_instruction_goes_to_system_prompt_not_db(self):
        """plan_mode=true → instruction อยู่ใน system prompt, prompt ใน DB สะอาด"""
        with patch("routers.chat.stream_response") as mock_stream, \
             patch("routers.chat.save_message", return_value=1) as mock_save:
            mock_stream.return_value = iter(["โอเค"])

            resp = client.post("/api/chat", json=_PLAN_BODY)
            assert resp.status_code == 200
            _ = resp.text  # drain stream → generator ทำงานจริง

            # 1) user message ที่บันทึกลง DB = prompt เดิมเป๊ะ ไม่มี instruction ปน
            user_saves = [c for c in mock_save.call_args_list if c.args[1] == "user"]
            assert user_saves, "ต้องมีการ save user message"
            saved_prompt = user_saves[0].args[2]
            assert saved_prompt == _PLAN_BODY["prompt"]
            assert "วางแผน" not in saved_prompt.replace(_PLAN_BODY["prompt"], "")

            # 2) instruction ฉีดเข้า system prompt (messages[0]) เท่านั้น
            messages = mock_stream.call_args.args[0]
            assert messages[0]["role"] == "system"
            assert "วางแผน" in messages[0]["content"]
            # user message ที่ส่งเข้า LLM ก็สะอาดเช่นกัน
            assert messages[-1]["content"] == _PLAN_BODY["prompt"]

    def test_no_plan_mode_no_instruction(self):
        """ไม่ส่ง plan_mode → system prompt ไม่มี instruction วางแผน"""
        body = {k: v for k, v in _PLAN_BODY.items() if k != "plan_mode"}
        with patch("routers.chat.stream_response") as mock_stream, \
             patch("routers.chat.save_message", return_value=1):
            mock_stream.return_value = iter(["โอเค"])

            resp = client.post("/api/chat", json=body)
            assert resp.status_code == 200
            _ = resp.text

            messages = mock_stream.call_args.args[0]
            assert "[โหมดวางแผน]" not in messages[0]["content"]

    def test_plan_mode_bypasses_response_cache(self):
        """plan_mode=true → ห้าม short-circuit จาก semantic response cache"""
        fake_hit = {
            "response": "คำตอบเก่าจาก cache",
            "similarity": 0.99,
            "source_prompt": _PLAN_BODY["prompt"],
            "model": "llama3",
        }
        with patch("utils.response_cache.lookup", return_value=fake_hit), \
             patch("routers.chat.stream_response") as mock_stream, \
             patch("routers.chat.save_message", return_value=1):
            mock_stream.return_value = iter(["คำตอบใหม่"])

            resp = client.post("/api/chat", json=_PLAN_BODY)
            assert resp.status_code == 200
            body_text = resp.text

            # ต้องเรียก LLM จริง ไม่ใช่คืน cache
            assert mock_stream.called, "plan_mode ต้อง bypass response cache"
            assert "คำตอบเก่าจาก cache" not in body_text
