"""Voice transcript → UI — regression test

บั๊กที่จับ (ต่อจาก thought-leak fix `6335c1e`): send_loop ใน server.py ส่ง
`{"type":"text"}` ให้ UI **เฉพาะจาก model_turn parts** เท่านั้น. สำหรับโมเดล
native-audio (gemini-2.5-flash-native-audio-latest) ข้อความที่ "พูดจริง" มาทาง
`output_transcription` ส่วน model_turn เป็น thought (ถูกกรองทิ้งหลัง 6335c1e).

ผล: หลังกรอง thought → ไม่มี {type:text} ส่ง UI เลย → bubble ผู้ช่วยว่างเปล่า
ทั้งที่เสียงเล่นได้และ transcript ถูกเซฟลง DB (ผ่าน ai_transcript).

helper `live_server_content_events()` ต้องส่ง output_transcription เป็น
{type:text} ให้ UI ด้วย (pure → unit-testable เหมือน speakable_part_text).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("UI_PASSWORD", "")

from utils.voice import live_server_content_events


class _Txt:
    def __init__(self, text):
        self.text = text


class _Part:
    def __init__(self, text=None, thought=False):
        self.text = text
        self.thought = thought


class _MT:
    def __init__(self, parts):
        self.parts = parts


class _SC:
    def __init__(self, input_transcription=None, output_transcription=None, model_turn=None):
        self.input_transcription = input_transcription
        self.output_transcription = output_transcription
        self.model_turn = model_turn


def test_output_transcription_is_sent_to_ui():
    # เสียงที่โมเดลพูด (native-audio) ต้องโชว์เป็น text bubble บน UI
    sc = _SC(output_transcription=_Txt("ได้ยินค่ะพี่ปอย"))
    events, user_delta, ai_delta = live_server_content_events(sc)
    assert {"type": "text", "text": "ได้ยินค่ะพี่ปอย"} in events
    assert ai_delta == "ได้ยินค่ะพี่ปอย"
    assert user_delta == ""


def test_input_transcription_is_user_text():
    sc = _SC(input_transcription=_Txt("ราคาทองวันนี้"))
    events, user_delta, ai_delta = live_server_content_events(sc)
    assert {"type": "user_text", "text": "ราคาทองวันนี้"} in events
    assert user_delta == "ราคาทองวันนี้"
    assert ai_delta == ""


def test_model_turn_thought_excluded_from_ui_and_transcript():
    # thought ของ native-audio ต้องไม่หลุดเข้า UI หรือ transcript
    sc = _SC(model_turn=_MT([_Part(text="ผู้ใช้ถามราคาทอง ฉันควร...", thought=True)]))
    events, user_delta, ai_delta = live_server_content_events(sc)
    assert events == []
    assert ai_delta == ""


def test_model_turn_spoken_text_passes_for_text_modality():
    # โมเดล text-modality (ไม่มี output_transcription) → ข้อความมาทาง model_turn
    sc = _SC(model_turn=_MT([_Part(text="สวัสดีครับ")]))
    events, user_delta, ai_delta = live_server_content_events(sc)
    assert {"type": "text", "text": "สวัสดีครับ"} in events
    assert ai_delta == "สวัสดีครับ"


def test_empty_server_content_yields_nothing():
    events, user_delta, ai_delta = live_server_content_events(_SC())
    assert events == []
    assert user_delta == "" and ai_delta == ""
