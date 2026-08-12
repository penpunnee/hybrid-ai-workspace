"""ซ่อมช่องว่างแทรกจาก PDF (Perfect World) — สูตร ③ "เต็มสูตร" ที่ user เลือกด้วยหู

**โรคนี้คนละตัวกับ PUA** — เจอจากไฟล์จริง 2026-08-10:
`Perfect World โลกอันสมบูรณ์แบบ (จบ).pdf` (21.2M ตัวอักษร) `pypdf` แกะแล้วได้:

    'อ ส ู ร บ ร ร พ ก า ล ป ร า ก ฏ ต ั ว'   ← "อสูรบรรพกาลปรากฏตัว"
    'เผ่าพันธุ ์วิญญาณ'                        ← "เผ่าพันธุ์วิญญาณ"
    'สือฮ่าวเป ็ นตัวเอก'                      ← "สือฮ่าวเป็นตัวเอก"
    'คําขอบคุณ'                                ← "คำขอบคุณ" (ํ+า แยกส่วน)

วัดทั้งเล่ม: ช่องว่างก่อนมาร์ก 200,045 · หลังมาร์ก 377,533 · ช่วงแยกทีละตัวอักษร 26,293
ไม่ซ่อม = TTS หยุดหายใจกลางคำทั้งเล่ม

🔑 **สูตรนี้ไม่ได้ออกแบบจากทฤษฎี — สอบกลับจากไฟล์เสียงที่ user ฟังแล้วเคาะ:**
เซสชัน 2026-08-11 ทำตัวอย่างเสียงหลายสูตรให้ user ฟัง user เลือก v_3 "เต็มสูตร" ·
เซสชัน 2026-08-12 brute-force ลำดับ operation จนได้ **B→N→AM→A1→A2** ที่ reproduce
ไฟล์ v_3 ได้ตรง 860/860 ตัวอักษร (fixture `pw_golden_v3.txt`) — บันทึกเก่าที่เขียนว่า
"สูตร ③ = A1+B" คลาดเคลื่อน ของจริงมี A2 + \n→วรรค + รวม ำ ด้วย

⚠️ fixture มาจากข้อความที่ `pypdf` แกะจากไฟล์จริงทุกตัว (กติกาเดียวกับ `test_thaipdf.py`)
"""

import os

import pytest

from utils.thaipdf import fix_inserted_spaces, has_inserted_spaces

_FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def _read(name: str) -> str:
    with open(os.path.join(_FIX, name), encoding="utf-8") as f:
        return f.read()


class TestGoldenReproduction:
    """ด่านหลัก: ต้องผลิตผลเหมือนไฟล์ที่ user ฟังแล้วเคาะ ทุกตัวอักษร"""

    def test_reproduces_the_exact_text_the_user_approved_by_ear(self):
        raw = _read("pw_raw_slice.txt")
        golden = _read("pw_golden_v3.txt").strip()
        assert fix_inserted_spaces(raw).startswith(golden)


class TestRealFragmentsFromPerfectWorld:
    """แต่ละเคสคือข้อความจริงที่แกะได้ คู่กับสิ่งที่ควรส่งเข้า TTS"""

    @pytest.mark.parametrize(
        "raw, expect, why",
        [
            ("อ ส ู ร บ ร ร พ ก า ล ป ร า ก ฏ ต ั ว",
             "อสูรบรรพกาลปรากฏตัว",
             "B: ช่วงแยกทีละตัวอักษร ≥6 ตัวต้องยุบ (26,293 ช่วงทั้งเล่ม)"),
            ("เผ่าพันธุ ์วิญญาณ",
             "เผ่าพันธุ์วิญญาณ",
             "A1: ช่องว่างก่อนมาร์ก (200,045 จุด)"),
            ("สือฮ่าวเป ็ นตัวเอก",
             "สือฮ่าวเป็นตัวเอก",
             "A1+A2: มาร์กที่มีช่องว่างขนาบสองข้าง"),
            ("ข้าขอกล่าวคําขอบคุณล่วงหน้า",
             "ข้าขอกล่าวคำขอบคุณล่วงหน้า",
             "AM: ํ+า สองตัวต้องรวมเป็น ำ ตัวเดียว"),
            ("เทพารักษ์ ม า\nถึงสถานที่ต้องห้าม",
             "เทพารักษ์ม า ถึงสถานที่ต้องห้าม",
             "ช่วงสั้นกว่าเกณฑ์ B คงไว้ (golden ยืนยัน 'ม า' ไม่ถูกยุบ) · \\n→วรรค · A2 ลบวรรคหลัง ์"),
            ("ล ป ร า ก ฏ ต ั ว  \nเสียงน่าสะพรึงกลัว",
             "ลปรากฏตัว   เสียงน่าสะพรึงกลัว",
             "B ยุบช่วงแยกตัวอักษร แต่วรรคจริงท้ายช่วง (รวม \\n→วรรค) คงอยู่ครบ ไม่ถูกกลืน"),
        ],
    )
    def test_fragment(self, raw, expect, why):
        assert fix_inserted_spaces(raw) == expect, why

    def test_known_limitation_pypdf_vowel_loss_is_not_our_job(self):
        """'จรงๆ' (สระหายจาก pypdf เอง) — สูตรนี้ **ไม่**พยายามเดาสระคืน
        golden ก็ปล่อยไว้เหมือนกัน · เดาสระ = เสี่ยงแก้คำถูกให้ผิด"""
        assert fix_inserted_spaces("ผู้มีความสามารถจรงๆ") == "ผู้มีความสามารถจรงๆ"


