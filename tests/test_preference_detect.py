"""Test: ตรวจจับ preference ของ user (P0 ข้อ 2 จาก audit 2026-08-02)

collection `preferences` = **0 รายการ** ทั้งที่ระบบรันมา 3 เดือน — บั๊กซ้อน 3 ชั้น
ใน `routers/chat.py`:
  1. เรียกได้เฉพาะในเธรด `_learn()` → ต้อง `len(full_response) > 100` **และ**
     ผ่าน `should_auto_learn()` ก่อน (ผูกติดกับการสร้าง lesson ทั้งที่คนละเรื่อง)
  2. keyword map มีแค่ 2 คำ: {"ตอบสั้น", "อธิบาย"}
  3. ทั้งสองคำ map ไป key เดียวกัน (`style`) → id ชนกัน (`pref_style`)

+ บั๊กที่ 4 ที่เจอตอนอ่านโค้ด: `"อธิบาย"` เป็นคำที่โผล่ในคำถามปกติแทบทุกครั้ง
  ("ช่วยอธิบาย FastAPI หน่อย") การนับว่าเป็น "ชอบคำตอบละเอียด" คือ false positive
  → ต้องใช้วลีที่บ่งบอกความชอบจริงเท่านั้น
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from reasoning.learn_gate import detect_preferences


@pytest.mark.parametrize("prompt,key,value_part", [
    ("ตอบสั้นๆ หน่อย", "style", "สั้น"),
    ("ขอแบบกระชับ", "style", "สั้น"),
    ("อธิบายละเอียดหน่อย", "style", "ละเอียด"),
    ("ขอแบบละเอียดๆ", "style", "ละเอียด"),
    ("ตอบเป็นข้อๆ", "format", "ข้อ"),
    ("ขอเป็นตาราง", "format", "ตาราง"),
    ("ขอเป็นแผนภาพ", "format", "แผนภาพ"),
    ("ทำเป็นไดอะแกรมให้หน่อย", "format", "แผนภาพ"),
])
def test_detects_real_preferences(prompt, key, value_part):
    prefs = dict(detect_preferences(prompt))
    assert key in prefs, f"{prompt!r} ควรตรวจเจอ preference '{key}' (ได้ {prefs})"
    assert value_part in prefs[key]


@pytest.mark.parametrize("prompt", [
    "ช่วยอธิบาย FastAPI หน่อย",          # "อธิบาย" เดี่ยว = ขอให้อธิบาย ไม่ใช่บอกความชอบ
    "อธิบายโค้ดนี้ให้ที",
    "ตารางนี้มีกี่แถว",                   # พูดถึงตาราง แต่ไม่ได้ขอ format ตาราง
    "สวัสดีครับ",
    "เขียนฟังก์ชัน bubble sort",
])
def test_no_false_positive_on_normal_questions(prompt):
    assert detect_preferences(prompt) == [], \
        f"{prompt!r} ไม่ได้บอกความชอบ ไม่ควรบันทึกเป็น preference"


def test_multiple_preferences_use_distinct_keys():
    """style กับ format ต้องเก็บแยก key — ไม่งั้น id ชนกันเหมือนบั๊กเดิม"""
    prefs = detect_preferences("ตอบสั้นๆ เป็นข้อๆ นะ")
    keys = [k for k, _ in prefs]
    assert "style" in keys and "format" in keys
    assert len(set(keys)) == len(keys), "key ต้องไม่ซ้ำกันในผลเดียว"


def test_conflicting_style_prefers_last_mention():
    """ถ้าพูดทั้งสั้นและละเอียดในประโยคเดียว เอาอันหลัง (เจตนาล่าสุด)"""
    prefs = dict(detect_preferences("ตอบสั้นๆ ก่อน เอาจริงๆ ขอแบบละเอียดๆ ดีกว่า"))
    assert "ละเอียด" in prefs["style"]


def test_empty_prompt_safe():
    assert detect_preferences("") == []
    assert detect_preferences(None) == []
