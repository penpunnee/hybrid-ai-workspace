"""ทดสอบ pure extractor ของ Gemini grounding sources (ดึงแหล่งจาก grounding_metadata)
— ใช้ตอน local model "ยืม" Gemini grounding ค้นเว็บ (session 2026-06-20)"""
import os
os.environ.setdefault("UI_PASSWORD", "")
from types import SimpleNamespace
from utils.llm import _extract_grounding_sources


def _chunk(uri, title):
    return SimpleNamespace(web=SimpleNamespace(uri=uri, title=title))


def test_extract_basic():
    cand = SimpleNamespace(grounding_metadata=SimpleNamespace(
        grounding_chunks=[_chunk("https://goldtraders.or.th", "สมาคมค้าทอง"),
                          _chunk("https://thairath.co.th/x", "ไทยรัฐ")]))
    out = _extract_grounding_sources(cand)
    assert len(out) == 2
    # shape ต้องเข้ากับ citations.add_web_results (title/href/body)
    assert out[0] == {"title": "สมาคมค้าทอง", "href": "https://goldtraders.or.th", "body": "สมาคมค้าทอง"}
    assert all({"title", "href", "body"} <= set(r) for r in out)


def test_extract_no_metadata():
    assert _extract_grounding_sources(SimpleNamespace(grounding_metadata=None)) == []
    assert _extract_grounding_sources(SimpleNamespace()) == []


def test_extract_skips_chunk_without_uri():
    cand = SimpleNamespace(grounding_metadata=SimpleNamespace(
        grounding_chunks=[_chunk("", "ไม่มี url"), _chunk("https://ok.com", "")]))
    out = _extract_grounding_sources(cand)
    assert len(out) == 1
    assert out[0]["href"] == "https://ok.com"
    assert out[0]["title"] == "https://ok.com"  # ไม่มี title → ใช้ uri แทน


def test_extract_empty_chunks():
    cand = SimpleNamespace(grounding_metadata=SimpleNamespace(grounding_chunks=[]))
    assert _extract_grounding_sources(cand) == []
