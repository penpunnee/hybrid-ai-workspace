"""Tests สำหรับ OR-gate ของ skills injection — `utils/skills_select.py`

**กติกาเดียวของฟีเจอร์นี้: เติมเฉพาะที่เคยได้ศูนย์ ห้ามแตะที่เหลือ**

ที่มา (วัดจริง 432 เทิร์นบน prod 2026-08-03): `.split()` ฉีดให้ prompt ไทยล้วนได้ 29.7%
แต่ที่มี Latin ปนได้ 81.7% · ตัวแทนที่ลองแล้วแย่กว่าทั้งคู่ — `ngram` ฉีด 92.8% (ท่วม)
· `semantic` เกณฑ์สัมบูรณ์ 0.40 ฉีดไทยแค่ 5.9% (แย่กว่าของเดิม)
· ส่วนกฎสัมพัทธ์ดูดีกว่าแต่ **พิสูจน์ไม่ได้** ด้วย label ที่มี (positives 11 คู่ = noise)

→ ออกแบบให้ **ไม่ต้องตอบคำถามที่ข้อมูลตอบไม่ได้**: ไม่เลือกว่าใครแม่นกว่า แต่ให้ semantic
ทำงานเฉพาะตอน lexical ยอมแพ้ (pattern เดียวกับ OR-gate ใน `memory/lexical.py` ข้อ 16)
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import rag, skills_select as sel


@pytest.fixture()
def skills_dir(tmp_path):
    (tmp_path / "memory-system.md").write_text(
        "# ระบบความจำ\nระบบความจำใช้ chromadb เก็บ embedding", encoding="utf-8")
    (tmp_path / "deploy-nas.md").write_text(
        "# deploy\ndeploy ขึ้น NAS ด้วย docker compose", encoding="utf-8")
    (tmp_path / "unrelated.md").write_text("# อื่นๆ\nเรื่องอื่นไม่เกี่ยว", encoding="utf-8")
    return str(tmp_path)


# ── ข้อห้ามสูงสุด: เส้นที่ทำงานอยู่แล้วต้องไม่ถูกแตะ ────────────────────────────
def test_lexical_hit_short_circuits_before_touching_semantic(skills_dir, monkeypatch):
    """ถ้า `.split()` เจอของ → **ห้ามเรียก semantic เลย** ไม่ใช่เรียกแล้วไม่ใช้

    สำคัญ 2 ชั้น: (1) ผลลัพธ์ต้องเท่าเดิมเป๊ะ (2) ต้องไม่เพิ่ม latency/ChromaDB call
    ให้เทิร์นที่ไม่ต้องการมัน — เทสนี้บังคับด้วยการทำให้ semantic ระเบิดถ้าถูกเรียก
    """
    def boom(*a, **k):
        raise AssertionError("เรียก semantic ทั้งที่ lexical เจอของแล้ว")
    monkeypatch.setattr(sel, "semantic_scores", boom)

    picks, source = sel.select_skills(skills_dir, "chromadb embedding")
    assert source == "lexical"
    assert [p.name for p in picks] == [p.name for p in rag.select_skill_files(skills_dir, "chromadb embedding")]


def test_output_identical_to_old_behaviour_when_lexical_hits(skills_dir, monkeypatch):
    monkeypatch.setattr(sel, "semantic_scores", lambda *a, **k: {"unrelated.md": 0.99})
    for q in ["chromadb", "deploy docker", "nas compose"]:
        picks, _ = sel.select_skills(skills_dir, q)
        assert rag.format_skill_files(picks) == rag.load_skills_relevant(skills_dir, q), q


# ── เส้นที่เพิ่มมา: ทำงานเฉพาะตอนได้ศูนย์ ────────────────────────────────────────
def test_fallback_fires_only_when_lexical_finds_nothing(skills_dir, monkeypatch):
    """prompt ไทยล้วนที่ `.split()` มองไม่เห็น — เดิมได้ศูนย์ไฟล์ ตอนนี้ต้องได้ของ"""
    monkeypatch.setattr(sel, "semantic_scores",
                        lambda *a, **k: {"memory-system.md": 0.61, "deploy-nas.md": 0.30,
                                         "unrelated.md": 0.28})
    q = "ระบบความจำทำงานยังไง"
    assert rag.select_skill_files(skills_dir, q) == [], "เทสนี้ต้องเริ่มจากเคสที่เดิมได้ศูนย์"
    picks, source = sel.select_skills(skills_dir, q)
    assert source == "semantic_margin"
    assert [p.name for p in picks] == ["memory-system.md"]
    assert "chromadb" in picks[0].content, "ต้องคืนเนื้อไฟล์จริง ไม่ใช่แค่ชื่อ"


def test_fallback_respects_margin_and_stays_silent_when_flat(skills_dir, monkeypatch):
    """คะแนนไล่ระดับเรียบ = ไม่มีไฟล์ไหนนำชัด → ไม่ฉีดดีกว่าเดาสุ่ม
    (ยอมได้เพราะนี่คือเทิร์นที่วันนี้ก็ได้ศูนย์อยู่แล้ว — ไม่มีอะไรเสียไป)"""
    monkeypatch.setattr(sel, "semantic_scores",
                        lambda *a, **k: {"memory-system.md": 0.31, "deploy-nas.md": 0.30,
                                         "unrelated.md": 0.29})
    picks, source = sel.select_skills(skills_dir, "ระบบความจำทำงานยังไง")
    assert picks == [] and source == "none"


def test_fallback_respects_cap(skills_dir, monkeypatch):
    monkeypatch.setattr(sel, "semantic_scores",
                        lambda *a, **k: {"memory-system.md": 0.61, "deploy-nas.md": 0.60,
                                         "unrelated.md": 0.59})
    picks, _ = sel.select_skills(skills_dir, "ระบบความจำทำงานยังไง", max_files=2)
    assert len(picks) <= 2


def test_fallback_silent_when_chromadb_down(skills_dir, monkeypatch):
    """ChromaDB ล่มต้องกลับไปเป็นพฤติกรรมเดิมเป๊ะ ไม่ใช่พังทั้งเทิร์น"""
    monkeypatch.setattr(sel, "semantic_scores", lambda *a, **k: {})
    picks, source = sel.select_skills(skills_dir, "ระบบความจำทำงานยังไง")
    assert picks == [] and source == "none"


def test_fallback_never_crashes_the_turn(skills_dir, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("chroma พัง")
    monkeypatch.setattr(sel, "semantic_scores", boom)
    picks, source = sel.select_skills(skills_dir, "ระบบความจำทำงานยังไง")
    assert picks == [] and source == "none"


def test_fallback_ignores_files_that_no_longer_exist(skills_dir, monkeypatch):
    """index ค้างหลัง .md ถูกลบ = เคยเกิดจริง (ไฟล์เหลือ 52 แต่ index 128, 2026-08-02)
    ต้องข้ามเงียบๆ ไม่ใช่ฉีดชื่อไฟล์เปล่าหรือพัง"""
    monkeypatch.setattr(sel, "semantic_scores",
                        lambda *a, **k: {"ผีไม่มีจริง.md": 0.9, "memory-system.md": 0.4})
    picks, _ = sel.select_skills(skills_dir, "ระบบความจำทำงานยังไง")
    assert [p.name for p in picks] == []      # ผีนำอยู่ → กลุ่มที่เลือกคือผี → ตกไปทั้งกลุ่ม


# ── ปิดได้ ────────────────────────────────────────────────────────────────────
def test_disabled_by_env_restores_old_behaviour(skills_dir, monkeypatch):
    monkeypatch.setattr(sel, "FALLBACK_MARGIN", None)
    monkeypatch.setattr(sel, "semantic_scores",
                        lambda *a, **k: {"memory-system.md": 0.99})
    picks, source = sel.select_skills(skills_dir, "ระบบความจำทำงานยังไง")
    assert picks == [] and source == "none"


def test_margin_parsed_from_env():
    assert sel._parse_margin("0.08") == 0.08
    assert sel._parse_margin("off") is None
    assert sel._parse_margin("") is None
    assert sel._parse_margin("ขยะ") is None       # ค่าพิมพ์ผิด = ปิด ไม่ใช่ crash ตอน import


# ── พื้นสัมบูรณ์: สิ่งที่กฎสัมพัทธ์ทำแทนไม่ได้ ───────────────────────────────────
def test_absolute_floor_blocks_irrelevant_leader(skills_dir, monkeypatch):
    """คำถามที่ไม่เกี่ยวกับ skill ไหนเลย ต้องได้ศูนย์ ไม่ใช่ได้ "ตัวที่แพ้น้อยที่สุด"

    เจอจริงตอนเปิดดูผลบน prod 2026-08-03: `"ราคาทองคำวันนี้เท่าไหร่"` →
    `env-variables-reference.md` ที่คะแนน **0.138** เพราะมันนำตัวอื่นอยู่ ทั้งที่
    ไม่เกี่ยวอะไรเลย — ตัวเลขสรุปทุกช่องดูดีขึ้นแต่ของที่ฉีดจริงเป็น noise
    """
    monkeypatch.setattr(sel, "semantic_scores",
                        lambda *a, **k: {"unrelated.md": 0.138, "deploy-nas.md": 0.02,
                                         "memory-system.md": 0.01})
    picks, source = sel.select_skills(skills_dir, "ราคาทองคำวันนี้เท่าไหร่")
    assert picks == [] and source == "none"


def test_floor_and_margin_must_both_pass(skills_dir, monkeypatch):
    # นำขาด แต่ต่ำกว่าพื้น → ไม่ผ่าน
    monkeypatch.setattr(sel, "semantic_scores",
                        lambda *a, **k: {"memory-system.md": 0.34, "deploy-nas.md": 0.10,
                                         "unrelated.md": 0.05})
    assert sel.select_skills(skills_dir, "ความจำของเครื่องทำงานยังไง")[0] == []
    # เหนือพื้น และนำขาด → ผ่าน
    monkeypatch.setattr(sel, "semantic_scores",
                        lambda *a, **k: {"memory-system.md": 0.52, "deploy-nas.md": 0.10,
                                         "unrelated.md": 0.05})
    picks, source = sel.select_skills(skills_dir, "ความจำของเครื่องทำงานยังไง")
    assert [p.name for p in picks] == ["memory-system.md"] and source == "semantic_margin"
