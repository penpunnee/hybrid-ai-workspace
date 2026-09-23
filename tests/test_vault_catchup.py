"""vault sync อัตโนมัติเมื่อ PC (embedder) กลับมา (2026-09-23)

**ทำไม:** sync ที่ล้มตอน PC ปิดไม่มีอะไรลองใหม่ ⇒ index ค้างเวอร์ชันเก่าจนกว่าจะมีคนกด sync เอง
(09-23: 22 โน้ตค้างจนผมสั่ง sync ด้วยมือ) · error ที่เคยเกิดทั้งหมด **103 ครั้งเป็นเรื่องต่อไม่ติด**
(`timed out` / `Failed to connect to Ollama`) ไม่เคยมีไฟล์ล้มถาวร — แต่ยังต้องกันวนไม่จบไว้

**กติกา**
- "ค้าง" = sync ล่าสุดถูกหยุด/มี errors · **เริ่มต้นเป็นค้างทุกครั้งที่แอปเริ่ม** (จับของที่เปลี่ยนตอนแอปดับ)
- job ทุก 5 นาที: ค้าง + embedder ต่อได้ → sync แบบ **ไม่รอคิว** · ต่อไม่ได้ → ข้ามเงียบ (ไม่ ERROR ทุก 5 นาที)
- embedder ต่อได้แล้ว แต่ sync ยังมี error → **เลิกลองอัตโนมัติ** (กันวนไม่จบ) ให้คนกดเอง
"""
import logging
from types import SimpleNamespace

import pytest

import utils.obsidian_sync as ov


@pytest.fixture(autouse=True)
def _reset_pending():
    before = ov._catchup_pending
    yield
    ov._catchup_pending = before


@pytest.fixture
def world(monkeypatch):
    """ควบคุม collection / ผล TCP / ผล sync และจดการเรียก"""
    st = {"reach": True, "tcp_calls": 0, "sync_calls": [], "result": {"ok": True, "errors": 0}}
    col = SimpleNamespace(_embedding_function=SimpleNamespace(url="http://192.168.51.235:11434"))
    monkeypatch.setattr(ov, "_get_collection", lambda: col)

    def tcp(host, port, timeout):
        st["tcp_calls"] += 1
        return st["reach"]

    def fake_unlocked(vault_path=""):
        st["sync_calls"].append(vault_path)
        return dict(st["result"])

    monkeypatch.setattr(ov, "_tcp_reachable", tcp)
    monkeypatch.setattr(ov, "_sync_vault_unlocked", fake_unlocked)
    return st


# ── สถานะ "ค้าง" ถูกตั้งจากผลของ sync ทุกรอบ (รวมที่คนกด) ────────────────────────

def test_เริ่มแอปมา_ถือว่าค้าง():
    import importlib
    fresh = importlib.reload(ov)
    assert fresh._catchup_pending is True


@pytest.mark.parametrize("result,expected", [
    ({"ok": False, "errors": 3, "halted": "ต่อ embedder ไม่ได้"}, True),
    ({"ok": False, "errors": 1}, True),
    ({"ok": True, "errors": 0}, False),
])
def test_ผล_sync_ตั้งสถานะค้าง(world, result, expected):
    ov._catchup_pending = not expected
    world["result"] = result
    ov.sync_vault()
    assert ov._catchup_pending is expected


def test_busy_ไม่เปลี่ยนสถานะ(world):
    ov._catchup_pending = True
    assert ov._sync_lock.acquire(timeout=1)
    try:
        res = ov.sync_vault(wait_timeout=0)
    finally:
        ov._sync_lock.release()
    assert res.get("busy") is True and ov._catchup_pending is True


# ── job อัตโนมัติ ───────────────────────────────────────────────────────────────

def test_ไม่ค้าง_ไม่ทำอะไรเลย(world):
    ov._catchup_pending = False
    assert ov.catchup_sync_if_pending() is None
    assert world["tcp_calls"] == 0 and world["sync_calls"] == []


def test_ค้าง_แต่_PC_ยังปิด_ข้ามเงียบ(world, caplog):
    ov._catchup_pending = True
    world["reach"] = False
    with caplog.at_level(logging.DEBUG, logger=ov.logger.name):
        assert ov.catchup_sync_if_pending() is None
    assert world["sync_calls"] == [] and ov._catchup_pending is True
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING], \
        "PC ปิดทั้งคืน = job ยิงทุก 5 นาที ห้ามเป็น WARNING/ERROR"


def test_ค้าง_และ_PC_กลับมา_sync_แล้วหายค้าง(world):
    ov._catchup_pending = True
    res = ov.catchup_sync_if_pending()
    assert world["sync_calls"] == [""] and res["ok"] is True
    assert ov._catchup_pending is False


def test_PC_กลับมาแล้วแต่ยังมี_error_เลิกลองอัตโนมัติ(world, caplog):
    """กันวนไม่จบ — ไฟล์ที่ล้มถาวรต้องไม่ถูกลองทุก 5 นาทีตลอดไป"""
    ov._catchup_pending = True
    world["result"] = {"ok": False, "errors": 1}
    with caplog.at_level(logging.WARNING, logger=ov.logger.name):
        ov.catchup_sync_if_pending()
    assert ov._catchup_pending is False
    assert "กด sync" in caplog.text


def test_PC_หลุดอีกระหว่าง_sync_ยังค้างต่อ(world):
    """preflight ผ่านแต่ sync ถูกหยุด (embedder หลุดกลางทาง) = ยังเป็นเรื่อง PC ⇒ ลองรอบหน้า"""
    ov._catchup_pending = True
    world["result"] = {"ok": False, "errors": 2, "halted": "ต่อ embedder ไม่ได้ 2 ครั้งติด"}
    ov.catchup_sync_if_pending()
    assert ov._catchup_pending is True


def test_มีรอบอื่นรันอยู่_ไม่รอคิว(world):
    ov._catchup_pending = True
    assert ov._sync_lock.acquire(timeout=1)
    try:
        import time
        t = time.monotonic()
        res = ov.catchup_sync_if_pending()
        assert time.monotonic() - t < 1.0, "job ต้องไม่รอคิว 180 วิ"
    finally:
        ov._sync_lock.release()
    assert res.get("busy") is True and world["sync_calls"] == []
    assert ov._catchup_pending is True


def test_ไม่รู้_endpoint_ของ_embedder_ยัง_sync_ได้(world, monkeypatch):
    """EF แบบไม่มี url — ไม่รู้จะเช็คที่ไหน ต้องไม่บล็อก (เหมือน preflight ใน sync)"""
    ov._catchup_pending = True
    monkeypatch.setattr(ov, "_get_collection", lambda: SimpleNamespace(_embedding_function=None))
    ov.catchup_sync_if_pending()
    assert world["tcp_calls"] == 0 and world["sync_calls"] == [""]


# ── ลงทะเบียนใน scheduler ────────────────────────────────────────────────────

def test_scheduler_มี_job_ทุก_5_นาที():
    import core.scheduler as sm
    sm.start_scheduler()
    try:
        job = sm.scheduler.get_job("vault_catchup")
        assert job is not None
        assert job.trigger.interval.total_seconds() == 300
    finally:
        sm.scheduler.remove_all_jobs()
        if sm.scheduler.running:
            sm.scheduler.shutdown(wait=False)
