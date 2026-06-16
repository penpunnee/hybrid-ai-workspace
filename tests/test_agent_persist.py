"""C: agent memory write ต้องผ่าน should_auto_learn gate

คำตอบ agent มาจาก tool real-time เสมอ → ถ้า prompt เป็นงาน realtime/home-tool
(should_auto_learn=False) ต้อง **ไม่** remember() ลง episodic (กันปนเปื้อน volatile),
แต่ยังต้อง save_message + push_working ตามปกติ
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

    def test_remembers_when_gate_true(self):
        with patch("routers.chat.should_auto_learn", return_value=(True, "ok")), \
             patch("routers.chat.save_message", return_value=9), \
             patch("routers.chat.push_working"), \
             patch("routers.chat.remember") as rem:
            mid = persist_agent_turn("kwan", "เมืองหลวงญี่ปุ่นชื่ออะไร", "โตเกียว", "s1")
        rem.assert_called_once()
        assert mid == 9
