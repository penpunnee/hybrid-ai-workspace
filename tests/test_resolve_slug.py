"""D: collection slug ต้องมาจาก config["slug"] ไม่ใช่ derive จากชื่อ display

bug: _safe_slug("🧡 ขวัญ (Logic)") → "logic" (ตัด emoji+ไทย เหลือวงเล็บ) →
episodic ของขวัญไปอยู่ memory_logic แทน memory_kwan. resolve_slug() ต้องคืน
slug ที่เสถียรจาก config (กัน collection orphan เมื่อ rename ชื่อ display)
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("UI_PASSWORD", "")

from memory.store import resolve_slug, _safe_slug


class TestResolveSlug:
    def test_display_name_resolves_to_config_slug(self):
        # เดิม _safe_slug ให้ "logic" — resolve_slug ต้องให้ slug จริงจาก config
        assert resolve_slug("🧡 ขวัญ (Logic)") == "kwan"
        assert _safe_slug("🧡 ขวัญ (Logic)") == "logic"   # ยืนยัน bug เดิมยังอยู่ในตัว raw

    def test_slug_passes_through(self):
        assert resolve_slug("kwan") == "kwan"

    def test_removed_assistant_falls_back_to_safe_slug(self):
        # ฟ้า ถอดจาก config แล้ว → resolve_slug ตก fallback _safe_slug (ไม่ crash)
        assert resolve_slug("🩵 ฟ้า (UI)") == _safe_slug("🩵 ฟ้า (UI)")

    def test_unknown_assistant_falls_back_to_safe_slug(self):
        # assistant ที่ไม่อยู่ใน config → คง behavior เดิม (backwards-compat)
        assert resolve_slug("Random Helper 99") == _safe_slug("Random Helper 99")