class TestCleanTextSafety:
    """ข้อความสะอาดต้องรอดจากตัวซ่อม — โดนตัวซ่อมทำพังคือแย่กว่าไม่ซ่อม"""

    @pytest.mark.parametrize(
        "text",
        [
            "ผู้เยาว์เดินผ่านท้องฟ้า เห็นแสงนุ่มนวล",
            "ฉันไปตลาด ซื้อของหลายอย่าง เจอเพื่อนเก่า",
        ],
    )
    def test_normal_thai_with_real_phrase_spaces_is_untouched(self, text):
        """วรรคจริงหลังตัวอักษรที่ไม่ใช่มาร์ก (า ว ง ด ฯลฯ) ต้องอยู่ครบ"""
        assert fix_inserted_spaces(text) == text

    def test_documented_tradeoff_space_after_mark_final_word_is_swallowed(self):
        """⚠️ trade-off ที่รู้และยอมรับ: A2 กลืนวรรคจริงหลังคำที่ลงท้ายด้วยมาร์ก

        'อากาศดี ฉัน' → 'อากาศดีฉัน' (ี เป็นมาร์ก) — user ฟังผลจริงเทียบหลายสูตร
        แล้วเลือกแบบนี้: TTS ไทยตัดคำเองได้ แต่วรรคปลอมกลางคำมันช่วยตัวเองไม่ได้
        ถ้าจะ "แก้" เทสนี้ให้วรรครอด ต้องกลับไปเทสเสียงกับ user ใหม่ทั้งชุดก่อน
        """
        assert fix_inserted_spaces("วันนี้อากาศดี ฉันไปตลาด") == "วันนี้อากาศดีฉันไปตลาด"

    def test_empty_and_none_safe(self):
        assert fix_inserted_spaces("") == ""

    def test_idempotent(self):
        """ซ่อมซ้ำต้องไม่เปลี่ยนอะไรเพิ่ม — กันเรียกซ้อนจากหลายชั้นของ pipeline"""
        raw = _read("pw_raw_slice.txt")
        once = fix_inserted_spaces(raw)
        assert fix_inserted_spaces(once) == once


class TestDiseaseDetector:
    """ตัวตัดสินว่าเล่มไหนควรโดนสูตร — เล่มสะอาดต้องไม่โดน A2 กลืนวรรคจริงฟรีๆ

    วัดจากของจริงทั้งสองฝั่ง (2026-08-12):
      Perfect World: ช่องว่างก่อนมาร์ก 0.94% ของตัวอักษร
      Xian Ni (ใน prod, ผ่าน fix_thai_pua แล้ว): 0.0000% · B runs = 0
    ห่างกันเกินพันเท่า ⇒ ขีดแบ่ง 0.1% อยู่กลางทุ่งโล่ง
    """

    def test_perfect_world_raw_is_detected(self):
        assert has_inserted_spaces(_read("pw_raw_slice.txt")) is True

    def test_fixed_text_is_no_longer_detected(self):
        assert has_inserted_spaces(_read("pw_golden_v3.txt")) is False

    def test_clean_thai_book_is_not_detected(self):
        """ข้อความสไตล์ xianni (สะอาดหลังซ่อม PUA) — วรรคจริงหลังมาร์กมีปกติ
        แต่ไม่ถึงขีด ห้าม false positive ไม่งั้นเล่มสะอาดโดนกลืนวรรคทั้งเล่ม"""
        clean = "ความคิดหวังหลินเคลื่อนผ่านผู้เยาว์ ไม่นานก็มาถึง ฝ่ามือฟาดลงมา " * 50
        assert has_inserted_spaces(clean) is False

    def test_empty_is_not_detected(self):
        assert has_inserted_spaces("") is False
