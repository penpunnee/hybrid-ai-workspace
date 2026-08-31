"""Brave Search เป็น provider ตัวแรกของชั้นค้นเว็บ

ทำไมต้องมี (วัดจริงบน prod 2026-08-31): ชั้นค้นเว็บเหลือ DDG ตัวเดียว —
Gemini grounding 429 ทุกครั้ง (free tier ไม่เปิด grounding) และ Google CSE
403 ทุกครั้ง (คีย์อยู่คนละ Cloud project กับที่เปิด API ไว้) ผลคือถามราคาเกม
แล้ว DDG คืนเว็บโป๊มาเป็นผลค้น

user เลือก Brave เพราะ **ไม่ผูกกับ Google Cloud project** ที่ย้ายไปมา
— ต้นตอของการวนแก้คีย์รอบนี้

⚠️ กับดักที่เทสชุดนี้ตรึงไว้ 2 ข้อ:
1. free tier = **1 คำขอ/วินาที** แต่ `_web_search_impl` ยิง sub-query รัวติดกัน
   2-3 ตัวในลูปเดียว ⇒ ตัวที่ 2 เป็นต้นไปโดน 429 แน่ถ้าไม่มีตัวหน่วง
2. ห้ามกลืน HTTP error เป็น "ผลว่าง" — บทเรียนสดๆ จาก _google_search ที่
   403 มา 48/48 ครั้งโดยไม่มีใครรู้ (commit 436f22b)
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


_OK = {"web": {"results": [
    {"title": "GTA V on Steam", "description": "฿499",
     "url": "https://store.steampowered.com/app/271590"},
    {"title": "GTA V ราคา", "description": "ลด 60%", "url": "https://x.co/2"},
]}}


@pytest.fixture()
def brave_key(monkeypatch):
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "bk")
    # ตัวหน่วงต้องไม่ทำให้ชุดเทสช้า — และการที่มันถูก "ปิดได้" ก็ต้องเทสด้วย
    monkeypatch.setattr(websearch, "_brave_last_call", 0.0, raising=False)


def _patch_get(monkeypatch, resp, sink=None):
    def fake_get(url, **kw):
        if sink is not None:
            sink.append((url, kw))
        return resp
    monkeypatch.setattr(requests, "get", fake_get)


# ── การแปลงผล ────────────────────────────────────────────────────────────────

def test_แปลงผลเป็นรูปเดียวกับ_provider_ตัวอื่น(monkeypatch, brave_key):
    """title/body/href — ผู้เรียกทั้งเส้นคาดรูปนี้ ห้ามคืนรูปของ Brave ดิบ"""
    _patch_get(monkeypatch, _Resp(200, _OK))

    got = websearch._brave_search("ราคา GTA V Steam", max_results=5)

    assert got == [
        {"title": "GTA V on Steam", "body": "฿499",
         "href": "https://store.steampowered.com/app/271590"},
        {"title": "GTA V ราคา", "body": "ลด 60%", "href": "https://x.co/2"},
    ]


def test_ส่ง_token_ทาง_header_ไม่ใช่_query_string(monkeypatch, brave_key):
    """คีย์ห้ามไปโผล่ใน URL — URL ถูก log/แคชได้ ส่วน header ไม่"""
    calls = []
    _patch_get(monkeypatch, _Resp(200, _OK), sink=calls)

    websearch._brave_search("อะไรก็ได้")

    url, kw = calls[0]
    assert "bk" not in url
    assert "bk" not in str(kw.get("params", {}))
    assert kw["headers"]["X-Subscription-Token"] == "bk"


def test_ขอ_safesearch_เข้มที่ต้นทาง(monkeypatch, brave_key):
    """แก้เว็บโป๊ที่ต้นตอ ไม่ใช่มาตัดทีหลังด้วยพื้นคะแนนอย่างเดียว

    DDG รับ safesearch='on' แล้วไม่กรองให้จริง (มีเทสยืนยันอยู่แล้ว) — ของ Brave
    ต้องขอ ไม่ใช่เพราะเชื่อว่าได้ผล แต่เพราะไม่ขอแล้วแน่ๆ ว่าไม่ได้
    """
    calls = []
    _patch_get(monkeypatch, _Resp(200, _OK), sink=calls)

    websearch._brave_search("ราคา GTA V")

    assert calls[0][1]["params"]["safesearch"] == "strict"


# ── ความล้มเหลวต้องดัง ───────────────────────────────────────────────────────

def test_http_error_ต้องเป็น_error_ไม่ใช่ผลว่างเงียบ(monkeypatch, brave_key, caplog):
    _patch_get(monkeypatch, _Resp(422, {"error": {"detail": "SUBSCRIPTION_TOKEN_INVALID"}}))

    with caplog.at_level(logging.DEBUG, logger=websearch.logger.name):
        assert websearch._brave_search("q") == []

    errs = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errs, "HTTP error ถูกกลืนเงียบ — ซ้ำรอย _google_search 403 ที่รอดมา 48 ครั้ง"
    assert "422" in errs[0].getMessage()


def test_ไม่มีคีย์_ต้องไม่ยิงเน็ตเลย(monkeypatch, caplog):
    """ปล่อยว่าง = ปิด — ต้องเงียบสนิท ไม่ใช่ยิงแล้วได้ 401 แล้วบ่นทุกครั้ง"""
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    calls = []
    _patch_get(monkeypatch, _Resp(200, _OK), sink=calls)

    with caplog.at_level(logging.DEBUG, logger=websearch.logger.name):
        assert websearch._brave_search("q") == []

    assert calls == [], "ไม่มีคีย์แต่ยังยิงคำขอออกไป"
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


# ── ตัวหน่วง 1 คำขอ/วินาที ───────────────────────────────────────────────────

def test_ยิงติดกันต้องถูกหน่วงให้ห่างกันอย่างน้อย_1_วินาที(monkeypatch, brave_key):
    """free tier = 1 req/s · `_web_search_impl` ยิง sub-query ติดกันในลูปเดียว

    ไม่มีตัวหน่วง = คำขอที่ 2 เป็นต้นไปได้ 429 ทุกครั้ง แล้วเราจะไปสรุปผิดว่า
    "Brave ก็ใช้ไม่ได้" ทั้งที่เป็นความผิดของฝั่งเราเอง
    """
    _patch_get(monkeypatch, _Resp(200, _OK))
    slept = []
    monkeypatch.setattr(websearch.time, "sleep", lambda s: slept.append(s))
    clock = [100.0]
    monkeypatch.setattr(websearch.time, "monotonic", lambda: clock[0])

    websearch._brave_search("q1")
    clock[0] += 0.2          # ยิงตัวถัดไปหลังผ่านไปแค่ 0.2 วิ
    websearch._brave_search("q2")

    assert slept, "ยิงติดกัน 0.2 วิ แต่ไม่มีการหน่วงเลย"
    assert sum(slept) >= 0.8, f"หน่วงน้อยเกินกว่าจะกัน 429: {slept}"


def test_เว้นช่วงนานพอแล้วต้องไม่หน่วงซ้ำ(monkeypatch, brave_key):
    """กลุ่มควบคุม — ตัวหน่วงที่หน่วงทุกครั้งคือการทำให้ทุกคำค้นช้าลงฟรีๆ"""
    _patch_get(monkeypatch, _Resp(200, _OK))
    slept = []
    monkeypatch.setattr(websearch.time, "sleep", lambda s: slept.append(s))
    clock = [100.0]
    monkeypatch.setattr(websearch.time, "monotonic", lambda: clock[0])

    websearch._brave_search("q1")
    clock[0] += 5.0
    websearch._brave_search("q2")

    assert not slept, f"เว้นมา 5 วิแล้วยังหน่วงอีก: {slept}"


# ── ลำดับใน search_web ───────────────────────────────────────────────────────

def test_มีคีย์_brave_แล้วต้องไม่แตะ_google(monkeypatch, brave_key):
    """Brave มาก่อน — และเมื่อ Brave ได้ผล ต้องไม่ยิง Google ที่ 403 อยู่

    สำคัญกว่าเรื่องลำดับ: _google_search ตอนนี้ log ERROR ทุกครั้งที่ล้ม
    ถ้ายังถูกเรียกทั้งที่ Brave สำเร็จแล้ว = ปลุกเสียงเตือนทุกคำค้นจนคนเลิกฟัง
    """
    _patch_get(monkeypatch, _Resp(200, _OK))
    monkeypatch.setattr(websearch, "_google_search",
                        lambda *a, **k: pytest.fail("Brave สำเร็จแล้วแต่ยังเรียก Google"))
    monkeypatch.setattr(websearch, "_ddg_search",
                        lambda *a, **k: pytest.fail("Brave สำเร็จแล้วแต่ยังเรียก DDG"))

    got = websearch.search_web("ราคา GTA V Steam")

    assert [r["href"] for r in got] == [
        "https://store.steampowered.com/app/271590", "https://x.co/2"]


def test_brave_ล้มแล้วยังตกไป_ddg_ได้เหมือนเดิม(monkeypatch, brave_key):
    """กลุ่มควบคุม — เพิ่มชั้นบนสุดต้องไม่ทำให้ชั้นล่างที่ยังทำงานอยู่หายไป"""
    monkeypatch.setattr(websearch, "_brave_search", lambda *a, **k: [])
    monkeypatch.setattr(websearch, "_google_search", lambda *a, **k: [])
    monkeypatch.setattr(websearch, "_ddg_search",
                        lambda *a, **k: [{"title": "t", "body": "b", "href": "https://d/1"}])

    got = websearch.search_web("q")

    assert got == [{"title": "t", "body": "b", "href": "https://d/1"}]
