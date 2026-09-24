"""teach() ต้องบันทึก fact ครั้งเดียวต่อเทิร์น + pattern อังกฤษต้อง anchor (audit 2026-09-24 ข้อ 10)

`routers/chat.py` เรียก `teach()` 2 รอบ: ก่อนตอบ (`:159` ตรวจ signal ให้ทันเทิร์นนี้) และหลังตอบ
ในเธรด (`:621` มี prev_answer สำหรับเส้น correction) — prompt ที่เข้า `detect_teaching` จึงถูก
`save_entry` ลง `user_facts` **2 doc** · ดีไซน์ 2 รอบคงไว้ (เทส test_test_request_header ตรึง)
ปิดแค่การ save ซ้ำ: รอบหลังข้ามเมื่อรอบแรกบันทึกแล้ว

regex: `note`/`remember`/`prefer` ไม่ anchor → "ช่วยดู note ใน obsidian หน่อย" ถูกเก็บเป็น fact
verified 0.95 แล้วฉีดทุก prompt (รันจริง) · anchor ที่ `^` เท่านั้น (`\b` ไม่ช่วย — ช่องว่างก่อนคำก็เป็น boundary)
· ไม่แตะ pattern ไทย/`แก้ไข` — prompt จริง 600 ข้อ = 0 hit ไม่มีหลักฐานให้จูน
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from memory.teach import detect_teaching, process_teaching


# ---------- regex anchor ----------

@pytest.mark.parametrize("text", [
    "ช่วยดู note ใน obsidian หน่อย",
    "please remember to check the logs later",
    "which one do you prefer for the config file",
])
def test_คำอังกฤษกลางประโยคต้องไม่ถูกเก็บเป็น_fact(text):
    assert detect_teaching(text) == (None, "")


@pytest.mark.parametrize("text,expected_type", [
    ("note: ประชุมทีมทุกวันจันทร์ 9 โมง", "fact"),
    ("remember: NAS ชื่อ DS923+", "fact"),
    ("prefer ตอบกระชับ ไม่ใช้ bullet เยอะ", "preference"),
    ("  Remember that the router is ASUS", "fact"),
    ("จำไว้ว่า NAS ชื่อ DS923+", "fact"),
])
def test_ขึ้นต้นประโยคยังเก็บได้เหมือนเดิม(text, expected_type):
    knowledge, mem_type = detect_teaching(text)
    assert knowledge and mem_type == expected_type


# ---------- ไม่ save ซ้ำ ----------

def _two_rounds(prompt: str):
    """จำลองลำดับเรียกจริงของ routers/chat.py: รอบแรกไม่มี prev_answer · รอบหลังมี"""
    saved = []
    with patch("memory.teach.save_entry", side_effect=lambda e, collection_name=None: saved.append(e.content) or True), \
         patch("memory.teach.update_confidence"):
        first = process_teaching("kwan", prompt)
        if not first:                       # กติกาใหม่ที่ chat.py ต้องทำ: ข้ามรอบหลังเมื่อรอบแรกบันทึกแล้ว
            process_teaching("kwan", prompt, ai_response="ตอบ", prev_answer="ตอบเก่า")
    return saved


def test_fact_ถูกบันทึกครั้งเดียวจากสองรอบ():
    assert _two_rounds("จำไว้ว่า NAS ชื่อ DS923+") == ["NAS ชื่อ DS923+"]


def test_correction_ยังเดินได้ในรอบหลัง():
    """กลุ่มควบคุม — prompt ที่ไม่ใช่ fact ต้องไปถึงรอบหลังซึ่งมี prev_answer (เส้น correction)"""
    with patch("memory.teach.save_entry", return_value=True) as se, \
         patch("memory.teach.update_confidence") as uc, \
         patch("memory.teach.build_correction_record", return_value="เราเตอร์คือ ASUS"):
        first = process_teaching("kwan", "ไม่ใช่ละ เราเตอร์คือ ASUS ต่างหาก")
        assert first is False
        second = process_teaching("kwan", "ไม่ใช่ละ เราเตอร์คือ ASUS ต่างหาก", ai_response="ตอบ", prev_answer="TP-Link")
    assert second is True and uc.called and se.call_count == 1


# ---------- router: ข้ามเธรดรอบหลังเมื่อรอบแรกบันทึกแล้ว ----------

def _post_with_teach_result(monkeypatch, result: bool):
    import routers.chat as chatmod
    from fastapi.testclient import TestClient
    from server import app

    class _Thread:
        instances = []

        def __init__(self, target=None, daemon=None, **k):
            self.target = target
            _Thread.instances.append(self)

        def start(self):
            pass

    _Thread.instances = []
    monkeypatch.setattr(chatmod, "threading", SimpleNamespace(Thread=_Thread))
    with patch("routers.chat.stream_response") as ms, \
         patch("routers.chat.save_message", return_value=1), \
         patch("routers.chat.remember"), \
         patch("routers.chat.teach", return_value=result) as mt:
        ms.return_value = iter(["ก" * 150])
        r = TestClient(app).post("/api/chat", json={"assistant": "kwan", "session_id": "s1", "prompt": "จำไว้ว่า x"})
        _ = r.text
    return r, mt, {t.target.__name__ for t in _Thread.instances if t.target}


def test_router_รอบแรกบันทึกแล้ว_ต้องไม่สปอนเธรด_teach(monkeypatch):
    r, mt, spawned = _post_with_teach_result(monkeypatch, True)
    assert r.status_code == 200 and mt.call_count == 1
    assert "_teach" not in spawned, f"บันทึกไปแล้วยัง spawn รอบหลัง = save ซ้ำ ({spawned})"


def test_router_รอบแรกไม่ได้บันทึก_ต้องสปอนเธรด_teach(monkeypatch):
    r, mt, spawned = _post_with_teach_result(monkeypatch, False)
    assert r.status_code == 200 and mt.call_count == 1
    assert "_teach" in spawned, f"ดีไซน์ 2 รอบต้องคงไว้ ({spawned})"
