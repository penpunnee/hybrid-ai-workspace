"""Tests สำหรับ utils/citations.py — CitationTracker accumulator"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from utils.citations import CitationTracker, Citation


def test_empty_tracker_len_bool_nextid():
    t = CitationTracker()
    assert len(t) == 0
    assert bool(t) is False
    assert t.next_id == 1


def test_add_assigns_sequential_ids():
    t = CitationTracker()
    c1 = t.add(type="web", source="A", snippet="x")
    c2 = t.add(type="skill", source="B", snippet="y")
    assert c1.id == 1 and c2.id == 2
    assert len(t) == 2 and bool(t) is True
    assert t.next_id == 3


def test_add_truncates_snippet_and_normalizes_newlines():
    t = CitationTracker()
    c = t.add(type="web", source="S", snippet="line1\nline2" + "z" * 500)
    assert "\n" not in c.snippet
    assert len(c.snippet) <= 400


def test_add_truncates_source_and_url():
    t = CitationTracker()
    c = t.add(type="web", source="s" * 300, snippet="x", url="u" * 600)
    assert len(c.source) == 200 and len(c.url) == 500


def test_add_score_rounded_and_none_safe():
    t = CitationTracker()
    assert t.add(type="web", source="s", snippet="x", score=0.123456).score == 0.1235
    assert t.add(type="web", source="s", snippet="x", score=None).score == 0.0


def test_add_web_results_skips_empty_snippet():
    t = CitationTracker()
    added = t.add_web_results([
        {"title": "T1", "fetched_text": "content one", "href": "http://a", "_rerank_score": 0.7},
        {"title": "T2", "fetched_text": "", "body": ""},  # ไม่มี snippet → ข้าม
    ])
    assert len(added) == 1
    assert added[0].source == "T1" and added[0].url == "http://a" and added[0].score == 0.7


def test_add_doc_chunks_source_format():
    t = CitationTracker()
    added = t.add_doc_chunks([{"text": "chunk body", "source": "report.pdf", "chunk_index": 3, "score": 0.5}])
    assert added[0].source == "report.pdf#3" and added[0].type == "document"


def test_to_list_returns_dicts():
    t = CitationTracker()
    t.add(type="vault", source="note", snippet="hi")
    lst = t.to_list()
    assert isinstance(lst, list) and isinstance(lst[0], dict)
    assert lst[0]["type"] == "vault" and lst[0]["id"] == 1


def test_format_inline_legend_empty_is_blank():
    assert CitationTracker().format_inline_legend() == ""


def test_format_inline_legend_lists_sources_with_url():
    t = CitationTracker()
    t.add(type="web", source="Wikipedia", snippet="x", url="http://wiki")
    t.add(type="skill", source="cooking", snippet="y")
    legend = t.format_inline_legend()
    assert "[1]" in legend and "[2]" in legend
    assert "Wikipedia" in legend and "http://wiki" in legend
    assert "cooking" in legend
