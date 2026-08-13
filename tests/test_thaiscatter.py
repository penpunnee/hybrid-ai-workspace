"""ซ่อมโรคกระจายที่ไม่เริ่มด้วยสระหน้า ("ก ร ะต่าย" · "ข ณ ะ" · "ฝึก ฝ น") — ตระกูลที่ 6

เจอ 2026-08-13 หลังปิดตระกูลสระหน้า: PW เหลือ run สมาชิกเดี่ยว 2-5 ตัว ~2,257 จุด
ที่ **ไม่มีลายเซ็นปลอดภัยเชิง regex** (สมาชิกเป็นพยัญชนะเปล่า/สระตาม/คำจริงปนกัน และ
"ว่า เจ้า" ในบทพูดคือวรรคจริง) ⇒ ต้องใช้ความรู้ระดับคำ: pythainlp newmm + thai_words

หลักการ: หา seed (token สั้น ≤3 ที่ไม่ใช่คำ) → ขยาย region เพื่อนบ้านวรรคเดียว →
ลองทุก variant join/keep → เลือก uncovered ต่ำสุด (เสมอกัน join มากกว่าชนะ ตามปรัชญา
A2 ที่ user เคาะด้วยหู: วรรคปลอมกลางคำร้ายแรงกว่า glue) → ไม่ดีขึ้นไม่แตะ

แยกสองโหมดโดยตั้งใจ: compute (ต้องมี pythainlp — รันนอก prod) ผลิตตำแหน่งวรรคที่ลบ
+ md5 กันข้อความเคลื่อน · apply (ไม่มี dependency — รันในคอนเทนเนอร์ได้) ตรวจแล้วลบ
⇒ prod image ไม่ต้องแบก pythainlp · เทส compute ข้ามอัตโนมัติใน CI (ไม่มี pythainlp)
"""

import importlib.util

import pytest

from utils.thaiscatter import apply_removals, compute_removals, shift_bookmark

# ฝั่ง compute ต้องมี pythainlp (dev/offline เท่านั้น — prod image ไม่แบก) ·
# ฝั่ง apply ต้องรันได้เสมอแม้ใน CI ที่ไม่มี pythainlp — ห้ามใช้ importorskip ระดับโมดูล
requires_dict = pytest.mark.skipif(
    importlib.util.find_spec("pythainlp") is None,
    reason="compute mode ต้องมี pythainlp (dev เท่านั้น)",
)


