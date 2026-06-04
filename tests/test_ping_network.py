"""Tests สำหรับ ping_network — ping router/NAS/PC จริง (แทนการให้โมเดลเดา online/offline)

root cause สุดท้าย: build_tool_context ไม่เคย ping router/NAS → โมเดลไม่มีข้อมูล → เดา 'Online'
แก้: ping จริงทั้ง 3 อุปกรณ์ → ฉีดผลจริงเข้า context (pure helpers เทสได้ ไม่ต้อง network)
"""
from utils.home_tools import _default_gateway, _format_ping_results, detect_home_tools


# ── _default_gateway ────────────────────────────────────────────────────────
def test_gateway_derived_from_subnet():
    assert _default_gateway("192.168.51.49") == "192.168.51.1"
    assert _default_gateway("10.0.0.5") == "10.0.0.1"


def test_gateway_malformed_returns_input():
    assert _default_gateway("ไม่ใช่ ip") == "ไม่ใช่ ip"


# ── _format_ping_results ────────────────────────────────────────────────────
def test_format_online_with_latency():
    out = _format_ping_results([
        {"name": "Router", "ip": "192.168.51.1", "online": True, "latency_ms": 2.1},
    ])
    assert "Router" in out and "192.168.51.1" in out
    assert "🟢" in out and "2.1" in out


def test_format_offline_honest():
    out = _format_ping_results([
        {"name": "Router", "ip": "192.168.51.1", "online": False},
    ])
    assert "🔴" in out
    assert "ไม่ตอบสนอง" in out or "offline" in out


def test_format_multiple_devices():
    out = _format_ping_results([
        {"name": "Router", "ip": "192.168.51.1", "online": True, "latency_ms": 1.0},
        {"name": "NAS", "ip": "192.168.51.49", "online": True, "latency_ms": 0.5},
        {"name": "PC", "ip": "192.168.51.235", "online": False},
    ])
    for n in ["Router", "NAS", "PC"]:
        assert n in out


# ── detect_home_tools routing ───────────────────────────────────────────────
def test_network_question_triggers_ping_network():
    """ถาม router/เครือข่าย → ping_network (ไม่ใช่ ping_pc เดี่ยว)"""
    tools = detect_home_tools("ช่วย ping เช็คอุปกรณ์ในเครือข่ายบ้าน router กับ NAS ออนไลน์ไหม")
    assert "ping_network" in tools
    assert "ping_pc" not in tools          # ไม่ ping ซ้ำ


def test_plain_pc_question_still_ping_pc():
    """ถาม PC เฉยๆ → ping_pc ตามเดิม (ไม่ over-trigger network)"""
    tools = detect_home_tools("PC เปิดอยู่ไหม")
    assert "ping_pc" in tools
    assert "ping_network" not in tools


# ── "รัน" keyword over-broad fix ─────────────────────────────────────────────
def test_run_code_question_no_docker_trigger():
    """'รัน' คำเดียวใน coding context ต้องไม่ trigger docker tool"""
    assert "docker" not in detect_home_tools("ทำไมรันโค้ดผิด")
    assert "docker" not in detect_home_tools("รัน Python ยังไง")
    assert "docker" not in detect_home_tools("รันสคริปต์ไม่ได้")


def test_docker_specific_terms_still_trigger():
    """คำเฉพาะ docker ต้องยัง trigger ได้"""
    assert "docker" in detect_home_tools("docker container รันอยู่ไหม")
    assert "docker" in detect_home_tools("container หยุดทำงาน")
    assert "docker" in detect_home_tools("service ล่ม")


def test_docker_run_compound_triggers():
    """compound ที่ชัดเจนต้อง trigger"""
    assert "docker" in detect_home_tools("docker รัน container ไหม")
    assert "docker" in detect_home_tools("container รันอยู่ไหม")


def test_stop_working_non_docker_context_no_trigger():
    """'หยุดทำงาน' ใน context ที่ไม่ใช่ docker ต้องไม่ trigger"""
    assert "docker" not in detect_home_tools("โปรแกรมหยุดทำงาน")
    assert "docker" not in detect_home_tools("เน็ตหยุดทำงาน")
    assert "docker" not in detect_home_tools("แอปหยุดทำงาน")


def test_docker_stop_compound_triggers():
    """'docker/service หยุดทำงาน' ต้อง trigger"""
    assert "docker" in detect_home_tools("docker หยุดทำงานแล้ว")
    assert "docker" in detect_home_tools("service หยุดทำงาน restart ด้วย")
