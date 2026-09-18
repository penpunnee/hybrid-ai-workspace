"""ท่อนที่เสียงออกไม่ครบ ต้อง **ไม่เลื่อนที่คั่น** แล้วอ่านซ้ำ (user เคาะ 2026-09-18)

🔴 หลักฐานบน prod (log จริง · เวลา UTC):
    09-03 07:26:48–07:27:02  perfectworld.pdf 7 ท่อนติด `turn_complete` มาปกติแต่
                             **เสียง 0.0s** ⇒ ที่คั่นวิ่ง 28678 → 32760 · + 33355→33955
    08-27 17:26 / 17:30      xianni.pdf 4 ท่อนได้เสียงแค่ 0.24–2.20 วิ/100 ตัว
                             (ปกติ 5.8–7.6 · ค่ากลาง 6.42 จาก 61 ท่อน) ⇒ ที่คั่นก็เลื่อน
ตอนนั้นเงื่อนไขเลื่อนที่คั่นมีตัวเดียวคือ `turn_complete` — ไม่ดูว่ามีเสียงออกไปไหม
· 7 ท่อนเปล่าเกิดใน **session เดียว ไม่มีการต่อใหม่คั่น** · กดพัก (= ต่อ session ใหม่)
  แล้วท่อนถัดไปอ่านได้ปกติ ⇒ หลักฐานชิ้นเดียวว่า "session ใหม่หาย"
· **ไม่ได้เกิดใกล้ 1011/quota** (1011 ล่าสุดห่าง 3 ชม. 17 นาที คนละ session)
  · ต้นเหตุยังไม่รู้ — python-genai #2117 รายงานอาการเดียวกันบนโมเดลเดียวกัน ยังเปิดอยู่

ดีลที่ user เคาะ (grilling 2026-09-18):
  เกณฑ์ < 5.0 วิ/100 ตัว = ไม่ครบ · ลองซ้ำใน session เดิม 1 ครั้งก่อน แล้วต่อ session ใหม่
  · หน่วง 1/2/4 วิ · เพดาน 3 ครั้งต่อท่อน · เกินแล้ว **พัก** (ที่คั่นค้างที่ท่อนนั้น)
  · ขึ้นป้ายบอกทุกครั้งที่ลองซ้ำ · log `server_content` เฉพาะท่อนที่ไม่ครบ
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

BPS = 48_000   # PCM16 mono 24kHz — ไบต์ต่อวินาทีของเสียง


def _bytes(sec: float) -> int:
    return int(sec * BPS)


# ── เกณฑ์ ──────────────────────────────────────────────────────────────────────
class TestIncompleteThreshold:
    """ตัวเลขทุกตัวมาจากบรรทัด "ท่อนจบ" จริงบน prod ไม่ได้แต่งขึ้น"""

    def test_zero_audio_is_incomplete(self):
        from utils.voice import reader_block_incomplete
        assert reader_block_incomplete(0, 572)          # 09-03 07:26:50

    def test_partial_audio_from_prod_is_incomplete(self):
        from utils.voice import reader_block_incomplete
        assert reader_block_incomplete(_bytes(1.4), 575)    # xianni 0.24 วิ/100
        assert reader_block_incomplete(_bytes(13.1), 595)   # xianni 2.20 วิ/100

    def test_borderline_below_five_counts(self):
        """user เลือกเกณฑ์ 5.0 โดยรู้ว่า 4.59/4.98 จะถูกนับ — ตรึงไว้ไม่ให้ใครเลื่อนเงียบๆ"""
        from utils.voice import reader_block_incomplete
        assert reader_block_incomplete(_bytes(29.7), 596)   # 4.98 วิ/100
        assert reader_block_incomplete(_bytes(27.3), 595)   # 4.59 วิ/100

    def test_normal_blocks_are_complete(self):
        """กลุ่มควบคุม — ท่อนปกติที่ต่ำสุดใน 61 ท่อนต้องไม่ถูกอ่านซ้ำ"""
        from utils.voice import reader_block_incomplete
        assert not reader_block_incomplete(_bytes(34.4), 593)   # 5.80 วิ/100 (ต่ำสุด)
        assert not reader_block_incomplete(_bytes(38.5), 600)   # ~6.42 ค่ากลาง
        assert not reader_block_incomplete(_bytes(43.3), 573)   # 7.56 (สูงสุด)

    def test_empty_block_is_never_incomplete(self):
        """หารด้วยศูนย์ไม่ได้ — และท่อนว่างถูก skip ก่อนถึงตรงนี้อยู่แล้ว"""
        from utils.voice import reader_block_incomplete
        assert not reader_block_incomplete(0, 0)


class TestRetryPlan:
    def test_sequence_matches_what_user_decided(self):
        """ครั้งแรก: session เดิม · ครั้งที่ 2-3: session ใหม่ · หน่วง 1/2/4 · ครั้งที่ 4: พัก"""
        from utils.voice import reader_incomplete_action
        assert reader_incomplete_action(0) == ("resend", 1.0)
        assert reader_incomplete_action(1) == ("reconnect", 2.0)
        assert reader_incomplete_action(2) == ("reconnect", 4.0)
        assert reader_incomplete_action(3) == ("pause", 0.0)

    def test_never_loops_forever(self):
        from utils.voice import reader_incomplete_action
        assert reader_incomplete_action(99)[0] == "pause"


class TestIncompleteLogLine:
    def test_logs_the_fields_that_could_explain_why(self):
        """ต้นเหตุยังไม่มีใครรู้ — 4 ฟิลด์นี้มาจากซอร์ส SDK (LiveServerContent /
        LiveServerMessage) ไม่ได้เดา · ไม่ log = เกิดอีกก็เดาเหมือนเดิม"""
        from utils.voice import reader_incomplete_log_line

        sc = types.SimpleNamespace(
            turn_complete=True,
            turn_complete_reason=types.SimpleNamespace(value="GENERATED_AUDIO_SAFETY"),
            waiting_for_input=False,
            interaction_status=None,
        )
        r = types.SimpleNamespace(
            server_content=sc,
            usage_metadata=types.SimpleNamespace(
                prompt_token_count=812, response_token_count=0, total_token_count=812),
        )
        line = reader_incomplete_log_line(
            tag="pw#bc50", pos=28678, block_len=572, elapsed_s=1.9,
            audio_bytes=0, attempt=1, response=r,
        )
        assert "pw#bc50" in line and "@28678" in line
        assert "GENERATED_AUDIO_SAFETY" in line
        assert "waiting_for_input=False" in line
        assert "interaction_status=None" in line
        assert "812" in line
        assert "1/3" in line

    def test_missing_fields_do_not_crash(self):
        """SDK/เซิร์ฟเวอร์อาจไม่ส่งฟิลด์เหล่านี้ — log ต้องไม่ทำให้ท่อนอ่านพัง"""
        from utils.voice import reader_incomplete_log_line

        r = types.SimpleNamespace(server_content=types.SimpleNamespace(turn_complete=True))
        line = reader_incomplete_log_line(
            tag="t", pos=1, block_len=1, elapsed_s=0.1, audio_bytes=0, attempt=2, response=r,
        )
        assert "turn_complete_reason=None" in line


# ── ขับ handler ทั้งเส้นด้วย Live session ปลอม ──────────────────────────────────
รอ = 8.0
เล่ม = "x"
ข้อความ = "ก" * 600_000


class _Sessionปลอม:
    """ป้อนท่อน → (เสียงตาม `plan`) → turn_complete → เงียบรอ

    `plan(n_session, pos) -> ไบต์เสียง` · จด `("feed", n, pos)`
    """

    def __init__(self, log, n, marks, plan):
        self.log, self.n, self.marks, self.plan = log, n, marks, plan

    async def send_client_content(self, **kw):
        self.log.append(("feed", self.n, self.marks[เล่ม]))

    def receive(self):
        nbytes = self.plan(self.n, self.marks[เล่ม])

        async def gen():
            await asyncio.sleep(0.01)
            if nbytes:
                yield types.SimpleNamespace(data=b"\x00" * nbytes, server_content=None,
                                            go_away=None, session_resumption_update=None)
            yield types.SimpleNamespace(
                data=None, go_away=None, session_resumption_update=None,
                usage_metadata=None,
                server_content=types.SimpleNamespace(
                    turn_complete=True, turn_complete_reason=None,
                    waiting_for_input=None, interaction_status=None))
            while True:
                await asyncio.sleep(0.02)
        return gen()


@pytest.fixture()
def เส้นอ่าน(monkeypatch):
    import server
    import routers.reader as rr
    import utils.voice as uv

    class _Log(list):
        """จดเวลาทุกเหตุการณ์ — ใช้วัดว่าหน่วงก่อนลองซ้ำจริง"""
        def __init__(self):
            super().__init__()
            self.t: list[float] = []

        def append(self, x):
            self.t.append(time.monotonic())
            super().append(x)

    log = _Log()
    marks = {เล่ม: 0}
    state = {"plan": lambda n, pos: 0}

    monkeypatch.setattr(server, "GEMINI_API_KEY", "fake-key")
    monkeypatch.setattr(server, "websocket_authorized", lambda ws, t: True)
    monkeypatch.setattr(rr._books, "text", lambda src: ข้อความ)
    monkeypatch.setattr(rr._marks, "get", lambda src: marks[src])
    monkeypatch.setattr(rr._marks, "set", lambda src, pos: marks.__setitem__(src, pos))
    # หน่วง 1/2/4 วิจริง = เทสรอ 7 วิ · ลำดับ/ชนิดการลองซ้ำเทสแยกใน TestRetryPlan แล้ว
    monkeypatch.setattr(uv, "READER_INCOMPLETE_BACKOFF", (0.0, 0.0, 0.0))
    # เสียง "ปกติ" ของ fake = 48,000 ไบต์ (1 วิ) ต่อท่อน 600 ตัว = 0.17 วิ/100
    # ⇒ ลดเกณฑ์ให้ 1 วิผ่าน โดยที่ 0 ไบต์ยังไม่ผ่าน (ส่ง 30+ วิจริงทุกท่อน = MB ต่อท่อน)
    monkeypatch.setattr(uv, "READER_MIN_AUDIO_SEC_PER_100", 0.1)

    class _Liveปลอม:
        def __init__(self):
            self.n = 0

        def connect(self, **kw):
            self.n += 1
            n = self.n

            class _CM:
                async def __aenter__(s):
                    log.append(f"open#{n}")
                    return _Sessionปลอม(log, n, marks, lambda a, b: state["plan"](a, b))

                async def __aexit__(s, *a):
                    log.append(f"close#{n}")
                    return False
            return _CM()

    class _Clientปลอม:
        def __init__(self, **kw):
            self.aio = types.SimpleNamespace(live=_Liveปลอม())

    monkeypatch.setattr("google.genai.Client", _Clientปลอม)
    return log, marks, state


def _รอจน(เงื่อนไข, ข้อความ, log):
    หมดเวลา = time.monotonic() + รอ
    while time.monotonic() < หมดเวลา:
        if เงื่อนไข():
            return
        time.sleep(0.02)
    pytest.fail(f"{ข้อความ} · log={log}")


def _feeds(log):
    return [(x[1], x[2]) for x in log if isinstance(x, tuple)]


def _รับจนเจอ(ws, ชนิด, เก็บ):
    """อ่านข้อความจาก server จนเจอชนิดที่ต้องการ — เก็บทุกอันไว้ตรวจลำดับ"""
    while True:
        m = ws.receive_json()
        เก็บ.append(m)
        if m.get("type") == ชนิด:
            return m
        if m.get("type") in ("done_book", "error"):
            pytest.fail(f"รอ {ชนิด} แต่ได้ {m} ก่อน · ที่ได้มาทั้งหมด={เก็บ[-5:]}")


def test_ท่อนเปล่า_ไม่เลื่อนที่คั่น_ลองซ้ำตามแผน_แล้วพัก(เส้นอ่าน):
    import server

    log, marks, state = เส้นอ่าน
    ได้รับ: list = []
    with TestClient(server.app).websocket_connect(f"/ws/reader?source={เล่ม}") as ws:
        assert ws.receive_json()["type"] == "connected"
        พัก = _รับจนเจอ(ws, "paused", ได้รับ)

        # 🔴 ตัวชี้ขาดของทั้งงาน: ท่อนเปล่ากี่ครั้งก็ตาม ที่คั่นต้องไม่ขยับ
        assert marks[เล่ม] == 0, f"ท่อนเปล่าแต่ที่คั่นเลื่อนไป {marks[เล่ม]} · log={log}"

        # ลำดับที่ user เคาะ: session เดิม 2 ครั้ง (ต้นฉบับ + ซ้ำ) · session ใหม่อีก 2
        assert _feeds(log) == [(1, 0), (1, 0), (2, 0), (3, 0)], f"ลำดับลองซ้ำผิด: {log}"
        retries = [m for m in ได้รับ if m.get("type") == "retry"]
        assert [m["attempt"] for m in retries] == [1, 2, 3], f"ป้ายลองซ้ำไม่ครบ: {ได้รับ}"
        assert all(m["max"] == 3 for m in retries)
        assert พัก.get("message"), "พักเองโดยไม่บอกเหตุผล — user จะคิดว่าแอปค้าง"

        # พัก = ไม่มี session เปิดค้าง และห้ามเปิดใหม่เอง
        _รอจน(lambda: "close#3" in log, "ชนเพดานแล้วไม่ปิด session", log)
        time.sleep(0.3)
        assert "open#4" not in log, f"พักอยู่แต่เปิด session ใหม่เอง: {log}"
        assert marks[เล่ม] == 0

        # กดอ่านต่อ = ลองใหม่จากท่อนเดิม (ตัวนับเริ่มใหม่) · คราวนี้ Gemini อ่านได้
        state["plan"] = lambda n, pos: BPS
        ws.send_json({"type": "resume"})
        _รอจน(lambda: marks[เล่ม] > 0, "กดอ่านต่อแล้วไม่อ่านท่อนเดิมต่อ", log)
        assert ("feed", 4, 0) in log, f"อ่านต่อแล้วไม่ได้เริ่มจากท่อนที่ค้าง: {log}"
        ws.send_json({"type": "close"})


def test_session_ใหม่อ่านได้_ที่คั่นเดินต่อ_ไม่พัก(เส้นอ่าน):
    """ตรงกับหลักฐาน 09-03: session เดิมเปล่าต่อเนื่อง · session ใหม่อ่านได้"""
    import server

    log, marks, state = เส้นอ่าน
    state["plan"] = lambda n, pos: 0 if n == 1 else BPS
    with TestClient(server.app).websocket_connect(f"/ws/reader?source={เล่ม}") as ws:
        assert ws.receive_json()["type"] == "connected"
        _รอจน(lambda: marks[เล่ม] > 0, "session ใหม่อ่านได้แต่ที่คั่นไม่เดิน", log)
        ws.send_json({"type": "close"})

    f = _feeds(log)
    assert f[:3] == [(1, 0), (1, 0), (2, 0)], f"ไม่ได้ลองซ้ำก่อนแล้วต่อ session ใหม่: {log}"
    assert "open#3" not in log, f"session ใหม่อ่านได้แล้วแต่ยังต่อใหม่อีก: {log}"


def test_หน่วงก่อนลองซ้ำจริง_ทั้งในสายเดิมและก่อนต่อใหม่(เส้นอ่าน, monkeypatch):
    """เทสอื่นตั้งหน่วงเป็น 0 ให้เร็ว ⇒ ตัวนี้ตรวจว่าหน่วงถูกใช้จริง (วัดขอบล่างเท่านั้น
    ไม่ผูกกับจังหวะ) · ไม่หน่วง = ลองซ้ำถี่รัวจนเผาโควตาเหมือนที่ 1011 เคยปิดหนังสือ"""
    import server
    import utils.voice as uv

    ห่าง = 0.3
    monkeypatch.setattr(uv, "READER_INCOMPLETE_BACKOFF", (ห่าง, ห่าง, ห่าง))
    log, marks, state = เส้นอ่าน
    state["plan"] = lambda n, pos: 0 if n == 1 else BPS
    with TestClient(server.app).websocket_connect(f"/ws/reader?source={เล่ม}") as ws:
        assert ws.receive_json()["type"] == "connected"
        _รอจน(lambda: marks[เล่ม] > 0, "ไม่ฟื้นหลังต่อ session ใหม่", log)
        ws.send_json({"type": "close"})

    ป้อน = [i for i, x in enumerate(log) if isinstance(x, tuple) and x[2] == 0]
    assert len(ป้อน) >= 3, log
    ป้อนซ้ำ = log.t[ป้อน[1]] - log.t[ป้อน[0]]
    assert ป้อนซ้ำ >= ห่าง, f"ป้อนซ้ำในสายเดิมโดยไม่หน่วง ({ป้อนซ้ำ:.2f}s)"
    ต่อใหม่ = log.t[log.index("open#2")] - log.t[log.index("close#1")]
    assert ต่อใหม่ >= ห่าง, f"ต่อ session ใหม่โดยไม่หน่วง ({ต่อใหม่:.2f}s)"


def test_กลุ่มควบคุม_เสียงปกติ_ไม่ลองซ้ำเลย(เส้นอ่าน):
    """ถ้าทุกท่อนมีเสียง ต้องเดินหน้าบน session เดียว — ไม่มีการอ่านท่อนเดิมสองรอบ"""
    import server

    log, marks, state = เส้นอ่าน
    state["plan"] = lambda n, pos: BPS
    with TestClient(server.app).websocket_connect(f"/ws/reader?source={เล่ม}") as ws:
        assert ws.receive_json()["type"] == "connected"
        _รอจน(lambda: len(_feeds(log)) >= 3, "ไม่อ่านต่อเนื่อง", log)
        ws.send_json({"type": "close"})

    pos = [p for _, p in _feeds(log)]
    assert len(pos) == len(set(pos)), f"ท่อนปกติถูกอ่านซ้ำ: {log}"
    assert "open#2" not in log, f"ไม่มีท่อนเสียแต่ต่อ session ใหม่: {log}"
