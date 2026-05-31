"""Tests สำหรับ guard กันแต่งผล tool ใน utils/home_tools.py

root cause (verify บน production): build_tool_context ฉีดข้อมูลจริง (NAS disk, PC ping)
เข้า context แต่โมเดลเล็กเอามา 'ห่อเป็นผล ping ปลอม' — แต่ง IP/response time/อุปกรณ์
ที่ไม่มีในข้อมูลจริง → ต้องวาง guard ติดกับข้อมูลที่ฉีด (ใกล้ attention โมเดล)
"""
from utils.home_tools import _join_with_guard, _TOOL_GUARD


def test_empty_parts_no_guard():
    """ไม่มี tool ทำงาน → ไม่ฉีดอะไรเลย (ไม่ต้องมี guard)"""
    assert _join_with_guard([]) == ""


def test_guard_appended_when_data_present():
    """มีข้อมูลจริง → ต่อท้ายด้วย guard เสมอ"""
    out = _join_with_guard(["[PC Status — 192.168.51.235] 🟢 Online (2.1ms)"])
    assert "192.168.51.235" in out          # ข้อมูลจริงคงอยู่
    assert _TOOL_GUARD in out                # guard ถูกแนบ
    assert out.endswith(_TOOL_GUARD)         # guard อยู่ท้ายสุด (ปิดท้าย context)


def test_guard_forbids_fabrication_and_points_to_honesty():
    """guard ต้องห้ามแต่ง + บอกให้ยอมรับเมื่อไม่มีข้อมูล"""
    assert "ห้ามแต่ง" in _TOOL_GUARD or "ห้าม" in _TOOL_GUARD
    assert "ยังไม่ได้เช็ค" in _TOOL_GUARD


def test_multiple_parts_joined_then_guard():
    parts = ["[NAS Disk — 192.168.51.49] ...", "[PC Status — 192.168.51.235] 🟢"]
    out = _join_with_guard(parts)
    assert parts[0] in out and parts[1] in out
    assert out.count(_TOOL_GUARD) == 1       # แนบครั้งเดียว ไม่ซ้ำ
