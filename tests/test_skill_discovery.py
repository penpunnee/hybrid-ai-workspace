"""Tests สำหรับ utils/skill_discovery.py — clustering, dedup, fetch, accept, discover

Pure helpers ทดสอบตรงๆ; discover_skills/accept_proposal mock embed+LLM+filesystem.
"""
import json
import os
import sys
import types
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import utils.skill_discovery as sd
from utils.history import _get_conn


def _add_message(role, content, created_at=None):
    conn = _get_conn()
    try:
        conn.execute(
            """INSERT INTO messages (assistant, role, content, provider, created_at, session_id)
               VALUES (?,?,?,?,?,?)""",
            ("kwan", role, content, "ollama", created_at or datetime.now().isoformat(), "s1"),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def clean_cache():
    sd._proposals_cache.clear()
    yield
    sd._proposals_cache.clear()


# ── _greedy_cluster ───────────────────────────────────────────────────────────
def test_greedy_cluster_groups_similar():
    prompts = ["a", "b", "c"]
    vectors = [[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]]   # a,b เหมือน; c ต่าง
    clusters = sd._greedy_cluster(prompts, vectors, threshold=0.72)
    sizes = sorted(len(c) for c in clusters)
    assert sizes == [1, 2]


def test_greedy_cluster_all_distinct():
    vectors = [[1.0, 0.0], [0.0, 1.0], [-1.0, 0.0]]
    clusters = sd._greedy_cluster(["x", "y", "z"], vectors, threshold=0.72)
    assert len(clusters) == 3


def test_greedy_cluster_skips_empty_vec():
    clusters = sd._greedy_cluster(["x", "y"], [[], [1.0, 0.0]], threshold=0.72)
    # vec ว่างถูกข้าม → เหลือ cluster เดียวจาก y
    assert sum(len(c) for c in clusters) == 1


# ── _is_duplicate ─────────────────────────────────────────────────────────────
def test_is_duplicate_match():
    assert sd._is_duplicate([1.0, 0.0], [("existing", [1.0, 0.0])], threshold=0.82) == "existing"


def test_is_duplicate_no_match():
    assert sd._is_duplicate([1.0, 0.0], [("existing", [0.0, 1.0])], threshold=0.82) is None


def test_is_duplicate_empty_vec():
    assert sd._is_duplicate([], [("x", [1.0, 0.0])]) is None


# ── _fetch_recent_prompts ─────────────────────────────────────────────────────
def test_fetch_recent_filters_by_role_length_and_age(monkeypatch):
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM messages")
        conn.commit()
    finally:
        conn.close()

    _add_message("user", "this is a good length prompt")        # เก็บ
    _add_message("user", "sh")                                  # สั้นเกิน (<8) → ตัด
    _add_message("assistant", "assistant message should skip")  # role ไม่ใช่ user → ตัด
    _add_message("user", "old prompt long enough text",
                 created_at=(datetime.now() - timedelta(days=40)).isoformat())  # เก่าเกิน → ตัด

    got = sd._fetch_recent_prompts(days=30)
    assert "this is a good length prompt" in got
    assert "sh" not in got
    assert all("assistant message" not in g for g in got)
    assert all("old prompt" not in g for g in got)


# ── SkillProposal ─────────────────────────────────────────────────────────────
def test_proposal_to_dict():
    p = sd.SkillProposal(id="p1", topic="t", summary="s", cluster_size=3)
    d = p.to_dict()
    assert d["id"] == "p1" and d["cluster_size"] == 3
    assert "examples" in d and "avg_similarity" in d


def test_list_cached_proposals(clean_cache):
    sd._proposals_cache["p1"] = sd.SkillProposal(id="p1", topic="t", summary="s")
    out = sd.list_cached_proposals()
    assert len(out) == 1 and out[0]["id"] == "p1"


# ── accept_proposal ───────────────────────────────────────────────────────────
def test_accept_proposal_not_found(clean_cache):
    res = sd.accept_proposal("nope")
    assert res["ok"] is False
    assert "not found" in res["error"]


def test_accept_proposal_writes_md_and_db(monkeypatch, tmp_path, clean_cache):
    monkeypatch.setattr(sd, "_SKILLS_DIR", str(tmp_path / "skills"))
    monkeypatch.setattr(sd, "_SKILLS_DB", str(tmp_path / "skills_db.json"))
    # กัน ChromaDB sync
    fake_mod = types.ModuleType("utils.skills_search")
    fake_mod.sync_skills_to_search = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "utils.skills_search", fake_mod)

    sd._proposals_cache["p1"] = sd.SkillProposal(
        id="p1", topic="Docker Deploy", summary="ถามเรื่อง deploy บ่อย",
        examples=["deploy ยังไง", "docker คืออะไร"], cluster_size=4,
        detected_at="2026-05-29T00:00:00",
    )
    res = sd.accept_proposal("p1")
    assert res["ok"] is True
    assert res["topic"] == "Docker Deploy"
    # ไฟล์ .md ถูกสร้าง
    assert os.path.isfile(res["path"])
    body = open(res["path"], encoding="utf-8").read()
    assert "Docker Deploy" in body
    # skills_db.json ถูก update
    db = json.load(open(str(tmp_path / "skills_db.json"), encoding="utf-8"))
    assert db["Docker Deploy"]["auto_discovered"] is True
    # proposal ถูกลบจาก cache หลัง accept
    assert "p1" not in sd._proposals_cache


