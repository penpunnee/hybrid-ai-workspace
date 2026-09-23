"""Web search ต้องป้อนเนื้อหาให้โมเดลพอที่จะตอบละเอียด — ไม่ใช่ snippet สั้นๆ

ทำไมสำคัญ: user รายงาน (2026-06-11) ว่าคำตอบจาก web_search "รายละเอียดจำกัด ตอบสั้น"
root cause: _extract_text ตัดที่ 1,500 ตัวอักษร/หน้า + fetch แค่ 2 หน้าแรก
+ format_for_context ตัด fetched[:1500] snippet[:300] → โมเดลเห็นรวม ~3k ตัวอักษร
"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import websearch


def _fake_results(n=5):
    return [
        {"title": f"ผลที่ {i}", "body": "สรุปย่อ " * 40, "href": f"https://example{i}.com/a"}
        for i in range(1, n + 1)
    ]


class TestExtractTextDepth:
    def test_keeps_long_article_content(self):
        """บทความยาว 4,000 ตัวอักษร ต้องเหลือเนื้อหา ≥ 2,400 (เดิมตัดทิ้งที่ 1,500)"""
        body = "เนื้อหาบทความสำคัญมาก " * 200  # ~4,400 chars
        html = f"<html><body><article>{body}</article></body></html>"
        text = websearch._extract_text(html)
        assert len(text) >= 2400, f"เนื้อหาโดนตัดเหลือ {len(text)} ตัวอักษร"


class TestEnrichDepth:
    def test_fetches_top3_pages_by_default(self):
        """ต้อง fetch เนื้อหาจริงอย่างน้อย 3 หน้าแรก (เดิม 2)"""
        calls = []
        with patch.object(websearch, "_fetch_url", side_effect=lambda u: calls.append(u) or "เนื้อหา"):
            websearch._enrich_with_fetch(_fake_results(5))
        assert len(calls) >= 3, f"fetch แค่ {len(calls)} หน้า"


class TestFormatDepth:
    def test_includes_long_fetched_text(self):
        """fetched_text 2,400 ตัวอักษร ต้องเข้า context ≥ 2,200 (เดิมตัดที่ 1,500)"""
        marker_text = ("ข้อมูลเชิงลึกย่อหน้า " * 120)[:2400]
        results = [{"title": "บทความ", "body": "สั้น", "href": "https://x.go.th/a",
                    "fetched_text": marker_text}]
        ctx = websearch.format_for_context(results, "ทดสอบ")
        kept = max(len(s) for s in ctx.splitlines())
        assert kept >= 2200, f"fetched_text โดนตัดเหลือ ~{kept} ตัวอักษร"

    def test_snippet_not_overly_truncated(self):
        """snippet (ไม่มี fetched_text) ควรได้ ≥ 450 ตัวอักษร (เดิม 300)"""
        long_snippet = ("รายละเอียดสรุปจาก search engine " * 30)[:600]
        results = [{"title": "ผล", "body": long_snippet, "href": "https://y.com/b"}]
        ctx = websearch.format_for_context(results, "ทดสอบ")
        kept = max(len(s) for s in ctx.splitlines())
        assert kept >= 450, f"snippet โดนตัดเหลือ ~{kept} ตัวอักษร"


# ── หน้าเว็บช้าหน้าเดียวต้องไม่ทำ web_search ล้มทั้งก้อน (2026-09-23) ─────────────
# ของจริง: "current gold price" → apmex.com ทยอยส่ง 36 วิ → as_completed(timeout=8)
# โยน TimeoutError ที่ไม่มีใครดัก ⇒ tool web_search ล้ม ทิ้งผลค้น 6 ตัวที่ได้แล้ว
# และ `with ThreadPoolExecutor` ยังรอเธรดที่ค้างตอนออก ⇒ ใช้เวลา 35.5 วิ

import time  # noqa: E402


class TestEnrichSlowPage:
    def _fetch(self, url):
        if "slow" in url:
            time.sleep(3.0)
            return "ไม่ควรได้"
        return f"เนื้อหาจาก {url}"

    def _results(self):
        return [{"title": t, "body": "b", "href": f"https://{t}.example/a"}
                for t in ("fast1", "slow", "fast2")]

    def test_หน้าช้าไม่ทำให้ล้ม_และเก็บหน้าที่เสร็จแล้วไว้(self, monkeypatch):
        monkeypatch.setattr(websearch, "_FETCH_TIMEOUT", 0.2)  # as_completed รอ 2.2 วิ
        monkeypatch.setattr(websearch, "_fetch_url", self._fetch)
        out = websearch._enrich_with_fetch(self._results())
        by = {r["title"]: r.get("fetched_text") for r in out}
        assert by["fast1"].startswith("เนื้อหาจาก") and by["fast2"].startswith("เนื้อหาจาก")
        assert by["slow"] == ""

    def test_ไม่รอเธรดที่ค้างตอนออก(self, monkeypatch):
        monkeypatch.setattr(websearch, "_FETCH_TIMEOUT", 0.2)
        monkeypatch.setattr(websearch, "_fetch_url", self._fetch)
        t = time.monotonic()
        websearch._enrich_with_fetch(self._results())
        took = time.monotonic() - t
        assert took < 2.9, f"ใช้ {took:.1f} วิ — ยังรอเธรดที่ค้าง (หน้าช้าใช้ 3 วิ)"

    def test_บอกใน_log_ว่าหน้าไหนช้า(self, monkeypatch, caplog):
        """หน้าช้าถูกทิ้ง ≠ หน้าว่าง — ต้องมีร่องรอยให้ตามได้"""
        monkeypatch.setattr(websearch, "_FETCH_TIMEOUT", 0.2)
        monkeypatch.setattr(websearch, "_fetch_url", self._fetch)
        with caplog.at_level("WARNING", logger=websearch.logger.name):
            websearch._enrich_with_fetch(self._results())
        assert "slow.example" in caplog.text

    def test_fetch_ส่งเพดานเวลารวมให้_fetch_url_safe(self, monkeypatch):
        seen = {}

        def fake_safe(url, **kw):
            seen.update(kw)
            raise RuntimeError("stop")

        import utils.urlguard as ug
        monkeypatch.setattr(ug, "fetch_url_safe", fake_safe)
        websearch._fetch_url("https://x.example/")
        assert seen.get("deadline") is not None and seen["deadline"] <= websearch._FETCH_TIMEOUT + 2
