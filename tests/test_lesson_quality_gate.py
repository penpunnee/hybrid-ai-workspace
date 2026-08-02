"""Test: อุดรูที่ทำให้ lessons กลายเป็นคลังขยะ (พบจาก audit 2026-08-02)

ตรวจ lessons จริงบน prod 30 รายการ เจอขยะ 4 แบบที่หลุดเข้ามาได้:

  [บทเรียน: คืนนี้ฝนจะตกไหม] คืนนี้ฝนจะตกไหม? SKIP
  [บทเรียน: hi] ⚠️ ยังไม่ได้ตั้งค่า ANTHROPIC_API_KEY เปิด .env แล้วใส่...
  [บทเรียน: ราคาทองคำแท่งวันนี้] ราคาทองคำแท่ง 96.5% วันที่ 11 มิถุนายน 2569...
  [บทเรียน: ฝนตกไหมคืนนี้] Here is a summary of the lesson in 1-2 sentences: "tonight...

สาเหตุ:
1. `should_auto_learn()` กันแค่ home_tool ไม่ได้กันคำถามข้อมูลสดที่ค้นเว็บ
   → ราคาทอง/พยากรณ์อากาศของวันนั้น ถูกแช่แข็งเป็น "ความรู้ถาวร" ป้อนให้ AI
   อ่านทุก prompt ไปตลอด (นี่คือเหตุผลที่คะแนน lessons กลับด้าน: คลังมีแต่
   ข้อมูลสดเก่า คำถามราคาน้ำมันเลยแมตช์ 0.452 ส่วน deploy NAS ได้แค่ 0.292)
2. เช็ค SKIP ใช้ `lesson != "SKIP"` เป๊ะๆ → "คืนนี้ฝนจะตกไหม? SKIP" รอดเข้ามา
3. ไม่กรอง error message ที่โมเดลคายออกมา
4. ไม่ตัดคำนำของโมเดล ("Here is a summary...")
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from reasoning.learn_gate import should_auto_learn, clean_lesson


# ── 1. กันคำถามข้อมูลสดไม่ให้ตกผลึกเป็นบทเรียนถาวร ──────────────────────────
@pytest.mark.parametrize("prompt", [
    "ราคาทองคำแท่งวันนี้บาทละเท่าไหร่",
    "คืนนี้ฝนจะตกไหม",
    "ราคาน้ำมันเบนซินวันนี้เท่าไหร่",
    "ข่าวด่วนวันนี้",
    "น้ำท่วมตอนนี้ที่ไหนบ้าง",
])
def test_realtime_prompts_never_become_lessons(prompt):
    ok, reason = should_auto_learn(prompt)
    assert ok is False, f"{prompt!r} เป็นข้อมูลสด ห้ามเก็บเป็นความรู้ถาวร (ได้ reason={reason})"
    assert reason == "realtime_query"


@pytest.mark.parametrize("prompt", [
    "ช่วยอธิบายความต่างของ FastAPI กับ Flask",
    "เขียนฟังก์ชัน bubble sort ให้หน่อย",
    "อธิบายหลักการทำงานของ index ในฐานข้อมูล",
])
def test_evergreen_prompts_still_learnable(prompt):
    """ความรู้ที่ใช้ซ้ำได้ต้องยังเก็บเป็นบทเรียนได้ ไม่งั้น auto-learn ตายทั้งระบบ"""
    ok, reason = should_auto_learn(prompt)
    assert ok is True, f"{prompt!r} ควรเก็บเป็นบทเรียนได้ (ได้ reason={reason})"


def test_existing_gates_still_work():
    """gate เดิมต้องไม่ regress"""
    assert should_auto_learn("")[0] is False
    assert should_auto_learn("ไม่ใช่ละ ตอบผิด")[1] == "negative_feedback"


# ── 2. SKIP ต้องทนคำนำ/คำต่อท้าย ────────────────────────────────────────────
@pytest.mark.parametrize("raw", [
    "SKIP",
    "  SKIP  ",
    "คืนนี้ฝนจะตกไหม? SKIP",          # เคสจริงที่หลุดเข้า prod
    "SKIP — ไม่มีบทเรียนจากบทสนทนานี้",
    "skip",
])
def test_skip_variants_are_discarded(raw):
    assert clean_lesson(raw) is None, f"{raw!r} มี SKIP ต้องไม่ถูกเก็บ"


# ── 3. error message ห้ามกลายเป็นบทเรียน ────────────────────────────────────
@pytest.mark.parametrize("raw", [
    "⚠️ ยังไม่ได้ตั้งค่า ANTHROPIC_API_KEY เปิด `.env` แล้วใส่: ANTHROPIC_API_KEY=sk-ant-...",
    "❌ เชื่อมต่อ server ไม่ได้",
    "⚠️ โมเดลไม่ได้ให้คำตอบ (อาจใช้เวลาคิดจนหมดโควตา token)",
])
def test_error_messages_are_discarded(raw):
    assert clean_lesson(raw) is None, f"{raw!r} เป็น error ไม่ใช่บทเรียน"


# ── 4. ตัดคำนำของโมเดลออก ───────────────────────────────────────────────────
def test_strips_english_preamble():
    raw = 'Here is a 1-2 sentence summary in Thai:\n\nFastAPI เร็วกว่า Flask เพราะใช้ ASGI'
    out = clean_lesson(raw)
    assert out is not None
    assert "Here is" not in out
    assert "FastAPI เร็วกว่า Flask" in out


def test_strips_thai_preamble():
    raw = "นี่คือบทสรุป 1-2 ประโยค:\nการ deploy ต้อง restart container หลังแก้ server.py"
    out = clean_lesson(raw)
    assert out is not None
    assert "นี่คือบทสรุป" not in out
    assert "restart container" in out


def test_keeps_clean_lesson_untouched():
    raw = "การ deploy ขึ้น NAS ต้อง git reset --hard แล้ว restart container เสมอ"
    assert clean_lesson(raw) == raw


def test_too_short_after_cleaning_is_discarded():
    """เหลือสั้นเกินไปหลังตัดคำนำ = ไม่มีเนื้อหาจริง"""
    assert clean_lesson("Here is a summary in Thai:\n\nok") is None
    assert clean_lesson("สั้น") is None
