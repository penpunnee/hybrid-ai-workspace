"""Tests สำหรับ reasoning/classifier.py — complexity + internet classifiers

ทำไมสำคัญ: `needs_internet()` คือตัวที่ตัดสินว่าจะส่ง query ไป Gemini (web search)
หรือ local model — ถ้าตัดสินผิดจะ route ผิด (เหมือนเคสที่เจอ session 2026-05-27
ที่ chitchat ถูกส่งไป Gemini จน quota หมด). ทั้งโมดูลเป็น pure pattern-matching
ไม่มี side-effect → เทสต์ได้ deterministic 100%
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from reasoning.classifier import (
    needs_internet, classify, classify_label, Complexity,
)


# ─────────────────────────────────────────────────────────────
# needs_internet() — ต้อง True เฉพาะคำถามที่ต้องใช้ข้อมูล real-time/นิยาม
# ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text", [
    "ราคาทองวันนี้เท่าไหร่",          # ราคา + วันนี้ (real-time)
    "ข่าวล่าสุดเรื่องการเมือง",         # ข่าวล่าสุด
    "พยากรณ์อากาศพรุ่งนี้",            # พยากรณ์อากาศ
    "Bitcoin คืออะไร",                # definitional (Wikipedia)
    "ช่วยหาข้อมูลให้หน่อย",            # หาข้อมูลให้
    "ราคาหุ้น PTT ตอนนี้",            # ราคา...ตอนนี้
])
def test_needs_internet_true_for_realtime_and_definitional(text):
    assert needs_internet(text) is True, f"ควรต้องใช้ internet: {text!r}"


@pytest.mark.parametrize("text", [
    "สวัสดีครับ ขวัญ",                # ทักทาย
    "ช่วยเขียนฟังก์ชัน bubble sort",   # coding ทั่วไป
    "ขอบคุณมากนะ",                    # ขอบคุณ
    "เล่าเรื่องตลกให้ฟังหน่อย",         # chitchat
    "2 บวก 2 ได้เท่าไหร่",            # คำนวณในหัว ไม่ต้อง net
])
def test_needs_internet_false_for_chitchat_and_local(text):
    assert needs_internet(text) is False, f"ไม่ควรต้องใช้ internet: {text!r}"


# ─────────────────────────────────────────────────────────────
# classify() — REASONING (priority สูงสุด) > length > SIMPLE > NORMAL
# ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text", [
    "ทำไมท้องฟ้าถึงเป็นสีฟ้า",          # ทำไม
    "เปรียบเทียบ Python กับ Java",     # เปรียบเทียบ
    "ช่วย debug error นี้ให้หน่อย",     # debug / error
    "แนะนำวิธีออกแบบ schema ฐานข้อมูล", # แนะนำ / design / schema
])
def test_classify_reasoning_patterns(text):
    assert classify(text) == Complexity.REASONING, f"ควรเป็น reasoning: {text!r}"


def test_classify_long_text_is_reasoning():
    """คำถามยาว >= 15 คำ → REASONING แม้ไม่มี reasoning keyword"""
    text = "i have a small garden with many flowers and some trees near the old wooden house today"
    assert len(text.split()) >= 15
    assert classify(text) == Complexity.REASONING


@pytest.mark.parametrize("text", ["สวัสดี", "hello", "hi", "ok", "thanks"])
def test_classify_simple_greetings(text):
    assert classify(text) == Complexity.SIMPLE, f"ควรเป็น simple: {text!r}"


def test_classify_short_single_word_is_simple():
    """คำเดี่ยวสั้น (< 8 ตัวอักษร, 1 คำ) → SIMPLE"""
    assert classify("หิว") == Complexity.SIMPLE


@pytest.mark.parametrize("text", [
    "ขอสูตรแกงเขียวหวานหน่อย",   # 1 token, ยาว, ไม่มี reasoning keyword
    "เล่า เรื่อง แมว ให้ ฟัง",      # 5 คำ ไม่เข้า simple/reasoning
])
def test_classify_normal_fallthrough(text):
    assert classify(text) == Complexity.NORMAL, f"ควรเป็น normal: {text!r}"


# ─────────────────────────────────────────────────────────────
# classify_label() — map enum → string มี emoji
# ─────────────────────────────────────────────────────────────
def test_classify_label_maps_each_complexity():
    assert "simple" in classify_label("hello")
    assert "reasoning" in classify_label("ทำไมถึงเป็นแบบนี้")
    # ทุก label ต้องขึ้นต้นด้วย emoji + มีชื่อ complexity
    assert classify_label("ขอสูตรแกงเขียวหวานหน่อย").endswith("normal")
