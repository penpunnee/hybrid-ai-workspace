"""`POST /api/memory/{assistant}` ต้องไม่รายงานสำเร็จเมื่อเขียนไม่ลง

`save_memory()` / `save_lesson()` คืน `False` เมื่อ ChromaDB ไม่พร้อมหรือเขียนพลาด
(ทั้งคู่ `except` แล้ว log อย่างเดียว ไม่ raise) — handler ทิ้งค่าที่คืนมาแล้วตอบ
`{"ok": True}` เสมอ = **ผู้ใช้กด "บันทึก" แล้วเห็นว่าสำเร็จ ทั้งที่ไม่มีอะไรถูกเก็บ**

เป็นโหมดพัง "ล้มเหลว → เงียบ" ซึ่งแย่กว่าพังดังๆ: ไม่มีใครรู้ว่าต้องบันทึกซ้ำ
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient

import routers.memory as mem_router
import server


@pytest.fixture
def client():
    return TestClient(server.app)


def test_เขียน_memory_ไม่ลงต้องตอบ_ok_false(client, monkeypatch):
    monkeypatch.setattr(mem_router, "save_memory", lambda *a, **kw: False)
    monkeypatch.setattr(mem_router, "save_lesson", lambda *a, **kw: True)

    r = client.post("/api/memory/ขวัญ", json={"text": "ข้อมูลที่ต้องจำ"})
    assert r.status_code == 200
    assert r.json()["ok"] is False, "ChromaDB เขียนไม่ลงแต่รายงานว่าสำเร็จ"


def test_เขียน_lesson_ไม่ลงต้องตอบ_ok_false(client, monkeypatch):
    monkeypatch.setattr(mem_router, "save_memory", lambda *a, **kw: True)
    monkeypatch.setattr(mem_router, "save_lesson", lambda *a, **kw: False)

    r = client.post("/api/memory/ขวัญ", json={"text": "ข้อมูลที่ต้องจำ"})
    assert r.json()["ok"] is False


def test_เขียนลงครบต้องตอบ_ok_true(client, monkeypatch):
    monkeypatch.setattr(mem_router, "save_memory", lambda *a, **kw: True)
    monkeypatch.setattr(mem_router, "save_lesson", lambda *a, **kw: True)

    r = client.post("/api/memory/ขวัญ", json={"text": "ข้อมูลที่ต้องจำ"})
    body = r.json()
    assert body["ok"] is True
    assert body["saved"] == "ข้อมูลที่ต้องจำ"