def test_accept_proposal_custom_content(monkeypatch, tmp_path, clean_cache):
    monkeypatch.setattr(sd, "_SKILLS_DIR", str(tmp_path / "skills"))
    monkeypatch.setattr(sd, "_SKILLS_DB", str(tmp_path / "skills_db.json"))
    fake_mod = types.ModuleType("utils.skills_search")
    fake_mod.sync_skills_to_search = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "utils.skills_search", fake_mod)

    # topic/content ต้องผ่านเกณฑ์คุณภาพ (backlog ข้อ 20) — ของเดิมใช้ค่า placeholder
    # "X"/"s" ซึ่งตอนนี้ถูก gate ปฏิเสธถูกต้องแล้ว · เทสนี้ตรวจว่า custom_content
    # ถูกใช้เป็นบอดี้ ไม่ได้ตรวจว่า gate ยอมรับอะไรก็ได้ (ดู tests/test_skill_entry_gate.py)
    sd._proposals_cache["p2"] = sd.SkillProposal(
        id="p2", topic="Custom Skill", summary="สรุปที่ผู้ใช้เขียนเองสำหรับหัวข้อนี้",
    )
    res = sd.accept_proposal("p2", custom_content="# Custom\nบอดี้เองที่ผู้ใช้เขียนมาเต็มๆ")
    assert res["ok"] is True
    assert "บอดี้เอง" in open(res["path"], encoding="utf-8").read()


# ── discover_skills (happy path, mocked) ──────────────────────────────────────
def test_discover_skills_produces_proposal(monkeypatch, clean_cache):
    prompts = [f"deploy docker question {i}" for i in range(5)]
    monkeypatch.setattr(sd, "_fetch_recent_prompts", lambda days=30: prompts)
    monkeypatch.setattr(sd, "embed_texts", lambda ts: [[1.0, 0.0] for _ in ts])  # เหมือนกันหมด → 1 cluster
    monkeypatch.setattr(sd, "embed_query", lambda t: [1.0, 0.0])
    monkeypatch.setattr(sd, "_load_existing_skill_topics", lambda: [])
    monkeypatch.setattr(sd, "_summarize_cluster", lambda ps: ("Docker", "deploy ถามบ่อย"))

    out = sd.discover_skills(days=30, min_cluster=3)
    assert len(out) == 1
    assert out[0].topic == "Docker"
    assert out[0].cluster_size == 5
    assert out[0].id in sd._proposals_cache


def test_discover_skills_too_few_prompts(monkeypatch, clean_cache):
    monkeypatch.setattr(sd, "_fetch_recent_prompts", lambda days=30: ["only one"])
    assert sd.discover_skills(min_cluster=3) == []


def test_discover_skills_skips_duplicate(monkeypatch, clean_cache):
    prompts = [f"q{i} long enough prompt" for i in range(4)]
    monkeypatch.setattr(sd, "_fetch_recent_prompts", lambda days=30: prompts)
    monkeypatch.setattr(sd, "embed_texts", lambda ts: [[1.0, 0.0] for _ in ts])
    monkeypatch.setattr(sd, "embed_query", lambda t: [1.0, 0.0])
    # existing skill ใกล้ centroid → ถูกมองเป็น duplicate
    monkeypatch.setattr(sd, "_load_existing_skill_topics", lambda: [("old", [1.0, 0.0])])
    monkeypatch.setattr(sd, "_summarize_cluster", lambda ps: ("Dup", "x"))
    assert sd.discover_skills(min_cluster=3) == []
