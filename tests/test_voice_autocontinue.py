"""เล่าต่ออัตโนมัติ — user เคาะ 2026-08-09: "ถามบ่อยเกิน ต้องมาคอยตอบว่าต่อไปตลอด"

**ทำไมต้องแก้ที่ server ไม่ใช่ที่ prompt:**
`_VOICE_MODE` สั่งห้ามไว้ตรงๆ อยู่แล้วว่า "ห้ามถามขออนุญาตกลางเรื่อง เช่น
'จะให้เล่าต่อเลยไหมคะ' 'อยากฟังต่อไหมคะ'" — **แล้วโมเดลพูดประโยคที่อยู่ในบัญชีห้าม
นั้นคำต่อคำ** (prod 08-09 18:30:04 และ 18:31:39 "อยากให้เล่าต่อเลยไหมคะ" ·
13:44:27 "อยากฟังต่อเลยไหมคะ")

นับจริงช่วง 18:20–18:37: ขวัญพูด 26 เทิร์น **จบด้วยคำถาม 16 = 62%**
· อินพุตที่ถอดเป็นไทยชัด → ถาม 11/20 = 55% · อินพุตที่ถอดมั่วเป็นภาษาอื่น → 5/6 = 83%
⇒ เสียงถอดมั่วเป็น**ตัวเร่ง** แต่ต่อให้ได้ยินชัดมันก็ยังถามอยู่ดี = ไม่ใช่ต้นเหตุ

🔑 **บทเรียน: โมเดลละเมิดคำสั่งที่เขียนชัดอยู่แล้ว ⇒ เขียนให้ชัดกว่าเดิมคือการดัน
ลูกโยกที่ไม่ได้ต่อกับอะไร** ต้องย้ายไปหาคันโยกที่บังคับได้จริง (ฝั่ง server)

⚠️ **ข้อจำกัด:** ไฟล์นี้เทส *กฎการตัดสินใจ* เท่านั้น — พิสูจน์ไม่ได้ว่าโมเดลจะเล่าต่อ
จริงเมื่อได้รับข้อความ ตัวชี้ขาดคือหูของ user
"""

import pytest

from utils.voice import AUTO_CONTINUE_MAX, AUTO_CONTINUE_TEXT, should_auto_continue


class TestAutoContinueRules:
    def test_off_by_default_state(self):
        """ปิดอยู่ → ไม่ยิงอะไรเลย แม้เงื่อนไขอื่นครบ"""
        assert should_auto_continue(enabled=False, user_spoke=False, count=0) is False

    def test_fires_when_model_finished_and_user_stayed_quiet(self):
        assert should_auto_continue(enabled=True, user_spoke=False, count=0) is True

    def test_does_not_fire_when_user_spoke_in_that_turn(self):
        """พี่ปอยสั่งเองแล้ว — ยิง "เล่าต่อ" ทับจะกลายเป็นเถียงกับคำสั่งของ user

        นี่คือเบรกเส้นหลัก: ตราบใดที่ user ยังพูด ระบบจะไม่แทรกอะไรเลย
        """
        assert should_auto_continue(enabled=True, user_spoke=True, count=0) is False

    def test_stops_at_the_cap(self):
        """เพดานกันวิ่งหนี — โมเดลตอบสั้นรัวๆ ได้ ถ้าไม่มีเพดานจะยิงไม่หยุดและเผาโควตา"""
        assert should_auto_continue(enabled=True, user_spoke=False, count=AUTO_CONTINUE_MAX) is False

    def test_still_fires_one_step_below_the_cap(self):
        """กลุ่มควบคุมของเพดาน — กันเขียน `>=` เป็น `>` แล้วเกินไปหนึ่งครั้งโดยไม่มีใครรู้"""
        assert should_auto_continue(enabled=True, user_spoke=False, count=AUTO_CONTINUE_MAX - 1) is True

    def test_cap_is_not_absurdly_large(self):
        """เพดานที่ใหญ่เกินไป = ไม่มีเพดาน · ที่เล็กเกินไป = ยังต้องคอยพิมพ์อยู่ดี"""
        assert 5 <= AUTO_CONTINUE_MAX <= 50


