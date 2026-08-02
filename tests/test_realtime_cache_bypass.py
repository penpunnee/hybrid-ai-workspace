"""Test: คำถามข้อมูลสดต้อง bypass response cache เสมอ

บั๊กจริง (พบจาก audit 2026-08-02): ระบบมี 2 รายการคำที่ต้องสอดคล้องกันแต่ดริฟต์
ออกจากกัน — `needs_internet()` (ตัดสินว่าต้องค้นเว็บไหม) กับ `is_realtime_query()`
(ตัดสินว่าห้ามใช้คำตอบจากแคชไหม) ทำให้ 6 หมวดที่ระบบ**รู้อยู่แล้วว่าเป็นข้อมูลสด**
(ค้นเว็บให้จริง) กลับไม่กันแคช:

  ถาม "น้ำท่วมตอนนี้ที่ไหนบ้าง" → ค้นเว็บได้ข้อมูลสดถูกต้อง → user กด 👍
  → เก็บเข้า response cache (TTL 30 วัน) → อีกสองสัปดาห์ถามซ้ำ
  → เสิร์ฟข้อมูลน้ำท่วมของสองสัปดาห์ก่อนเหมือนเป็นข้อมูลปัจจุบัน

หลักการแก้: อะไรก็ตามที่สดพอจะต้องค้นเว็บ = สดเกินกว่าจะแคช → ให้
is_realtime_query() ถือ needs_internet() เป็นเงื่อนไขเพียงพอ (single source of
truth) ส่วน keyword เดิมคงไว้สำหรับของสดที่ค้นเว็บไม่ได้ (ping/disk/docker/NAS)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from utils.response_cache import is_realtime_query
from reasoning.classifier import needs_internet


@pytest.mark.parametrize("prompt", [
    "น้ำท่วมตอนนี้ที่ไหนบ้าง",
    "แผ่นดินไหวตอนนี้ที่ไหน",
    "ไฟดับตอนนี้ที่ไหน",
    "ข่าวด่วนวันนี้",
    "ผลบอลเมื่อคืน",
    "รถติดไหมตอนนี้",
    "วันนี้เกิดอะไรขึ้นบ้าง",
])
def test_web_searchable_realtime_queries_bypass_cache(prompt):
    """6 หมวดที่ค้นเว็บให้จริงแต่เดิมไม่กันแคช — ข้อมูลภัยพิบัติค้างเก่าอันตรายกว่าไม่มี"""
    assert is_realtime_query(prompt) is True, \
        f"{prompt!r} ค้นเว็บให้จริงแต่ไม่กันแคช → คำตอบเก่าถูกเสิร์ฟซ้ำได้"


@pytest.mark.parametrize("prompt", [
    "ราคาทองวันนี้เท่าไหร่",
    "หุ้นไทยวันนี้เขียวหรือแดง",
    "วันนี้อากาศเป็นยังไง",
])
def test_previously_covered_realtime_still_bypasses(prompt):
    """เคสที่เดิมทำงานถูกอยู่แล้ว ต้องไม่ regress"""
    assert is_realtime_query(prompt) is True


@pytest.mark.parametrize("prompt", [
    "ping 192.168.51.49 หน่อย",
    "disk เหลือเท่าไหร่",
    "docker รันอยู่กี่ตัว",
    "สถานะ nas เป็นยังไง",
])
def test_local_realtime_without_web_search_still_bypasses(prompt):
    """ของสดที่ค้นเว็บไม่ได้ (สถานะเครื่องในบ้าน) — needs_internet ไม่จับ
    ต้องพึ่ง keyword list เดิม ห้ามหลุด"""
    assert is_realtime_query(prompt) is True


@pytest.mark.parametrize("prompt", [
    "ช่วยเขียนฟังก์ชัน bubble sort",
    "ขอบคุณมากนะ",
    "ช่วยแนะนำวิธีจัดโต๊ะทำงานให้เป็นระเบียบหน่อย",
])
def test_evergreen_queries_still_cacheable(prompt):
    """คำถามที่คำตอบไม่เน่า ต้องยังแคชได้ — ไม่งั้น cache ไร้ประโยชน์"""
    assert is_realtime_query(prompt) is False, \
        f"{prompt!r} ไม่ใช่ข้อมูลสด ควรแคชได้ (ไม่งั้น response cache ตายทั้งระบบ)"


def test_needs_internet_is_sufficient_condition_for_bypass():
    """invariant กันดริฟต์: ทุก prompt ที่ needs_internet=True ต้อง bypass cache
    (นี่คือกฎที่ทำให้ 2 รายการคำไม่หลุดกันอีก)"""
    samples = [
        "น้ำท่วมตอนนี้ที่ไหนบ้าง", "ข่าวด่วนวันนี้", "ราคา bitcoin เท่าไหร่",
        "ผลบอลเมื่อคืน", "One Piece ออกตอนล่าสุดกี่ตอนแล้ว", "Bitcoin คืออะไร",
    ]
    for s in samples:
        if needs_internet(s):
            assert is_realtime_query(s) is True, \
                f"{s!r}: needs_internet=True แต่ไม่ bypass cache — 2 รายการคำดริฟต์กันอีกแล้ว"
