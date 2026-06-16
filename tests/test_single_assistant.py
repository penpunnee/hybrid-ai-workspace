"""เหลือขวัญตัวเดียว — ASSISTANTS เหลือ kwan ตัวเดียว, default = kwan

ระบบ data-driven จาก ASSISTANTS ทั้ง backend (/api/config, chat/agent default)
และ frontend (config.assistants[]) — ลบ entry อื่นออกแล้วต้องเหลือขวัญ
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("UI_PASSWORD", "")

from assistants.config import ASSISTANTS


class TestSingleAssistant:
    def test_only_kwan_remains(self):
        slugs = [cfg["slug"] for cfg in ASSISTANTS.values()]
        assert slugs == ["kwan"]

    def test_default_assistant_is_kwan(self):
        # chat/agent default = list(ASSISTANTS.keys())[0]
        first_name = list(ASSISTANTS.keys())[0]
        assert ASSISTANTS[first_name]["slug"] == "kwan"
        assert "ขวัญ" in first_name
