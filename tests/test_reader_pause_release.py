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

🔑 **กติกาของเทสในไฟล์นี้ (บทเรียน 2026-09-03 — scrutinize จับได้):**
· fake ต้องซื่อสัตย์กับของจริง — เวอร์ชันแรก `_marks.set` เป็น no-op ⇒ handler อ่าน
  "ท่อนเดิม" ซ้ำทุก ~40ms ซึ่ง**ไม่มีในของจริง** แล้วเทสก็ไป assert ตำแหน่งใน log
  (`log[:4] == [...]`) = ผูกกับหน้าต่างจังหวะ 40ms · หน่วง 60ms ก่อนกดพักแล้วแดง
  ทั้งที่พฤติกรรมถูกทุกประการ
· assert **invariant** ที่ commit อ้าง ไม่ใช่ตำแหน่งใน log:
  (1) พัก → session ปิด  (2) พักอยู่ → ห้ามเปิดใหม่
  (3) ที่คั่น**ไม่ขยับระหว่างพัก** และ session ใหม่ป้อนท่อนจากที่คั่นนั้น
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
เล่ม = "x"
# ยาวพอให้อ่านไม่จบภายในเทส (600 ตัว/ท่อน × ~40ms/ท่อน ⇒ 600k ตัว ≈ 40 วิ ≫ `รอ`)
# — fake `_marks` เก็บค่าจริง ⇒ ที่คั่นเดินหน้าเหมือน prod ไม่ใช่วนท่อนเดิม
ข้อความ = "ก" * 600_000


class _Sessionปลอม:
    """เลียน Live session: ป้อนท่อน → ส่งเสียง 1 ก้อน → turn_complete → เงียบรอ

    จด `("feed", n, pos)` โดย `pos` = ที่คั่น ณ ตอนป้อน (handler อ่าน `_marks.get`
    แล้วป้อนในเทิร์นเดียวกันของ event loop จึงเป็นค่าเดียวกับ `pos` ของท่อนนั้น)
    """

    def __init__(self, log, n, marks):
        self.log, self.n, self.marks = log, n, marks

    async def send_client_content(self, **kw):
        self.log.append(("feed", self.n, self.marks[เล่ม]))

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
    def __init__(self, log, marks):
        self.log, self.marks, self.n = log, marks, 0

    def connect(self, **kw):
        self.n += 1
        n, log, marks = self.n, self.log, self.marks

        class _CM:
            async def __aenter__(s):
                log.append(f"open#{n}")
                return _Sessionปลอม(log, n, marks)

            async def __aexit__(s, *a):
                log.append(f"close#{n}")
                return False
        return _CM()


@pytest.fixture()
def เส้นอ่าน(monkeypatch):
    import server
    import routers.reader as rr

    log: list = []
    marks = {เล่ม: 0}
    monkeypatch.setattr(server, "GEMINI_API_KEY", "fake-key")
    monkeypatch.setattr(server, "websocket_authorized", lambda ws, t: True)
    monkeypatch.setattr(rr._books, "text", lambda src: ข้อความ)
    monkeypatch.setattr(rr._marks, "get", lambda src: marks[src])
    monkeypatch.setattr(rr._marks, "set", lambda src, pos: marks.__setitem__(src, pos))

    class _Clientปลอม:
        def __init__(self, **kw):
            self.aio = types.SimpleNamespace(live=_Liveปลอม(log, marks))

    monkeypatch.setattr("google.genai.Client", _Clientปลอม)
    return log, marks


def _รอจน(log, เงื่อนไข, ข้อความ):
    หมดเวลา = time.monotonic() + รอ
    while time.monotonic() < หมดเวลา:
        if เงื่อนไข(log):
            return
        time.sleep(0.02)
    pytest.fail(f"{ข้อความ} · log={log}")


def _ป้อนของ(log, n):
    """pos ของทุกท่อนที่ถูกป้อนบน session #n ตามลำดับ"""
    return [pos for x in log if isinstance(x, tuple) and x[1] == n for pos in [x[2]]]


