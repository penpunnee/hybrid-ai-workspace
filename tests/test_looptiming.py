"""จับเวลางาน sync บน event loop ของ WS (/ws/voice · /ws/reader) — ขั้น 5B 2026-09-29 (วัดเท่านั้น 🔒 ห้ามแตะค่าเสียง)

`log_timing` (core/observability.py) ใช้ไม่ได้ที่นี่ — มันเก็บค่าใน contextvar ให้ /api/chat ใส่ใน `done` **ไม่เขียน log**
⇒ ตัวจับเวลาของ WS ต้อง log เอง: WARNING เฉพาะ call ที่เกิน 50 ms + บรรทัดสรุปตอนปิดสาย
ห่อ object ครั้งเดียวที่บรรทัด import (ไม่ใช่ call site) — เทสเดิมยึดข้อความ `_marks.set(source, new_pos)` /
`_save_msg(asst_name, "user"` ไว้ และ `_marks.set()` ต้องยัง sync (ที่คั่นไม่เสียหายเมื่อถูก cancel — server.py:923)
"""
import ast
import logging
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils.looptiming as lt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


@pytest.fixture
def clock(monkeypatch):
    c = _Clock()
    monkeypatch.setattr(lt, "_now", c)
    return c


def _slow(clock, ms, ret=None, exc=None):
    def fn(*a, **k):
        clock.t += ms / 1000
        if exc:
            raise exc
        return (a, k, ret)
    return fn


def test_wrap_คืนผลเดิมและส่งอาร์กิวเมนต์ครบ(clock):
    t = lt.SyncCallTimer("voice")
    f = t.wrap("save_msg", _slow(clock, 1, ret="ok"))
    assert f(1, 2, x=3) == ((1, 2), {"x": 3}, "ok")


def test_exception_ส่งต่อเหมือนเดิมและยังถูกนับ(clock):
    t = lt.SyncCallTimer("voice")
    f = t.wrap("save_msg", _slow(clock, 2, exc=ValueError("db locked")))
    with pytest.raises(ValueError, match="db locked"):
        f()
    assert "save_msg n=1" in t.summary()


def test_log_warning_เฉพาะที่เกินเกณฑ์(clock, caplog):
    t = lt.SyncCallTimer("reader", slow_ms=50)
    fast, slow = t.wrap("marks.get", _slow(clock, 49)), t.wrap("marks.set", _slow(clock, 51))
    with caplog.at_level(logging.INFO, logger="utils.looptiming"):
        fast()
        slow()
    warns = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warns) == 1 and "reader" in warns[0] and "marks.set" in warns[0] and "51" in warns[0]


def test_summary_นับ_max_total(clock):
    t = lt.SyncCallTimer("reader")
    g = t.wrap("marks.get", _slow(clock, 3))
    g(); g()
    t.wrap("marks.get", _slow(clock, 10))()
    s = t.summary()
    assert "marks.get n=3" in s and "max=10.0ms" in s and "total=16.0ms" in s


def test_always_อยู่ในสรุปแม้ไม่ถูกเรียก():
    t = lt.SyncCallTimer("reader", always=("books.text",))
    assert "books.text n=0" in t.summary()


def test_proxy_ห่อเฉพาะ_callable_และส่งผ่าน_attribute_อื่น(clock):
    class Store:
        path = "/data/reader.db"

        def get(self, src):
            clock.t += 0.002
            return f"pos:{src}"

    t = lt.SyncCallTimer("reader")
    p = t.proxy(Store(), "marks")
    assert p.path == "/data/reader.db"
    assert p.get("book1") == "pos:book1"
    assert "marks.get n=1" in t.summary()


def test_proxy_ไม่มี_await_คงเป็น_sync(clock):
    """_marks.set ต้องเสร็จในจังหวะเดียวกับที่เรียก (cancel-safety) — ผลต้องไม่ใช่ coroutine"""
    import inspect
    t = lt.SyncCallTimer("reader")
    p = t.proxy(type("S", (), {"set": lambda self, s, n: n})(), "marks")
    assert not inspect.iscoroutine(p.set("a", 5)) and p.set("a", 5) == 5


# ── wiring ใน server.py ─────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def src():
    with open(os.path.join(ROOT, "server.py"), encoding="utf-8") as f:
        return f.read()


def _func(src, name):
    tree = ast.parse(src)
    return next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == name)


def test_voice_ห่อ_save_msg_ที่บรรทัด_import_และสรุปตอนปิดสาย(src):
    voice = ast.unparse(_func(src, "voice_websocket"))
    assert "_save_msg = _loop_timer.wrap('save_msg'" in voice
    assert "SyncCallTimer('voice')" in voice
    assert "_loop_timer.summary()" in voice


def test_reader_ห่อ_books_marks_และ_books_text_อยู่ในสรุปเสมอ(src):
    reader = ast.unparse(_func(src, "reader_websocket"))
    assert "SyncCallTimer('reader', always=('books.text',))" in reader
    assert "_loop_timer.proxy(_books_raw, 'books')" in reader and "_loop_timer.proxy(_marks_raw, 'marks')" in reader
    assert "_loop_timer.summary()" in reader


def test_call_site_ไม่เปลี่ยนแม้แต่ตัวเดียว(src):
    """นับก่อนแก้ (2026-09-29): _marks.get( 4 · _marks.set( 3 (รวมคอมเมนต์ :923) · _books.text( 1 · _save_msg( 2"""
    assert (src.count("_marks.get("), src.count("_marks.set("), src.count("_books.text("),
            src.count("_save_msg(")) == (4, 3, 1, 2)
    assert src.count("_marks.set(source, new_pos)") == 2
