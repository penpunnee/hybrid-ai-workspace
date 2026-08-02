"""Tests for scripts/clean_episodic.py — ล้าง episodic memory ที่เน่าแล้ว (backlog ข้อ 14)

หลักการที่ต่างจาก lessons/skills: **ห้ามล้างยกคลัง** — episodic ควรเป็นบันทึก
บทสนทนาตามหน้าที่ของมัน ลบเฉพาะที่พิสูจน์แล้วว่าเป็นโทษ (ข้อมูลสดหมดอายุ /
ข้อความ error) โดยใช้ `should_remember()` ตัวเดียวกับ gate ที่กันของใหม่ไม่ให้เข้า
— เกณฑ์เข้ากับเกณฑ์ออกต้องเป็นตัวเดียวกัน ไม่งั้นคลังจะเพี้ยนอีกในอนาคต
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from scripts.clean_episodic import classify_doc, split_qa


class TestSplitQA:
    def test_parses_standard_format(self):
        assert split_qa("Q: ราคาทอง\nA: 72,100 บาท") == ("ราคาทอง", "72,100 บาท")

    def test_answer_may_span_multiple_lines(self):
        doc = "Q: ขวัญ\nA: บรรทัดแรก\nบรรทัดสอง\nQ: ไม่ใช่หัวข้อใหม่"
        prompt, response = split_qa(doc)
        assert prompt == "ขวัญ"
        assert response.startswith("บรรทัดแรก")
        assert "ไม่ใช่หัวข้อใหม่" in response, "ห้ามตัดที่ 'Q:' ที่โผล่กลางคำตอบ"

    def test_empty_prompt_still_parses(self):
        """doc ที่ Q ว่าง มีจริงบน prod (2 รายการ) — ต้อง parse ได้ ไม่ใช่ตกเป็น unparsed"""
        assert split_qa("Q: \nA: สวัสดีค่ะ") == ("", "สวัสดีค่ะ")

    def test_empty_answer_still_parses(self):
        assert split_qa("Q: เล่าเรื่องตลก\nA: ") == ("เล่าเรื่องตลก", "")

    def test_returns_none_for_unknown_shape(self):
        assert split_qa("ข้อความอิสระที่ไม่มีรูปแบบ Q/A") is None
        assert split_qa("") is None


class TestClassifyDoc:
    def test_keeps_ordinary_conversation(self):
        keep, reason = classify_doc("Q: อธิบาย FastAPI dependency injection\nA: FastAPI ใช้ Depends() เพื่อ...")
        assert keep is True
        assert reason == "ok"

    def test_drops_stale_realtime_data(self):
        keep, reason = classify_doc("Q: ราคาทองวันนี้\nA: ทองคำแท่งขายออก 72,100 บาท")
        assert keep is False
        assert reason == "realtime_query"

    def test_drops_error_response(self):
        keep, reason = classify_doc("Q: คำตอบละ\nA: ขอโทษครับ/ค่ะ แต่ไม่สามารถช่วยเหลือในกรณีนี้ได้")
        assert keep is False
        assert reason == "error_response"

    def test_drops_empty_answer(self):
        keep, reason = classify_doc("Q: เล่าเรื่องตลกสั้นๆ\nA: ")
        assert keep is False
        assert reason == "empty_response"

    def test_unparsed_doc_is_kept_not_deleted(self):
        """กฎความปลอดภัย: อะไรที่อ่านไม่ออก = ไม่ลบ

        สคริปต์ลบข้อมูล prod ที่กู้ยาก — ความไม่แน่ใจต้องเอียงไปทาง 'เก็บไว้' เสมอ
        """
        keep, reason = classify_doc("รูปแบบแปลกที่ยังไม่เคยเจอ")
        assert keep is True
        assert reason == "unparsed"

    @pytest.mark.parametrize("doc", ["", None])
    def test_blank_input_is_kept(self, doc):
        keep, reason = classify_doc(doc)
        assert keep is True
