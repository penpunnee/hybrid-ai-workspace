"""Test: Dream Cycle ต้องไม่เลื่อนขั้น "ธีม" ที่ไม่ใช่ความรู้ขึ้นเป็น skill ถาวร

ตรวจ skills จริงบน prod 2026-08-02: จาก 112 หัวข้อ มี 60 อันที่ Dream สร้างเอง
และ **ไม่มีสักอันที่เป็นความรู้ใช้ซ้ำได้จริง** — แบ่งเป็น

  บันทึกความล้มเหลว (5)   [Dream] System Limitations & Errors
                          [Dream] ระบบไม่สามารถเข้าถึงข้อมูลสภาพอากาศแบบเรียลไทม์
  ข้อมูลสด/เน่าได้ (26)   [Dream] Weather Forecast / วันพรุ่งนี้อากาศ
                          [Dream] ตรวจสอบ ping และความเร็วในการตอบสนอง
  บันทึกว่าเคยคุย (29)    [Dream] Greetings / ตอบเป็นภาษาไทย / การตรวจสอบระบบ

ที่แย่ที่สุด: `[Dream] ตรวจสอบ โครงสร้างเครือข่ายในบ้าน` บันทึกว่า
"Router: TP-Link Archer C7, Modem: Huawei HG533" ทั้งที่ของจริงคือ ASUS RT-BE92U
→ **ข้อมูลผิดถูกป้อนให้ AI เป็นความรู้ถาวรทุก prompt**

ต้นเหตุ: `PROMOTE_MIN_HITS = 1` — ธีมที่โผล่ครั้งเดียวก็เลื่อนขั้นได้ = ไม่มีการ
กรองเลย ทั้งที่จุดประสงค์ของ Dream promotion คือหา "รูปแบบที่เกิดซ้ำ"
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from utils.dream import should_promote_theme, PROMOTE_MIN_HITS


def test_min_hits_requires_actual_repetition():
    """เจอครั้งเดียว = ไม่ใช่ 'รูปแบบที่เกิดซ้ำ' ตามนิยามของ Dream promotion"""
    assert PROMOTE_MIN_HITS >= 2, \
        f"PROMOTE_MIN_HITS={PROMOTE_MIN_HITS} — ธีมที่โผล่ครั้งเดียวไม่ควรเป็นความรู้ถาวร"


@pytest.mark.parametrize("name,summary", [
    ("System Limitations & Errors", "The system explicitly encountered an error once"),
    ("ระบบไม่สามารถเข้าถึงข้อมูลสภาพอากาศ", "System unable to access real-time weather data"),
    ("Gemini Agent Errors", "A large majority of interactions resulted in various errors"),
    ("Model Issues", "System encounters model issues, including quota limits"),
])
def test_failure_records_are_not_knowledge(name, summary):
    """บันทึกว่า 'ระบบทำไม่ได้' ไม่ใช่ความรู้ — ยิ่งป้อนให้โมเดลยิ่งชวนให้ปฏิเสธงาน"""
    ok, reason = should_promote_theme(name, summary, hits=5)
    assert ok is False, f"{name!r} เป็นบันทึกความล้มเหลว ไม่ควรเลื่อนขั้น"
    assert reason == "failure_record"


@pytest.mark.parametrize("name,summary", [
    ("Weather Forecast", "User frequently asks about weather forecast"),
    ("วันพรุ่งนี้อากาศ", "User frequently asks about tomorrow's weather in Bangkok"),
    ("อากาศวันนี้ จะมีฝนตกไหม", "คืนนี้จะมีฝนตกเล็กน้อย ในอำเภอละเว"),
    ("ตรวจสอบ ping และความเร็วในการตอบสนอง", "Router (192.168.51.1) อยู่ออนไลน์"),
])
def test_realtime_themes_are_not_promoted(name, summary):
    """ข้อมูลสดเน่าได้ — ราคา/อากาศ/ping ของวันนั้น ไม่ควรกลายเป็นความรู้ถาวร
    (เจอจริง: skill บันทึกรุ่น router ผิดไว้ถาวรจากการ ping ครั้งหนึ่ง)"""
    ok, reason = should_promote_theme(name, summary, hits=9)
    assert ok is False, f"{name!r} เป็นข้อมูลสด ไม่ควรเลื่อนขั้น"
    assert reason == "realtime"


@pytest.mark.parametrize("name,summary", [
    ("Greetings", "A brief and friendly interaction involving a simple greeting"),
    ("Thai Responses", "User prefers concise Thai responses (consolidated 9 times)"),
    ("การตรวจสอบระบบ", "การตรวจสอบระบบทำงานได้ดี และมีการถามถึงความช่วยเหลือ"),
    ("UI/UX Design", "A request was made for an example of UI/UX product design"),
])
def test_conversation_meta_records_are_not_promoted(name, summary):
    """'ผู้ใช้ชอบถามเรื่อง X' = บันทึกว่าเคยคุย ไม่ใช่ความรู้ที่เอาไปตอบได้"""
    ok, reason = should_promote_theme(name, summary, hits=9)
    assert ok is False, f"{name!r} เป็น meta-record ไม่ควรเลื่อนขั้น"
    assert reason == "conversation_meta"


@pytest.mark.parametrize("name,summary", [
    ("วิธี deploy ด้วย docker compose",
     "ขั้นตอน deploy: git reset --hard แล้ว docker compose up -d --force-recreate"),
    ("การเปรียบเทียบ FastAPI กับ Flask",
     "FastAPI เร็วกว่าเพราะใช้ ASGI และมี type hints ในตัว ส่วน Flask ยืดหยุ่นกว่า"),
])
def test_real_procedural_knowledge_still_promoted(name, summary):
    """ความรู้จริงต้องยังผ่าน — ไม่งั้น Dream promotion ตายทั้งระบบ"""
    ok, reason = should_promote_theme(name, summary, hits=3)
    assert ok is True, f"{name!r} เป็นความรู้จริง ควรเลื่อนขั้นได้ (ได้ {reason})"


def test_below_min_hits_blocked_even_if_good_content():
    ok, reason = should_promote_theme(
        "วิธี deploy ด้วย docker compose", "ขั้นตอน deploy อย่างละเอียด", hits=1)
    assert ok is False
    assert reason == "too_few_hits"
