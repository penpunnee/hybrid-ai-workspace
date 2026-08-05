"""dead-man's switch ของ backup job — utils/heartbeat.py + การต่อสายใน scheduler

ทำไม: ถ้า APScheduler thread ตาย จะไม่มี log error ใดๆ เลย (มันคือ "ความเงียบ"
ไม่ใช่ "ข้อผิดพลาด") และ retention 7 วันจะทยอยลบ archive เก่าจนหมดเกลี้ยง
→ ต้องให้ปลายทางเป็นคนสังเกตว่า "ไม่มีสัญญาณเข้ามา" แทนที่จะรอเราสังเกตเอง

⚠️ กับดักที่เคยเจอในโปรเจกต์ phrae: healthchecks.io ตอบ **200 แม้ check ไม่มีอยู่จริง**
— status code เป็นแค่ ack ว่ารับ request แล้ว ความจริงอยู่ใน body ("OK" เท่านั้น)
เทสชุดนี้จึงต้องมีเคสที่ status=200 แต่ผลลัพธ์ต้องเป็น False
"""
import logging
from unittest.mock import patch

import pytest

from utils import heartbeat


class _Resp:
    def __init__(self, status_code=200, text="OK"):
        self.status_code = status_code
        self.text = text


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv("HEARTBEAT_URL", raising=False)


def test_ping_success_when_body_says_ok():
    with patch("utils.heartbeat.requests.post", return_value=_Resp()) as post:
        assert heartbeat.ping("https://hc-ping.com/abc") is True
    assert post.call_args[0][0] == "https://hc-ping.com/abc"


def test_ping_false_when_status_200_but_body_is_not_ok(caplog):
    """เคสหลักของกับดัก — check ถูกลบทิ้ง/พิมพ์ uuid ผิด แต่ยังได้ 200"""
    resp = _Resp(status_code=200, text="not found")
    with caplog.at_level(logging.ERROR):
        with patch("utils.heartbeat.requests.post", return_value=resp):
            assert heartbeat.ping("https://hc-ping.com/wrong-uuid") is False
    assert "not found" in caplog.text, "ต้อง log body ที่ปลายทางตอบกลับมาจริง"


def test_ping_false_on_http_error():
    with patch("utils.heartbeat.requests.post", return_value=_Resp(500, "boom")):
        assert heartbeat.ping("https://hc-ping.com/abc") is False


def test_ping_never_raises_when_network_down():
    """heartbeat ล้มต้องไม่ทำให้ backup ที่สำเร็จแล้วกลายเป็นล้มเหลว"""
    with patch("utils.heartbeat.requests.post", side_effect=OSError("no route")):
        assert heartbeat.ping("https://hc-ping.com/abc") is False


def test_ping_noop_when_not_configured():
    """ไม่ได้ตั้ง HEARTBEAT_URL (เครื่อง dev) → เงียบ ไม่ยิง ไม่ error"""
    with patch("utils.heartbeat.requests.post") as post:
        assert heartbeat.ping() is False
    post.assert_not_called()


def test_ping_uses_env_when_no_arg(monkeypatch):
    monkeypatch.setenv("HEARTBEAT_URL", "https://hc-ping.com/from-env")
    with patch("utils.heartbeat.requests.post", return_value=_Resp()) as post:
        assert heartbeat.ping() is True
    assert post.call_args[0][0] == "https://hc-ping.com/from-env"


# ─── การต่อสาย: backup ที่ไม่สำเร็จต้องไม่ยิง heartbeat ───────────────────
# นี่คือหัวใจของ dead-man's switch — ถ้ายิงทุกครั้งที่ job "รันจบ"
# มันจะยืนยันว่าระบบแข็งแรงแม้ตอนที่ backup ออกมาเป็นของเปล่า

def _run_scheduled_backup():
    from core import scheduler as sched_mod
    sched_mod._scheduled_db_backup()


def test_heartbeat_pinged_when_backup_healthy():
    with patch("utils.db_backup.run_db_backup", return_value="/tmp/a.tar.gz"):
        with patch("utils.heartbeat.ping") as ping:
            _run_scheduled_backup()
    ping.assert_called_once()


def test_heartbeat_not_pinged_when_backup_unhealthy():
    from utils.db_backup import BackupUnhealthy
    err = BackupUnhealthy("chat_history.db ว่าง", archive="/tmp/a.tar.gz")
    with patch("utils.db_backup.run_db_backup", side_effect=err):
        with patch("utils.heartbeat.ping") as ping:
            _run_scheduled_backup()
    ping.assert_not_called()


def test_heartbeat_not_pinged_when_backup_crashes():
    with patch("utils.db_backup.run_db_backup", side_effect=OSError("disk full")):
        with patch("utils.heartbeat.ping") as ping:
            _run_scheduled_backup()
    ping.assert_not_called()


def test_heartbeat_not_pinged_when_nothing_to_back_up():
    """คืน None = ไม่พบ DB เลย — ไม่ใช่ความสำเร็จ ห้ามยืนยันว่าปกติ"""
    with patch("utils.db_backup.run_db_backup", return_value=None):
        with patch("utils.heartbeat.ping") as ping:
            _run_scheduled_backup()
    ping.assert_not_called()
