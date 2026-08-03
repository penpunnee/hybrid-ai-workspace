"""Tests สำหรับ shadow logging ของ skills injection (backlog ข้อ 21 ขั้นที่ 2)

**shadow = บันทึกว่าแต่ละ scorer *จะ* เลือกไฟล์ไหน โดยไม่เปลี่ยนสิ่งที่ฉีดจริง**
เป้าหมายคือสะสมข้อมูล 1 สัปดาห์แล้วเอาไปเทียบกับ 👍/👎 ที่มีอยู่แล้ว — แทนการมาร์คมือ
ซึ่งพิสูจน์แล้วว่าได้ positives แค่ 11 คู่ (ไม่มีพลังพอจะยืนยัน threshold)

กติกาที่เทสชุดนี้ล็อกไว้ (ทุกข้อมาจากบั๊กที่เคยเจอจริง ไม่ใช่ข้อควรระวังลอยๆ):
  1. shadow ห้ามเปลี่ยนพฤติกรรมการฉีด — output ของ prod ต้องเท่าเดิมเป๊ะหลัง refactor
  2. ของที่ log ต้องเป็น **สิ่งที่ prod เลือกจริง** ไม่ใช่ผลจำลองที่คำนวณซ้ำ
     (บทเรียน 2026-08-03: จำลองไม่ครบขั้น cap/top-k → P=0.170 ทั้งที่ของจริง 0.109)
  3. "ไม่รู้" ต้องไม่หน้าตาเหมือน "เป็นศูนย์" — semantic ล่ม = ไม่มีคีย์ ไม่ใช่ 0.0
  4. shadow พังต้องไม่ทำให้แชทพัง (fail-quiet) — มันเป็นเครื่องมือวัด ไม่ใช่ฟีเจอร์
  5. traffic จากการเทสต้องไม่ปนเข้าข้อมูล (บทเรียน memory contamination 2026-06-11)
"""
import json
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from utils import rag, skills_shadow as shadow


