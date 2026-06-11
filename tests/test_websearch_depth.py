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
