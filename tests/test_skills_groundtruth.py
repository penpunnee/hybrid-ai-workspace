"""Tests สำหรับ scripts/skills_groundtruth.py — เครื่องมือวัดต้องเชื่อได้ก่อนใช้ตัดสินใจ

บทเรียนที่ต้องกันซ้ำ (จาก Phrae Data Map + ข้อ 12/16): **เครื่องมือวัดโกหกได้**
ถ้า sweep นับคู่ที่ยังไม่มาร์ค หรือคำนวณ P/R ผิด เราจะได้ "หลักฐาน" ที่พาไปแก้ผิดทาง
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import skills_groundtruth as gt


def _pair(label, split, ngram, thai=True):
    return {"prompt": "p", "skill_file": "f.md", "thai_only": thai,
            "scores": {"split": split, "ngram": ngram}, "label": label}


# ── กติกาหลัก: ห้ามเดาแทนคน ──────────────────────────────────────────────────
def test_sweep_ignores_unlabelled_pairs():
    pairs = [_pair(True, 1.0, 1.0), _pair(None, 1.0, 1.0), _pair(None, 0.0, 0.0)]
    at_zero = [m for m in gt.sweep(pairs) if m.scorer == "split" and m.threshold == 0.0]
    assert at_zero[0].tp + at_zero[0].fp == 1, "คู่ที่ยังไม่มาร์คถูกนับด้วย"


def test_sweep_with_no_labels_returns_empty_counts():
    rows = gt.sweep([_pair(None, 1.0, 1.0)])
    assert all(m.tp == 0 and m.fp == 0 and m.fn == 0 for m in rows)


# ── เลขต้องถูก ────────────────────────────────────────────────────────────────
def test_metrics_arithmetic():
    m = gt.Metrics("split", 0.5, tp=3, fp=1, fn=1)
    assert m.precision == 0.75
    assert m.recall == 0.75
    assert abs(m.f1 - 0.75) < 1e-9


def test_threshold_splits_correctly():
    pairs = [_pair(True, 0.8, 0.8), _pair(False, 0.2, 0.2)]
    rows = {m.threshold: m for m in gt.sweep(pairs) if m.scorer == "split"}
    assert rows[0.5].tp == 1 and rows[0.5].fp == 0 and rows[0.5].fn == 0
    assert rows[0.9].tp == 0 and rows[0.9].fn == 1        # เกณฑ์สูงเกิน → พลาดของที่ควรได้
    assert rows[0.0].fp == 1                              # เกณฑ์ต่ำสุด → รับของที่ไม่ควรมาด้วย


# ── scorer: ต้องสะท้อนบั๊กที่กำลังจะแก้จริง ─────────────────────────────────────
def test_split_scorer_fails_on_thai_without_spaces():
    """หัวใจของข้อ 21 — ไทยเขียนติดกัน `.split()` เลยได้ token เดียวที่ยาวเกินจะ match"""
    hay = "memory-system-chromadb.md ระบบความจำใช้ chromadb เก็บ embedding"
    assert gt.score_split("ระบบความจำทำงานยังไง", hay) == 0.0
    assert gt.score_ngram("ระบบความจำทำงานยังไง", hay) > 0.0


def test_split_scorer_works_when_latin_present():
    """เส้นที่ทำงานอยู่แล้ววันนี้ — ต้องไม่ถูกทำพังตอนเปลี่ยน tokenizer"""
    hay = "memory-system-chromadb.md ระบบความจำใช้ chromadb เก็บ embedding"
    assert gt.score_split("memory system ทำงานยังไง", hay) > 0.0


def test_scorers_return_zero_for_empty_query():
    assert gt.score_split("", "อะไรก็ได้") == 0.0
    assert gt.score_ngram("", "อะไรก็ได้") == 0.0


# ── haystack ต้องตรงกับของจริง ไม่งั้นวัดคนละอย่างกับที่ prod ทำ ────────────────
def test_skill_docs_matches_production_haystack(tmp_path):
    """`load_skills_relevant()` เทียบกับ `filename + " " + content[:500]` (lower)
    ถ้าสคริปต์วัดคนละก้อน ตัวเลขที่ได้จะไม่เกี่ยวกับพฤติกรรมจริงเลย"""
    (tmp_path / "a.md").write_text("HEAD" + "x" * 1000, encoding="utf-8")
    docs = gt._skill_docs(str(tmp_path))
    assert set(docs) == {"a.md"}
    assert docs["a.md"] == ("a.md " + ("HEAD" + "x" * 1000)[:gt.HEAD_CHARS]).lower()
    assert gt.HEAD_CHARS == 500


def test_skill_docs_skips_non_skill_files(tmp_path):
    (tmp_path / "ok.md").write_text("เนื้อหา", encoding="utf-8")
    (tmp_path / "skip.png").write_bytes(b"\x89PNG")
    assert set(gt._skill_docs(str(tmp_path))) == {"ok.md"}


# ── worksheet round-trip: กาใน .md แล้วต้องกลับเข้า pairs.json ให้ตรงคู่ ────────
def _fixture_pairs():
    return [
        {"prompt": "ระบบความจำทำงานยังไง", "skill_file": "memory.md", "thai_only": True,
         "scores": {"split": 0.0, "ngram": 0.31}, "label": None},
        {"prompt": "ระบบความจำทำงานยังไง", "skill_file": "deploy.md", "thai_only": True,
         "scores": {"split": 0.0, "ngram": 0.12}, "label": None},
        {"prompt": "deploy ขึ้น NAS ยังไง", "skill_file": "deploy.md", "thai_only": False,
         "scores": {"split": 0.5, "ngram": 0.40}, "label": None},
    ]


def test_worksheet_import_roundtrip(tmp_path):
    import json as _json
    import types
    pairs_path = tmp_path / "pairs.json"
    ws_path = tmp_path / "ws.md"
    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "memory.md").write_text("# ระบบความจำ ChromaDB\nเนื้อหา", encoding="utf-8")
    (skills / "deploy.md").write_text("# Deploy ขึ้น NAS\nเนื้อหา", encoding="utf-8")
    pairs_path.write_text(_json.dumps(_fixture_pairs(), ensure_ascii=False), encoding="utf-8")

    gt.cmd_worksheet(types.SimpleNamespace(
        pairs=str(pairs_path), skills_dir=str(skills), out=str(ws_path)))
    ws = ws_path.read_text(encoding="utf-8")
    assert "ระบบความจำ ChromaDB" in ws, "worksheet ต้องบอกว่าไฟล์นั้นเรื่องอะไร"
    assert ws.count("- [ ]") == 3

    # คนกาช่องแรก (memory.md ของ prompt ที่ 1) อย่างเดียว
    ws = ws.replace("- [ ] `memory.md`", "- [x] `memory.md`", 1)
    ws_path.write_text(ws, encoding="utf-8")

    gt.cmd_import(types.SimpleNamespace(pairs=str(pairs_path), worksheet=str(ws_path)))
    out = {(p["prompt"], p["skill_file"]): p["label"]
           for p in _json.loads(pairs_path.read_text(encoding="utf-8"))}
    assert out[("ระบบความจำทำงานยังไง", "memory.md")] is True
    assert out[("ระบบความจำทำงานยังไง", "deploy.md")] is False
    assert out[("deploy ขึ้น NAS ยังไง", "deploy.md")] is False


def test_import_ignores_deleted_lines(tmp_path):
    """ลบบรรทัดทิ้ง = ไม่แน่ใจ → ต้องคง label=None ไม่ใช่กลายเป็น false"""
    import json as _json
    import types
    pairs_path = tmp_path / "pairs.json"
    ws_path = tmp_path / "ws.md"
    pairs_path.write_text(_json.dumps(_fixture_pairs(), ensure_ascii=False), encoding="utf-8")
    ws_path.write_text("### [1] ไทยล้วน — ระบบความจำทำงานยังไง\n"
                       "- [x] `memory.md`  (split 0.00)\n", encoding="utf-8")

    gt.cmd_import(types.SimpleNamespace(pairs=str(pairs_path), worksheet=str(ws_path)))
    out = {(p["prompt"], p["skill_file"]): p["label"]
           for p in _json.loads(pairs_path.read_text(encoding="utf-8"))}
    assert out[("ระบบความจำทำงานยังไง", "memory.md")] is True
    assert out[("ระบบความจำทำงานยังไง", "deploy.md")] is None    # ไม่มีในไฟล์ → ยังไม่มาร์ค
    assert out[("deploy ขึ้น NAS ยังไง", "deploy.md")] is None
