"""Voice WebSocket handler (`/ws/voice/{slug}`) — regression test

บั๊กที่จับ: handler ใน server.py อ้างชื่อ GEMINI_API_KEY / GEMINI_LIVE_MODEL /
WebSocketDisconnect ที่ไม่ได้ import เข้ามาใน module → ทุกการเชื่อมต่อ voice
จะ NameError ทันที (line 209 อยู่นอก try → exception ไม่ถูกจับ → หลุดออกมา).

เทสนี้ mock genai.Client ให้ live.connect ล้มแบบควบคุมได้ (ไม่แตะ network จริง)
แล้วคาดหวังว่า handler ตอบ error json อย่าง graceful — ไม่ใช่ NameError.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("UI_PASSWORD", "")

from fastapi.testclient import TestClient
from server import app

client = TestClient(app)


class _FakeLive:
    def connect(self, **kw):
        # async with client.aio.live.connect(...) — เราล้มตรงนี้ก่อนเข้า context
        raise RuntimeError("FAKE_NO_NETWORK")


class _FakeAio:
    live = _FakeLive()


class _FakeClient:
    def __init__(self, **kw):
        self.aio = _FakeAio()


def test_voice_ws_no_nameerror(monkeypatch):
    import google.genai as genai_mod
    import server
    # กัน network ด้วย fake client + บังคับมี key เอง (CI ไม่มี .env → ต้องไม่พึ่ง ambient key)
    # patch ที่ server.GEMINI_API_KEY เพราะ bind ตอน import แล้ว setenv ไม่ทัน
    monkeypatch.setattr(genai_mod, "Client", _FakeClient)
    monkeypatch.setattr(server, "GEMINI_API_KEY", "test-key")

    with client.websocket_connect("/ws/voice/test-slug") as ws:
        msg = ws.receive_json()

    # ต้องได้ error json จากการที่ connect ปลอมล้ม — ไม่ใช่ NameError หลุดออกมา
    assert msg["type"] == "error"
    assert "FAKE_NO_NETWORK" in msg["message"]
