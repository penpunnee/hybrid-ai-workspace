"""สคริปต์กู้ metadata ที่ถูก bump สลับ (audit 2026-09-24 ข้อ 4) — ส่วน pure ต้องถูกก่อนแตะ prod"""

import importlib.util
import pathlib

_p = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "restore_memory_created_at.py"
_spec = importlib.util.spec_from_file_location("restore_memory_created_at", _p)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def test_อ่านเวลาจาก_id_ได้ถึงวินาที():
    assert mod.created_at_from_id("mem_20260527045354_636c8d") == "2026-05-27T04:53:54"


def test_id_รูปอื่นต้องไม่เดา():
    assert mod.created_at_from_id("doc_123") is None
    assert mod.created_at_from_id("mem_2026052704535_636c8d") is None   # หลักไม่ครบ


def test_แผนกู้_เขียนเฉพาะตัวที่เพี้ยน_และรีเซ็ตตัวนับ():
    ids = ["mem_20260527045354_636c8d", "mem_20260611050215_e1977b", "doc_x"]
    metas = [
        # สลับไปแล้ว: created_at เป็นของคนอื่น
        {"created_at": "2026-07-13T11:05:57.1", "timestamp": "2026-07-13T11:05:57.1",
         "last_accessed": "2026-09-23T00:00:00", "access_count": 4, "confidence": 0.55, "source": "conversation"},
        # ถูกอยู่แล้วและรีเซ็ตแล้ว → ข้าม
        {"created_at": "2026-06-11T05:02:15.9", "timestamp": "2026-06-11T05:02:15.9",
         "last_accessed": "2026-06-11T05:02:15", "access_count": 0},
        {"created_at": "2026-01-01T00:00:00"},
    ]
    w_ids, w_metas, skipped = mod.plan_restore(ids, metas)
    assert w_ids == ["mem_20260527045354_636c8d"]
    assert skipped == 2
    m = w_metas[0]
    assert m["created_at"] == m["timestamp"] == m["last_accessed"] == "2026-05-27T04:53:54"
    assert m["access_count"] == 0
    assert m["confidence"] == 0.55 and m["source"] == "conversation", "ฟิลด์ที่ไม่มีแหล่งความจริงห้ามแตะ"


def test_created_at_ถูกแต่ตัวนับยังไม่รีเซ็ต_ต้องเขียน():
    ids = ["mem_20260611050215_e1977b"]
    metas = [{"created_at": "2026-06-11T05:02:15.9", "timestamp": "2026-06-11T05:02:15.9",
              "last_accessed": "2026-09-01T00:00:00", "access_count": 2}]
    w_ids, w_metas, _ = mod.plan_restore(ids, metas)
    assert w_ids == ids and w_metas[0]["access_count"] == 0
