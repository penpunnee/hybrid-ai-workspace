"""`utils.memory._get_client()` ต้องไม่ถือ lock ค้างตอน ChromaDB ต่อไม่ได้ (audit 2026-09-24 MEDIUM ข้อ 6)

chromadb 1.5.9 สร้าง `httpx.Client(timeout=None)` แบบ hardcode (`chromadb/api/fastapi.py`) และ
`_get_client()` เรียก `HttpClient()+heartbeat()` **ใต้ `_lock`** ⇒ host ที่ black-hole = ทุก thread ที่
เรียก memory ต่อคิวหลัง lock จน threadpool (40) หมด · แก้: (1) TCP pre-check สั้นๆ ก่อนสร้าง client
(2) จำว่าล้มไว้ `_CONNECT_RETRY_SEC` วิ — ระหว่างนั้นคืน None ทันทีไม่แตะ lock/เน็ต
(3) ตั้ง timeout ให้ session ของ client ที่สร้างสำเร็จ (best-effort ผ่าน private attr) กันเคส Chroma ตายทีหลัง
"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import chromadb
import httpx
import utils.memory as um


@pytest.fixture(autouse=True)
def _reset():
    um._client = None
    um._collections = {}
    um._last_connect_fail = 0.0
    yield
    um._client = None
    um._collections = {}
    um._last_connect_fail = 0.0


def _fake_client_factory(calls, heartbeat_ok=True):
    class _Sess:
        timeout = None
    class _Server:
        _session = _Sess()
    class _Client:
        _server = _Server()
        def heartbeat(self):
            if not heartbeat_ok:
                raise ConnectionError("down")
            return 1
    def factory(**kw):
        calls.append(kw)
        return _Client()
    return factory


def test_host_ต่อไม่ได้_คืน_None_โดยไม่สร้าง_HttpClient(monkeypatch):
    monkeypatch.setattr(um, "_tcp_reachable", lambda h, p, t: False)
    def must_not(**kw):
        raise AssertionError("ห้ามสร้าง HttpClient เมื่อ TCP ต่อไม่ถึง (จะไปค้างใน httpx timeout=None ใต้ lock)")
    monkeypatch.setattr(chromadb, "HttpClient", must_not)
    assert um._get_client() is None


def test_จำว่าล้ม_ไม่_probe_ซ้ำจนพ้นช่วงพัก(monkeypatch):
    probes = []
    monkeypatch.setattr(um, "_tcp_reachable", lambda h, p, t: probes.append(1) is None and False)
    assert um._get_client() is None
    assert um._get_client() is None
    assert len(probes) == 1, "ภายในช่วงพักต้องคืน None ทันที ไม่ probe ซ้ำ (ทุก turn เรียก _get_client หลายครั้ง)"
    um._last_connect_fail = time.monotonic() - um._CONNECT_RETRY_SEC - 1
    assert um._get_client() is None
    assert len(probes) == 2, "พ้นช่วงพักแล้วต้องลองใหม่"


def test_heartbeat_ล้ม_ก็จำว่าล้ม_ไม่สร้างซ้ำทันที(monkeypatch):
    monkeypatch.setattr(um, "_tcp_reachable", lambda h, p, t: True)
    calls = []
    monkeypatch.setattr(chromadb, "HttpClient", _fake_client_factory(calls, heartbeat_ok=False))
    assert um._get_client() is None
    assert um._get_client() is None
    assert len(calls) == 1


def test_ต่อได้_สร้าง_client_และตั้ง_timeout_ให้_session(monkeypatch):
    monkeypatch.setattr(um, "_tcp_reachable", lambda h, p, t: True)
    calls = []
    monkeypatch.setattr(chromadb, "HttpClient", _fake_client_factory(calls))
    c = um._get_client()
    assert c is not None and len(calls) == 1
    assert c._server._session.timeout == httpx.Timeout(um._CHROMA_HTTP_TIMEOUT), \
        "session ของ chromadb เกิดมาเป็น timeout=None — ต้องตั้งเพดานให้ ไม่งั้น Chroma ตายทีหลัง = thread ค้างถาวร"
    assert um._get_client() is c, "สร้างครั้งเดียวแล้ว cache"


def test_pre_check_ต้องสั้น_ไม่ใช่รอ_TCP_ของ_OS():
    assert 0 < um._CONNECT_PROBE_SEC <= 3.0


def test_สมมติฐานเรื่องลิบ_chromadb_ยังจริง():
    """ถ้าวันหนึ่ง chromadb เลิก hardcode timeout=None หรือย้าย `_server._session` เทสนี้แดง → ทบทวนว่ายังต้อง override ไหม"""
    import inspect
    import chromadb.api.fastapi as fa
    src = inspect.getsource(fa)
    assert "httpx.Client(" in src and "timeout=None" in src
    assert "self._session" in src


def test_ช่วงจำว่าล้ม_ต้องไม่รอ_lock(monkeypatch):
    """หัวใจของข้อ 6: ตอน Chroma ล่ม thread ที่แตะ memory ต้องคืน None ทันที ไม่ต่อคิวหลัง `_lock`
    (จำลอง: เทสถือ lock ไว้เอง — ถ้า _get_client เข้า lock จะค้าง)"""
    import threading
    um._last_connect_fail = time.monotonic()          # เพิ่งล้ม
    result = {}
    um._lock.acquire()
    try:
        t = threading.Thread(target=lambda: result.setdefault("v", um._get_client()), daemon=True)
        t.start()
        t.join(1.0)
        assert not t.is_alive(), "_get_client() ไปรอ lock ทั้งที่รู้อยู่แล้วว่าเพิ่งล้ม"
        assert result["v"] is None
    finally:
        um._lock.release()
