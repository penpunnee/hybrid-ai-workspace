"""อ่านสัญญาณควบคุม session ของ Gemini Live — go_away + session resumption

**เคสจริงที่ทำให้ต้องมี (ยืนยัน 2 ครั้ง):**
เล่านิยายผ่าน voice แล้วราวนาทีที่ 10 session ตาย — `server.log`:
```
[Voice WS] send_loop APIError: 1008 None. Connection aborted because the client failed to
close the connection after receiving a GoAway signal once the session duration...
```
- 2026-08-03 18:14:14 UTC (เซสชันแรกของ user)
- 2026-08-03 21:33:32 UTC (ตรงกับนาทีที่ 10:32 ของคลิปที่ user อัดมา — เสียงเริ่มเพี้ยน 9:55)

**ต้นเหตุ:** `send_loop` อ่านแค่ `response.data` กับ `response.server_content`
· `go_away` กับ `session_resumption_update` เป็น field คนละตัวระดับบนของ `LiveServerMessage`
→ **ไม่มีใครอ่านเลย** → Gemini เตือนแล้วเราเงียบ มันเลยตัดทิ้งเอง
("client failed to close" ในข้อความคือ server ของเรานี่แหละ)

⚠️ `server.py:244-246` เขียนไว้ว่า *"เปิด sliding-window compression → session 'ไม่มีลิมิตอายุ'
→ ไม่มี go_away จาก duration"* — **log พิสูจน์แล้วว่าไม่จริง เกิด 2 ครั้ง**
(คอมเมนต์คือเจตนา ไม่ใช่หลักฐาน)

field name ยืนยันกับ SDK จริงบน prod (google-genai 2.10.0):
  LiveServerMessage: go_away, session_resumption_update, server_content, ...
  LiveServerGoAway: time_left
  LiveServerSessionResumptionUpdate: new_handle, resumable, last_consumed_client_message_index
"""

from datetime import timedelta

from utils.voice import live_control_signals


class _Obj:
    """object เปล่าๆ ที่เซ็ต attribute ได้ — จำลอง message ของ SDK"""

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def _msg(**kw):
    base = {"go_away": None, "session_resumption_update": None}
    base.update(kw)
    return _Obj(**base)


class TestGoAway:
    def test_plain_message_signals_nothing(self):
        assert live_control_signals(_msg()) == (False, None, None)

    def test_detects_go_away(self):
        got_go_away, _secs, _h = live_control_signals(_msg(go_away=_Obj(time_left=timedelta(seconds=12))))
        assert got_go_away is True, "ไม่จับ go_away → session จะถูก Gemini ตัดทิ้งเหมือนเดิม"

    def test_reads_time_left_as_seconds(self):
        _g, secs, _h = live_control_signals(_msg(go_away=_Obj(time_left=timedelta(seconds=12.5))))
        assert secs == 12.5

    def test_go_away_without_readable_time_still_counts(self):
        """เวลาที่เหลืออ่านไม่ได้ ก็ยังต้องรู้ว่าโดนเตือนแล้ว — ห้ามเงียบ

        ("ไม่รู้เวลา" ต้องไม่ถูกตีความเป็น "ไม่มี go_away")
        """
        for weird in (None, "12s", object()):
            got, secs, _h = live_control_signals(_msg(go_away=_Obj(time_left=weird)))
            assert got is True, f"time_left={weird!r} แล้วไม่นับว่าได้รับ go_away"
            assert secs is None

    def test_go_away_object_without_time_left_attr(self):
        got, secs, _h = live_control_signals(_msg(go_away=_Obj()))
        assert (got, secs) == (True, None)


class TestSessionResumption:
    def test_reads_new_handle(self):
        _g, _s, handle = live_control_signals(
            _msg(session_resumption_update=_Obj(new_handle="abc123", resumable=True))
        )
        assert handle == "abc123"

    def test_ignores_handle_when_not_resumable(self):
        """resumable=False = handle ใช้ต่อไม่ได้ ห้ามเก็บไว้แล้วเอาไปใช้"""
        _g, _s, handle = live_control_signals(
            _msg(session_resumption_update=_Obj(new_handle="abc123", resumable=False))
        )
        assert handle is None

    def test_ignores_empty_handle(self):
        _g, _s, handle = live_control_signals(
            _msg(session_resumption_update=_Obj(new_handle="", resumable=True))
        )
        assert handle is None


class TestRobustness:
    """ห้าม throw ไม่ว่าจะได้ message หน้าตาแบบไหน — throw = ตัดเสียงกลางเรื่อง"""

    def test_missing_attributes_do_not_raise(self):
        assert live_control_signals(_Obj()) == (False, None, None)

    def test_none_message(self):
        assert live_control_signals(None) == (False, None, None)


class TestHandlerWiring:
    """กันการถอยกลับไปเป็นโค้ดที่ไม่อ่าน go_away (บั๊กเดิม)"""

    def _ws_block(self) -> str:
        from pathlib import Path

        text = (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")
        block = text[text.index('@app.websocket("/ws/voice/'):]
        return block[: block.index("\n@app.")] if "\n@app." in block else block

    def test_handler_reads_control_signals(self):
        assert "live_control_signals(" in self._ws_block(), (
            "voice handler ไม่ได้อ่านสัญญาณควบคุม → go_away จะถูกเมินเหมือนเดิม "
            "แล้ว Gemini ตัด session ทิ้งราวนาทีที่ 10"
        )

    def test_handler_asks_for_resumption_handle(self):
        assert "SessionResumptionConfig" in self._ws_block(), (
            "ไม่ได้ขอ session resumption → ต่อ session ใหม่ได้แต่ความจำหาย "
            "(กำลังเล่านิยายอยู่แล้วเริ่มเรื่องใหม่)"
        )

    def test_handler_can_reconnect_without_dropping_client(self):
        """ต้องมีลูปต่อ session ใหม่ ไม่ใช่ connect ครั้งเดียวแล้วจบ"""
        block = self._ws_block()
        assert "while not stop.is_set():" in block, "ไม่มีลูปต่อ session ใหม่"
        assert block.count("live.connect(") == 1, "ควรมีจุด connect เดียวที่อยู่ในลูป"
        # ต้องส่ง "connected" ครั้งเดียว ไม่งั้น UI จะรีเซ็ตทุกครั้งที่ต่อใหม่
        assert "announced" in block, "ไม่ได้กันการส่ง connected ซ้ำตอนต่อ session ใหม่"