@requires_dict
class TestComputeFromRealFragments:
    """ทุกเคสคือข้อความจริงจาก reader.db prod (หลังผ่านตัวซ่อมตระกูล 1-5 แล้ว)"""

    @pytest.mark.parametrize(
        "raw, expect, why",
        [
            ("หรือ?” ก ร ะต่ายน้อยพุ่ง เข้าใส่",
             "หรือ?” กระต่ายน้อยพุ่ง เข้าใส่",
             "run กลางคำ + เศษคำติดเพื่อนบ้าน (ะต่ายน้อยพุ่ง)"),
            ("หมึกที่ดูสยดสยอง  ข ณ ะ นั้น สีหน้าของเด็ก",
             "หมึกที่ดูสยดสยอง  ขณะนั้น สีหน้าของเด็ก",
             "ณ เป็นสมาชิก region ได้เมื่อติด seed (ข·ะ)"),
            ("มันได้ฝึก ฝ น อย่างช้าๆ  และมีความ",
             "มันได้ฝึกฝน อย่างช้าๆ  และมีความ",
             "เพื่อนบ้านซ้าย (ฝึก) เข้า region · วรรคจริงก่อน 'อย่าง' ต้องรอด (prosody)"),
            ("ได้เพียงเจ็ดเท่านั้ น หากเจ้าไม่พอใจ",
             "ได้เพียงเจ็ดเท่านั้น หากเจ้าไม่พอใจ",
             "shape ของ xianni: พยัญชนะท้ายคำหลุดก่อนวรรคจริง — วรรคจริงต้องรอด"),
            ("ทหารรับใช้ค น ห นึ่งลงจากรถศึก",
             "ทหารรับใช้คน หนึ่งลงจากรถศึก",
             "สองคำติดกันกระจายพร้อมกัน — ขอบคำตรงรอยต่อ เก็บวรรคได้ (คำจริงทั้งคู่)"),
        ],
    )
    def test_joins_scattered_words(self, raw, expect, why):
        assert apply_removals(raw, compute_removals(raw)) == expect, why

    @pytest.mark.parametrize(
        "text, why",
        [
            ("เขายืนอยู่ ณ ที่นั้น อย่างสงบ",
             "ณ จริง (PW มี 340 จุด) ไม่มี seed ข้างเคียง — ห้ามแตะ"),
            ("ข้ายอมรับ ว่า เจ้า แข็งแกร่ง",
             "คำจริงคั่นวรรคจริงในบทพูด — ไม่มี seed ห้ามแตะ"),
            ("ผู้เยาว์เดินผ่านท้องฟ้า เห็นแสงนุ่มนวล",
             "ประโยคสะอาดปกติ"),
            ("เด็ก ๆ วิ่งเล่นกัน อย่างสนุกสนาน",
             "ๆ ไม่เป็นทั้ง seed และสมาชิก region"),
        ],
    )
    def test_clean_or_ambiguous_text_untouched(self, text, why):
        assert compute_removals(text) == [], why

    def test_known_limitation_newmm_segments_bokwa_as_bo_kwa(self):
        """⚠️ ข้อจำกัดที่รู้และยอมรับ: newmm ตัด 'บอกว่า' เป็น บอ|กว่า (กว่า ยาวกว่า ว่า)
        ⇒ 'บ อ กว่า' ซ่อมได้แค่ 'บอ กว่า' — ขอบคำ (ของ newmm) ตรงรอยต่อพอดีเลยเก็บวรรค
        จะแก้ต้องได้ตัวตัดคำ/พจนานุกรมที่ดีกว่า ไม่ใช่บิด tie-break (จะพังเคสอื่น)"""
        raw = "นั้นเป็นแน่บ อ กว่าเขาไม่มา"
        assert apply_removals(raw, compute_removals(raw)) == "นั้นเป็นแน่บอ กว่าเขาไม่มา"

    def test_no_improvement_means_no_touch(self):
        """ชื่อเฉพาะที่ join แล้ว uncovered ไม่ลด — conservative ปล่อยไว้"""
        text = "เขาชื่อฮ วี น สั้นๆ"
        fixed = apply_removals(text, compute_removals(text))
        assert fixed.replace(" ", "") == text.replace(" ", "")

    def test_only_spaces_removed_invariant(self):
        text = "หิวโหย ก ร ะหายน้ำ และ อ่อนล้า ณ กลางทะเลทราย"
        fixed = apply_removals(text, compute_removals(text))
        assert fixed.replace(" ", "") == text.replace(" ", "")


class TestApplySide:
    """ฝั่ง apply ไม่มี dependency — ต้องปฏิเสธ input ที่ไม่ตรงสัญญาเสมอ"""

    def test_apply_removes_given_space_positions(self):
        assert apply_removals("ก ข ค", [1, 3]) == "กขค"

    def test_apply_rejects_non_space_position(self):
        with pytest.raises(ValueError):
            apply_removals("กขค", [1])

    def test_apply_rejects_out_of_range(self):
        with pytest.raises(ValueError):
            apply_removals("ก ข", [99])

    def test_shift_bookmark_counts_removals_before_pos(self):
        # ลบ 3 ตำแหน่ง: สองตัวอยู่ก่อน pos=10 → ที่คั่นถอย 2
        assert shift_bookmark(10, [2, 7, 15]) == 8
        assert shift_bookmark(0, [2, 7]) == 0
        # ตำแหน่งที่ = pos พอดี ไม่นับ (ยังไม่ได้อ่านถึง)
        assert shift_bookmark(7, [7]) == 7
