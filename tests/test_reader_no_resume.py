"""โหมดอ่าน: ต่อ session ใหม่ **ต้องไม่ส่ง resume_handle** ไม่ว่าจะต่อเพราะอะไร

🔴 หลักฐาน (ทดสอบจริงกับ Gemini Live บน prod 2026-09-21 · ไม่ใช่อ่านจาก log เก่า):
  · handle พาบริบทไปจริง — prompt token ของท่อนเดียวกัน: ต่อด้วย handle 958–2,524
    · เปิดสด 733 · และบน prod 09-18 สะสมถึง 57–58k ข้าม go_away/ลองซ้ำ
  · session ที่ต่อด้วย handle แล้วป้อน @49619 **อ่านท่อนก่อนหน้า (@48427) ซ้ำ**
    (ถอดเสียงแล้วได้ท่อนเก่าครบ 592 ตัว ไม่มีเนื้อหาท่อนที่ป้อนเลย · เสียงยาว ~2 เท่า 4/5 รอบ)
  · session สดอ่านท่อนที่ป้อนถูก 5/5 · @49619 ที่ล้ม 4/4 ใน session มีบริบท อ่านครบ 3/3
โหมดอ่านป้อนข้อความทีละท่อนเอง ⇒ ไม่มีอะไรต้อง "ต่อ" จากบริบทเดิมเลย
(ต่างจากโหมดคุยที่ต้องใช้ handle ไม่งั้นความจำหาย — เทสนี้ไม่แตะโหมดคุย)

⚠️ บั๊กเดิม (09-18): ทิ้ง handle เฉพาะตอนกดพัก ⇒ เส้นลองซ้ำ/`go_away` ส่ง handle เดิมไป
เทส 12 ตัวของ test_reader_incomplete.py จับไม่ได้เพราะ Live ปลอม **ไม่ตรวจ config ตอน connect**
และไม่เคยส่ง handle มาให้เก็บ — ไฟล์นี้ปิดทั้งสองรู
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

BPS = 48_000
รอ = 8.0
เล่ม = "x"
ข้อความ = "ก" * 600_000


def _msg(**kw):
    base = dict(data=None, server_content=None, go_away=None,
                session_resumption_update=None, usage_metadata=None)
    base.update(kw)
    return types.SimpleNamespace(**base)


def _handle_update(h):
    return _msg(session_resumption_update=types.SimpleNamespace(resumable=True, new_handle=h))


def _turn_complete():
    return _msg(server_content=types.SimpleNamespace(
        turn_complete=True, turn_complete_reason=None,
        waiting_for_input=None, interaction_status=None))


class _Session:
    """ทุกท่อน: ส่ง handle ใหม่มาก่อนเสมอ (เหมือน Gemini จริง) แล้วทำตาม `plan`"""

    def __init__(self, log, n, marks, plan):
        self.log, self.n, self.marks, self.plan = log, n, marks, plan

    async def send_client_content(self, **kw):
        self.log.append(("feed", self.n, self.marks[เล่ม]))

    def receive(self):
        kind = self.plan(self.n, self.marks[เล่ม])
        n = self.n

        async def gen():
            await asyncio.sleep(0.01)
            yield _handle_update(f"handle-จาก-session-{n}")
            if kind == "go_away":
                yield _msg(go_away=types.SimpleNamespace(time_left=None))
            else:
                if kind == "ok":
                    yield _msg(data=b"\x00" * BPS)
                yield _turn_complete()
            while True:
                await asyncio.sleep(0.02)
        return gen()


@pytest.fixture()
def เส้นอ่าน(monkeypatch):
    import server
    import routers.reader as rr
    import utils.voice as uv

    log: list = []
    handles: list = []          # handle ที่ถูกส่งตอน connect แต่ละครั้ง (ตามลำดับ)
    marks = {เล่ม: 0}
    state = {"plan": lambda n, pos: "ok"}

    monkeypatch.setattr(server, "GEMINI_API_KEY", "fake-key")
    monkeypatch.setattr(server, "websocket_authorized", lambda ws, t: True)
    monkeypatch.setattr(rr._books, "text", lambda src: ข้อความ)
    monkeypatch.setattr(rr._marks, "get", lambda src: marks[src])
    monkeypatch.setattr(rr._marks, "set", lambda src, pos: marks.__setitem__(src, pos))
    monkeypatch.setattr(uv, "READER_INCOMPLETE_BACKOFF", (0.0, 0.0, 0.0))
    monkeypatch.setattr(uv, "READER_MIN_AUDIO_SEC_PER_100", 0.1)

    class _Live:
        def __init__(self):
            self.n = 0

        def connect(self, **kw):
            self.n += 1
            n = self.n
            # 🔑 ตัวที่เทสเดิมไม่เคยดู: config ที่ส่งไปจริงตอนเปิด session
            handles.append(kw["config"].session_resumption.handle)

            class _CM:
                async def __aenter__(s):
                    log.append(f"open#{n}")
                    return _Session(log, n, marks, lambda a, b: state["plan"](a, b))

                async def __aexit__(s, *a):
                    log.append(f"close#{n}")
                    return False
            return _CM()

    class _Client:
        def __init__(self, **kw):
            self.aio = types.SimpleNamespace(live=_Live())

    monkeypatch.setattr("google.genai.Client", _Client)
    return log, handles, marks, state


def _รอจน(cond, why, log):
    end = time.monotonic() + รอ
    while time.monotonic() < end:
        if cond():
            return
        time.sleep(0.02)
    pytest.fail(f"{why} · log={log}")


def _เปิดอ่าน(log, cond, why):
    import server
    with TestClient(server.app).websocket_connect(f"/ws/reader?source={เล่ม}") as ws:
        assert ws.receive_json()["type"] == "connected"
        _รอจน(cond, why, log)
        ws.send_json({"type": "close"})


def test_ลองซ้ำด้วยการต่อ_session_ใหม่_ต้องไม่ส่ง_handle(เส้นอ่าน):
    """session 1 เปล่าทุกท่อน (ครั้งแรก + ซ้ำในสายเดิม) → ต่อใหม่ครั้งที่ 2 → อ่านได้"""
    log, handles, marks, state = เส้นอ่าน
    state["plan"] = lambda n, pos: "empty" if n == 1 else "ok"
    _เปิดอ่าน(log, lambda: marks[เล่ม] > 0, "ต่อ session ใหม่แล้วไม่อ่านต่อ")
    assert len(handles) >= 2, f"ไม่ได้ต่อ session ใหม่เลย: {log}"
    assert handles == [None] * len(handles), f"ส่ง handle ไปตอนต่อใหม่: {handles}"


def test_go_away_ต่อ_session_ใหม่_ต้องไม่ส่ง_handle(เส้นอ่าน):
    log, handles, marks, state = เส้นอ่าน
    state["plan"] = lambda n, pos: "go_away" if n == 1 else "ok"
    _เปิดอ่าน(log, lambda: marks[เล่ม] > 0, "go_away แล้วไม่อ่านต่อ")
    assert len(handles) >= 2, f"go_away แล้วไม่ต่อ session ใหม่: {log}"
    assert handles == [None] * len(handles), f"ส่ง handle ไปตอน go_away: {handles}"


def test_ท่อนที่อ่านหลังต่อใหม่_คือท่อนเดิม_ไม่ข้าม(เส้นอ่าน):
    """ทิ้ง handle แล้วต้องยังอ่านท่อนที่ค้าง ไม่ใช่ข้ามไปท่อนถัดไป (สัญญา "ไม่มีวันข้ามเนื้อหา")"""
    log, handles, marks, state = เส้นอ่าน
    state["plan"] = lambda n, pos: "go_away" if n == 1 else "ok"
    _เปิดอ่าน(log, lambda: marks[เล่ม] > 0, "ไม่อ่านต่อ")
    feeds = [x for x in log if isinstance(x, tuple)]
    assert ("feed", 2, 0) in feeds, f"session ใหม่ไม่ได้เริ่มจากท่อนที่ค้าง: {log}"


def test_กลุ่มควบคุม_fake_ส่ง_handle_มาจริง(เส้นอ่าน):
    """ถ้า fake ไม่เคยส่ง handle มา เทสสองตัวบนจะผ่านฟรีแม้โค้ดยังเก็บ handle ไปใช้
    ⇒ ตรวจว่า live_control_signals อ่าน handle จาก fake ได้จริง"""
    from utils.voice import live_control_signals
    assert live_control_signals(_handle_update("h1"))[2] == "h1"
