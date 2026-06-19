"""Tests: /api/chat input sanitization (scrutinize Major 1, 2026-06-15)

`prompt` อ่านจาก `await request.json()` แบบไม่ validate type — ถ้า client ส่ง
list/dict มา จะไหลเข้า messages → crash ทุก provider (types.Part / .lower() ฯลฯ)
+ ขยะลง DB. coerce เป็น str ที่ entry point กันครบทุก provider ในที่เดียว
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
import server
import routers.chat as chatmod

client = TestClient(server.app)


def test_chat_coerces_nonstr_prompt(monkeypatch):
    cap = {}

    def fake_stream(messages, **k):
        cap["messages"] = messages
        yield "ok"

    monkeypatch.setattr(chatmod, "stream_response", fake_stream)
    r = client.post("/api/chat", json={
        "session_id": "scrut-coerce",
        "prompt": ["a", "b"],          # ❌ ไม่ใช่ str — เคยทำ crash ทุก provider
        "provider": "ollama",
        "active_learning": False,      # กัน short-circuit ถามกลับ (ไม่เรียก stream)
        "response_cache": False,       # กัน cache short-circuit
    })
    assert r.status_code == 200
    _ = r.text  # consume SSE → generator รัน → cap ถูกเซ็ต
    assert "messages" in cap, "stream_response ไม่ถูกเรียก"
    user_msgs = [m for m in cap["messages"] if m["role"] == "user"]
    assert user_msgs, "ไม่มี user message"
    assert all(isinstance(m["content"], str) for m in user_msgs), \
        f"user content ต้องเป็น str ทั้งหมด ได้ {[type(m['content']).__name__ for m in user_msgs]}"


def test_chat_normal_str_prompt_unchanged(monkeypatch):
    cap = {}

    def fake_stream(messages, **k):
        cap["messages"] = messages
        yield "ok"

    monkeypatch.setattr(chatmod, "stream_response", fake_stream)
    r = client.post("/api/chat", json={
        "session_id": "scrut-normal",
        "prompt": "สวัสดีครับ",
        "provider": "ollama",
        "active_learning": False,
        "response_cache": False,
    })
    assert r.status_code == 200
    _ = r.text
    user_msgs = [m for m in cap["messages"] if m["role"] == "user"]
    assert any(m["content"] == "สวัสดีครับ" for m in user_msgs)


# ── web-search grounding สำหรับ path ที่เลือกโมเดลเฉพาะ (Work A, 2026-06-15) ──
def test_chat_injects_websearch_for_realtime_query(monkeypatch):
    """คำถาม real-time + โมเดล local → ยืม Gemini grounding ค้นแล้ว inject context
    (เปลี่ยนจาก DDG-first เป็น Gemini-grounding-first 2026-06-20)"""
    import utils.llm as llm
    import utils.websearch as ws
    cap = {}
    ddg_called = {"n": 0}

    def fake_stream(messages, **k):
        cap["messages"] = messages
        yield "ok"

    def fake_gemini_search(prompt, **k):
        return ("One Piece ตอนล่าสุดคือ 1120", [{"title": "x", "href": "http://x", "body": "1120"}])

    def fake_ddg(prompt, **k):  # fallback — ไม่ควรถูกเรียกเมื่อ Gemini สำเร็จ
        ddg_called["n"] += 1
        return ("DDG ไม่ควรถูกใช้", [])

    monkeypatch.setattr(chatmod, "stream_response", fake_stream)
    monkeypatch.setattr(llm, "gemini_web_search", fake_gemini_search)
    monkeypatch.setattr(ws, "web_search_with_results", fake_ddg)
    r = client.post("/api/chat", json={
        "session_id": "scrut-ws",
        "prompt": "One Piece ออกตอนล่าสุดกี่ตอนแล้ว",   # needs_internet → ควรเสิร์ช
        "provider": "lmstudio",                          # โมเดล local → ยืม Gemini grounding
        "model": "qwen/qwen3.5-9b",                      # เลือกโมเดลเฉพาะ (req_model)
        "active_learning": False,
        "response_cache": False,
    })
    assert r.status_code == 200
    _ = r.text
    sys_msg = cap["messages"][0]["content"]
    assert "INTERNET CONTEXT" in sys_msg, "คำถาม real-time + โมเดล local ต้อง inject web context"
    assert "1120" in sys_msg
    assert ddg_called["n"] == 0, "Gemini grounding สำเร็จ → ไม่ควร fallback ไป DDG"


def test_chat_gemini_uses_builtin_grounding_not_ddg(monkeypatch):
    """Option B: โมเดล Gemini + คำถาม real-time → ใช้ google_search ในตัว (web_grounding=True)
    ไม่ inject DDG context (ปล่อยให้ Gemini ground เอง)"""
    import utils.websearch as ws
    cap = {}
    ddg_called = {"n": 0}

    def fake_stream(messages, **k):
        cap["messages"] = messages
        cap["web_grounding"] = k.get("web_grounding")
        yield "ok"

    def fake_search(prompt, **k):
        ddg_called["n"] += 1
        return ("[1] ไม่ควรถูกเรียก", [])

    monkeypatch.setattr(chatmod, "stream_response", fake_stream)
    monkeypatch.setattr(ws, "web_search_with_results", fake_search)
    r = client.post("/api/chat", json={
        "session_id": "scrut-gemini-ground",
        "prompt": "One Piece ออกตอนล่าสุดกี่ตอนแล้ว",
        "provider": "gemini",
        "model": "gemini-3.1-flash-lite",
        "active_learning": False,
        "response_cache": False,
    })
    assert r.status_code == 200
    _ = r.text
    assert cap["web_grounding"] is True, "Gemini real-time ต้องเปิด web_grounding (google_search ในตัว)"
    assert "INTERNET CONTEXT" not in cap["messages"][0]["content"], "Gemini ไม่ควร inject DDG context"
    assert ddg_called["n"] == 0, "Gemini ไม่ควรเรียก DDG"


def test_chat_no_websearch_for_casual_query(monkeypatch):
    import utils.websearch as ws
    cap = {}
    called = {"n": 0}

    def fake_stream(messages, **k):
        cap["messages"] = messages
        yield "ok"

    def fake_search(prompt, **k):
        called["n"] += 1
        return ("x", [])

    monkeypatch.setattr(chatmod, "stream_response", fake_stream)
    monkeypatch.setattr(ws, "web_search_with_results", fake_search)
    r = client.post("/api/chat", json={
        "session_id": "scrut-casual",
        "prompt": "สวัสดีครับ ขวัญ",                    # ทักทาย → ไม่ควรเสิร์ช
        "provider": "ollama",
        "model": "qwen/qwen3.5-9b",
        "active_learning": False,
        "response_cache": False,
    })
    assert r.status_code == 200
    _ = r.text
    assert called["n"] == 0, "คำถามทักทายไม่ควรเสิร์ชเว็บ"
    assert "INTERNET CONTEXT" not in cap["messages"][0]["content"]
