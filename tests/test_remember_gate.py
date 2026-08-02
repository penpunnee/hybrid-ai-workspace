"""Test: episodic memory ต้องไม่เก็บข้อมูลสด/ข้อความ error (P0 จาก audit 2026-08-02)

วัดจริงบน prod:
  memory_kwan  92 รายการ → 57 (62%) เป็นข้อมูลสดที่เน่าแล้ว · 27 มี error ปน
  memory_logic 62 รายการ → 47 (76%) เป็นข้อมูลสด          · 21 มี error
ของจริงที่อยู่ในคลัง:
  "Q: ราคาทองวันนี้ A: ทองคำแท่งขายออก 72,100 บาท"   (วันนี้จริง 64,200 ผิดไป 7,900)
  "Q: คำตอบละ A: ขอโทษครับ/ค่ะ แต่ไม่สามารถช่วยเหลือในกรณีนี้ได้..."

ต้นเหตุ: `routers/chat.py` เส้น chat ปกติเรียก `remember()` โดยมีแค่เงื่อนไข
`not empty_guard_fired and not is_test_request` — **ไม่ผ่าน should_auto_learn()**
ขณะที่เส้น agent (`persist_agent_turn`) gate ถูกอยู่แล้ว → สองเส้นไม่ตรงกัน

⚠️ หลักการ: episodic **ควร**เป็นบันทึกบทสนทนาตามหน้าที่ของมัน (ต่างจาก lessons/
skills ที่ควรเป็นความรู้) จึงกันเฉพาะ 2 อย่างที่พิสูจน์แล้วว่าเป็นโทษ —
ข้อมูลที่หมดอายุ กับข้อความ error — ไม่ได้กันบทสนทนาทั่วไป
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from reasoning.learn_gate import should_remember


# ── ข้อมูลสด: คำตอบถูกแค่ ณ วันนั้น เก็บไว้ = ป้อนของผิดให้ตัวเองในอนาคต ──────
@pytest.mark.parametrize("prompt", [
    "ราคาทองวันนี้",
    "ราคาน้ำมันเบนซินวันนี้เท่าไหร่",
    "คืนนี้ฝนจะตกไหม",
    "ข่าวด่วนวันนี้",
    "น้ำท่วมตอนนี้ที่ไหนบ้าง",
])
def test_realtime_answers_not_remembered(prompt):
    ok, reason = should_remember(prompt, "ทองคำแท่งขายออก 72,100 บาท")
    assert ok is False, f"{prompt!r} เป็นข้อมูลสด ไม่ควรเก็บเป็น episodic"
    assert reason == "realtime_query"


# ── ข้อความ error/ระบบ: ไม่ใช่บทสนทนาจริง ───────────────────────────────────
@pytest.mark.parametrize("response", [
    "⚠️ ยังไม่ได้ตั้งค่า ANTHROPIC_API_KEY เปิด `.env` แล้วใส่...",
    "❌ เชื่อมต่อ server ไม่ได้",
    "⚠️ การตอบหยุดกลางคัน: RuntimeError boom",
    "ขอโทษครับ/ค่ะ แต่ไม่สามารถช่วยเหลือในกรณีนี้ได้ เนื่องจากข้อมูลที่ได้รับ",
])
def test_error_responses_not_remembered(response):
    ok, reason = should_remember("ช่วยอธิบายเรื่อง FastAPI หน่อย", response)
    assert ok is False, f"คำตอบ error ไม่ควรเก็บ: {response[:40]!r}"
    assert reason == "error_response"


# ── บทสนทนาปกติต้องยังเก็บได้ (ไม่งั้น episodic ตายทั้งระบบ) ──────────────────
@pytest.mark.parametrize("prompt,response", [
    ("ช่วยอธิบายความต่างของ FastAPI กับ Flask",
     "FastAPI ใช้ ASGI จึงรองรับ async ได้เต็มที่ ส่วน Flask เป็น WSGI แบบดั้งเดิม"),
    ("เขียนฟังก์ชัน bubble sort ให้หน่อย",
     "def bubble_sort(a):\n    for i in range(len(a)): ..."),
    ("ชอบกินอะไรตอนเช้า",
     "ขวัญว่ากาแฟดำกับขนมปังก็ดีนะคะ"),
])
def test_normal_conversation_still_remembered(prompt, response):
    ok, reason = should_remember(prompt, response)
    assert ok is True, f"บทสนทนาปกติต้องเก็บได้ (ได้ reason={reason})"


def test_existing_prompt_side_gates_still_apply():
    """gate เดิมของ should_auto_learn ต้องยังมีผล (negative feedback / home tool)"""
    assert should_remember("ไม่ใช่ละ ตอบผิด", "ขอโทษค่ะ")[1] == "negative_feedback"
    assert should_remember("", "อะไรก็ได้")[1] == "empty"


def test_empty_response_not_remembered():
    """คำตอบว่าง = ไม่มีอะไรให้จำ"""
    ok, reason = should_remember("คำถามปกติ", "   ")
    assert ok is False
    assert reason == "empty_response"
