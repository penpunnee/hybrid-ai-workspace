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
        pairs=str(pairs_path), skills_dir=str(skills), out=str(ws_path),
        only_unlabeled=False, by_importance=False))
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
    ws_path.write_text(f"### [1] ไทยล้วน — ระบบความจำทำงานยังไง "
                       f"<!--k:{gt._pkey('ระบบความจำทำงานยังไง')}-->\n"
                       "- [x] `memory.md`  (split 0.00)\n", encoding="utf-8")

    gt.cmd_import(types.SimpleNamespace(pairs=str(pairs_path), worksheet=str(ws_path)))
    out = {(p["prompt"], p["skill_file"]): p["label"]
           for p in _json.loads(pairs_path.read_text(encoding="utf-8"))}
    assert out[("ระบบความจำทำงานยังไง", "memory.md")] is True
    assert out[("ระบบความจำทำงานยังไง", "deploy.md")] is None    # ไม่มีในไฟล์ → ยังไม่มาร์ค
    assert out[("deploy ขึ้น NAS ยังไง", "deploy.md")] is None


# ── candidate pool ต้องครอบคลุมพอที่จะวัด recall ได้จริง (เจอจุดบอด 2026-08-03) ──
#
# รอบแรก candidate = union ของ top-3 จาก scorer แบบ lexical เท่านั้น
# → prompt "NAS ที่บ้านรุ่นอะไร" ไม่เคยได้ `pawin-context.md` เป็นตัวเลือกให้มาร์ค
#   ทั้งที่ไฟล์นั้นมีคำตอบอยู่จริง (`Infrastructure: Synology NAS DS923+`)
# → ไฟล์ที่ "ควรฉีดแต่ทุก scorer ให้คะแนนต่ำ" มองไม่เห็น = FN หายไปจากการนับ
#   = **recall ที่วัดได้สวยเกินจริงทุกวิธีพร้อมกัน**
def test_sweep_derives_scorers_from_data_not_hardcoded():
    """เพิ่ม scorer ใหม่ (semantic) แล้ว sweep ต้องเทียบให้ด้วย ไม่ใช่รู้จักแค่ที่ hardcode"""
    pairs = [
        {"prompt": "p", "skill_file": "a.md", "thai_only": True,
         "scores": {"split": 0.0, "ngram": 0.1, "semantic": 0.9}, "label": True},
        {"prompt": "p", "skill_file": "b.md", "thai_only": True,
         "scores": {"split": 0.9, "ngram": 0.9, "semantic": 0.1}, "label": False},
    ]
    names = {m.scorer for m in gt.sweep(pairs)}
    assert "semantic" in names, "sweep ไม่เห็น scorer ที่มีอยู่ในข้อมูล"
    sem_best = max((m for m in gt.sweep(pairs) if m.scorer == "semantic"), key=lambda m: m.f1)
    assert sem_best.f1 == 1.0


def test_merge_preserves_existing_labels():
    """สร้าง candidate เพิ่มแล้วต้องไม่ล้าง label ที่คนมาร์คไว้แล้ว"""
    old = [{"prompt": "p", "skill_file": "a.md", "thai_only": True,
            "scores": {"split": 0.5}, "label": True}]
    new = [{"prompt": "p", "skill_file": "a.md", "thai_only": True,
            "scores": {"split": 0.5, "semantic": 0.8}, "label": None},
           {"prompt": "p", "skill_file": "b.md", "thai_only": True,
            "scores": {"split": 0.0, "semantic": 0.7}, "label": None}]
    merged = gt.merge_pairs(old, new)
    got = {(p["prompt"], p["skill_file"]): p for p in merged}
    assert got[("p", "a.md")]["label"] is True, "label เดิมหาย = คนต้องมาร์คใหม่ทั้งชุด"
    assert got[("p", "a.md")]["scores"].get("semantic") == 0.8, "คะแนนใหม่ไม่ได้ถูกอัปเดต"
    assert got[("p", "b.md")]["label"] is None
    assert len(merged) == 2


def test_merge_keeps_pairs_that_dropped_out_of_candidates():
    """คู่ที่เคยมาร์คแล้วแต่รอบใหม่ไม่ติด candidate ต้องไม่หายไป (ไม่งั้นเสียแรงมาร์คฟรี)"""
    old = [{"prompt": "p", "skill_file": "gone.md", "thai_only": True,
            "scores": {"split": 0.1}, "label": False}]
    merged = gt.merge_pairs(old, [])
    assert len(merged) == 1 and merged[0]["label"] is False


