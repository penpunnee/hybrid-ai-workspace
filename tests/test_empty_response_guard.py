"""Empty-response guard — กัน AI bubble ว่างเปล่า + save '' ลง DB

เจอจริง 2026-07-05: qwen3.5-9b "คิด" ใน <think> จนหมด token ไม่เคยตอบจริง
→ stream จบด้วย full_response ว่างเปล่า → frontend โชว์บับเบิลว่าง 131s
และ save_message บันทึก '' ลง chat_history.db (ปนเปื้อน history/fine-tune)

ชั้นแรกกันที่ parser (salvage think tail — tests/test_parser.py)
ชั้นนี้กันที่ router: ถ้า provider ไหนก็ตามคืน stream ว่างเปล่า →
ต้อง yield ข้อความแจ้งผู้ใช้แทน และข้อความที่ save ต้องไม่ว่าง
"""
import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

os.environ["UI_PASSWORD"] = ""
import server  # noqa: E402

client = TestClient(server.app)

_BODY = {
    "provider": "ollama",
    "assistant": "ฟ้า",
    "prompt": "ช่วยเล่าเรื่องตลกสั้นๆ ให้ฟังหน่อยได้ไหม",
    "session_id": "test_empty_guard",
}


def _chunks_of(resp_text: str) -> str:
    out = ""
    for line in resp_text.splitlines():
        if not line.startswith("data: "):
            continue
        try:
            obj = json.loads(line[6:])
        except json.JSONDecodeError:
            continue
        out += obj.get("chunk", "")
    return out


class TestEmptyResponseGuard:
    def test_empty_stream_yields_notice_not_blank(self):
        """stream ว่างเปล่า → SSE ต้องมี chunk แจ้งผู้ใช้ ไม่ใช่เงียบหาย"""
        with patch("routers.chat.stream_response") as mock_stream, \
             patch("routers.chat.save_message", return_value=1):
            mock_stream.return_value = iter([])

            resp = client.post("/api/chat", json=_BODY)
            assert resp.status_code == 200
            text = _chunks_of(resp.text)
            assert text.strip() != ""
            assert "Regenerate" in text or "ลองใหม่" in text

    def test_empty_stream_never_saves_blank_assistant_message(self):
        """ข้อความ assistant ที่บันทึกลง DB ต้องไม่ว่างเปล่า"""
        with patch("routers.chat.stream_response") as mock_stream, \
             patch("routers.chat.save_message", return_value=1) as mock_save:
            mock_stream.return_value = iter([])

            resp = client.post("/api/chat", json=_BODY)
            _ = resp.text  # drain → generator ทำงานจริง

            asst_saves = [c for c in mock_save.call_args_list if c.args[1] == "assistant"]
            assert asst_saves, "ต้องมีการ save assistant message"
            assert asst_saves[0].args[2].strip() != ""

    def test_whitespace_only_stream_treated_as_empty(self):
        """stream ที่มีแต่ whitespace = ว่างเปล่าเช่นกัน"""
        with patch("routers.chat.stream_response") as mock_stream, \
             patch("routers.chat.save_message", return_value=1):
            mock_stream.return_value = iter(["  ", "\n"])

            resp = client.post("/api/chat", json=_BODY)
            text = _chunks_of(resp.text)
            assert text.strip() != ""

    def test_empty_guard_notice_never_enters_memory(self):
        """notice ห้ามเข้า remember()/teach() — กัน episodic contamination
        (recall ดึงกลับมาแล้วโมเดลเลียนแบบ notice เป็นคำตอบ)"""
        with patch("routers.chat.stream_response") as mock_stream, \
             patch("routers.chat.save_message", return_value=1), \
             patch("routers.chat.remember") as mock_remember, \
             patch("routers.chat.teach") as mock_teach:
            mock_stream.return_value = iter([])

            resp = client.post("/api/chat", json=_BODY)
            _ = resp.text

            mock_remember.assert_not_called()
            # teach(prompt) เฉยๆ (เก็บ user facts จาก prompt ก่อน LLM ตอบ) ยังเรียกได้
            # แต่ teach ที่แนบ ai_response=notice ห้ามเกิด
            for c in mock_teach.call_args_list:
                assert "ai_response" not in c.kwargs, \
                    f"notice ห้ามเข้า teach เป็น ai_response: {c}"

    def test_normal_stream_unchanged(self):
        """stream ปกติ → ไม่มีข้อความ guard ปน (พฤติกรรมเดิมห้ามเปลี่ยน)"""
        with patch("routers.chat.stream_response") as mock_stream, \
             patch("routers.chat.save_message", return_value=1):
            mock_stream.return_value = iter(["คำตอบ", "ปกติ"])

            resp = client.post("/api/chat", json=_BODY)
            text = _chunks_of(resp.text)
            assert text == "คำตอบปกติ"
