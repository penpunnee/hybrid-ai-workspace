"""C: เทิร์น agent ไม่จดลง episodic เลย (เดิม gate ด้วย should_auto_learn · เปลี่ยน 2026-10-04 ต่อ 81)

คำตอบ agent มาจาก tool real-time (หรืออ้างว่าใช้) → จดไว้ = ป้อนของเน่า/ของแต่งให้ตัวเองในอนาคต ·
gate เดิมเช็คคำสะกด จึงหลุดเมื่อพิมพ์ผิด · ความรู้ทั่วไปที่หาจากเน็ตได้ user เคาะ 09-30 ว่าไม่เก็บ ·
ยังต้อง save_message + push_working ตามปกติ
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("UI_PASSWORD", "")

from unittest.mock import patch
from routers.chat import persist_agent_turn


class TestPersistAgentTurnGate:
    def test_skips_remember_when_gate_false(self):
        with patch("routers.chat.should_auto_learn", return_value=(False, "realtime_home_tool")), \
             patch("routers.chat.save_message", return_value=123) as sm, \
             patch("routers.chat.push_working") as pw, \
             patch("routers.chat.remember") as rem:
            mid = persist_agent_turn("kwan", "ปิงเน็ตให้หน่อย", "ออนไลน์หมด", "s1")
        rem.assert_not_called()                 # gate False → ไม่เขียน episodic
        sm.assert_called_once()                  # แต่ยังเซฟ history
        assert pw.call_count == 2                # push_working user+assistant
        assert mid == 123

    def test_never_remembers_even_when_gate_true(self):
        """🔴 prod 10-04 03:37 (devlog ต่อ 81): "เช็คเครื่อข่าย" (สะกดผิด) หลุด gate คำสะกด → (True,'ok') ·
        qwen ไม่เรียก tool แต่ตอบว่า "เพิ่งดึงสถานะสด" → ถูกจดลง episodic → ถูก recall ให้ลอกทุกรอบถัดไป ·
        ตัวกันต้องผูกกับคุณสมบัติ (เป็นเทิร์น agent = ผล tool สด/คำอ้างว่าใช้ tool) ไม่ใช่การสะกดคำ"""
        with patch("routers.chat.should_auto_learn", return_value=(True, "ok")), \
             patch("routers.chat.save_message", return_value=9) as sm, \
             patch("routers.chat.push_working") as pw, \
             patch("routers.chat.remember") as rem:
            mid = persist_agent_turn("kwan", "เช็คเครื่อข่าย", "ขวัญเพิ่งดึงสถานะเครือข่ายสด…", "s1")
        rem.assert_not_called()
        sm.assert_called_once()                  # ประวัติแชทยังบันทึก
        assert pw.call_count == 2                # working memory ของ session ยังได้
        assert mid == 9
