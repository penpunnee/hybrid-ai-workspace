"""Dream cycle ต้องวิ่งได้ทีละตัวเดียวทั้งระบบ (audit 2026-09-24 MEDIUM)

เดิม: `core/state.dream_lock` เป็น asyncio.Lock (ใช้จาก thread ไม่ได้) · job กลางคืน (`core/scheduler`) เรียก
`run_dream_cycle` ตรงไม่ผ่าน lock · router ปล่อย lock ตอน timeout ทั้งที่ thread ยังวิ่ง ⇒ ซ้อนกันได้ 2 ทาง
แก้: `threading.Lock` ตัวเดียวใน `utils/dream` ที่ `run_dream_cycle()` ถือเอง (ทุกทางเข้าเดินผ่านจุดเดียว)
"""
import logging
import os
import sys
import threading
import time

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils.dream as dream


@pytest.fixture(autouse=True)
def _free_lock():
    yield
    if dream._run_lock.locked():
        dream._run_lock.release()


def _blocking_light_sleep(gate: threading.Event, started: threading.Event):
    def fake(hours=24):
        started.set()
        gate.wait(5)
        return []
    return fake


def test_เรียกซ้อนจาก_thread_อื่น_ต้องได้_DreamBusy_ทันที(monkeypatch):
    gate, started = threading.Event(), threading.Event()
    monkeypatch.setattr(dream, "light_sleep", _blocking_light_sleep(gate, started))
    monkeypatch.setattr(dream, "_save_report", lambda r: None)
    t = threading.Thread(target=lambda: dream.run_dream_cycle(provider="ollama"), daemon=True)
    t.start()
    assert started.wait(2)
    assert dream.is_running() is True
    t0 = time.perf_counter()
    with pytest.raises(dream.DreamBusy):
        dream.run_dream_cycle(provider="ollama")
    assert time.perf_counter() - t0 < 1.0, "ต้องปฏิเสธทันที ไม่รอคิว"
    gate.set(); t.join(3)
    assert dream.is_running() is False


def test_ล้มกลางทาง_ต้องปล่อย_lock(monkeypatch):
    def boom(hours=24):
        raise RuntimeError("chroma down")
    monkeypatch.setattr(dream, "light_sleep", boom)
    with pytest.raises(RuntimeError):
        dream.run_dream_cycle(provider="ollama")
    assert dream.is_running() is False
    monkeypatch.setattr(dream, "light_sleep", lambda hours=24: [])
    monkeypatch.setattr(dream, "_save_report", lambda r: None)
    assert dream.run_dream_cycle(provider="ollama")["skipped"], "รอบถัดไปต้องวิ่งได้ (lock ไม่ค้าง)"


def test_router_ตอบ_409_เมื่อกำลังวิ่ง(monkeypatch):
    import server
    import routers.dream as rd
    client = TestClient(server.app)
    # ใช้คลาสที่ router ผูกไว้ตอน import (`rd.DreamBusy`) — เทสไฟล์อื่น reload utils.dream ทำให้
    # `utils.dream.DreamBusy` เป็นคนละ object กับที่ router ถือ (บทเรียน 09-24: ห้าม reload โมดูลที่มีคลาส exception)
    monkeypatch.setattr(rd, "run_dream_cycle", lambda *a, **k: (_ for _ in ()).throw(rd.DreamBusy("busy")))
    r = client.post("/api/dream", json={"provider": "ollama"})
    assert r.status_code == 409, r.text
    assert r.json().get("ok") is False


def test_scheduler_ข้ามคืนนี้เมื่อ_busy_ไม่ราวว่าล้มเหลว(monkeypatch, caplog):
    import core.scheduler as sch
    monkeypatch.setattr(dream, "run_dream_cycle", lambda **k: (_ for _ in ()).throw(dream.DreamBusy("busy")))
    notes = []
    monkeypatch.setattr("utils.notify.send_line_notify", lambda msg: notes.append(msg))
    with caplog.at_level(logging.WARNING, logger="core.scheduler"):
        sch._scheduled_dream()
    assert any("ข้าม" in r.getMessage() for r in caplog.records), "ต้อง log ว่าข้าม ไม่ใช่ error"
    assert not any("ล้มเหลว" in n for n in notes), "busy ไม่ใช่ความล้มเหลว — ห้ามแจ้ง LINE ว่าล้ม"


def test_ไม่เหลือ_asyncio_lock_ของ_dream():
    """lock เดียว = source of truth เดียว — `core/state.dream_lock` และ `async with dream_lock` ต้องหายไป"""
    for path in ("core/state.py", "routers/dream.py", "core/scheduler.py"):
        src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), path), encoding="utf-8").read()
        assert "dream_lock" not in src, f"{path} ยังอ้าง dream_lock"
