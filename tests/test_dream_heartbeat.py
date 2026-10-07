"""heartbeat ของ Dream 02:00 — check แยกจาก backup 03:30

ทำไมต้องมี: ช่องเดียวที่แจ้งเมื่อ Dream ล้มคือ LINE Notify ซึ่งปิดบริการแล้ว (31 มี.ค. 2025)
และ prod ไม่ได้ตั้ง token ⇒ Dream ล้ม/ไม่วิ่ง = เงียบสนิท (devlog [10-07] · system-map ข้อ 10)

กติกา:
- สำเร็จ (รวม "ข้ามเพราะไม่มีความจำในช่วงเวลา" — งานวิ่งครบตามปกติ) → ยิง URL ของ Dream
- ล้ม (exception) → ยิง `<URL>/fail` ให้เตือนทันทีไม่ต้องรอ grace
- `DreamBusy` (มีรอบอื่นวิ่งอยู่) → ไม่ยิงทั้งคู่ · ปล่อยให้ grace ตัดสิน
- 🔴 ไม่ได้ตั้ง `DREAM_HEARTBEAT_URL` → **ห้ามยิงอะไรเลย** แม้ `HEARTBEAT_URL` (backup) ตั้งอยู่
  (`ping(url="")` ถอยไปใช้ URL ของ backup เอง — ถ้าหลุดทางนี้ Dream จะไปยืนยันแทน check ของ backup)
"""
import logging
from unittest.mock import patch

import pytest

from utils import dream
from utils import heartbeat

_DREAM = "https://hc-ping.com/dream-uuid"
_BACKUP = "https://hc-ping.com/backup-uuid"


class _Resp:
    def __init__(self, status=200, text="OK"):
        self.status_code = status
        self.text = text


@pytest.fixture
def urls(monkeypatch):
    monkeypatch.setattr(heartbeat, "HEARTBEAT_URL", _BACKUP)
    monkeypatch.setattr(heartbeat, "DREAM_HEARTBEAT_URL", _DREAM)
    monkeypatch.setattr("utils.notify.send_line_notify", lambda msg: None)


def _run(monkeypatch, behaviour):
    import core.scheduler as sch
    monkeypatch.setattr(dream, "run_dream_cycle", behaviour)
    with patch("utils.heartbeat.requests.post", return_value=_Resp()) as post:
        sch._scheduled_dream()
    return [c.args[0] for c in post.call_args_list]


def _raise(exc):
    def f(**k):
        raise exc
    return f


def test_สำเร็จ_ยิง_url_ของ_dream(monkeypatch, urls):
    assert _run(monkeypatch, lambda **k: {"memories_processed": 3}) == [_DREAM]


def test_ข้ามเพราะไม่มีความจำ_นับว่าสำเร็จ(monkeypatch, urls):
    assert _run(monkeypatch, lambda **k: {"skipped": "no memories in window"}) == [_DREAM]


def test_ล้ม_ยิง_fail(monkeypatch, urls):
    assert _run(monkeypatch, _raise(RuntimeError("gemini 429"))) == [_DREAM + "/fail"]


def test_busy_ไม่ยิงอะไรเลย(monkeypatch, urls):
    assert _run(monkeypatch, _raise(dream.DreamBusy("busy"))) == []


@pytest.mark.parametrize("behaviour", [
    lambda **k: {"memories_processed": 3},
    _raise(RuntimeError("boom")),
], ids=["สำเร็จ", "ล้ม"])
def test_ไม่ได้ตั้ง_url_ของ_dream_ห้ามถอยไปยิง_check_ของ_backup(monkeypatch, urls, behaviour):
    monkeypatch.setattr(heartbeat, "DREAM_HEARTBEAT_URL", "")
    assert heartbeat.HEARTBEAT_URL == _BACKUP, "เทสนี้ต้องมี URL ของ backup ตั้งอยู่จริงถึงจะพิสูจน์ได้"
    assert _run(monkeypatch, behaviour) == []


def test_url_มี_slash_ท้าย_fail_ไม่ซ้อน_slash(monkeypatch, urls):
    monkeypatch.setattr(heartbeat, "DREAM_HEARTBEAT_URL", _DREAM + "/")
    assert _run(monkeypatch, _raise(RuntimeError("boom"))) == [_DREAM + "/fail"]


def test_heartbeat_ล้ม_ไม่ทำให้_scheduler_โยน(monkeypatch, urls):
    import core.scheduler as sch
    monkeypatch.setattr(dream, "run_dream_cycle", lambda **k: {})
    with patch("utils.heartbeat.requests.post", side_effect=OSError("no route")), \
         patch("utils.heartbeat.time.sleep"):
        sch._scheduled_dream()   # ต้องไม่ raise


def test_url_ของ_dream_ไม่หลุดลง_log(monkeypatch, urls, caplog):
    with caplog.at_level(logging.DEBUG):
        _run(monkeypatch, _raise(RuntimeError("boom")))
    assert "dream-uuid" not in caplog.text