def test_random_extras_are_marked_as_such():
    """ตัวสุ่มมีไว้วัดว่า candidate pool ยังมีจุดบอดไหม — ต้องแยกออกจากตัวที่ scorer เลือก"""
    picked = gt.pick_candidates(
        scores={"split": {"a.md": 0.9, "b.md": 0.0, "c.md": 0.0, "d.md": 0.0}},
        top_k=1, random_extra=2, rng_seed=1,
    )
    assert picked["a.md"] == "scorer"
    extras = [f for f, src in picked.items() if src == "random"]
    assert len(extras) == 2 and "a.md" not in extras


def test_import_maps_by_stable_key_not_by_order(tmp_path):
    """worksheet ที่เรียงใหม่ (--by-importance) ต้อง import กลับถูก prompt

    เดิม import แมปด้วย `### [n]` → order[n-1] ที่คำนวณจากลำดับใน pairs.json
    พอ worksheet เรียงคนละแบบ label จะไปลง prompt ผิดตัวแบบเงียบๆ
    """
    import json as _json
    import types
    pairs_path = tmp_path / "pairs.json"
    ws_path = tmp_path / "ws.md"
    skills = tmp_path / "skills"; skills.mkdir()
    (skills / "a.md").write_text("# A", encoding="utf-8")
    data = [
        {"prompt": "คำถามแรก", "skill_file": "a.md", "thai_only": True,
         "scores": {"split": 0.1}, "label": None},
        {"prompt": "คำถามที่สอง", "skill_file": "a.md", "thai_only": True,
         "scores": {"split": 0.9}, "label": None},
    ]
    pairs_path.write_text(_json.dumps(data, ensure_ascii=False), encoding="utf-8")

    # by_importance → "คำถามที่สอง" (0.9) ขึ้นก่อน = สลับกับลำดับใน pairs.json
    gt.cmd_worksheet(types.SimpleNamespace(
        pairs=str(pairs_path), skills_dir=str(skills), out=str(ws_path),
        only_unlabeled=True, by_importance=True))
    ws = ws_path.read_text(encoding="utf-8")
    assert ws.index("คำถามที่สอง") < ws.index("คำถามแรก"), "ไม่ได้เรียงตามความสำคัญ"

    # กาช่องแรกสุด (= คำถามที่สอง)
    ws_path.write_text(ws.replace("- [ ]", "- [x]", 1), encoding="utf-8")
    gt.cmd_import(types.SimpleNamespace(pairs=str(pairs_path), worksheet=str(ws_path)))
    got = {p["prompt"]: p["label"] for p in _json.loads(pairs_path.read_text(encoding="utf-8"))}
    assert got["คำถามที่สอง"] is True, "label ไปลงผิด prompt"
    assert got["คำถามแรก"] is False


# ── scrutinize 2026-08-03: เครื่องมือไม่ตรงกับ prod / ไม่พิมพ์ scorer ที่ชนะ ──────
def test_cmd_sweep_reports_every_scorer_in_data(tmp_path, capsys):
    """cmd_sweep วนด้วย SCORERS ที่ hardcode → `semantic` หายจากรายงานเงียบๆ
    ทั้งที่ sweep() คำนวณให้แล้ว = คนที่รันคำสั่งจริงไม่เห็นวิธีที่ชนะ"""
    import json as _json
    import types
    p = tmp_path / "pairs.json"
    p.write_text(_json.dumps([
        {"prompt": "p1", "skill_file": "a.md", "thai_only": True,
         "scores": {"split": 0.0, "ngram": 0.1, "semantic": 0.9}, "label": True},
        {"prompt": "p1", "skill_file": "b.md", "thai_only": True,
         "scores": {"split": 0.9, "ngram": 0.9, "semantic": 0.1}, "label": False},
    ], ensure_ascii=False), encoding="utf-8")
    gt.cmd_sweep(types.SimpleNamespace(labeled=str(p), cap=3))
    out = capsys.readouterr().out
    for name in ("split", "ngram", "semantic"):
        assert f"[{name}]" in out, f"รายงานไม่มี {name}"


