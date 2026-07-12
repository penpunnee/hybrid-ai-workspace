"""Tests for dream theme classification — Skill vs Memory (User Facts)

หลักการ:
- Procedural theme ("วิธี X", "how to X") → "skill"
- Personal context ("ชอบ", "กำลังทำ", "โปรเจกต์ของปอย") → "memory"
- Ambiguous → "both" (safe default)
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.dream import classify_theme


class TestClassifyTheme:
    def test_procedural_th_returns_skill(self):
        assert classify_theme("วิธีติดตั้ง Docker", "") == "skill"

    def test_procedural_how_to_returns_skill(self):
        assert classify_theme("how to debug FastAPI", "") == "skill"

    def test_procedural_steps_returns_skill(self):
        assert classify_theme("ขั้นตอน deploy บน NAS", "") == "skill"

    def test_procedural_in_summary_returns_skill(self):
        assert classify_theme("docker setup", "วิธีรัน container บน NAS คือ...") == "skill"

    def test_personal_preference_returns_memory(self):
        assert classify_theme("ชอบ dark mode", "") == "memory"

    def test_personal_working_on_returns_memory(self):
        assert classify_theme("กำลังทำ phrae data map", "") == "memory"

    def test_personal_project_returns_memory(self):
        assert classify_theme("โปรเจกต์ ScanDoc iOS", "") == "memory"

    def test_personal_user_mentioned_returns_memory(self):
        assert classify_theme("ปอยใช้ Mac M1", "") == "memory"

    def test_personal_in_summary_returns_memory(self):
        assert classify_theme("user preference", "พี่ปอยชอบตอบกระชับ ไม่อยากได้ bullet เยอะ") == "memory"

    def test_ambiguous_returns_both(self):
        assert classify_theme("Python", "เรื่องทั่วไปเกี่ยวกับ Python") == "both"

    def test_empty_returns_both(self):
        assert classify_theme("", "") == "both"

    def test_case_insensitive(self):
        assert classify_theme("HOW TO setup Redis", "") == "skill"
