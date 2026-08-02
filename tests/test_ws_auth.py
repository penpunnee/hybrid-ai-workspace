"""Tests สำหรับ auth ของ WebSocket `/ws/voice/{slug}`

ทำไมสำคัญ (security): `app.middleware("http")` = BaseHTTPMiddleware ซึ่งลัดผ่านทุก scope
ที่ไม่ใช่ `http` → auth/rate-limit/request-id **ไม่เคยทำงานกับ WebSocket เลย**
เส้น voice เปิด session Gemini Live จริง (เผา quota + เขียนลง chat history)
และแอปเปิด public ผ่าน Cloudflare Tunnel → ต้อง gate ที่ตัว handler เอง

browser ตั้ง header บน WebSocket ไม่ได้ → token มาทาง query param (`?token=`)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import core.auth as auth
import server


def _client(host="8.8.8.8"):
    return TestClient(server.app, client=(host, 50000))


@pytest.fixture(autouse=True)
def no_gemini(monkeypatch):
    """กันเทสต่อ Gemini Live จริง — handler จะตอบ error ทันทีหลัง accept
    (.env ของ dev มี GEMINI_API_KEY จริง และ conftest ไม่ได้ล้างให้)"""
    monkeypatch.setattr(server, "GEMINI_API_KEY", "")


def test_ws_rejects_public_without_token(monkeypatch):
    monkeypatch.setattr(auth, "UI_PASSWORD", "s3cret")
    with pytest.raises(WebSocketDisconnect) as exc:
        with _client().websocket_connect("/ws/voice/kwan"):
            pass
    assert exc.value.code == 1008


def test_ws_rejects_public_with_wrong_token(monkeypatch):
    monkeypatch.setattr(auth, "UI_PASSWORD", "s3cret")
    with pytest.raises(WebSocketDisconnect):
        with _client().websocket_connect("/ws/voice/kwan?token=nope"):
            pass


def test_ws_accepts_public_with_correct_token(monkeypatch):
    monkeypatch.setattr(auth, "UI_PASSWORD", "s3cret")
    with _client().websocket_connect("/ws/voice/kwan?token=s3cret") as ws:
        # GEMINI_API_KEY ไม่ได้ตั้งใน test → handler ตอบ error หลัง accept
        # (สิ่งที่เทสพิสูจน์คือ "ต่อติด" ไม่ใช่ตัว Live session)
        assert ws.receive_json()["type"] == "error"


def test_ws_accepts_lan_peer_without_token(monkeypatch):
    monkeypatch.setattr(auth, "UI_PASSWORD", "s3cret")
    with _client(host="192.168.51.10").websocket_connect("/ws/voice/kwan") as ws:
        assert ws.receive_json()["type"] == "error"


def test_ws_open_when_password_unset(monkeypatch):
    monkeypatch.setattr(auth, "UI_PASSWORD", "")
    with _client().websocket_connect("/ws/voice/kwan") as ws:
        assert ws.receive_json()["type"] == "error"
