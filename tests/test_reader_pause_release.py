"""กดพักแล้ว /ws/reader ต้อง **ปล่อย** Gemini Live session ไม่ใช่นอนกอดไว้

🔴 หลักฐานบน prod 2026-08-27 (log จริง):
    17:31:05  พักกลางท่อน → หยุดส่งเสียงทันที
              ← **2 ชั่วโมง 33 นาที ไม่มี log สักบรรทัด**
    20:04:22  ปิด xianni.pdf#7b10 ที่คั่น 48001
ตอนนั้น `next_read_action(paused=True) → "wait"` แล้ว feed_loop วน `sleep(0.3)`
อยู่ **ข้างใน** `async with live.connect(...)` ⇒ session เปิดค้างโดยไม่มีใครฟัง
· "ไม่มี log" ไม่ได้แปลว่าปกติ — watchdog กับตัวจับ `go_away` อยู่ *ข้างใน* ลูปรับเสียง
  ซึ่งตอนพักไม่มีใครเข้าไปเลย ⇒ session ตายไปแล้วก็ไม่มีใครรู้จนกดอ่านต่อ

⚠️ ไฟล์นี้ขับ handler **ทั้งเส้นจริง** ด้วย Live session ปลอม (ไม่ใช่ AST) — ตัวชี้ขาด
คือลำดับ `open#/close#` ที่ fake context manager จดไว้ · ส่วนเทสโครงสร้าง (ห้าม
sleep ใน session ฯลฯ) อยู่ที่ `test_reader_voice.py::TestPauseReleasesTheLiveSession`
"""
import asyncio
import os
import sys
import time
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("UI_PASSWORD", "")

import pytest
from fastapi.testclient import TestClient

รอ = 8.0        # วินาที — เผื่อ CI ช้า (เงื่อนไขจริงเกิดใน ~0.2 วิ)


class _SessionปลอมJ:
    """เลียน Live session: ป้อนท่อน → ส่งเสียง 1 ก้อน → turn_complete → เงียบรอ"""

    def __init__(self, log, n):
        self.log, self.n = log, n

    async def send_client_content(self, **kw):
        self.log.append(f"feed#{self.n}")

    def receive(self):
        async def gen():
            await asyncio.sleep(0.02)
            yield types.SimpleNamespace(data=b"\x00" * 16, server_content=None,
                                        go_away=None, session_resumption_update=None)
            await asyncio.sleep(0.02)
            yield types.SimpleNamespace(
                data=None, go_away=None, session_resumption_update=None,
                server_content=types.SimpleNamespace(turn_complete=True))
            while True:      # จบ turn แล้วเงียบรอ — เหมือนของจริงระหว่างท่อน
                await asyncio.sleep(0.02)
        return gen()


class _Liveปลอม:
    def __init__(self, log):
        self.log, self.n = log, 0

    def connect(self, **kw):
        self.n += 1
        n, log = self.n, self.log

        class _CM:
            async def __aenter__(s):
                log.append(f"open#{n}")
                return _SessionปลอมJ(log, n)

            async def __aexit__(s, *a):
                log.append(f"close#{n}")
                return False
        return _CM()


@pytest.fixture()
def เส้นอ่าน(monkeypatch):
    import server
    import routers.reader as rr

    log = []
    monkeypatch.setattr(server, "GEMINI_API_KEY", "fake-key")
    monkeypatch.setattr(server, "websocket_authorized", lambda ws, t: True)
    monkeypatch.setattr(rr._books, "text", lambda src: "ก" * 4000)
    monkeypatch.setattr(rr._marks, "get", lambda src: 0)
    monkeypatch.setattr(rr._marks, "set", lambda src, pos: None)

    class _Clientปลอม:
        def __init__(self, **kw):
            self.aio = types.SimpleNamespace(live=_Liveปลอม(log))

    monkeypatch.setattr("google.genai.Client", _Clientปลอม)
    return log


def _รอจน(log, เงื่อนไข, ข้อความ):
    หมดเวลา = time.monotonic() + รอ
    while time.monotonic() < หมดเวลา:
        if เงื่อนไข(log):
            return
        time.sleep(0.02)
    pytest.fail(f"{ข้อความ} · log={log}")


def test_กดพักแล้วปิด_session_กดอ่านต่อแล้วเปิดใหม่(เส้นอ่าน):
    import server

    log = เส้นอ่าน
    with TestClient(server.app).websocket_connect("/ws/reader?source=x") as ws:
        assert ws.receive_json()["type"] == "connected"
        _รอจน(log, lambda L: "feed#1" in L, "ไม่เริ่มอ่านเลย")

        ws.send_json({"type": "pause"})
        # 🔴 ตัวชี้ขาดของทั้งงาน: session ต้องถูกปิดจริง ไม่ใช่แค่หยุดส่งเสียง
        _รอจน(log, lambda L: "close#1" in L,
              "กดพักแล้ว Live session ไม่ถูกปิด — กลับไปกอด session เหมือนเดิม")

        time.sleep(0.4)
        assert "open#2" not in log, f"พักอยู่แต่ยังเปิด session ใหม่ทันที: {log}"

        ws.send_json({"type": "resume"})
        _รอจน(log, lambda L: "open#2" in L, "กดอ่านต่อแล้วไม่เปิด session ใหม่")
        _รอจน(log, lambda L: "feed#2" in L, "เปิด session แล้วแต่ไม่อ่านต่อ")
        ws.send_json({"type": "close"})

    assert log[:4] == ["open#1", "feed#1", "close#1", "open#2"], f"ลำดับผิด: {log}"


def test_ปิดหนังสือระหว่างพักได้_ไม่ค้าง(เส้นอ่าน):
    """ตัวรอระหว่างพักต้องยังฟัง WS อยู่ — ไม่งั้นสั่งอะไรไม่ได้เลยตลอดกาล"""
    import server

    log = เส้นอ่าน
    with TestClient(server.app).websocket_connect("/ws/reader?source=x") as ws:
        assert ws.receive_json()["type"] == "connected"
        _รอจน(log, lambda L: "feed#1" in L, "ไม่เริ่มอ่านเลย")
        ws.send_json({"type": "pause"})
        _รอจน(log, lambda L: "close#1" in L, "กดพักแล้ว session ไม่ถูกปิด")
        ws.send_json({"type": "close"})
        _รอจน(log, lambda L: L.count("open#1") == 1 and "open#2" not in L,
              "กดปิดระหว่างพักแล้วยังเปิด session ใหม่")