def test_simulate_injection_applies_top_k_cap():
    """prod เอาแค่ top-3 ต่อ prompt — ถ้าไม่ cap ตัวเลขที่รายงานจะไม่ใช่พฤติกรรมจริง
    (เจอจริง: split ที่ไม่ cap ให้ P=0.170 R=0.818 · cap แล้วได้ P=0.109 R=0.455)"""
    pairs = [
        {"prompt": "p", "skill_file": f"f{i}.md", "scores": {"s": 0.9 - i * 0.1},
         "label": i == 3}                      # ตัวที่ถูกอยู่อันดับ 4 → prod ไม่ฉีด
        for i in range(5)
    ]
    n, tp, P, R, F = gt.simulate_injection(pairs, "s", threshold=0.0, cap=3)
    assert n == 3 and tp == 0, "ไม่ได้ตัด top-3 → นับไฟล์ที่ prod ไม่เคยฉีด"
    n2, tp2, *_ = gt.simulate_injection(pairs, "s", threshold=0.0, cap=99)
    assert n2 == 5 and tp2 == 1


def test_random_seed_is_stable_across_processes():
    """เดิมใช้ hash() ซึ่ง Python randomize ต่อ process → สุ่มไม่ซ้ำ รันใหม่ได้คนละชุด
    = 'การทดลองวัดจุดบอด' ที่ทำซ้ำไม่ได้"""
    assert gt._seed("ราคาทองวันนี้เท่าไหร่") == gt._seed("ราคาทองวันนี้เท่าไหร่")
    # ตรึงค่าไว้เลย — ถ้าใครเปลี่ยนไปใช้ hash() อีก เทสนี้จะแดงทันที
    import hashlib
    expect = int(hashlib.sha1("ราคาทองวันนี้เท่าไหร่".encode()).hexdigest()[:8], 16)
    assert gt._seed("ราคาทองวันนี้เท่าไหร่") == expect


def test_sweep_skips_pairs_missing_that_score_instead_of_imputing_zero():
    """คู่ที่ไม่มีคะแนนของ scorer นั้น ต้องถูก 'ข้าม' ไม่ใช่นับเป็น 0

    merge เก็บคู่เก่าที่ยังไม่มีคะแนน semantic ไว้ → เดาเป็น 0 = คู่ negative
    กลายเป็น 'semantic ไม่ฉีด' ฟรีๆ ดัน precision ให้สูงเกินจริง
    (แพตเทิร์น 'ล้มเหลว → ศูนย์')
    """
    pairs = [
        {"prompt": "p", "skill_file": "a.md", "scores": {"split": 0.9}, "label": False},
        {"prompt": "p", "skill_file": "b.md", "scores": {"split": 0.9, "semantic": 0.9},
         "label": True},
    ]
    rows = [m for m in gt.sweep(pairs) if m.scorer == "semantic" and m.threshold == 0.0]
    assert rows[0].fp == 0 and rows[0].tp == 1
    assert rows[0].skipped == 1, "ไม่ได้รายงานว่ามีคู่ที่ประเมินไม่ได้"


def test_merge_refreshes_scores_of_carried_over_pairs():
    """คู่เก่าที่ไม่ติด candidate รอบใหม่ ต้องได้คะแนนชุดใหม่ด้วย ไม่ใช่ค้างคะแนนเก่า

    ไม่งั้นมันจะไม่มีคะแนนของ scorer ที่เพิ่งเพิ่ม (semantic) → ถูกข้ามตอนประเมิน
    = ประเมิน scorer ใหม่บนตัวอย่างน้อยกว่าตัวอื่นโดยไม่มีใครรู้
    """
    old = [{"prompt": "p", "skill_file": "old.md", "thai_only": True,
            "scores": {"split": 0.1}, "label": False}]
    table = {"p": {"split": {"old.md": 0.2}, "semantic": {"old.md": 0.8}}}
    merged = gt.merge_pairs(old, [], score_table=table)
    got = merged[0]
    assert got["label"] is False
    assert got["scores"] == {"split": 0.2, "semantic": 0.8}, "คะแนนเก่าค้าง"


def test_merge_leaves_pairs_from_other_runs_untouched():
    """prompt ที่ไม่ได้อยู่ในรอบนี้ (ไม่มีใน score_table) ต้องไม่ถูกแตะ"""
    old = [{"prompt": "อื่น", "skill_file": "x.md", "thai_only": True,
            "scores": {"split": 0.1}, "label": True}]
    merged = gt.merge_pairs(old, [], score_table={"p": {"split": {"x.md": 0.9}}})
    assert merged[0]["scores"] == {"split": 0.1} and merged[0]["label"] is True
