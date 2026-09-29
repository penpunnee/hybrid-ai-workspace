"""บันทึกข้อความโหมดเสียงนอก event loop โดยรักษาลำดับ — ขั้น 1 (ทางที่ 1) 2026-09-29

วัดบน prod ด้วย 5B: `_save_msg` (sqlite commit) 0.8–1.7 วิ/ครั้ง × 2 ครั้ง/turn บน event loop ของ /ws/voice
(heartbeat ไมค์ทุก 5 วิเลื่อนเป็น 7 วิ) · ต้นเหตุ = fsync บน RAID5 HDD 5,400 rpm (dd dsync 213 ms/ครั้ง)
ทางแก้: ThreadPoolExecutor(max_workers=1) — คิว FIFO + worker ตัวเดียว = ลำดับ user→assistant ถูกเสมอ
(concurrent/futures/thread.py) · `asyncio.to_thread` ใช้ default executor หลาย worker → fire-and-forget ลำดับไม่รับประกัน
· shutdown(wait=False) ไม่ยกเลิกงานที่ค้าง (docs concurrent.futures) = ปิดสายแล้วข้อความไม่หาย
ห่อที่บรรทัด import เท่านั้น — call site `_save_msg(asst_name, "user"` เดิม (เทสยึดไว้) · 🔒 ไม่แตะค่าเสียง
"""
import ast
import logging
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.bgwriter import OrderedBackgroundWriter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_wrap_คืนทันทีไม่รองานเสร็จ():
    w = OrderedBackgroundWriter("t")
    gate = threading.Event()
    f = w.wrap(lambda: gate.wait(2))
    t0 = time.perf_counter()
    assert f() is None
    assert time.perf_counter() - t0 < 0.05, "ต้องไม่บล็อกผู้เรียก (event loop)"
    gate.set()
    w.close(wait_for_test=True)


def test_ลำดับการเขียนตรงกับลำดับที่ส่ง_แม้งานแรกช้า():
    w = OrderedBackgroundWriter("t")
    out = []

    def save(tag, delay):
        time.sleep(delay)
        out.append(tag)

    s = w.wrap(save)
    s("user-1", 0.2)       # ช้า
    s("ai-1", 0.0)         # เร็ว — ต้องไม่แซง
    s("user-2", 0.05)
    w.close(wait_for_test=True)
    assert out == ["user-1", "ai-1", "user-2"]


def test_งานโยน_exception_ต้องมี_log_และงานถัดไปยังทำงาน(caplog):
    w = OrderedBackgroundWriter("voice-save")
    out = []

    def boom():
        raise RuntimeError("database is locked")

    with caplog.at_level(logging.ERROR, logger="utils.bgwriter"):
        w.wrap(boom)()
        w.wrap(lambda: out.append("ok"))()
        w.close(wait_for_test=True)
    assert out == ["ok"]
    assert any("database is locked" in r.getMessage() and "voice-save" in r.getMessage() for r in caplog.records)


def test_close_ไม่ทิ้งงานที่ค้าง_และ_then_รันเป็นงานสุดท้าย():
    w = OrderedBackgroundWriter("t")
    out = []
    s = w.wrap(lambda x: (time.sleep(0.05), out.append(x)))
    s(1)
    s(2)
    w.close(then=lambda: out.append("summary"))
    deadline = time.time() + 2
    while len(out) < 3 and time.time() < deadline:
        time.sleep(0.01)
    assert out == [1, 2, "summary"], "สรุปต้องออกหลังบันทึกทุกรายการ"


def test_close_คืนทันที(monkeypatch):
    w = OrderedBackgroundWriter("t")
    gate = threading.Event()
    w.wrap(lambda: gate.wait(2))()
    t0 = time.perf_counter()
    w.close()
    assert time.perf_counter() - t0 < 0.05, "ปิดสายต้องไม่ค้างรอ DB"
    gate.set()


# ── wiring ใน server.py ─────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def voice():
    with open(os.path.join(ROOT, "server.py"), encoding="utf-8") as f:
        tree = ast.parse(f.read())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "voice_websocket")
    return ast.unparse(fn)


def test_voice_ห่อ_save_msg_ด้วย_writer_ที่บรรทัด_import(voice):
    assert "_writer = OrderedBackgroundWriter('voice-save')" in voice
    assert "_save_msg = _writer.wrap(_loop_timer.wrap('save_msg', _save_msg_raw))" in voice


def test_voice_ปิด_writer_ตอนปิดสายและสรุปหลังบันทึกเสร็จ(voice):
    assert "_writer.close(then=" in voice and "_loop_timer.summary()" in voice
    reader_like = voice.split("finally:")[-1]
    assert "_writer.close(then=" in reader_like
