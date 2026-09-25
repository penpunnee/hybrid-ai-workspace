"""`/api/agent` ต้อง validate + clamp `max_steps` (audit 2026-09-24 MEDIUM ข้อ 5)

เดิม `int(data.get("max_steps", 4))` ตรงๆ → `"abc"` = ValueError → 500 · `500` = วน tool-call 500 รอบ
"""
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server
import routers.agent as agentmod

client = TestClient(server.app)


@pytest.fixture
def seen(monkeypatch):
    box = {}

    def fake_run_agent(messages, max_steps=4, provider="gemini", **k):
        box["max_steps"] = max_steps
        yield ("chunk", "ok")

    monkeypatch.setattr(agentmod, "run_agent", fake_run_agent)
    return box


def _post(body):
    return client.post("/api/agent", json={"assistant": "kwan", "session_id": "s_agent_steps", "prompt": "hi", **body})


@pytest.mark.parametrize("raw,expected", [
    ("abc", 4),        # ขยะ → default ไม่ใช่ 500
    (None, 4),
    ({}, 4),
    ("7", 7),          # สตริงตัวเลขยังรับ (client เก่าส่งแบบนี้)
    (0, 1),            # ต่ำกว่า 1 → 1
    (-3, 1),
    (500, agentmod.MAX_STEPS_CAP),   # เพดาน
    (2.9, 2),
])
def test_max_steps_ถูก_validate_และ_clamp(seen, raw, expected):
    r = _post({"max_steps": raw})
    assert r.status_code == 200, r.text
    assert seen["max_steps"] == expected


def test_ไม่ส่ง_max_steps_ได้_default(seen):
    r = _post({})
    assert r.status_code == 200
    assert seen["max_steps"] == 4


def test_เพดานต้องอยู่ในช่วงที่มีเหตุผล():
    assert 4 <= agentmod.MAX_STEPS_CAP <= 20
