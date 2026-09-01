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
    col = SimpleNamespace(
        query=lambda **k: res,
        get=lambda ids=None, **k: {"metadatas": []},   # สำหรับ bump_access_count
        update=lambda **k: None,
    )
    return SimpleNamespace(get_collection=lambda name: col)


def test_search_entries_no_client_returns_empty(monkeypatch):
    monkeypatch.setattr(store, "_get_chroma_client", lambda: None)
    assert search_entries("logic", "q") == []


def test_search_entries_filters_and_sorts(monkeypatch):
    res = {
        "ids": [["a", "b", "c"]],
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
        "ids": [["a", "b"]],
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


def test_search_entries_bumps_access_count(monkeypatch):
    """Step 0: recall/search → access_count++ + last_accessed refresh
    (เดิม bump_access_count ไม่เคยถูกเรียก → usage signal ตาย)"""
    query_res = {
        "ids": [["m1"]],
        "documents": [["hello"]],
        "metadatas": [[{"confidence": 0.8, "verified": False, "access_count": 0}]],
        "distances": [[0.1]],
    }
    get_res = {"metadatas": [{"confidence": 0.8, "verified": False, "access_count": 0}]}
    updates = []

    class _Col:
        def query(self, **k):
            return query_res

        def get(self, ids=None, **k):
            return get_res

        def update(self, ids=None, metadatas=None, **k):
            updates.append((ids, metadatas))

    client = SimpleNamespace(get_collection=lambda name: _Col())
    monkeypatch.setattr(store, "_get_chroma_client", lambda: client)

    out = search_entries("logic", "q")
    assert out and out[0]["content"] == "hello"
    assert out[0].get("id") == "m1", "ผลลัพธ์ควรมี doc id"
    assert updates, "search ต้อง bump access_count (ยังไม่ถูก wire)"
    _ids, _metas = updates[0]
    assert _ids == ["m1"]
    assert _metas[0]["access_count"] == 1
    assert _metas[0]["last_accessed"], "ต้อง refresh last_accessed"


def test_list_entries_no_client_returns_empty(monkeypatch):
    monkeypatch.setattr(store, "_get_chroma_client", lambda: None)
    assert store.list_entries("logic") == []


def test_list_entries_no_query_uses_get_sorted_by_timestamp_desc(monkeypatch):
    """ไม่มี q → list ล่าสุดก่อน (สำหรับ preview ก่อนลบ)"""
    get_res = {
        "ids": ["a", "b"],
        "documents": ["doc-a", "doc-b"],
        "metadatas": [
            {"confidence": 0.8, "timestamp": "2026-07-01T00:00:00"},
            {"confidence": 0.6, "timestamp": "2026-07-13T00:00:00"},
        ],
    }
    col = SimpleNamespace(get=lambda **k: get_res)
    client = SimpleNamespace(get_collection=lambda name: col)
    monkeypatch.setattr(store, "_get_chroma_client", lambda: client)

    out = store.list_entries("logic")
    assert [r["id"] for r in out] == ["b", "a"]  # newest ก่อน


def test_list_entries_with_query_uses_semantic_search(monkeypatch):
    query_res = {
        "ids": [["m1"]],
        "documents": [["hello"]],
        "metadatas": [[{"confidence": 0.9, "type": "fact", "timestamp": "2026-07-01"}]],
    }
    col = SimpleNamespace(query=lambda **k: query_res)
    client = SimpleNamespace(get_collection=lambda name: col)
    monkeypatch.setattr(store, "_get_chroma_client", lambda: client)

    out = store.list_entries("logic", query="hi")
    assert out == [{
        "id": "m1", "content": "hello", "confidence": 0.9, "verified": False,
        "type": "fact", "source": "conversation", "timestamp": "2026-07-01",
    }]


def test_delete_entry_no_client_returns_false(monkeypatch):
    monkeypatch.setattr(store, "_get_chroma_client", lambda: None)
    assert store.delete_entry("logic", "mem_1") is False


def test_delete_entry_calls_col_delete_with_id(monkeypatch):
    """ตั้งแต่ 2026-09-02 ต้องลบ **สองที่**: เงา `memory_logic__keys` ก่อน แล้วตัวหลัก
    (กุญแจกำพร้า = `merge_max()` ฉีดของที่ลบไปแล้วกลับเข้า context ได้)"""
    touched = []
    col = SimpleNamespace(delete=lambda ids: None)
    client = SimpleNamespace(
        get_collection=lambda name, **kw: (touched.append(name), col)[1])
    monkeypatch.setattr(store, "_get_chroma_client", lambda: client)

    ok = store.delete_entry("logic", "mem_1")
    assert ok is True
    assert touched == ["memory_logic__keys", "memory_logic"], touched


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
    monkeypatch.setattr(ops, "process_teaching",
                        lambda a, u, r="", prev_answer="": ("called", a, u, prev_answer))
    assert ops.teach("logic", "จำไว้ว่า x") == ("called", "logic", "จำไว้ว่า x", "")
    # prev_answer ต้องถูกส่งต่อ ไม่ใช่ถูกกลืนหาย
    assert ops.teach("logic", "ผิดแล้ว", prev_answer="คำตอบเก่า")[3] == "คำตอบเก่า"


def test_push_working_delegates():
    ops.working_memory.clear("sp")
    ops.push_working("sp", "user", "hi")
    assert ops.working_memory.get_recent("sp")[0]["content"] == "hi"
    ops.working_memory.clear("sp")


def test_get_memory_summary_no_client(monkeypatch):
    monkeypatch.setattr(store, "_get_chroma_client", lambda: None)
    summary = ops.get_memory_summary("logic")
    assert summary["available"] is False and summary["episodic"] == 0


# ── _rank_results (Fix #4) — ranking ต้องผสม semantic score ไม่ใช่ confidence ล้วน ──
def test_rank_results_blends_semantic_score():
    """เดิม sort confidence ล้วน → memory มั่นใจสูงแต่ไม่ relevant เด้งทับ relevant"""
    results = [
        {"id": "hi_conf", "verified": False, "confidence": 0.95, "score": 0.10},
        {"id": "relevant", "verified": False, "confidence": 0.60, "score": 0.95},
    ]
    ranked = store._rank_results(list(results), n_results=2)
    assert ranked[0]["id"] == "relevant"   # blended score สูงชนะ (เดิม hi_conf ชนะ)


def test_rank_results_verified_always_first():
    results = [
        {"id": "unv", "verified": False, "confidence": 0.9, "score": 0.9},
        {"id": "ver", "verified": True, "confidence": 0.5, "score": 0.2},
    ]
    assert store._rank_results(list(results), 2)[0]["id"] == "ver"


def test_rank_results_truncates_to_n():
    results = [{"id": str(i), "verified": False, "confidence": 0.5, "score": 0.5} for i in range(5)]
    assert len(store._rank_results(results, 3)) == 3
