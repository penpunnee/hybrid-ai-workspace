"""log ผลของ tool 1 บรรทัดใน `_run_agent_fc` (Gemini + LM Studio) — ขั้น 4 ที่ user เคาะ 2026-09-29

เดิมมีแค่ `[Tool] name(args)` (tools.py) ไม่มีผลลัพธ์ ⇒ แยกไม่ได้ว่า tool ได้ข้อมูลหรือล้ม → ตัดสินไม่ได้ว่าต้องมี guard
"ไม่มีข้อมูลจริง" ไหม · บันทึกแค่ ชื่อ/step/ความยาว/สถานะ — **ห้ามบันทึกเนื้อหาผลลัพธ์** (ผล web/memory อาจมีข้อมูลส่วนตัว
และ server.log rotate เก็บ 5 ไฟล์)
"""
import logging
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agents.orchestrator as orch
from agents.orchestrator import ToolCall, _run_agent_fc

SECRET = "ข้อมูลลับของพี่ปอย-บ้านเลขที่ 99"


class _Adapter:
    name = "Fake"

    def __init__(self, calls):
        self._calls = calls
        self._n = 0

    def step(self):
        self._n += 1
        if self._n == 1:
            for c in self._calls:
                yield ("call", c)
        else:
            yield ("text", "สรุป")

    def add_tool_results(self, results):
        pass

    def synthesize(self):
        yield ("text", "สรุป")


def _run(monkeypatch, caplog, results: dict):
    monkeypatch.setattr(orch, "execute_tool", lambda name, args: results[name])
    calls = [ToolCall(name=n, args={"q": SECRET}, id=f"id_{n}") for n in results]
    with caplog.at_level(logging.INFO, logger="agents.orchestrator"):
        list(_run_agent_fc(_Adapter(calls), max_steps=3))
    return [r.getMessage() for r in caplog.records if " tool " in r.getMessage()]


@pytest.mark.parametrize("result,status", [
    (f"ราคาทอง 41,000 บาท {SECRET}", "ok"),
    ("❌ tool error: timeout", "error"),
    ("⚠️ NAS ตอบ แต่ไม่ยืนยันได้ว่าสำเร็จ", "warn"),
    ("   ", "empty"),
    ("", "empty"),
])
def test_log_หนึ่งบรรทัดต่อ_tool_บอกสถานะ(monkeypatch, caplog, result, status):
    lines = _run(monkeypatch, caplog, {"web_search": result})
    assert len(lines) == 1, lines
    line = lines[0]
    assert "[Agent/Fake] tool web_search" in line and "step=1" in line
    assert f"len={len(result)}" in line and f"status={status}" in line, line


def test_ห้ามมีเนื้อหาผลลัพธ์หรือ_args_ใน_log(monkeypatch, caplog):
    lines = _run(monkeypatch, caplog, {"web_search": f"ผลค้น {SECRET}", "memory_search": f"❌ {SECRET}"})
    assert len(lines) == 2
    for line in lines:
        assert SECRET not in line and "ผลค้น" not in line, f"เนื้อหาหลุดลง log: {line}"
