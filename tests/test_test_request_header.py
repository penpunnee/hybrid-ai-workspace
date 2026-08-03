"""X-Test-Request header (P2-9 เสริม) — smoke test เรียก /api/chat จริงได้โดยไม่ปนเปื้อน
episodic memory/lessons/preferences ในตัว ChromaDB (แก้ pain ที่ต้องลบทีหลังผ่าน
admin API หรือต่อ ChromaDB ตรง — ดู ROADMAP.md P2-9 + CLAUDE.md Known Quirks)
"""
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["UI_PASSWORD"] = ""
import server  # noqa: E402
import routers.chat as chatmod  # noqa: E402
from fastapi.testclient import TestClient

client = TestClient(server.app)

_BODY = {
    "provider": "ollama",
    "assistant": "ฟ้า",
    "prompt": "สวัสดี",
    "session_id": "test_header_sess",
    "response_cache": False,
}


class _RecordingThread:
    """แทน threading.Thread เฉพาะใน routers.chat namespace — ไม่แตะ threading
    module จริง กัน pollute background thread อื่นของแอป (rate limit/observability ฯลฯ)"""
    instances = []

    def __init__(self, target=None, daemon=None, **kw):
        type(self).instances.append(target)

    def start(self):
        pass  # ไม่รัน target จริง — กันแตะ ChromaDB จริงระหว่างเทส


def _post(monkeypatch, headers=None):
    _RecordingThread.instances = []
    monkeypatch.setattr(chatmod, "threading", SimpleNamespace(Thread=_RecordingThread))
    with patch("routers.chat.stream_response") as mock_stream, \
         patch("routers.chat.save_message", return_value=1), \
         patch("routers.chat.remember") as mock_remember, \
         patch("routers.chat.teach") as mock_teach:
        mock_stream.return_value = iter(["ก" * 150])  # >100 chars → auto-learn branch ปกติจะทำงาน
        resp = client.post("/api/chat", json=_BODY, headers=headers or {})
        _ = resp.text  # drain stream
        return resp, mock_remember, mock_teach


def test_test_request_header_skips_remember_teach_and_lesson_thread(monkeypatch):
    resp, mock_remember, mock_teach = _post(monkeypatch, headers={"X-Test-Request": "1"})
    assert resp.status_code == 200
    mock_remember.assert_not_called()
    mock_teach.assert_not_called()
    assert _RecordingThread.instances == [], "test request ต้องไม่สปอน auto-learn lesson thread"


def test_without_header_calls_remember_teach_and_lesson_thread(monkeypatch):
    resp, mock_remember, mock_teach = _post(monkeypatch)
    assert resp.status_code == 200
    mock_remember.assert_called_once()
    # teach() เรียกตรงๆ ครั้งเดียว (signal detection ต้น request) — ส่วนรอบหลัง stream จบ
    # ย้ายไปเธรดเบื้องหลังแล้ว เพราะมันเรียก LLM สกัดข้อเท็จจริง (~40-60 วิ) ซึ่งถ้าค้าง
    # อยู่ในสาย SSE ผู้ใช้จะเห็น stream ไม่ปิดทั้งที่คำตอบพิมพ์จบแล้ว (วัดจริง prod: 61 วิ)
    mock_teach.assert_called_once()
    # เช็คด้วย "ชื่อเธรด" ไม่ใช่ "จำนวน" — เดิมล็อกไว้ที่ 2 ทำให้เธรดเบื้องหลังที่เพิ่ม
    # ทีหลังโดยชอบธรรม (shadow logging ข้อ 21) ทำเทสแดงทั้งที่เจตนาของเทสไม่ได้ถูกละเมิด
    spawned = {t.__name__ for t in _RecordingThread.instances}
    assert {"_teach", "_learn"} <= spawned, f"ต้อง spawn ทั้งเธรด teach และ auto-learn lesson (ได้ {spawned})"


def test_is_test_request_helper_reads_header_case_insensitive():
    from routers.chat import _is_test_request
    from types import SimpleNamespace
    req_true = SimpleNamespace(headers={"x-test-request": "true"})
    req_false = SimpleNamespace(headers={})
    assert _is_test_request(req_true) is True
    assert _is_test_request(req_false) is False


def test_persist_agent_turn_skips_remember_when_test_request():
    with patch("routers.chat.save_message", return_value=42) as mock_save, \
         patch("routers.chat.push_working") as mock_push, \
         patch("routers.chat.remember") as mock_remember:
        from routers.chat import persist_agent_turn
        msg_id = persist_agent_turn("kwan", "prompt", "response", "sess1", is_test_request=True)
        assert msg_id == 42
        mock_save.assert_called_once()
        assert mock_push.call_count == 2
        mock_remember.assert_not_called()


def test_persist_agent_turn_calls_remember_when_not_test_request(monkeypatch):
    import routers.chat as chatmod
    monkeypatch.setattr(chatmod, "should_auto_learn", lambda p: (True, "ok"))
    with patch("routers.chat.save_message", return_value=42), \
         patch("routers.chat.push_working"), \
         patch("routers.chat.remember") as mock_remember:
        from routers.chat import persist_agent_turn
        persist_agent_turn("kwan", "prompt", "response", "sess1", is_test_request=False)
        mock_remember.assert_called_once()