class TestAutoContinueMessage:
    """ข้อความที่ยิงต้องสู้กับพฤติกรรมที่วัดได้จริง ไม่ใช่แค่คำว่า "ต่อ" """

    def test_tells_it_to_continue(self):
        assert "เล่าต่อ" in AUTO_CONTINUE_TEXT

    def test_forbids_asking_back(self):
        """ถ้าไม่สั่งห้ามถาม มันจะจบเทิร์นด้วยคำถามอีก แล้วเราก็ยิงต่อวนไปจนชนเพดาน"""
        assert "ห้ามถาม" in AUTO_CONTINUE_TEXT

    def test_forbids_recapping(self):
        """วัดจาก prod: มันชอบทวนของเดิมก่อนเล่าต่อ ทำให้เนื้อเรื่องเดินช้ามาก"""
        assert "ห้ามทวน" in AUTO_CONTINUE_TEXT

    def test_is_short(self):
        """ยิงทุก turn — ยาวไปคือเปลืองโควตาคูณจำนวนครั้ง"""
        assert len(AUTO_CONTINUE_TEXT) < 200


class TestServerWiring:
    """กันกรณี "ฟังก์ชันถูก แต่ไม่มีใครเรียก" — เทสข้างบนเขียวได้ทั้งที่ฟีเจอร์ตายสนิท"""

    @pytest.fixture()
    def voice_handler(self):
        from pathlib import Path

        src = (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")
        ws = src[src.index('@app.websocket("/ws/voice/'):]
        return ws[: ws.index("\n@app.")] if "\n@app." in ws else ws

    def test_handler_calls_the_decision_function(self, voice_handler):
        assert "should_auto_continue(" in voice_handler

    def test_handler_accepts_the_toggle_from_client(self, voice_handler):
        assert "autocontinue" in voice_handler, "client เปิดสวิตช์แล้ว server ไม่มีที่รับ"

    def test_handler_resets_the_counter_when_user_speaks(self, voice_handler):
        """ไม่รีเซ็ต = คุยยาวๆ ครั้งเดียวก็ชนเพดานถาวร แล้วฟีเจอร์ตายเงียบทั้ง session

        🔴 **เขียนครั้งแรกเป็น `"auto_count = 0" in voice_handler` แล้วผ่านฟรี** —
        เพราะตัวรับสวิตช์ก็มี `auto_count = 0` อยู่แล้วอีกที่ · ถอดตัวรีเซ็ตใน
        `send_loop` ทิ้งทั้งบรรทัดแล้วเทสยังเขียว (mutation จับไม่ได้)
        ⇒ ต้อง **นับ** ไม่ใช่ถามว่ามีไหม (เข้าเกณฑ์ "assert count == expect" ใน CLAUDE.md)

        3 ที่ที่ต้องมี: (1) ประกาศตัวแปรตอนต้น (2) ตอนเปิด/ปิดสวิตช์ (3) ตอน user พูด
        · ตอนเขียนเทสนี้ผมเดาว่า 2 — การนับจริงจับได้ว่าลืมนับตัวประกาศ
        """
        assert voice_handler.count("auto_count = 0") == 3, (
            "ต้องมี 3 ที่ — ประกาศ · ตอนสลับสวิตช์ · ตอน user พูด"
        )
        # ตัวรีเซ็ตต้องอยู่ "หลัง" จุดที่เซฟ transcript ของ user = อยู่ในสาย turn_complete จริง
        after_save = voice_handler[voice_handler.index('_save_msg(asst_name, "user"'):]
        assert "auto_count = 0" in after_save, "ตัวรีเซ็ตไม่ได้อยู่ในสายที่ user พูดจริง"
