"""DDG fallback hardening — กันผลขยะ/NSFW ที่ DDG คืนมาตอนโดน throttle

ทำไมสำคัญ: เจอจริง 2026-06-15 — Google CSE ใช้ไม่ได้ (key/project 403) → ตก DDG
ซึ่งบางครั้งโดน throttle แล้วคืนผลไม่เกี่ยว (คลิปโป๊/MV) สำหรับคำถาม "ราคาทอง"

fix แบบพอดี (2 จุด ใน search_web):
1. safesearch="on" — ตัด NSFW ที่ต้นทาง DDG
2. retry 1 ครั้งถ้ารอบแรกคืนผลว่าง — กัน throttle ชั่วคราว
"""
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import websearch


def test_ddg_safesearch_defaults_on():
    """ค่า default ของ safesearch ต้องเป็น 'on' (เดิม 'moderate' ปล่อย NSFW หลุด)"""
    sig = inspect.signature(websearch._ddg_search)
    assert sig.parameters["safesearch"].default == "on"


def test_retries_once_when_first_empty(monkeypatch):
    """รอบแรกว่าง (throttle) → ลองซ้ำอีกครั้ง → ได้ผลรอบสอง"""
    calls = {"n": 0}

    def fake_ddg(query, max_results, region="th-th", safesearch="on"):
        calls["n"] += 1
        return [] if calls["n"] == 1 else [{"title": "ราคาทอง", "href": "https://sanook.com"}]

    monkeypatch.setattr(websearch, "_google_search", lambda q, n=5: [])
    monkeypatch.setattr(websearch, "_ddg_search", fake_ddg)
    out = websearch.search_web("ราคาทอง", 5)
    assert calls["n"] == 2
    assert out and out[0]["title"] == "ราคาทอง"


def test_no_retry_when_first_ok(monkeypatch):
    """รอบแรกมีผล → ไม่ต้อง retry (ไม่ยิงซ้ำเปล่าๆ)"""
    calls = {"n": 0}

    def fake_ddg(query, max_results, region="th-th", safesearch="on"):
        calls["n"] += 1
        return [{"title": "ok", "href": "https://x.com"}]

    monkeypatch.setattr(websearch, "_google_search", lambda q, n=5: [])
    monkeypatch.setattr(websearch, "_ddg_search", fake_ddg)
    out = websearch.search_web("q", 5)
    assert calls["n"] == 1
    assert out[0]["title"] == "ok"