@pytest.fixture()
def skills_dir(tmp_path):
    """โฟลเดอร์ skill จำลอง — ตั้งใจให้ไฟล์ 'memory' แมตช์ prompt ไทยได้ทาง n-gram
    แต่แมตช์ทาง .split() ไม่ได้ (คือปรากฏการณ์ที่ข้อ 21 กำลังวัด)"""
    (tmp_path / "memory-system.md").write_text(
        "# ระบบความจำ\nระบบความจำใช้ chromadb เก็บ embedding ของบทสนทนา", encoding="utf-8")
    (tmp_path / "deploy-nas.md").write_text(
        "# deploy\ndeploy ขึ้น NAS ด้วย docker compose", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("chromadb ทั่วไป", encoding="utf-8")
    (tmp_path / "skip.png").write_bytes(b"\x89PNG")
    return str(tmp_path)


# ── 1. refactor ต้องไม่เปลี่ยนพฤติกรรมการฉีด ────────────────────────────────────
def test_injected_context_format_is_frozen(tmp_path):
    """รูปแบบก้อน context ที่ฉีดเข้า prompt จริง — ตรึงเป็นตัวอักษร ห้ามเปลี่ยนโดยบังเอิญ

    ⚠️ **ห้ามเขียนเทสนี้เป็น `format_skill_files(select(...)) == load_skills_relevant(...)`**
    เพราะ `load_skills_relevant()` เรียก `format_skill_files()` เอง → แก้ตัวคั่นแล้วสองฝั่ง
    เปลี่ยนพร้อมกัน เทสเขียวตลอดกาล (ลองแกล้งแก้ตัวคั่นเป็น XXX แล้ว เทสรุ่นแรกไม่จับ)
    ต้องเทียบกับค่าที่เขียนตรงๆ เท่านั้น
    """
    (tmp_path / "a.md").write_text("alpha docker", encoding="utf-8")
    (tmp_path / "b.md").write_text("beta docker", encoding="utf-8")
    out = rag.load_skills_relevant(str(tmp_path), "docker")
    assert out in (
        "[a.md]\nalpha docker\n\n---\n\n[b.md]\nbeta docker",
        "[b.md]\nbeta docker\n\n---\n\n[a.md]\nalpha docker",   # คะแนนเสมอ → ลำดับ listdir
    ), out


def test_wrapper_and_selector_stay_in_sync(skills_dir):
    """`load_skills_relevant()` ต้องฉีดไฟล์ *ชุดเดียวกัน* กับที่ selector รายงาน
    (เทสนี้คุม 'ชุดไฟล์' ส่วนเทสข้างบนคุม 'รูปแบบ' — แยกกันเพื่อไม่ให้กลายเป็น tautology)"""
    for q in ["chromadb ระบบความจำ", "deploy docker", "ไม่มีอะไรตรงเลยจริงๆ", ""]:
        text = rag.load_skills_relevant(skills_dir, q)
        for pick in rag.select_skill_files(skills_dir, q):
            assert f"[{pick.name}]" in text, (q, pick.name)
        assert text.count("[") >= len(rag.select_skill_files(skills_dir, q))


def test_selector_respects_max_files_cap(skills_dir):
    picked = rag.select_skill_files(skills_dir, "chromadb", max_files=1)
    assert len(picked) == 1


def test_selector_returns_filenames_not_just_text(skills_dir):
    names = [f.name for f in rag.select_skill_files(skills_dir, "chromadb ระบบความจำ")]
    assert "memory-system.md" in names


def test_selector_skips_zero_score_files(skills_dir):
    """คะแนน 0 = ไม่ฉีด (พฤติกรรมเดิมของ prod) — ไม่ใช่ฉีดทุกไฟล์แล้วค่อยเรียง"""
    assert rag.select_skill_files(skills_dir, "ไม่มีอะไรตรงเลยจริงๆ") == []


# ── 2. scorer ต้องเป็นตัวเดียวกับที่เครื่องมือ ground truth ใช้ ──────────────────
def test_scorers_are_shared_with_groundtruth_script():
    """single source of truth — ถ้าแยกสำเนากันเมื่อไหร่ ตัวเลขสองที่จะเริ่มไม่ตรงกันเงียบๆ"""
    import skills_groundtruth as gt
    assert gt.score_split is shadow.score_split
    assert gt.score_ngram is shadow.score_ngram
    assert gt.HEAD_CHARS == shadow.HEAD_CHARS == 500


def test_shadow_select_caps_like_prod(tmp_path):
    """cap top-3 คือขั้นที่ทำตัวเลขผิดมาแล้ว (P=0.170 ที่ไม่ cap vs 0.109 ของจริง)
    ต้องมีเทสคุมตรงๆ — เทสรุ่นแรกไม่มี พอถอด `[:cap]` ออกก็ยังเขียวทั้งชุด"""
    for i in range(6):
        (tmp_path / f"f{i}.md").write_text("docker compose deploy", encoding="utf-8")
    hays = shadow.skill_haystacks(str(tmp_path))
    assert len(shadow.select("docker", hays, "ngram")) == shadow.CAP == 3
    assert len(shadow.select("docker", hays, "ngram", cap=1)) == 1


def test_shadow_select_matches_prod_selection_for_split(skills_dir):
    """คอลัมน์ `split` ของ shadow ต้อง = ไฟล์ที่ prod ฉีดจริง ไม่งั้นเทียบ scorer ไม่ได้"""
    q = "chromadb ระบบความจำ deploy docker"
    prod = [p.name for p in rag.select_skill_files(skills_dir, q)]
    hadow = [f for f, _ in shadow.select(q, shadow.skill_haystacks(skills_dir), "split")]
    assert hadow == prod


def test_split_scorer_blind_to_thai_but_ngram_is_not(skills_dir):
    """อาการหลักของข้อ 21 ต้องยังปรากฏในเครื่องมือวัด ไม่งั้นวัดผิดตัว"""
    hays = shadow.skill_haystacks(skills_dir)
    q = "ระบบความจำทำงานยังไง"
    assert shadow.select(q, hays, "split") == []
    assert [f for f, _ in shadow.select(q, hays, "ngram")]


# ── 3. "ไม่รู้" ≠ "ศูนย์" ────────────────────────────────────────────────────────
def test_semantic_absent_when_chromadb_unavailable(monkeypatch, skills_dir):
    monkeypatch.setattr(shadow, "semantic_scores", lambda *a, **k: {})
    row = shadow.build_row("ระบบความจำทำงานยังไง", skills_dir, injected=[])
    assert "semantic" not in row["choices"], "ChromaDB ล่มแล้ว log เป็น 0 = ข้อมูลปลอม"
    assert "ngram" in row["choices"]


def test_semantic_recorded_when_available(monkeypatch, skills_dir):
    monkeypatch.setattr(shadow, "semantic_scores",
                        lambda *a, **k: {"memory-system.md": 0.71, "deploy-nas.md": 0.12})
    row = shadow.build_row("ระบบความจำทำงานยังไง", skills_dir, injected=[])
    assert row["choices"]["semantic"][0] == ["memory-system.md", 0.71]


def test_row_records_what_prod_actually_injected(skills_dir):
    row = shadow.build_row("chromadb", skills_dir, injected=["memory-system.md", "notes.txt"])
    assert row["injected"] == ["memory-system.md", "notes.txt"]


def test_row_flags_thai_only_prompt(skills_dir):
    assert shadow.build_row("ระบบความจำ", skills_dir, injected=[])["thai_only"] is True
    assert shadow.build_row("chromadb คือ", skills_dir, injected=[])["thai_only"] is False


# ── 4. เก็บลง DB แล้ว join กับ feedback ได้จริง ─────────────────────────────────
def test_record_row_is_joinable_with_feedback(skills_dir, tmp_path, monkeypatch):
    """หัวใจของทั้งงาน: 1 สัปดาห์ผ่านไปต้อง join shadow × feedback ได้ด้วย message_id"""
    from utils import feedback, history
    aid = history.save_message("kwan", "assistant", "ตอบแล้ว", "test", "s1")
    row = shadow.build_row("ระบบความจำทำงานยังไง", skills_dir, injected=["memory-system.md"])
    shadow.record(row, message_id=aid, assistant="kwan", session_id="s1")
    feedback.save_feedback("kwan", "s1", aid, "up")

    conn = history._get_conn()
    got = conn.execute(
        """SELECT s.choices, f.rating FROM skill_shadow s
           JOIN feedback f ON f.message_id = s.message_id WHERE s.message_id = ?""",
        (aid,),
    ).fetchone()
    conn.close()
    assert got is not None, "join ไม่ติด = ข้อมูลที่เก็บทั้งสัปดาห์ใช้ไม่ได้"
    assert got[1] == "up"
    assert "ngram" in json.loads(got[0])


def test_record_is_idempotent_per_message(skills_dir):
    from utils import history
    aid = history.save_message("kwan", "assistant", "x", "test", "s2")
    row = shadow.build_row("chromadb", skills_dir, injected=[])
    shadow.record(row, message_id=aid, assistant="kwan", session_id="s2")
    shadow.record(row, message_id=aid, assistant="kwan", session_id="s2")
    conn = history._get_conn()
    n = conn.execute("SELECT COUNT(*) FROM skill_shadow WHERE message_id = ?", (aid,)).fetchone()[0]
    conn.close()
    assert n == 1


# ── 5. shadow พังห้ามทำแชทพัง ───────────────────────────────────────────────────
def test_record_never_raises_on_db_error(skills_dir, monkeypatch):
    def boom():
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(shadow, "_get_conn", boom)
    row = shadow.build_row("chromadb", skills_dir, injected=[])
    assert shadow.record(row, message_id=1, assistant="k", session_id="s") is None


def test_build_row_never_raises_on_bad_folder():
    row = shadow.build_row("chromadb", "/ไม่มีโฟลเดอร์นี้", injected=[])
    assert row["choices"] == {} or all(v == [] for v in row["choices"].values())


def test_observe_swallows_everything(monkeypatch, skills_dir):
    """เส้นที่ `routers/chat.py` เรียกจริง — ต้องกลืน exception ทุกชนิด"""
    monkeypatch.setattr(shadow, "build_row", lambda *a, **k: 1 / 0)
    shadow.observe(prompt="x", skills_dir=skills_dir, injected=[], message_id=1,
                   assistant="k", session_id="s", is_test_request=False)


# ── 6. traffic เทสต้องไม่ปน + นโยบายเก็บข้อมูล ─────────────────────────────────
def test_test_traffic_is_never_logged():
    """บทเรียน 2026-06-11: smoke test ปนเข้า memory แล้วถูก recall กลับมาตอบซ้ำ"""
    assert shadow.should_shadow_log("คำถามปกติ", is_test_request=True) is False


def test_empty_prompt_is_never_logged():
    assert shadow.should_shadow_log("", is_test_request=False) is False
    assert shadow.should_shadow_log("   ", is_test_request=False) is False


def test_normal_traffic_is_logged():
    assert shadow.should_shadow_log("ระบบความจำทำงานยังไง", is_test_request=False) is True


# ── 7. กฎการตัด: สัมบูรณ์ vs สัมพัทธ์ ────────────────────────────────────────────
def test_rule_absolute_cuts_by_score_and_cap():
    ranked = [("a", 0.62), ("b", 0.45), ("c", 0.41), ("d", 0.39)]
    assert shadow.rule_absolute(ranked, 0.40) == [("a", 0.62), ("b", 0.45), ("c", 0.41)]
    assert shadow.rule_absolute(ranked, 0.50) == [("a", 0.62)]
    assert shadow.rule_absolute(ranked, 0.99) == []
    assert len(shadow.rule_absolute([(str(i), 0.9) for i in range(9)], 0.1)) == shadow.CAP


def test_rule_margin_takes_group_that_leads_the_rest():
    """กฎสัมพัทธ์ = เอา prefix ที่ 'นำ' ตัวถัดไปอยู่อย่างน้อย x

    เหตุผลที่ต้องมี: คะแนน semantic ของ prompt ไทยต่ำทั้งแผง (มัธยฐานอันดับ 1 = 0.253)
    เกณฑ์สัมบูรณ์ตัวเดียวจึงยุติธรรมกับสองภาษาพร้อมกันไม่ได้ — ส่วนระยะห่างเป็นปริมาณ
    *ภายในคำถามเดียวกัน* ไม่ต้องเทียบข้ามภาษา
    """
    # a นำ b อยู่ 0.10 → เอาแค่ a
    assert shadow.rule_margin([("a", 0.40), ("b", 0.30), ("c", 0.29)], 0.05) == [("a", 0.40)]
    # a,b เกาะกลุ่มกัน แล้วทั้งคู่นำ c อยู่ 0.10 → เอา a,b
    assert shadow.rule_margin([("a", 0.41), ("b", 0.40), ("c", 0.30)], 0.05) == [("a", 0.41), ("b", 0.40)]
    # ไล่ระดับเรียบ ไม่มีใครนำใคร → ไม่ฉีดเลย ดีกว่าเดาสุ่ม
    assert shadow.rule_margin([("a", 0.40), ("b", 0.39), ("c", 0.38), ("d", 0.37)], 0.05) == []


def test_rule_margin_respects_cap_and_edge_cases():
    assert shadow.rule_margin([], 0.05) == []
    assert shadow.rule_margin([("a", 0.5)], 0.05) == [("a", 0.5)]      # มีตัวเดียว = นำขาด
    # margin 0 = "ไม่ต้องนำเลยก็พอ" → prefix สั้นสุดที่ผ่านคือ top-1 (ไม่ใช่เต็ม cap)
    # กฎนี้เลือก prefix **สั้นที่สุด** ที่นำได้เสมอ = เอนเข้าหา precision ตามที่ตั้งใจ
    flat = [(str(i), 1.0 - i * 0.001) for i in range(9)]
    assert shadow.rule_margin(flat, 0.0) == [("0", 1.0)]
    # จะได้เกิน 1 ไฟล์ก็ต่อเมื่อหัวตารางเกาะกลุ่มกันจริง แล้วทั้งกลุ่มนำที่เหลือ
    assert len(shadow.rule_margin([("a", .5), ("b", .5), ("c", .5), ("d", .1)], 0.05)) == 3


# ── 8. threshold ตอนวิเคราะห์: semantic คืน top-N เสมอ ไม่กรองเอง ────────────────
def test_apply_thresholds_filters_only_named_scorer():
    """ChromaDB คืน top-3 ทุกเทิร์นไม่ว่าเกี่ยวหรือไม่ → semantic 'ฉีด 100%' เป็นภาพลวง
    ถ้าไม่ตั้งเกณฑ์ ตัวเลขที่เอาไปเทียบกับ split จะเอียงเข้าข้าง semantic ฟรีๆ"""
    import skills_shadow_backfill as bf
    rows = [{"prompt": "p", "thai_only": True, "injected": [],
             "choices": {"semantic": [["a.md", 0.71], ["b.md", 0.33]],
                         "split": [["c.md", 0.5]]}}]
    out = bf.apply_thresholds(rows, {"semantic": 0.40})
    assert out[0]["choices"]["semantic"] == [["a.md", 0.71]]
    assert out[0]["choices"]["split"] == [["c.md", 0.5]], "scorer อื่นต้องไม่ถูกแตะ"


def test_apply_thresholds_does_not_mutate_input():
    import skills_shadow_backfill as bf
    rows = [{"prompt": "p", "thai_only": True, "injected": [],
             "choices": {"semantic": [["a.md", 0.1]]}}]
    bf.apply_thresholds(rows, {"semantic": 0.9})
    assert rows[0]["choices"]["semantic"] == [["a.md", 0.1]], "ต้นฉบับต้องไม่ถูกแก้"


def test_apply_thresholds_can_empty_a_scorer():
    import skills_shadow_backfill as bf
    out = bf.apply_thresholds(
        [{"prompt": "p", "thai_only": True, "injected": [],
          "choices": {"semantic": [["a.md", 0.1]]}}], {"semantic": 0.9})
    assert out[0]["choices"]["semantic"] == []


# ── 9. shadow ต้องเก็บลึกกว่าที่ฉีด ไม่งั้นประเมินกฎที่ยังไม่ได้คิดไม่ได้ ─────────
def test_row_records_deeper_ranking_than_it_would_inject(tmp_path):
    """เก็บแค่ top-3 (= ที่ฉีดจริง) แล้วกฎที่ต้องดู "อันดับถัดไป" จะประเมินย้อนหลังไม่ได้

    เจอจริง 2026-08-03: `rule_margin` บน log ที่ตัดไว้ 3 มองไม่เห็นอันดับ 4 เลยคิดว่า
    top-3 นำที่เหลืออยู่อนันต์ → "ผ่านเกณฑ์" เกือบทุกเทิร์น = ตัวเลขเปรียบเทียบพัง
    """
    for i in range(8):
        (tmp_path / f"f{i}.md").write_text("docker compose deploy nas", encoding="utf-8")
    row = shadow.build_row("docker deploy", str(tmp_path), injected=[])
    assert len(row["choices"]["ngram"]) == shadow.RECORD_TOP > shadow.CAP


def test_recorded_ranking_is_still_capped_when_fewer_files(tmp_path):
    (tmp_path / "a.md").write_text("docker", encoding="utf-8")
    row = shadow.build_row("docker", str(tmp_path), injected=[])
    assert len(row["choices"]["ngram"]) == 1


def test_apply_thresholds_caps_back_to_prod_before_reporting():
    """log เก็บลึก 8 แต่ prod ฉีดแค่ 3 → ตอนรายงานต้องตัดกลับ ไม่งั้นตัวเลขเฟ้อทันที
    ลำดับต้องเป็น กรองคะแนน → เรียง → ตัด (ตรงกับ prod) ไม่ใช่ ตัด → กรอง"""
    import skills_shadow_backfill as bf
    picks = [["a", .9], ["b", .8], ["c", .7], ["d", .6], ["e", .5]]
    out = bf.apply_thresholds([{"prompt": "p", "thai_only": True, "injected": [],
                                "choices": {"semantic": picks}}], {"semantic": 0.55})
    assert out[0]["choices"]["semantic"] == [["a", .9], ["b", .8], ["c", .7]]


def test_rule_margin_does_not_treat_end_of_list_as_infinite_lead():
    """รายชื่อที่ไล่ระดับเรียบ *ทั้งชุด* ต้องคืน [] ไม่ใช่ผ่านที่ k ตัวสุดท้าย

    บั๊กเดียวกับตอน log เก็บแค่ top-3: "ไม่มีอันดับถัดไป" ถูกนับเป็น "นำอยู่อนันต์"
    """
    assert shadow.rule_margin([("a", .31), ("b", .30), ("c", .29)], 0.08) == []
    assert shadow.rule_margin([("a", .31), ("b", .30)], 0.08) == []
    assert shadow.rule_margin([("a", .31)], 0.08) == [("a", .31)]   # มีคนเดียว = นำขาด
