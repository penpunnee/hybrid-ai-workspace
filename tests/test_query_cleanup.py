"""เส้นสำรองที่ไม่พึ่ง LLM สำหรับแปลง "ประโยคสั่งงาน" → "คำค้น"

**ทำไมต้องมี** (prod 2026-08-03): `search_web()` ได้ prompt ดิบทั้งประโยคเป็นคำค้น
`'ช่วยค้นในเน็ตให้หน่อย ตอนนี้ Python เวอร์ชันเสถียรล่าสุดคือเวอร์ชันอะไร แล้วอ้างอิงแหล่งที่มาด้วย'`
→ DDG คืนเว็บสแปมไทย (รวมเว็บโป๊) → ฉีดเข้า context + ขึ้นจอเป็น citation

ต้นเหตุ: `rewrite_query()` เป็น LLM-based และ **ตายเงียบมาตั้งแต่เปลี่ยนไปใช้ Qwen3.5**
พิสูจน์ในคอนเทนเนอร์ prod 2026-08-03 — ยิงตรงไป LM Studio:

    max_tokens=200  finish_reason=length  content=''  reasoning_content='Thinking Process:...'
    max_tokens=800  finish_reason=length  content=''  reasoning_content='Thinking Process:...'

โมเดลเทงบทั้งหมดลง reasoning ไม่เคยปล่อย content · เพิ่ม max_tokens ไม่ช่วย และ
**ปิด thinking ของ Qwen ผ่าน API ไม่ได้** (บันทึกไว้ใน CLAUDE.md อยู่แล้ว)
→ เส้นสำรองต้องไม่พึ่ง LLM เลย ไม่งั้นตอน Gemini quota หมด (ซึ่งคือตอนที่ fallback ทำงานพอดี)
จะไม่มีอะไรทำงานสักตัว
"""

from utils.query_rewrite import clean_query


class TestStripsInstructionFiller:
    def test_the_actual_prod_failure_case(self):
        """เคสจริงที่ทำให้เจอบั๊ก — ต้องเหลือแก่นที่ค้นได้"""
        out = clean_query(
            "ช่วยค้นในเน็ตให้หน่อย ตอนนี้ Python เวอร์ชันเสถียรล่าสุดคือเวอร์ชันอะไร "
            "แล้วอ้างอิงแหล่งที่มาด้วย"
        )
        assert "Python" in out
        assert "เวอร์ชัน" in out
        # คำสั่งงานต้องหายไป — พวกนี้คือสิ่งที่ทำให้ search engine หลุดโฟกัส
        for filler in ("ช่วยค้นในเน็ต", "ให้หน่อย", "อ้างอิงแหล่งที่มา"):
            assert filler not in out, f"ยังเหลือคำสั่งงาน {filler!r} ใน {out!r}"

    def test_common_thai_openers(self):
        assert clean_query("ช่วยหาข้อมูล ราคาทองคำวันนี้ ให้หน่อยครับ").startswith("ราคาทองคำ")
        assert "เช็คเน็ต" not in clean_query("เช็คเน็ตให้หน่อย อากาศแพร่พรุ่งนี้")

    def test_english_openers(self):
        out = clean_query("please search the web for Synology DS923+ specs")
        assert "Synology DS923+ specs" in out
        assert "please search" not in out.lower()


class TestDoesNotDamageGoodQueries:
    """คำค้นที่ดีอยู่แล้วต้องไม่ถูกแตะ — กันการแก้ที่สร้างปัญหาใหม่"""

    def test_keyword_query_unchanged(self):
        for q in ("Python latest stable version", "Synology DS923+ specs", "ราคาทองคำวันนี้"):
            assert clean_query(q) == q

    def test_never_returns_empty(self):
        """ถ้าตัดจนเหลือว่าง ต้องคืนของเดิม — คำค้นห่วยยังดีกว่าไม่มีคำค้น"""
        for q in ("ช่วยหน่อย", "ค้นให้ที", "search"):
            assert clean_query(q).strip() != ""

    def test_handles_empty_and_whitespace(self):
        assert clean_query("") == ""
        assert clean_query("   ") .strip() == ""


class TestUsedByRewritePipeline:
    """rewrite ที่พึ่ง LLM ล้ม → ต้องตกมาที่ clean_query ไม่ใช่ prompt ดิบ"""

    def test_rewrite_falls_back_to_cleaned_query(self, monkeypatch):
        import utils.query_rewrite as qr

        # จำลอง LLM ตายแบบเดียวกับ prod — ต้อง patch `_call_llm` ตัวจริง
        # (เวอร์ชันแรกของเทสนี้ patch ชื่อที่ไม่มีอยู่ด้วย raising=False → เทสผ่านเพราะ
        #  LLM ต่อไม่ติดในเครื่องเทส ไม่ใช่เพราะโค้ดถูก = ผ่านด้วยเหตุผลผิด)
        called = {"n": 0}

        def fake_call_llm(q):
            called["n"] += 1
            return None

        monkeypatch.setattr(qr, "_call_llm", fake_call_llm)
        qr.clear_cache()

        rw = qr.rewrite_query("ช่วยค้นในเน็ตให้หน่อย ตอนนี้ Python เวอร์ชันเสถียรล่าสุดคือเวอร์ชันอะไร")
        qr.clear_cache()

        assert called["n"] == 1, "ไม่ได้เดินผ่าน _call_llm จริง — เทสนี้ไม่ได้วัดเส้น fallback"
        assert "ช่วยค้นในเน็ต" not in rw.rewritten, (
            f"LLM ล้มแล้วยังส่ง prompt ดิบไปค้น: {rw.rewritten!r}"
        )
        assert "Python" in rw.rewritten
        assert rw.used_llm is False
