"""`done.timings` ต้องมีเวลาทุกขั้น ไม่ใช่แค่ `llm_stream` (ต่อ 103)

prod 10-04: done.timings = {"llm_stream": …} อย่างเดียว · context_assembly/retrieval หาย
ต้นเหตุ: record_timing() `set()` dict ใหม่ลง contextvar แต่ starlette `iterate_in_threadpool`
รัน next() ของ generator แต่ละชิ้นใน copy_context() ของมันเอง ⇒ set ในชิ้นหนึ่งไม่ถึงชิ้นที่ส่ง done
(ต่อ 101 ต้องเขียน probe จับเวลาเองทีละขั้นเพราะเครื่องวัดนี้ใช้ไม่ได้)
"""
import contextvars
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch

from fastapi.testclient import TestClient

import routers.chat as chatmod
import server
from core import observability as obs

client = TestClient(server.app)


def _done(text: str) -> dict:
    evs = [json.loads(ln[6:]) for ln in text.splitlines() if ln.startswith("data: ")]
    done = [e for e in evs if e.get("done")]
    assert len(done) == 1, evs
    return done[0]


def _chat(sid: str, headers: dict | None = None) -> dict:
    body = {"assistant": "kwan", "session_id": sid, "prompt": "ทดสอบเวลา", "provider": "ollama",
            "active_learning": False, "response_cache": False}
    with patch.object(chatmod, "remember"), patch.object(chatmod, "teach", return_value=False), \
         patch.object(chatmod, "stream_response", lambda messages, **k: iter(["ตอบ"])):
        r = client.post("/api/chat", json=body, headers=headers or {})
    assert r.status_code == 200
    return _done(r.text)["timings"]


def test_done_timings_มีครบทุกขั้น():
    t = _chat("timings-all")
    for k in ("context_assembly", "retrieval", "llm_stream"):
        assert k in t, f"ขาด {k}: {t}"
        assert isinstance(t[k], (int, float)) and t[k] >= 0, t


def test_x_request_id_ยังได้_timings_ของคำขอตัวเอง():
    # header นี้เคยข้าม start_request() → ไม่ได้ dict ใหม่
    t1 = _chat("timings-rid-1", {"x-request-id": "trace-1"})
    t2 = _chat("timings-rid-2", {"x-request-id": "trace-2"})
    assert {"context_assembly", "retrieval", "llm_stream"} <= set(t1) and set(t1) == set(t2), (t1, t2)


def test_ไม่มี_start_request_ไม่ปนข้ามคำขอ():
    # ค่าเริ่มต้นเคยเป็น {} ตัวเดียวทั้งโปรเซส — ถ้าแก้ในที่โดยไม่มี dict ต่อคำขอ จะรั่วข้ามคำขอ
    contextvars.Context().run(obs.record_timing, "leak", 1.0)

    def other_request():
        obs.record_timing("mine", 2.0)
        return obs.get_timings()
    assert contextvars.Context().run(other_request) == {"mine": 2.0}


def test_เวลาที่จดใน_copy_context_ถึงผู้สร้างคำขอ():
    # จำลอง iterate_in_threadpool: แต่ละชิ้นรันใน copy_context() ของตัวเอง
    def request():
        obs.start_request()
        contextvars.copy_context().run(obs.record_timing, "step_a", 1.0)
        contextvars.copy_context().run(obs.record_timing, "step_b", 2.0)
        return obs.get_timings()
    assert contextvars.Context().run(request) == {"step_a": 1.0, "step_b": 2.0}


def test_timings_ลง_log_ด้วย(caplog):
    # done ไปถึงแค่เบราว์เซอร์ — ต่อ 101 ย้อนดูเวลาจาก server.log ไม่ได้ ต้องวัดสด
    import logging
    with caplog.at_level(logging.INFO, logger="routers.chat"):
        _chat("timings-log")
    lines = [r.getMessage() for r in caplog.records if "[Chat] timings" in r.getMessage()]
    assert len(lines) == 1, lines
    assert "context_assembly=" in lines[0] and "retrieval=" in lines[0] and "llm_stream=" in lines[0]
