"""Tests for memory/correction.py — แปลงการแก้ไขของ user เป็นข้อเท็จจริงที่อ่านรู้เรื่อง

ปัญหาที่แก้: เดิมเก็บข้อความดิบของ user ลง `user_facts` ตรงๆ
    "[การแก้ไข] ผิดแล้ว ds923+ ต่างหาก"
ซึ่งไม่มีบริบทว่า ds923+ คืออะไร — และก้อนนี้ถูกฉีดเข้า context **ทุก prompt**
ตลอดไป จึงต้องเป็นประโยคที่อ่านแล้วเข้าใจได้โดยไม่ต้องมีบทสนทนาประกอบ

ออกแบบตามที่ตกลง: ให้ LLM สกัดประโยคสมบูรณ์ โดยป้อน *คำตอบที่ผิด* เป็นบริบท
(ซึ่งเป็นตัวที่บอกว่า "ds923+" หมายถึงอะไร)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.correction import build_correction_record

WRONG = "NAS ที่บ้านของพี่ปอยคือ Synology DS918+ ครับ ติดตั้งอยู่ในห้องทำงาน"
FIX = "ผิดแล้ว ds923+ ต่างหาก"


class TestExtractorIsUsedWhenItWorks:
    def test_uses_extracted_sentence(self):
        record = build_correction_record(FIX, WRONG, extractor=lambda c, w: "NAS ที่บ้านคือ Synology DS923+")
        assert record == "NAS ที่บ้านคือ Synology DS923+"
        assert "ผิดแล้ว" not in record, "ต้องเป็นข้อเท็จจริง ไม่ใช่ประโยคบ่น"

    def test_extractor_receives_both_correction_and_wrong_answer(self):
        seen = {}

        def spy(correction, wrong):
            seen["correction"], seen["wrong"] = correction, wrong
            return "ข้อเท็จจริงที่สกัดได้"

        build_correction_record(FIX, WRONG, extractor=spy)
        assert seen["correction"] == FIX
        assert seen["wrong"] == WRONG, "คำตอบที่ผิดคือบริบทเดียวที่บอกว่า ds923+ คืออะไร"


class TestNeverLosesTheCorrection:
    """กฎเหล็ก: LLM ล้มยังไงก็ห้ามทำให้ข้อมูลที่ user อุตส่าห์แก้ให้หายไป

    บทเรียนที่ใช้ซ้ำจาก audit: "ล้มเหลว → ยอด 0" — ทางที่ผิดพลาดต้องคืนของที่ใช้ได้
    ไม่ใช่คืนค่าว่างที่หน้าตาเหมือนสำเร็จ
    """

    def test_extractor_raises_falls_back_to_raw(self):
        def boom(c, w):
            raise RuntimeError("LM Studio ล่ม")

        record = build_correction_record(FIX, WRONG, extractor=boom)
        assert "ds923+" in record

    def test_extractor_returns_none_falls_back_to_raw(self):
        record = build_correction_record(FIX, WRONG, extractor=lambda c, w: None)
        assert "ds923+" in record

    def test_no_extractor_at_all_still_produces_record(self):
        record = build_correction_record(FIX, WRONG, extractor=None)
        assert "ds923+" in record

    def test_fallback_pairs_wrong_answer_for_context(self):
        """fallback ต้องแนบคำตอบที่ผิดไปด้วย ไม่งั้นก็ไม่มีบริบทเหมือนเดิม"""
        record = build_correction_record(FIX, WRONG, extractor=None)
        assert "DS918+" in record, "ต้องมีคำตอบที่ผิดเป็นบริบท"


class TestRejectsGarbageFromLLM:
    """ของที่หลุด filter นี้จะอยู่ใน context ทุก prompt ตลอดไป — ต้องเข้มกว่าปกติ"""

    def test_rejects_too_short(self):
        record = build_correction_record(FIX, WRONG, extractor=lambda c, w: "ok")
        assert "ds923+" in record, "ผลสั้นเกินไป = ใช้ไม่ได้ ต้อง fallback"

    def test_rejects_refusal_text(self):
        record = build_correction_record(
            FIX, WRONG, extractor=lambda c, w: "ขอโทษครับ ไม่สามารถช่วยเหลือในกรณีนี้ได้"
        )
        assert "ds923+" in record

    def test_rejects_error_prefix(self):
        record = build_correction_record(FIX, WRONG, extractor=lambda c, w: "⚠️ เกิดข้อผิดพลาด")
        assert "ds923+" in record

    def test_rejects_skip_marker(self):
        record = build_correction_record(FIX, WRONG, extractor=lambda c, w: "SKIP ไม่มีข้อเท็จจริงให้สกัด")
        assert "ds923+" in record


class TestRecordStaysBounded:
    def test_output_is_capped(self):
        """เข้า context ทุก prompt — ยาวเกินไปกินที่ของอย่างอื่น"""
        record = build_correction_record("แก้ให้ด้วย " + "ก" * 5000, "ค" * 5000, extractor=None)
        assert len(record) <= 600

    def test_handles_empty_wrong_answer(self):
        record = build_correction_record(FIX, "", extractor=None)
        assert "ds923+" in record

    def test_blank_correction_returns_empty(self):
        assert build_correction_record("", WRONG, extractor=None) == ""
        assert build_correction_record("   ", "", extractor=None) == ""


class TestLastAssistantAnswer:
    """helper ที่ chat.py ใช้ดึง 'คำตอบที่ผิด' ออกจาก working memory

    ต้องเรียก **ก่อน** push เทิร์นปัจจุบัน ไม่งั้นจะได้คำตอบของเทิร์นนี้เอง
    """

    def test_returns_latest_assistant_message(self):
        from memory.correction import last_assistant_answer

        buf = [
            {"role": "user", "content": "NAS รุ่นอะไร"},
            {"role": "assistant", "content": "DS918+ ครับ"},
        ]
        assert last_assistant_answer(buf) == "DS918+ ครับ"

    def test_skips_trailing_user_messages(self):
        from memory.correction import last_assistant_answer

        buf = [
            {"role": "assistant", "content": "DS918+ ครับ"},
            {"role": "user", "content": "ผิดแล้ว"},
        ]
        assert last_assistant_answer(buf) == "DS918+ ครับ"

    def test_returns_empty_when_no_assistant_turn(self):
        from memory.correction import last_assistant_answer

        assert last_assistant_answer([{"role": "user", "content": "สวัสดี"}]) == ""
        assert last_assistant_answer([]) == ""
        assert last_assistant_answer(None) == ""


class TestCleanExtraction:
    """ทำความสะอาดผลดิบจาก LLM ก่อนเอาไปใช้

    เจอจริงบน prod (2026-08-02): Qwen3.5 ปิด thinking ผ่าน API ไม่ได้ →
    max_tokens ถูก reasoning trace กินหมด ได้ `<think>...` ที่ยังไม่ปิดกลับมา
    พอตัด think tag แบบ non-greedy ก็ไม่แมตช์อะไรเลย → เหลือข้อความครุ่นคิดล้วน
    ที่เกือบถูกเก็บเป็น "ข้อเท็จจริง"
    """

    def test_strips_closed_think_block(self):
        from memory.correction import clean_extraction

        assert clean_extraction("<think>ครุ่นคิด</think>NAS ที่บ้านคือ DS923+") == "NAS ที่บ้านคือ DS923+"

    def test_unterminated_think_block_is_rejected(self):
        from memory.correction import clean_extraction

        assert clean_extraction("<think>กำลังคิดว่าผู้ใช้หมายถึงอะไร แล้วก็ยังคิดไม่จบ") is None

    def test_strips_leading_arrow(self):
        from memory.correction import clean_extraction

        assert clean_extraction("→ NAS ที่บ้านคือ DS923+") == "NAS ที่บ้านคือ DS923+"

    def test_blank_returns_none(self):
        from memory.correction import clean_extraction

        assert clean_extraction("") is None
        assert clean_extraction("   \n ") is None
        assert clean_extraction(None) is None
