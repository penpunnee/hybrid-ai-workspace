"""Voice transcript thought-leak — regression test

บั๊กที่จับ: send_loop ใน server.py วน `model_turn.parts` แล้วต่อ `part.text`
ทุก part ที่มีข้อความ — รวม part ที่ `part.thought is True` (chain-of-thought
ของ Gemini Live thinking model เช่น gemini-2.5-flash-native-audio-latest)
→ เหตุผลภายในหลุดเข้า UI ({"type":"text"}) และ transcript ที่เซฟ (ai_transcript).

helper `speakable_part_text()` ต้องคืน text เฉพาะ part ที่ "พูดออกมา" จริง
และตัด thought ทิ้ง.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("UI_PASSWORD", "")

from utils.voice import speakable_part_text


class _Part:
    def __init__(self, text=None, thought=False):
        self.text = text
        self.thought = thought


def test_spoken_part_passes_through():
    assert speakable_part_text(_Part(text="ราคาทองวันนี้ ฿63,950")) == "ราคาทองวันนี้ ฿63,950"


def test_thought_part_is_excluded():
    # part เหตุผลภายใน — ห้ามหลุดเข้า transcript/UI
    assert speakable_part_text(_Part(text="ผู้ใช้ถามราคาทอง ฉันควร...", thought=True)) is None


def test_part_without_thought_attr_passes():
    class Bare:
        text = "สวัสดีครับ"
    assert speakable_part_text(Bare()) == "สวัสดีครับ"


def test_empty_text_returns_none():
    assert speakable_part_text(_Part(text=None)) is None
    assert speakable_part_text(_Part(text="", thought=False)) is None
