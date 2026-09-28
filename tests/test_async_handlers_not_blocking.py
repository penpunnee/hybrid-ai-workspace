"""ก้อน 11 — async handler ใน reader/system/sessions ต้องไม่รันงาน sync ช้าบน event loop (audit 2026-09-24 MEDIUM)

วัด prod: `POST /api/reader/seek` **833 ms** บน event loop (โหลดหนังสือทั้งเล่มจาก sqlite) · `text()` เล่ม 20.3 ล้านตัวอักษร
94 ms แม้ cache อุ่น · `_ingest` ซ่อมข้อความ 3 ขั้น + นับท่อนทั้งเล่ม (0.35 วิ/4.2 ล้านตัวอักษร · ไฟล์ถึง 200 MB) ·
admin memory = ChromaDB ผ่านเน็ต · sessions = sqlite (2.3 ms บน prod แต่กติกาโปรเจกต์ระบุ sqlite ไว้)
วิธีวัดเดียวกับ test_chat_router_concurrency: ระหว่าง route หนักทำงาน `/api/config` ต้องตอบเร็ว (วัดจาก t0 ก่อนยิงทั้งคู่)
"""
import asyncio
import os
import sqlite3
import sys
import time

import httpx
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server
import routers.reader as rr
import routers.sessions as rs

_BLOCK = 0.6


async def _race(heavy):
    transport = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        t0 = time.perf_counter()

        async def light():
            await asyncio.sleep(_BLOCK / 4)
            r = await c.get("/api/config")
            return time.perf_counter() - t0, r.status_code

        resp, (elapsed, status) = await asyncio.gather(heavy(c), light())
        return resp, elapsed, status


def _run(heavy):
    resp, elapsed, status = asyncio.run(_race(heavy))
    assert status == 200
    assert elapsed < _BLOCK * 0.8, f"/api/config ใช้ {elapsed:.3f}s — event loop ถูกบล็อก"
    return resp


class _SlowBooks:
    def __init__(self):
        self.store = {"เล่ม": "ก" * 5000}
    def text(self, source):
        time.sleep(_BLOCK)
        return self.store.get(source)
    def put(self, source, text):
        time.sleep(_BLOCK)
        self.store[source] = text
    def list(self):
        return []


class _Marks:
    def __init__(self):
        self.d = {}
    def get(self, s):
        return self.d.get(s, 0)
    def set(self, s, p):
        self.d[s] = p


@pytest.fixture
def slow_reader(monkeypatch):
    monkeypatch.setattr(rr, "_books", _SlowBooks())
    monkeypatch.setattr(rr, "_marks", _Marks())


def test_reader_seek_ไม่บล็อก(slow_reader):
    r = _run(lambda c: c.post("/api/reader/seek", json={"source": "เล่ม", "pos": 100}))
    assert r.status_code == 200 and r.json()["pos"] == 100


def test_reader_next_ไม่บล็อก(slow_reader):
    r = _run(lambda c: c.post("/api/reader/next", json={"source": "เล่ม"}))
    assert r.status_code == 200 and r.json()["text"]


def test_reader_add_ไม่บล็อก(slow_reader):
    r = _run(lambda c: c.post("/api/reader/add", json={"source": "ใหม่", "content": "สวัสดีครับ " * 50}))
    assert r.status_code == 200 and r.json()["ok"]


def test_reader_add_from_disk_ไม่บล็อก(slow_reader, tmp_path, monkeypatch):
    f = tmp_path / "book.txt"
    f.write_text("สวัสดีครับ " * 50, encoding="utf-8")
    import utils.fs_tools as ft
    monkeypatch.setattr(ft, "_resolve_safe", lambda p: f)
    r = _run(lambda c: c.post("/api/reader/add-from-disk", json={"path": "book.txt"}))
    assert r.status_code == 200 and r.json()["ok"]


def test_reader_error_จาก_thread_ยังเป็น_404(slow_reader):
    r = _run(lambda c: c.post("/api/reader/seek", json={"source": "ไม่มีเล่มนี้", "pos": 1}))
    assert r.status_code == 404, r.text


def test_admin_list_memory_ไม่บล็อก(monkeypatch):
    import memory.store as ms
    monkeypatch.setattr(ms, "list_entries", lambda *a, **k: time.sleep(_BLOCK) or [])
    r = _run(lambda c: c.get("/api/admin/memory/kwan"))
    assert r.status_code == 200 and r.json()["count"] == 0


def test_admin_delete_memory_ไม่บล็อก(monkeypatch):
    import memory.store as ms
    monkeypatch.setattr(ms, "delete_entry", lambda *a, **k: time.sleep(_BLOCK) or True)
    r = _run(lambda c: c.delete("/api/admin/memory/kwan/x1"))
    assert r.status_code == 200 and r.json()["deleted"] is True


def test_sessions_rename_ไม่บล็อก(monkeypatch):
    monkeypatch.setattr(rs, "rename_session", lambda *a, **k: time.sleep(_BLOCK))
    r = _run(lambda c: c.patch("/api/sessions/kwan/s1", json={"name": "ชื่อใหม่"}))
    assert r.json()["ok"] is True


def test_sessions_pin_ไม่บล็อก(monkeypatch):
    monkeypatch.setattr(rs, "pin_message", lambda *a, **k: time.sleep(_BLOCK))
    r = _run(lambda c: c.post("/api/pin/1", json={"pinned": True}))
    assert r.json()["ok"] is True


def test_sessions_share_ไม่บล็อก(monkeypatch):
    import utils.history as uh

    def slow_conn():
        time.sleep(_BLOCK)
        return sqlite3.connect(":memory:")
    monkeypatch.setattr(uh, "_get_conn", slow_conn)
    r = _run(lambda c: c.post("/api/share", json={"assistant": "kwan", "session_id": "s1"}))
    assert r.json()["ok"] is True and r.json()["token"]
