"""Test: prompt ของ REM sleep ต้องสอนให้สกัด "ความรู้" ไม่ใช่ "บันทึกว่าเคยคุย"

บั๊กจริง (audit 2026-08-02): few-shot example ใน prompt เดิมเขียนว่า
    "summary":"User frequently deploys to NAS using docker compose"
ซึ่งเป็นบันทึกว่าเคยคุย ไม่ใช่ความรู้ → โมเดลลอกรูปแบบนั้นตรงๆ มา 3 เดือน
ได้ skill 60 อันที่ใช้ได้จริง 1 อัน

พอแก้ prompt แล้ววัดกับ memory จริงบน prod (26 รายการ ผ่าน gemini):
    prompt เดิม      → 60 skills ใน 3 เดือน ใช้ได้จริง 1  (~2%)
    prompt รอบ 1     → 17 themes ส่วนใหญ่เป็น "AI can do X"  (~6%)
    prompt รอบ 2     → 7 themes · ผ่าน gate 6 · เป็นความรู้จริงส่วนใหญ่
                       (เช่น "วิธีปักหมุดข้อความ: เลื่อนเมาส์ไปที่กล่องข้อความ
                       แล้วกดปุ่ม 📌 Pin")

เทสนี้กัน prompt ถอยกลับไปรูปแบบเดิม — ไม่ได้เทสคุณภาพ LLM (ทำไม่ได้แบบ
deterministic) แต่กันโครงสร้าง prompt ที่พิสูจน์แล้วว่าเป็นต้นเหตุ
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import inspect
import pytest

import utils.dream as dream

SRC = inspect.getsource(dream.rem_sleep)


def test_bad_example_is_labelled_as_bad_not_as_the_format_example():
    """'User frequently deploys...' ต้องอยู่ในหมวดตัวอย่างที่ห้ามทำเท่านั้น"""
    assert "User frequently deploys" in SRC, "เก็บไว้เป็นตัวอย่าง BAD ให้โมเดลเห็น"
    bad_pos = SRC.find("BAD summar")
    good_pos = SRC.find("GOOD summary")
    example_pos = SRC.find("User frequently deploys")
    assert good_pos != -1 and bad_pos != -1, "prompt ต้องมีทั้งตัวอย่าง GOOD และ BAD"
    assert example_pos > bad_pos, \
        "'User frequently deploys' ต้องอยู่ใต้หัวข้อ BAD — ถ้าไปอยู่เป็น format example จะสอนผิดเหมือนเดิม"


@pytest.mark.parametrize("anti_pattern", [
    "AI can generate",        # กันรูปแบบ "AI can do X" ที่เจอตอนแก้รอบแรก
    "AI cannot",              # กันรูปแบบ "AI cannot do X"
    "A request was made",     # กันรูปแบบบันทึกว่าเคยคุย
])
def test_known_anti_patterns_are_listed_as_bad(anti_pattern):
    """anti-pattern ที่เคยเจอจริงต้องอยู่ใน prompt เป็นตัวอย่างที่ห้ามทำ"""
    assert anti_pattern in SRC, f"prompt ควรสอนไม่ให้ตอบแบบ {anti_pattern!r}"


def test_prompt_allows_empty_result():
    """ต้องบอกโมเดลว่าคืน list ว่างได้ ไม่งั้นมันจะปั้นธีมมาเติมให้ครบ"""
    low = SRC.lower()
    assert "empty" in low and ("correct" in low or "prefer an empty" in low), \
        "prompt ต้องระบุว่าคืน themes ว่างเป็นเรื่องปกติ"


def test_prompt_excludes_expiring_and_failure_themes():
    """หมวดที่พิสูจน์แล้วว่าเป็นขยะต้องถูกสั่งข้ามใน prompt ด้วย (ไม่ใช่พึ่ง gate อย่างเดียว)"""
    low = SRC.lower()
    assert "expire" in low or "wrong by next week" in low, "ต้องสั่งข้ามข้อมูลที่หมดอายุ"
    assert "failure" in low or "limitation" in low, "ต้องสั่งข้ามบันทึกความล้มเหลว"