def test_กดพักแล้วปิด_session_กดอ่านต่อแล้วเปิดใหม่จากที่คั่นเดิม(เส้นอ่าน):
    import server

    log, marks = เส้นอ่าน
    with TestClient(server.app).websocket_connect(f"/ws/reader?source={เล่ม}") as ws:
        assert ws.receive_json()["type"] == "connected"
        _รอจน(log, lambda L: _ป้อนของ(L, 1), "ไม่เริ่มอ่านเลย")

        ws.send_json({"type": "pause"})
        # (1) 🔴 ตัวชี้ขาดของทั้งงาน: session ต้องถูกปิดจริง ไม่ใช่แค่หยุดส่งเสียง
        _รอจน(log, lambda L: "close#1" in L,
              "กดพักแล้ว Live session ไม่ถูกปิด — กลับไปกอด session เหมือนเดิม")
        ที่คั่นตอนปิด = marks[เล่ม]

        # (2) พักอยู่ → ห้ามเปิด session ใหม่เอง
        time.sleep(0.4)
        assert "open#2" not in log, f"พักอยู่แต่ยังเปิด session ใหม่ทันที: {log}"
        # (3a) ระหว่างพักที่คั่นต้องนิ่งสนิท — ไม่มี session = ไม่มีใครมีสิทธิ์เลื่อน
        assert marks[เล่ม] == ที่คั่นตอนปิด, "ที่คั่นขยับระหว่างพักทั้งที่ไม่มี session"

        ws.send_json({"type": "resume"})
        _รอจน(log, lambda L: "open#2" in L, "กดอ่านต่อแล้วไม่เปิด session ใหม่")
        _รอจน(log, lambda L: _ป้อนของ(L, 2), "เปิด session แล้วแต่ไม่อ่านต่อ")
        ws.send_json({"type": "close"})

    # ลำดับที่ต้องจริงโดยไม่ขึ้นกับว่าอ่านไปกี่ท่อนก่อนกดพัก (ห้าม assert ตำแหน่งใน log)
    assert log.index("close#1") < log.index("open#2"), f"เปิด session ใหม่ก่อนปิดอันเก่า: {log}"
    # (3b) session ใหม่ต้องเริ่มจากที่คั่นที่ค้างไว้ตอนพัก — ไม่ข้าม ไม่ถอย
    ท่อนแรกหลังพัก = _ป้อนของ(log, 2)[0]
    assert ท่อนแรกหลังพัก == ที่คั่นตอนปิด, (
        f"อ่านต่อจาก {ท่อนแรกหลังพัก} แต่ที่คั่นตอนพักคือ {ที่คั่นตอนปิด} · log={log}"
    )
    # ที่คั่นตอนพักต้องไม่เกินท่อนที่กำลังอ่านค้าง (พักกลางท่อน = ที่คั่นอยู่ต้นท่อนนั้น ·
    # พักพอดีขอบท่อน = อยู่ต้นท่อนถัดไป) — เกินกว่านั้นคือเนื้อหาหาย
    ท่อนสุดท้ายก่อนพัก = _ป้อนของ(log, 1)[-1]
    assert ท่อนสุดท้ายก่อนพัก <= ที่คั่นตอนปิด <= ท่อนสุดท้ายก่อนพัก + 600, (
        f"ที่คั่นตอนพัก {ที่คั่นตอนปิด} ไม่สัมพันธ์กับท่อนที่อ่านค้าง {ท่อนสุดท้ายก่อนพัก}"
    )


def test_ปิดหนังสือระหว่างพักได้_ไม่ค้าง(เส้นอ่าน):
    """ตัวรอระหว่างพักต้องยังฟัง WS อยู่ — ไม่งั้นสั่งอะไรไม่ได้เลยตลอดกาล"""
    import server

    log, _ = เส้นอ่าน
    with TestClient(server.app).websocket_connect(f"/ws/reader?source={เล่ม}") as ws:
        assert ws.receive_json()["type"] == "connected"
        _รอจน(log, lambda L: _ป้อนของ(L, 1), "ไม่เริ่มอ่านเลย")
        ws.send_json({"type": "pause"})
        _รอจน(log, lambda L: "close#1" in L, "กดพักแล้ว session ไม่ถูกปิด")
        ws.send_json({"type": "close"})
        _รอจน(log, lambda L: L.count("open#1") == 1 and "open#2" not in L,
              "กดปิดระหว่างพักแล้วยังเปิด session ใหม่")
