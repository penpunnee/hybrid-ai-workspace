"""Test: insights จาก REM ต้องเป็น list ของข้อความเสมอ

ที่มา (2026-09-30 · devlog [ต่อ 42]): prompt สั่ง `"insights":["..."]` แต่ Gemini ส่ง object มาเป็นบางรอบ
— รายงานเก่า 6/270 ไฟล์มี `{"summary": "...", "count": 3}` · probe วันนี้ได้ `{"user": "ปอย"}` 1/3 รอบ
หน้าต่างรายงาน Dream แสดง `<li>{ins}</li>` → React 18 โยน "Objects are not valid as a React child"
แล้ว unmount ทั้ง root (จำลองด้วย 18.3.1 ใน jsdom: html เหลือ 0 ตัวอักษร) = จอขาวทั้งแอป
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils.dream as dream

_MEMS = [{"timestamp": "2026-09-29T15:31:00", "doc": "Q: x A: y"}]


def _rem(monkeypatch, reply: str) -> dict:
    def fake_stream(messages, **kw):
        yield reply

    monkeypatch.setattr(dream, "stream_response", fake_stream)
    return dream.rem_sleep(_MEMS, provider="gemini")


def test_ข้อความ_ผ่านตามเดิม(monkeypatch):
    r = _rem(monkeypatch, '{"themes":[],"insights":["ใช้ NAS DS923+"],"connections":[]}')
    assert r["insights"] == ["ใช้ NAS DS923+"]


def test_object_ที่มี_summary_ดึงข้อความออกมา(monkeypatch):
    r = _rem(monkeypatch, '{"themes":[],"insights":[{"summary":"ชอบทาสีบ้าน","count":3}],"connections":[]}')
    assert r["insights"] == ["ชอบทาสีบ้าน"]


def test_object_ที่มี_text_ดึงข้อความออกมา(monkeypatch):
    r = _rem(monkeypatch, '{"themes":[],"insights":[{"text":"ใช้ iPhone"}],"connections":[]}')
    assert r["insights"] == ["ใช้ iPhone"]


def test_มีทั้ง_summary_และ_text_ใช้_summary(monkeypatch):
    """รูปแบบที่เจอจริงในรายงานเก่าใช้ summary → ให้มาก่อน"""
    r = _rem(monkeypatch, '{"themes":[],"insights":[{"text":"รอง","summary":"หลัก"}],"connections":[]}')
    assert r["insights"] == ["หลัก"]


def test_object_แบบอื่น_กลายเป็น_JSON_string(monkeypatch):
    r = _rem(monkeypatch, '{"themes":[],"insights":[{"user":"ปอย"}],"connections":[]}')
    assert r["insights"] == ['{"user": "ปอย"}'], "ต้องเป็น JSON ภาษาไทยอ่านออก (ensure_ascii=False)"


def test_summary_ที่ไม่ใช่ข้อความ_กลายเป็น_JSON_string(monkeypatch):
    r = _rem(monkeypatch, '{"themes":[],"insights":[{"summary":{"a":1}}],"connections":[]}')
    assert r["insights"] == ['{"summary": {"a": 1}}']


def test_ชนิดอื่น_กลายเป็น_JSON_string(monkeypatch):
    r = _rem(monkeypatch, '{"themes":[],"insights":[3, null, ["a"]],"connections":[]}')
    assert r["insights"] == ["3", "null", '["a"]']


def test_insights_ไม่ใช่_list(monkeypatch):
    """frontend เรียก `.map` — ถ้าเป็นข้อความเดี่ยวก็พังเหมือนกัน"""
    r = _rem(monkeypatch, '{"themes":[],"insights":"ข้อเดียว","connections":[]}')
    assert r["insights"] == ["ข้อเดียว"]


def test_ไม่มี_insights(monkeypatch):
    r = _rem(monkeypatch, '{"themes":[],"connections":[]}')
    assert r["insights"] == []


def test_ทุกค่าที่ออกไปเป็นข้อความ_ครอบรอบสองด้วย(monkeypatch):
    replies = iter(["ไม่ใช่ JSON", '{"themes":[],"insights":[{"summary":"จากรอบสอง"}],"connections":[]}'])

    def fake_stream(messages, **kw):
        yield next(replies)

    monkeypatch.setattr(dream, "stream_response", fake_stream)
    r = dream.rem_sleep(_MEMS, provider="gemini")
    assert r["insights"] == ["จากรอบสอง"]
