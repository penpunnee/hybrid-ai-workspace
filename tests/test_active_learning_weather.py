"""Active Learning — weather query ที่ไม่มี location ต้องถามกลับ (clarify) ไม่ใช่กุ

บั๊กจริง (session 2026-06-14): ถาม "ฝนจะตกไหมวันนี้" (ไม่บอกจังหวัด) →
route ไป gemini_agent ถูก แต่ Gemini กุชื่อ "อำเภอละเว" ขึ้นมาตอบ เพราะ
ค้นไม่ได้ว่า "ฝนที่ไหน" และ active_learning เดิมมองว่า prompt นี้ "มี entity"
(chunk ไทยยาว) → ambiguity = 0 → ไม่ถามกลับ

สัญญาใหม่:
1. weather/forecast query ที่ไม่มี location → should_ask=True + clarify_directly=True
2. weather query ที่ "มี" location (จังหวัด/อำเภอ/ชื่อเมือง) → ไม่ clarify
3. location อาจมาจาก history ก่อนหน้า (recent_user_text) → ไม่ต้องถามซ้ำ
4. ประโยคที่ไม่ใช่ weather → ไม่ถูกกระทบ
5. clarify_directly ต้องมี clarify_message พร้อมใช้ (deterministic, ไม่เรียก LLM)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reasoning.active_learning import decide


# ── 1. weather ไม่มี location → ต้อง clarify ────────────────────────────────
def test_weather_no_location_asks_back():
    d = decide("ฝนจะตกไหมวันนี้")
    assert d.should_ask is True
    assert d.clarify_directly is True
    assert d.clarify_message  # ต้องมีข้อความถามกลับพร้อมใช้
    assert d.signals.get("weather_no_location") is True


def test_weather_no_location_variants():
    for q in ("อากาศวันนี้เป็นยังไง", "พรุ่งนี้ฝนตกไหม",
              "วันนี้ร้อนไหม", "คืนนี้จะมีฝนฟ้าคะนองไหม"):
        d = decide(q)
        assert d.clarify_directly is True, f"ควร clarify: {q!r}"


# ── 2. weather + location → ไม่ clarify (ปล่อยให้ค้นจริง) ────────────────────
def test_weather_with_province_no_clarify():
    for q in ("ฝนจะตกไหมวันนี้ ที่กรุงเทพ", "ฝนตกไหมเชียงใหม่",
              "อากาศวันนี้ที่ภูเก็ตเป็นไง", "พรุ่งนี้โคราชฝนตกไหม",
              "ฝนตกไหมแถวจังหวัดน่าน"):
        d = decide(q)
        assert d.clarify_directly is False, f"ไม่ควร clarify (มี location): {q!r}"


# ── 3. location จาก history ก่อนหน้า → ไม่ถามซ้ำ ────────────────────────────
def test_location_from_recent_history_suppresses_clarify():
    d = decide("แล้วพรุ่งนี้ล่ะ ฝนตกไหม",
               recent_user_text="ฝนวันนี้ที่ภูเก็ตเป็นไงบ้าง")
    assert d.clarify_directly is False


# ── 4. ไม่ใช่ weather → ไม่กระทบ ────────────────────────────────────────────
def test_non_weather_not_affected():
    for q in ("วิธีทำต้มยำกุ้ง", "เขียนฟังก์ชัน python อ่านไฟล์ csv",
              "สรุปข่าวเศรษฐกิจวันนี้"):
        d = decide(q)
        assert d.clarify_directly is False, f"ไม่ควร clarify: {q!r}"


# ── 5. user สั่งตอบตรงๆ → ไม่ถามกลับแม้ไม่มี location ───────────────────────
def test_user_wants_direct_overrides():
    d = decide("ฝนตกไหมวันนี้ ตอบเลย")
    assert d.clarify_directly is False
    assert d.should_ask is False


# ── 6. generic ambiguity เดิมยังทำงาน ───────────────────────────────────────
def test_existing_ambiguity_still_works():
    d = decide("อะไร")
    assert d.should_ask is True
    # bare ambiguity ไม่ใช่ weather → ไม่ short-circuit แบบ deterministic
    assert d.clarify_directly is False
