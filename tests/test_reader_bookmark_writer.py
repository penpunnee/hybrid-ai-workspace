"""`BookmarkStore.set` ต้องไม่บล็อก event loop ของ /ws/reader (วัด prod 09-30: 559–619 ms ต่อท่อน)

ต้นเหตุ: เปิด connection ใหม่ + commit บน journal=delete/synchronous=FULL ทุกครั้ง = fsync บน RAID5
probe บน NAS: WAL+NORMAL+connection ค้าง = 0 ms หลังครั้งแรก · WAL+NORMAL เปิดใหม่ทุกครั้ง 281 ms
⇒ ตัวที่ได้ผลคือ "connection ค้าง" — เทสจึงตรึงจำนวน connect ไม่ใช่แค่ว่าเขียนได้
⚠️ set ยังต้อง sync + commit ก่อนคืนค่า (ที่คั่นไม่เสียหายเมื่อ task ถูก cancel — server.py)
"""
import sqlite3
import threading

import pytest

import utils.reader as ur


@pytest.fixture()
def counting_connect(monkeypatch):
    calls = []
    real = sqlite3.connect

    def spy(*a, **kw):
        calls.append(a[0] if a else kw.get("database"))
        return real(*a, **kw)

    monkeypatch.setattr(ur.sqlite3, "connect", spy)
    return calls


def test_set_หลายครั้งเปิด_connection_ครั้งเดียว(tmp_path, counting_connect):
    store = ur.BookmarkStore(str(tmp_path / "r.db"))
    before = len(counting_connect)
    for i in range(5):
        store.set("นิยาย.pdf", i * 100)
    store.clear("นิยาย.pdf")
    store.set("นิยาย.pdf", 777)
    assert len(counting_connect) - before <= 1


def test_writer_เป็น_WAL_และ_NORMAL(tmp_path):
    p = str(tmp_path / "r.db")
    store = ur.BookmarkStore(p)
    store.set("x", 1)
    w = store._writer_conn
    assert w is not None
    assert w.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert w.execute("PRAGMA synchronous").fetchone()[0] == 1   # NORMAL


def test_commit_แล้วก่อนคืนค่า_connection_อื่นเห็นทันที(tmp_path):
    p = str(tmp_path / "r.db")
    store = ur.BookmarkStore(p)
    store.set("นิยาย.pdf", 4321)
    other = sqlite3.connect(p)
    try:
        row = other.execute("SELECT pos FROM reading_progress WHERE source=?", ("นิยาย.pdf",)).fetchone()
    finally:
        other.close()
    assert row == (4321,)


def test_เขียนพร้อมกันหลาย_thread_ไม่พัง(tmp_path):
    # WS เขียนบน event loop · HTTP seek/next เขียนใน threadpool — connection เดียวกันต้องมี lock
    store = ur.BookmarkStore(str(tmp_path / "r.db"))
    errors = []

    def work(k):
        try:
            for i in range(30):
                store.set(f"b{k}", i)
        except Exception as e:  # pragma: no cover - ใช้เก็บ error จาก thread
            errors.append(e)

    ts = [threading.Thread(target=work, args=(k,)) for k in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert errors == []
    assert [store.get(f"b{k}") for k in range(4)] == [29] * 4


def test_error_ทิ้ง_connection_แล้วครั้งหน้าเปิดใหม่(tmp_path):
    store = ur.BookmarkStore(str(tmp_path / "r.db"))
    store.set("x", 1)
    store._writer_conn.close()          # จำลอง connection เสีย
    with pytest.raises(sqlite3.Error):
        store.set("x", 2)
    store.set("x", 3)                   # ต้องกลับมาใช้ได้เอง
    assert store.get("x") == 3
