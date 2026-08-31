"""_google_search ต้องแยก "ค้นไม่ได้" ออกจาก "ค้นแล้วไม่เจอ"

เหตุที่ต้องมีเทสชุดนี้ (วัดจริงบน prod 2026-08-31):
คีย์ CSE อยู่ในโปรเจกต์ที่ไม่ได้เปิด Custom Search JSON API → ทุกคำขอได้
`403 PERMISSION_DENIED` แต่โค้ดอ่านแค่ `resp.json().get("items", [])` ⇒ 403
กลายเป็น "ไม่มี items" แล้ว log ว่า `INFO [Google] '…' → 0 results` ซึ่งอ่านแล้ว
เหมือน "ค้นแล้วไม่เจอ" ทั้งที่จริงคือ "ค้นไม่ได้เลย"

ผลคือชั้นค้นเว็บที่ดีที่สุดตายเงียบ **48/48 ครั้ง** เท่าที่ log ย้อนไปถึง โดยไม่มี
สัญญาณอะไรเลย เหลือแต่ DDG ที่คืนเว็บโป๊มาเป็นผลค้นราคาเกม

⚠️ เทสนี้ยืนยัน "สิ่งที่เราได้กลับมา" (log + ค่าคืน) ไม่ใช่ "สิ่งที่เราส่งไป" —
บทเรียนจาก test_embed_fallback_uses_same_model_name ที่ตรวจผิดฝั่งจนบั๊กรอด 22 วัน
"""
import logging

import pytest
import requests

from utils import websearch


class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def _keys(monkeypatch):
    monkeypatch.setenv("GOOGLE_SEARCH_API_KEY", "k")
    monkeypatch.setenv("GOOGLE_SEARCH_CX", "cx")


def _patch(monkeypatch, resp):
    # `_google_search` ทำ `import requests` ข้างในฟังก์ชัน → ต้อง patch ที่ตัวโมดูล
    # จริง ไม่ใช่ที่ namespace ของ utils.websearch (ซึ่งไม่มีชื่อนี้อยู่เลย)
    monkeypatch.setattr(requests, "get", lambda *a, **k: resp)


_FORBIDDEN = {"error": {"code": 403, "status": "PERMISSION_DENIED",
                        "message": "This project does not have the access to "
                                   "Custom Search JSON API."}}


def test_http_403_ถูกรายงานเป็น_error_ไม่ใช่_ผลลัพธ์ว่าง(monkeypatch, caplog):
    """เคสจริงบน prod — ต้องดังพอให้คนเห็นก่อนครบสัปดาห์"""
    _patch(monkeypatch, _Resp(403, _FORBIDDEN))

    with caplog.at_level(logging.DEBUG, logger=websearch.logger.name):
        assert websearch._google_search("ราคา GTA V Steam") == []

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors, "403 ถูกกลืนเงียบ — ไม่มี log ระดับ ERROR เลย"
    msg = errors[0].getMessage()
    assert "403" in msg, f"ไม่บอกรหัสสถานะ: {msg}"
    assert "Custom Search JSON API" in msg, f"ไม่พาสาเหตุจริงมาด้วย: {msg}"


def test_http_429_ก็ต้องดัง_ไม่ใช่เฉพาะ_403(monkeypatch, caplog):
    """กันการ 'แก้' ด้วยการ hardcode เช็คแค่ 403 ใบเดียว"""
    _patch(monkeypatch, _Resp(429, {"error": {"code": 429, "status":
                                              "RESOURCE_EXHAUSTED",
                                              "message": "Quota exceeded."}}))

    with caplog.at_level(logging.DEBUG, logger=websearch.logger.name):
        assert websearch._google_search("อะไรก็ได้") == []

    assert [r for r in caplog.records if r.levelno >= logging.ERROR], \
        "429 ถูกกลืนเงียบ"


def test_ค้นสำเร็จแต่ไม่เจอ_ต้องไม่ถูกรายงานเป็น_error(monkeypatch, caplog):
    """กลุ่มควบคุม — 200 + ไม่มี items คือ 'ไม่เจอ' จริงๆ ห้ามตีเป็นความพัง

    ตัวเตือนที่ดังผิดเรื่องคือทางที่ทำให้คนเลิกฟังเสียงเตือน ซึ่งแย่กว่าไม่มีเสียงเตือน
    """
    _patch(monkeypatch, _Resp(200, {}))

    with caplog.at_level(logging.DEBUG, logger=websearch.logger.name):
        assert websearch._google_search("คำที่ไม่มีใครเขียนถึง") == []

    assert not [r for r in caplog.records if r.levelno >= logging.ERROR], \
        "ผลว่างที่ HTTP 200 ไม่ใช่ความล้มเหลว แต่ถูกรายงานเป็น error"


def test_ค้นสำเร็จและเจอ_ยังคืนผลเหมือนเดิม(monkeypatch, caplog):
    """กลุ่มควบคุมเส้นสุข — เส้นที่ทำงานอยู่ต้องไม่เปลี่ยนพฤติกรรม"""
    _patch(monkeypatch, _Resp(200, {"items": [
        {"title": "GTA V on Steam", "snippet": "฿499", "link": "https://s.co/1"}]}))

    with caplog.at_level(logging.DEBUG, logger=websearch.logger.name):
        got = websearch._google_search("ราคา GTA V Steam")

    assert got == [{"title": "GTA V on Steam", "body": "฿499",
                    "href": "https://s.co/1"}]
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
