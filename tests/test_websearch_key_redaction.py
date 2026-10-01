"""คีย์ค้นเว็บต้องไม่หลุดลง log (audit 2026-09-24 MEDIUM ข้อ 3 · user เคาะ (ก) 09-25)

วัดจริงบน prod (สมัยยังมี Google CSE): `str(requests.ConnectionError)` มี URL เต็มพร้อม `?key=...`
แล้ว log `f"{e}"` ระดับ WARNING → คีย์อยู่ใน server.log · ปิด 2 ชั้น: (1) ส่งคีย์ทาง header
= ไม่อยู่ใน URL ตั้งแต่แรก (2) `_redact_secrets()` ก่อน log เผื่อ error อื่นสะท้อนค่ากลับมา

2026-10-01 ถอด Google CSE ออก (ปิดรับลูกค้าใหม่ · ปิดถาวร 2027-01-01) ⇒ ย้ายด่านมาคุม Brave
ซึ่งเป็น provider ที่มีคีย์ตัวเดียวที่เหลือ — เดิม Brave log `{e}` ดิบโดยไม่ผ่าน redact
"""
import os
import sys
import logging

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import websearch

SECRET = "BSAsecretTOKEN123456"


@pytest.fixture
def _keys(monkeypatch):
    monkeypatch.setattr(websearch, "BRAVE_SEARCH_API_KEY", SECRET)
    monkeypatch.setattr(websearch, "_brave_min_interval", lambda: 0.0)


def test_คีย์ต้องอยู่ใน_header_ไม่ใช่_query_string(monkeypatch, _keys):
    seen = {}

    class _R:
        status_code = 200
        def json(self): return {"web": {"results": []}}

    def fake_get(url, **kw):
        seen.update(kw); seen["url"] = url
        return _R()

    monkeypatch.setattr(requests, "get", fake_get)
    websearch._brave_search("x")
    assert SECRET not in str(seen.get("params", {})), "คีย์ใน params = โผล่ใน URL ของทุก exception/log ของ requests"
    assert seen.get("headers", {}).get("X-Subscription-Token") == SECRET
    assert SECRET not in seen["url"]


def test_exception_ที่สะท้อนคีย์ต้องไม่ทำคีย์หลุดลง_log(monkeypatch, _keys, caplog):
    def boom(*a, **k):
        raise requests.exceptions.ConnectionError(
            f"HTTPSConnectionPool(host='api.search.brave.com'): Max retries exceeded with url: "
            f"/res/v1/web/search?q=x&token={SECRET} (Caused by NameResolutionError)")
    monkeypatch.setattr(requests, "get", boom)
    with caplog.at_level(logging.DEBUG, logger="utils.websearch"):
        assert websearch._brave_search("x") == []
    assert any("[Brave]" in r.getMessage() for r in caplog.records), "ต้องยัง log ว่าค้นล้ม"
    assert SECRET not in caplog.text, "คีย์หลุดลง log"


def test_redact_ลบทั้งค่าคีย์และรูปแบบ_key_equals():
    msg = f"url ?key={SECRET}&cx=1 และค่าเปล่าๆ {SECRET} และ key=abc"
    out = websearch._redact_secrets(msg, [SECRET])
    assert SECRET not in out
    assert "key=abc" not in out, "รูปแบบ key=<ค่า> ต้องถูกบังไม่ว่าจะเป็นคีย์ตัวไหน"
    assert "cx=1" in out, "ค่าที่ไม่ใช่ความลับต้องยังอยู่ให้ debug ได้"
