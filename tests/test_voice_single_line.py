"""ห้องเดียว = สาย Live เดียว — สายเสียงเปิดซ้อน (งานเปิด ง · prod 10-01 13:36)

prod 10-01: iOS ซ่อนหน้าเว็บ (`vis=hidden` · `cap=interrupted`) → socket ฝั่ง client ตายเงียบ
ไม่มี close frame ถึง server · client ต่อสายใหม่ 13:36:04 แต่ handler เก่ายังถือ Gemini Live
session ไว้จนหมดเวลา ping ของ uvicorn (13:36:42 = 38 วิ) ⇒ Live 2 สายบน key เดียว
(ซึ่งเคยทำให้ 1011 · 09-03) · server ต้องปิดสายเก่าของห้องเดียวกันเองเมื่อมีสายใหม่
"""
import asyncio
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import server
from utils.voice import VoiceLineRegistry


class TestRegistry:
    def test_new_line_stops_the_older_one(self):
        reg = VoiceLineRegistry()
        old, new = asyncio.Event(), asyncio.Event()
        assert reg.claim("s1", old) is False
        assert reg.claim("s1", new) is True
        assert old.is_set() and not new.is_set()

    def test_other_rooms_are_untouched(self):
        reg = VoiceLineRegistry()
        a, b = asyncio.Event(), asyncio.Event()
        reg.claim("s1", a)
        assert reg.claim("s2", b) is False
        assert not a.is_set()

    def test_old_line_finishing_late_does_not_unregister_the_new_one(self):
        reg = VoiceLineRegistry()
        old, new = asyncio.Event(), asyncio.Event()
        reg.claim("s1", old)
        reg.claim("s1", new)
        reg.release("s1", old)          # handler เก่าออกทีหลัง
        third = asyncio.Event()
        assert reg.claim("s1", third) is True and new.is_set(), "สายที่ยังใช้อยู่ต้องยังถูกจำ"

    def test_released_lines_are_forgotten(self):
        reg = VoiceLineRegistry()
        e = asyncio.Event()
        reg.claim("s1", e)
        reg.release("s1", e)
        assert len(reg) == 0


_OPEN = {"n": 0}


class _Session:
    async def receive(self):
        await asyncio.sleep(3600)
        yield  # pragma: no cover

    async def send_realtime_input(self, **k):
        pass

    async def send_client_content(self, **k):
        pass


class _Connect:
    async def __aenter__(self):
        _OPEN["n"] += 1
        return _Session()

    async def __aexit__(self, *a):
        _OPEN["n"] -= 1


class _Client:
    def __init__(self, **k):
        self.aio = SimpleNamespace(live=SimpleNamespace(connect=lambda **kw: _Connect()))


@pytest.fixture()
def fake_live(monkeypatch):
    from google import genai
    monkeypatch.setattr(genai, "Client", _Client)
    monkeypatch.setattr(server, "GEMINI_API_KEY", "test-key")
    _OPEN["n"] = 0
    return _OPEN


def _wait(cond, timeout=6.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_second_line_in_same_room_closes_the_first(fake_live):
    client = TestClient(server.app)
    url = "/ws/voice/kwan?session_id=room-dup"
    with client.websocket_connect(url) as ws1:
        assert ws1.receive_json()["type"] == "connected"
        assert _wait(lambda: fake_live["n"] == 1)
        with client.websocket_connect(url) as ws2:
            assert ws2.receive_json()["type"] == "connected"
            assert _wait(lambda: fake_live["n"] == 1), (
                f"Live เปิดค้าง {fake_live['n']} สายในห้องเดียว — สายเก่าต้องถูกปิด")
            ws2.send_json({"type": "close"})
    assert _wait(lambda: fake_live["n"] == 0)
