"""Tests สำหรับ assistants/config.py — กัน hallucination (แต่งผล tool / ข้อมูล real-time)

root cause: เดิม system prompt สั่ง "ไม่เคยปฏิเสธ ไม่บอกว่าทำไม่ได้" → ดันโมเดลเล็ก
ให้กุข้อมูลที่ดึงจริงไม่ได้ (ping, ราคา, ผลค้นเว็บ) แทนที่จะยอมรับตรงๆ
"""
from assistants.config import ASSISTANTS

# คำที่บ่งชี้ว่า prompt มี "guard กันแต่งข้อมูล"
_GUARD_MARKERS = ["ห้ามแต่ง", "ห้ามกุ", "อย่ากุ", "ไม่กุ"]
# ตัวอย่างข้อมูล real-time ที่โมเดลดึงเองไม่ได้ — ต้องเตือนใน prompt
_REALTIME_MARKERS = ["ping", "real-time", "เรียลไทม์", "ข้อมูลสด"]


def test_every_assistant_has_anti_fabrication_guard():
    """ทุกผู้ช่วยต้องมีข้อห้ามแต่งผล tool/ข้อมูลที่ดึงจริงไม่ได้"""
    for label, cfg in ASSISTANTS.items():
        sp = cfg["system_prompt"]
        assert any(m in sp for m in _GUARD_MARKERS), \
            f"{label}: ขาด guard กันแต่งข้อมูล (เช่น 'ห้ามแต่ง')"


def test_guard_mentions_realtime_data():
    """guard ต้องอ้างถึงข้อมูล real-time (ที่โมเดล local ดึงเองไม่ได้)"""
    for label, cfg in ASSISTANTS.items():
        sp = cfg["system_prompt"]
        assert any(m in sp for m in _REALTIME_MARKERS), \
            f"{label}: guard ไม่ได้พูดถึงข้อมูล real-time/ping"


def test_guard_points_to_agent_mode_or_honesty():
    """เมื่อทำไม่ได้ ต้องแนะให้บอกตรงๆ หรือชี้ไป Agent mode (มี tool จริง)"""
    for label, cfg in ASSISTANTS.items():
        sp = cfg["system_prompt"]
        assert ("Agent" in sp) or ("บอกตรง" in sp or "บอกพี่ปอย" in sp), \
            f"{label}: ไม่ได้แนะทางออก (Agent mode / บอกตรงๆ)"


def test_kwan_no_longer_unconditional_never_refuse():
    """ขวัญต้องไม่มีคำสั่งห้ามปฏิเสธแบบไม่มีเงื่อนไข (ต้นเหตุ hallucination)"""
    sp = ASSISTANTS["🧡 ขวัญ (Logic)"]["system_prompt"]
    assert "ไม่เคยปฏิเสธคำถาม ไม่บอกว่าทำไม่ได้" not in sp


def test_thai_only_rule_preserved():
    """ต้องไม่เผลอลบกติกา 'ตอบภาษาไทยเท่านั้น' ตอนเพิ่ม guard"""
    for label, cfg in ASSISTANTS.items():
        assert "ภาษาไทยเท่านั้น" in cfg["system_prompt"], f"{label}: หาย Thai-only rule"
