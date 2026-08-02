"""Tests สำหรับ utils/ha_client.py — call_service() ไม่โกหกว่าสำเร็จ

บั๊กจริง (พบจาก audit 2026-08-01): call_service() เช็คแค่ HTTP status 200
แต่ Home Assistant คืน 200 พร้อม result เป็น [] เวลาสั่ง entity ที่ไม่มีอยู่
จริง (หรือคำสั่งไม่มีผล) — เดิมโค้ดรายงาน {"ok": True} เหมือนสำเร็จเป๊ะ ทำให้
tool ชั้นบน (`agents/tools.py:_t_ha_call_service`) บอก user/LLM ว่า "✅ สำเร็จ"
ทั้งที่ไฟ/อุปกรณ์ไม่ได้เปลี่ยนสถานะจริง (เช่น entity_id เพี้ยนจากการค้นหาก่อนหน้า)
"""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils.ha_client as ha


def _mock_resp(status_code=200, json_data=None, content=b"[]"):
    r = MagicMock()
    r.status_code = status_code
    r.content = content
    r.json.return_value = json_data if json_data is not None else []
    r.raise_for_status.return_value = None
    return r


@patch.object(ha, "HA_URL", "http://ha.local")
@patch.object(ha, "HA_TOKEN", "tok")
def test_call_service_success_with_changed_state():
    resp = _mock_resp(json_data=[{"entity_id": "light.living_room", "state": "on"}])
    with patch("utils.ha_client.requests.post", return_value=resp):
        r = ha.call_service("light", "turn_on", entity_id="light.living_room")
    assert r["ok"] is True
    assert "warning" not in r


@patch.object(ha, "HA_URL", "http://ha.local")
@patch.object(ha, "HA_TOKEN", "tok")
def test_call_service_empty_result_with_entity_id_flags_warning():
    """HA ตอบ 200 แต่ไม่มี entity ไหนเปลี่ยนสถานะเลย (entity_id ผิด/ไม่มีจริง)
    ต้องไม่รายงาน ok เฉยๆ — ต้องมี warning ให้ชั้นบนรู้ว่าอาจไม่ได้เกิดอะไรจริง"""
    resp = _mock_resp(json_data=[])
    with patch("utils.ha_client.requests.post", return_value=resp):
        r = ha.call_service("light", "turn_on", entity_id="light.does_not_exist")
    assert r["ok"] is True
    assert "warning" in r


@patch.object(ha, "HA_URL", "http://ha.local")
@patch.object(ha, "HA_TOKEN", "tok")
def test_call_service_empty_result_without_entity_id_no_warning():
    """service ที่ไม่ผูก entity_id (เช่น automation.trigger แบบ broadcast) คืน []
    ได้ตามปกติแม้สำเร็จจริง — ไม่ควร flag warning เพราะไม่มี entity ให้ตรวจสอบ"""
    resp = _mock_resp(json_data=[])
    with patch("utils.ha_client.requests.post", return_value=resp):
        r = ha.call_service("script", "reload")
    assert r["ok"] is True
    assert "warning" not in r


# ── agents/tools.py:_t_ha_call_service ต้องไม่รายงาน ✅ ทับ warning ────────────
def test_tool_ha_call_service_relays_warning_not_blind_success():
    import agents.tools as tools
    with patch("utils.ha_client.call_service",
               return_value={"ok": True, "result": [], "warning": "entity นี้อาจไม่มีอยู่จริง"}):
        out = tools._t_ha_call_service("light", "turn_on", entity_id="light.ghost")
    assert "⚠️" in out
    assert "✅" not in out


def test_tool_ha_call_service_reports_success_when_no_warning():
    with patch("utils.ha_client.call_service",
               return_value={"ok": True, "result": [{"entity_id": "light.living_room"}]}):
        import agents.tools as tools
        out = tools._t_ha_call_service("light", "turn_on", entity_id="light.living_room")
    assert "✅" in out
    assert "⚠️" not in out
