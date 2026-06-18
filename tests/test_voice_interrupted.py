"""Voice barge-in / interruption — regression test

บั๊กที่จับ: ตอน AI กำลังพูด แล้วผู้ใช้พูดแทรก (หรือ Gemini Live ตัดจังหวะเอง)
server จะส่ง `server_content.interrupted = True` มา — แต่
`live_server_content_events()` ไม่อ่าน field นี้เลย → client ไม่เคยรู้ว่าโดน
ตัดจังหวะ → คิวเสียงเก่า (nextPlayTimeRef) ไม่ถูก flush → เสียงตอบ turn ถัดไป
ต่อท้ายคิวเก่า เล่นช้า/ทับกัน → ผู้ใช้รู้สึกเหมือน "ค้าง" ตอนจะถามต่อ.

helper ต้องส่ง event {"type": "interrupted"} ให้ UI เมื่อ sc.interrupted เป็น True
เพื่อให้ client flush คิวเสียง + หยุด source nodes ที่ schedule ไว้.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("UI_PASSWORD", "")

from utils.voice import live_server_content_events


class _Txt:
    def __init__(self, text):
        self.text = text


class _SC:
    def __init__(self, input_transcription=None, output_transcription=None,
                 model_turn=None, interrupted=False):
        self.input_transcription = input_transcription
        self.output_transcription = output_transcription
        self.model_turn = model_turn
        self.interrupted = interrupted


def test_interrupted_emits_event():
    # โดน barge-in → ต้องบอก UI ให้ flush คิวเสียง
    events, user_delta, ai_delta = live_server_content_events(_SC(interrupted=True))
    assert {"type": "interrupted"} in events


def test_interrupted_with_transcript_still_emits_both():
    # ตัดจังหวะมาพร้อม output_transcription ของ turn ใหม่ → ส่งทั้ง interrupted + text
    sc = _SC(output_transcription=_Txt("ครับ"), interrupted=True)
    events, user_delta, ai_delta = live_server_content_events(sc)
    assert {"type": "interrupted"} in events
    assert {"type": "text", "text": "ครับ"} in events
    assert ai_delta == "ครับ"


def test_no_interrupted_attr_is_safe():
    # server_content ที่ไม่มี attr interrupted เลย → ห้าม error, ห้ามส่ง interrupted
    class Bare:
        input_transcription = None
        output_transcription = None
        model_turn = None
    events, _, _ = live_server_content_events(Bare())
    assert {"type": "interrupted"} not in events


def test_not_interrupted_does_not_emit():
    events, _, _ = live_server_content_events(_SC(interrupted=False))
    assert {"type": "interrupted"} not in events
