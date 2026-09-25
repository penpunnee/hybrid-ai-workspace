"""`/api/tts*` ต้องไม่ "พังเงียบ" (audit 2026-09-24 MEDIUM) — เดิมกลืน exception เป็น `{"error"}` 200 ไม่ log
= แบบเดียวกับที่ทำให้ปุ่ม 🔊 พังอยู่ 2 เดือนโดยไม่มีใครรู้ (devlog 08-06)
"""
import json
import logging
import os
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server
import routers.system as sysmod

client = TestClient(server.app)


def _boom(*a, **k):
    raise RuntimeError("429 RESOURCE_EXHAUSTED quota")


def test_tts_ล้ม_ต้อง_log_ERROR_และไม่ตอบ_200(monkeypatch, caplog):
    monkeypatch.setattr(sysmod, "generate_tts", _boom)
    with caplog.at_level(logging.ERROR, logger="routers.system"):
        r = client.post("/api/tts", json={"text": "สวัสดี", "assistant_slug": "kwan"})
    assert r.status_code == 502, r.text
    assert "quota" in r.json().get("error", "")
    assert any("quota" in rec.getMessage() and rec.levelno >= logging.ERROR for rec in caplog.records), \
        "exception ต้องลง log ระดับ ERROR — ไม่งั้นพังเงียบเหมือน 08-06"


def test_tts_stream_ล้ม_ต้อง_log_ERROR(monkeypatch, caplog):
    monkeypatch.setattr(sysmod, "generate_tts", _boom)
    with caplog.at_level(logging.ERROR, logger="routers.system"):
        r = client.post("/api/tts/stream", json={"text": "สวัสดี", "assistant_slug": "kwan"})
    assert r.status_code == 200
    events = [json.loads(l[6:]) for l in r.text.splitlines() if l.startswith("data: ")]
    assert any("quota" in e.get("error", "") for e in events), events
    assert any("quota" in rec.getMessage() and rec.levelno >= logging.ERROR for rec in caplog.records)
