"""Tests สำหรับ memory/ package ใหม่ (schema, working, teach, store, operations)

หมายเหตุ: test_memory.py เดิมเทสต์ utils/memory.py (legacy) — ไฟล์นี้เทสต์ package
ใหม่ที่ยังไม่มี coverage. ส่วน ChromaDB ถูก mock เพื่อทดสอบ logic ล้วนๆ
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


# ════════════════════════ schema.py ════════════════════════
from memory.schema import MemoryEntry


def test_memory_entry_defaults():
    e = MemoryEntry(content="hi")
    assert e.type == "event" and e.confidence == 0.7
    assert e.verified is False and e.source == "conversation"
    assert e.created_at and e.last_accessed  # ISO timestamps ถูกตั้ง


def test_memory_entry_to_metadata_keys():
    meta = MemoryEntry(content="x", assistant="logic").to_metadata()
    assert {"assistant", "type", "confidence", "source",
            "verified", "access_count", "created_at", "last_accessed"} <= set(meta)
    assert meta["assistant"] == "logic"


@pytest.mark.parametrize("score,word", [
    (0.95, "verified"), (0.9, "verified"),
    (0.7, "probable"), (0.5, "uncertain"), (0.49, "low"),
])
def test_confidence_label_boundaries(score, word):
    assert word in MemoryEntry.confidence_label(score)


# ════════════════════════ working.py ════════════════════════
from memory.working import WorkingMemory


def test_working_push_and_get_recent():
    wm = WorkingMemory()
    wm.push("s1", "user", "hello")
    wm.push("s1", "assistant", "hi there")
    recent = wm.get_recent("s1")
    assert [r["role"] for r in recent] == ["user", "assistant"]
    assert recent[0]["content"] == "hello"


def test_working_truncates_content_to_500():
    wm = WorkingMemory()
    wm.push("s1", "user", "x" * 1000)
    assert len(wm.get_recent("s1")[0]["content"]) == 500


def test_working_get_recent_respects_n():
    wm = WorkingMemory()
    for i in range(5):
        wm.push("s1", "user", f"m{i}")
    assert [r["content"] for r in wm.get_recent("s1", n=2)] == ["m3", "m4"]


def test_working_context_text_format_and_empty():
    wm = WorkingMemory()
    assert wm.get_context_text("missing") == ""
    wm.push("s1", "user", "ping")
    txt = wm.get_context_text("s1")
    assert "บทสนทนาล่าสุด" in txt and "[user]: ping" in txt


def test_working_clear():
    wm = WorkingMemory()
    wm.push("s1", "user", "x")
    wm.clear("s1")
    assert wm.get_recent("s1") == []


def test_working_max_per_session_drops_oldest():
    wm = WorkingMemory(max_per_session=2)
    for i in range(3):
        wm.push("s1", "user", f"m{i}")
    contents = [r["content"] for r in wm.get_recent("s1", n=10)]
    assert contents == ["m1", "m2"]  # m0 ถูกดันออก


def test_working_evicts_oldest_session_over_limit():
    wm = WorkingMemory(max_sessions=2)
    wm.push("s1", "user", "a")
    wm.push("s2", "user", "b")
    wm.push("s3", "user", "c")   # เกิน limit → s1 (เก่าสุด) ถูก evict
    assert wm.get_recent("s1") == []
    assert wm.get_recent("s3")[0]["content"] == "c"


# ════════════════════════ teach.py ════════════════════════
import memory.teach as teach
from memory.teach import detect_teaching, detect_correction


def test_detect_teaching_fact():
    knowledge, mtype = detect_teaching("จำไว้ว่า ผมชอบกาแฟดำไม่ใส่น้ำตาล")
    assert mtype == "fact" and "กาแฟ" in knowledge


def test_detect_teaching_preference():
    knowledge, mtype = detect_teaching("prefer dark mode interface")
    assert mtype == "preference" and "dark mode" in knowledge


def test_detect_teaching_rejects_too_short():
    assert detect_teaching("จำไว้ว่า: ก") == (None, "")


def test_detect_teaching_none():
    assert detect_teaching("วันนี้อากาศดีจัง") == (None, "")


@pytest.mark.parametrize("text,expected", [
    ("ไม่ถูกนะ", True),
    ("ที่ถูกคือเชียงใหม่", True),
    ("ขอบคุณมากครับ", False),
])
def test_detect_correction(text, expected):
    assert detect_correction(text) is expected


def test_process_teaching_saves_fact(monkeypatch):
    saved = []
    monkeypatch.setattr(teach, "save_entry", lambda e, *a, **k: (saved.append(e), True)[1])
    ok = teach.process_teaching("logic", "จำไว้ว่า ผมชอบกาแฟดำไม่ใส่น้ำตาล")
    assert ok is True
    assert saved[0].type == "fact" and saved[0].confidence == 0.95
    assert saved[0].verified is True and saved[0].source == "user_taught"


def test_process_teaching_correction_lowers_confidence(monkeypatch):
    saved, conf_calls = [], []
    monkeypatch.setattr(teach, "save_entry", lambda e, *a, **k: (saved.append(e), True)[1])
    monkeypatch.setattr(teach, "update_confidence",
                        lambda *a, **k: (conf_calls.append(a), True)[1])
    ok = teach.process_teaching("logic", "ที่ถูกคือเชียงใหม่อยู่ภาคเหนือจริงๆ",
                                ai_response="เชียงใหม่อยู่ภาคใต้")
    assert ok is True
    assert conf_calls                      # ลด confidence ของ response เดิม
    assert saved[0].type == "correction"


def test_process_teaching_nothing(monkeypatch):
    monkeypatch.setattr(teach, "save_entry", lambda *a, **k: True)
    assert teach.process_teaching("logic", "เล่าเรื่องตลกให้ฟังหน่อย") is False


# ════════════════════════ store.py ════════════════════════
import memory.store as store
from memory.store import _safe_slug, search_entries


@pytest.mark.parametrize("name,slug", [
    ("Logic AI", "logic_ai"),
    ("ฟ้า (UI)", "ui"),
    ("ขวัญ", "default"),       # ascii-only ว่าง → default
    ("Test-123", "test_123"),
])
def test_safe_slug(name, slug):
    assert _safe_slug(name) == slug


def _fake_client(res):
    col = SimpleNamespace(query=lambda **k: res)
    return SimpleNamespace(get_collection=lambda name: col)


def test_search_entries_no_client_returns_empty(monkeypatch):
    monkeypatch.setattr(store, "_get_chroma_client", lambda: None)
    assert search_entries("logic", "q") == []


def test_search_entries_filters_and_sorts(monkeypatch):
    res = {
        "documents": [["a", "b", "c"]],
        "metadatas": [[
            {"confidence": 0.9, "verified": True, "type": "fact"},
            {"confidence": 0.6, "verified": False, "type": "event"},
            {"confidence": 0.4, "verified": False, "type": "event"},
        ]],
        "distances": [[0.1, 0.2, 0.5]],
    }
    monkeypatch.setattr(store, "_get_chroma_client", lambda: _fake_client(res))
    out = search_entries("logic", "q", n_results=5, min_confidence=0.5)
    # c (0.4) ถูกตัด; เรียง verified→confidence desc
    assert [r["content"] for r in out] == ["a", "b"]
    assert out[0]["score"] == 0.9 and out[0]["verified"] is True


def test_search_entries_verified_only(monkeypatch):
    res = {
        "documents": [["a", "b"]],
        "metadatas": [[
            {"confidence": 0.9, "verified": True},
            {"confidence": 0.9, "verified": False},
        ]],
        "distances": [[0.1, 0.1]],
    }
    monkeypatch.setattr(store, "_get_chroma_client", lambda: _fake_client(res))
    out = search_entries("logic", "q", verified_only=True)
    assert [r["content"] for r in out] == ["a"]


# ════════════════════════ operations.py ════════════════════════
import memory.operations as ops


def test_remember_builds_qa_entry(monkeypatch):
    saved = []
    monkeypatch.setattr(ops, "save_entry", lambda e, *a, **k: saved.append(e))
    ops.remember("logic", "what is 2+2", "it is 4")
    assert saved[0].type == "event" and saved[0].confidence == 0.7
    assert "Q: what is 2+2" in saved[0].content and "A: it is 4" in saved[0].content


def test_recall_empty_when_nothing(monkeypatch):
    monkeypatch.setattr(ops, "search_entries", lambda *a, **k: [])
    monkeypatch.setattr(ops, "search_long_term", lambda *a, **k: [])
    assert ops.recall("logic", "q", session_id="nope") == ""


def test_recall_assembles_all_tiers(monkeypatch):
    ops.working_memory.clear("sx")
    ops.working_memory.push("sx", "user", "earlier message")
    monkeypatch.setattr(ops, "search_entries",
                        lambda *a, **k: [{"content": "episodic fact", "confidence": 0.8, "verified": True}])
    monkeypatch.setattr(ops, "search_long_term",
                        lambda *a, **k: [{"content": "long term theme"}])
    out = ops.recall("logic", "q", session_id="sx")
    assert "earlier message" in out               # tier 1 working
    assert "episodic fact" in out                  # tier 2 episodic
    assert "long term theme" in out                # tier 3 long-term
    ops.working_memory.clear("sx")


def test_teach_delegates_to_process_teaching(monkeypatch):
    monkeypatch.setattr(ops, "process_teaching", lambda a, u, r="": ("called", a, u))
    assert ops.teach("logic", "จำไว้ว่า x") == ("called", "logic", "จำไว้ว่า x")


def test_push_working_delegates():
    ops.working_memory.clear("sp")
    ops.push_working("sp", "user", "hi")
    assert ops.working_memory.get_recent("sp")[0]["content"] == "hi"
    ops.working_memory.clear("sp")


def test_get_memory_summary_no_client(monkeypatch):
    monkeypatch.setattr(store, "_get_chroma_client", lambda: None)
    summary = ops.get_memory_summary("logic")
    assert summary["available"] is False and summary["episodic"] == 0
