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
    # ── ความคืบหน้า/ตอนล่าสุด (anime/มังงะ/ซีรีส์/ซอฟต์แวร์) — เคสที่ user เจอจริง 2026-06-15 ──
    "คัมภีร์วิถีเซียน อนิเมะตอนนี้ถึงตอนไหนแล้ว",   # อนิเมะ + ถึงตอนไหน
    "One Piece ออกตอนล่าสุดกี่ตอนแล้ว",            # ล่าสุด + กี่ตอน
    "มังงะเรื่องนี้จบหรือยัง",                       # มังงะ + จบหรือยัง
    "เวอร์ชันล่าสุดของ Python คืออะไร",             # เวอร์ชันล่าสุด
    "ซีรีส์เรื่องนี้ออกตอนใหม่ยัง",                  # ซีรีส์ + ตอนใหม่
])
def test_needs_internet_true_for_realtime_and_definitional(text):
    assert needs_internet(text) is True, f"ควรต้องใช้ internet: {text!r}"


@pytest.mark.parametrize("text", [
    "สวัสดีครับ ขวัญ",                # ทักทาย
    "ช่วยเขียนฟังก์ชัน bubble sort",   # coding ทั่วไป
    "ขอบคุณมากนะ",                    # ขอบคุณ
    "เล่าเรื่องตลกให้ฟังหน่อย",         # chitchat
    "2 บวก 2 ได้เท่าไหร่",            # คำนวณในหัว ไม่ต้อง net
    "ชอบดูอนิเมะแนวไหน",              # พูดถึงอนิเมะ แต่ไม่ถามความคืบหน้า → ไม่ต้อง net
])
def test_needs_internet_false_for_chitchat_and_local(text):
    assert needs_internet(text) is False, f"ไม่ควรต้องใช้ internet: {text!r}"


# ── P3-12: gap audit (2026-07-13) — เจอ pattern ตกหล่นจากคำถาม real-time ที่ user
# มักถามจริง (สลับลำดับคำ/ไม่มี "ราคา"/"วันนี้" ตรงตัว) — ปิดครบ 8 หมวด ──
@pytest.mark.parametrize("text", [
    "ทองคำตอนนี้ราคาเท่าไหร่",       # สลับลำดับ (เดิมจับได้แค่ "ราคาทอง" คำติดกัน)
    "วันนี้ดอลลาร์เท่าไหร่",          # อัตราแลกเปลี่ยน ไม่มีคำว่า "อัตราแลกเปลี่ยน" ตรงๆ
    "ผลบอลเมื่อคืน",                 # กีฬา — หมวดใหม่ทั้งหมด
    "ผลฟุตบอลล่าสุด",
    "สกอร์เกมคืนนี้",
    "รถติดไหมตอนนี้",                # จราจร — หมวดใหม่
    "การจราจรตอนนี้เป็นยังไง",
    "หุ้นไทยวันนี้เขียวหรือแดง",       # หุ้น ไม่มีคำว่า "ราคาหุ้น" ตรงๆ
    "น้ำท่วมตอนนี้ที่ไหนบ้าง",         # ภัยพิบัติ — หมวดใหม่
    "แผ่นดินไหวตอนนี้ที่ไหน",
    "ข่าวด่วนวันนี้",
    "ไฟดับตอนนี้ที่ไหน",              # ไฟฟ้าขัดข้อง — หมวดใหม่
])
def test_needs_internet_true_for_gap_audit_2026_07_13(text):
    assert needs_internet(text) is True, f"เจอจาก gap audit — ควรต้องใช้ internet: {text!r}"


@pytest.mark.parametrize("text", [
    "ชอบดูบอลไหม",          # พูดถึงบอลทั่วไป ไม่ได้ถามผล/สกอร์
    "รถของฉันสีแดง",        # มีคำว่า "รถ" แต่ไม่ใช่ถามจราจร
])
def test_needs_internet_false_for_gap_audit_near_miss(text):
    """pattern ใหม่ (รถติด/ผลบอล) ต้องไม่ over-trigger คำใกล้เคียงที่ไม่เกี่ยวกับ real-time"""
    assert needs_internet(text) is False, f"ไม่ควร over-trigger: {text!r}"


# ── gap audit (2026-08-02) — พบจาก audit data flow: ราคาที่ไม่มีคำ "วันนี้"/
# "ตอนนี้" ต่อท้าย (เช่นถามราคาคริปโต) + ข่าวทั่วไปที่ไม่มีคำว่า "ข่าว"/"ล่าสุด"
# ยังหลุดผ่าน classifier ไปตอบจากข้อมูลเก่าโดยไม่บอก user ว่าไม่ได้ค้นเว็บ ──
@pytest.mark.parametrize("text", [
    "ราคา bitcoin เท่าไหร่",          # ราคาคริปโต ไม่มี "วันนี้"/"ตอนนี้"
    "เท่าไหร่ ราคา ethereum",         # สลับลำดับ
    "ราคาน้ำมันเท่าไหร่",             # ราคาทั่วไป ไม่มีคำเวลา
    "วันนี้เกิดอะไรขึ้นบ้าง",           # ข่าวทั่วไป ไม่มีคำว่า "ข่าว"/"ล่าสุด"
    "มีอะไรเกิดขึ้นบ้างวันนี้",
])
def test_needs_internet_true_for_gap_audit_2026_08_02(text):
    assert needs_internet(text) is True, f"เจอจาก audit 2026-08-02 — ควรต้องใช้ internet: {text!r}"


@pytest.mark.parametrize("text", [
    "ของสิ่งนี้มีคุณค่าทางใจเท่าไหร่",   # มีคำว่า "เท่าไหร่" แต่ไม่ใช่ถามราคา
])
def test_needs_internet_false_for_gap_audit_2026_08_02_near_miss(text):
    assert needs_internet(text) is False, f"ไม่ควร over-trigger: {text!r}"


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
