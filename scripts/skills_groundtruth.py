#!/usr/bin/env python3
"""Ground truth ของ skills injection — backlog ข้อ 21 (ตัวบล็อกของการแก้ tokenizer)

ปัญหา: `utils/rag.py:load_skills_relevant()` ตัดคำด้วย `query.lower().split()`
ภาษาไทยไม่มีช่องว่างระหว่างคำ → prompt ไทยล้วนเสียเปรียบ วัดจริงบน prod
(376 prompt จริง 2026-08-03):

    ไทยล้วน (ไม่มี A-Z) : 252 prompt → ฉีด  81 (32%)
    มี Latin ปน         : 124 prompt → ฉีด 105 (84%)

**แต่ห้ามแก้ลอยๆ** — ไฟล์ที่ฉีดเข้าไปมี median ~6,000 chars (≈1,500 tokens) ต่อเทิร์น
ถ้าดัน tokenizer ให้ไทยฉีดได้มากขึ้นโดยไม่รู้ว่า *ของที่ฉีดเพิ่มมาเกี่ยวจริงไหม*
ก็แค่เพิ่ม noise ให้ทุกบทสนทนา — ต้องรู้ precision ก่อน ไม่ใช่ดูอัตราฉีดอย่างเดียว

วิธี (เหมือน `scripts/recall_groundtruth.py` ของข้อ 12):
  เอา prompt จริงจาก prod → รวม candidate จากทุกวิธีให้ครบ → **คนมาร์ค** ว่าคู่ไหน
  ควรถูกฉีด → ค่อยเทียบวิธีตัดคำจากข้อมูลที่มาร์คแล้ว

    python scripts/skills_groundtruth.py pairs     --n 30 --out data/skills_pairs.json
    python scripts/skills_groundtruth.py worksheet --pairs data/skills_pairs.json
    # ← คนเปิด data/skills_labeling.md แล้วกาช่อง [x] = "ควรฉีดไฟล์นี้ให้ prompt นี้"
    python scripts/skills_groundtruth.py import    --pairs data/skills_pairs.json
    python scripts/skills_groundtruth.py sweep     --labeled data/skills_pairs.json

⚠️ คู่ที่ยังไม่มาร์ค (label=None) ถูกข้ามเสมอ — ห้ามเดาแทนคน (กติกาเดียวกับข้อ 12)
"""
from __future__ import annotations

import argparse
import json
import hashlib
import os
import random
import re
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# scorer/haystack ตัวจริงอยู่ที่ `utils/skills_shadow.py` ที่เดียว — สคริปต์นี้กับ shadow
# logging ต้องให้คะแนนเหมือนกันเป๊ะ ไม่งั้นตัวเลขสองที่จะค่อยๆ ไม่ตรงกันแบบไม่มีใครรู้
from utils.skills_shadow import (      # noqa: E402
    HEAD_CHARS,
    SCORERS,
    score_ngram,
    score_split,
    semantic_scores,
)

_LATIN = re.compile(r"[A-Za-z]")

__all__ = ["HEAD_CHARS", "SCORERS", "score_ngram", "score_split", "semantic_scores"]


def pick_candidates(scores: dict[str, dict[str, float]], top_k: int,
                    random_extra: int = 0, rng_seed: int | None = None) -> dict[str, str]:
    """เลือกไฟล์ที่จะให้คนมาร์ค → {filename: "scorer" | "random"}

    ตัวสุ่มมีไว้**วัดว่า candidate pool ยังมีจุดบอดไหม** ไม่ใช่เพิ่มงานเปล่า:
    ถ้าคนมาร์คแล้วเจอ "ควรฉีด" ในกลุ่มสุ่ม แปลว่ายังมีไฟล์ที่ควรฉีดแต่ไม่มี scorer ไหนดันขึ้นมา
    → recall ที่วัดได้ยังสวยเกินจริง (เจอจริงรอบแรก: `pawin-context.md` ที่มี "Synology NAS DS923+"
    ไม่เคยถูกเสนอให้มาร์คเลยสำหรับ prompt "NAS ที่บ้านรุ่นอะไร")
    """
    picked: dict[str, str] = {}
    everything: set[str] = set()
    for per_file in scores.values():
        everything.update(per_file)
        for f, sc in sorted(per_file.items(), key=lambda kv: -kv[1])[:top_k]:
            if sc > 0:
                picked.setdefault(f, "scorer")
    if random_extra > 0:
        rest = sorted(everything - set(picked))
        if rest:
            rng = random.Random(rng_seed)
            for f in rng.sample(rest, min(random_extra, len(rest))):
                picked[f] = "random"
    return picked


def merge_pairs(old: list[dict], new: list[dict],
                score_table: dict[str, dict[str, dict[str, float]]] | None = None) -> list[dict]:
    """รวม candidate รอบใหม่เข้ากับของเดิม **โดยไม่ทิ้ง label ที่คนมาร์คไว้**

    - คู่ที่เคยมาร์คแล้วและยังอยู่ → เก็บ label เดิม แต่รับคะแนนชุดใหม่
    - คู่ที่เคยมาร์คแล้วแต่รอบใหม่ไม่ติด candidate → **เก็บไว้** (ไม่งั้นเสียแรงมาร์คฟรี)
    - คู่ใหม่ → label=None รอคนมาร์ค
    """
    by_key = {(p["prompt"], p["skill_file"]): dict(p) for p in old}
    for p in new:
        k = (p["prompt"], p["skill_file"])
        if k in by_key:
            by_key[k]["scores"] = p["scores"]
            by_key[k].setdefault("source", p.get("source", "scorer"))
        else:
            by_key[k] = dict(p)

    # คู่เก่าที่ไม่ติด candidate รอบใหม่ ก็ยังต้องได้คะแนนชุดใหม่ ไม่งั้นมันจะไม่มีคะแนน
    # ของ scorer ที่เพิ่งเพิ่ม แล้วถูกข้ามตอนประเมิน = ประเมินบนตัวอย่างน้อยกว่าตัวอื่นเงียบๆ
    if score_table:
        for (prompt, fname), p in by_key.items():
            per_scorer = score_table.get(prompt)
            if not per_scorer:
                continue                      # prompt คนละรอบ — ไม่แตะ
            fresh = {n: round(tbl[fname], 4) for n, tbl in per_scorer.items() if fname in tbl}
            if fresh:
                p["scores"] = fresh
    return list(by_key.values())


@dataclass(frozen=True)
class Metrics:
    scorer: str
    threshold: float
    tp: int
    fp: int
    fn: int
    skipped: int = 0        # คู่ที่ไม่มีคะแนนของ scorer นี้ — ข้าม ไม่ใช่เดาเป็น 0

    @property
    def precision(self) -> float:
        got = self.tp + self.fp
        return self.tp / got if got else 1.0

    @property
    def recall(self) -> float:
        want = self.tp + self.fn
        return self.tp / want if want else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


def _skill_docs(skills_dir: str) -> dict[str, str]:
    """{filename: haystack} — haystack เหมือนที่ load_skills_relevant() ใช้เทียบเป๊ะ"""
    docs = {}
    for fn in sorted(os.listdir(skills_dir)):
        path = os.path.join(skills_dir, fn)
        if not (os.path.isfile(path) and fn.endswith((".txt", ".md", ".json", ".py"))):
            continue
        with open(path, encoding="utf-8", errors="ignore") as f:
            content = f.read()
        docs[fn] = (fn + " " + content[:HEAD_CHARS]).lower()
    return docs


def _real_prompts(limit: int) -> list[str]:
    from utils.history import _get_conn
    conn = _get_conn()
    rows = conn.execute(
        """SELECT DISTINCT content FROM messages
           WHERE role = 'user' AND length(content) BETWEEN 5 AND 300
           ORDER BY id DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    return [r[0] for r in rows]


def cmd_pairs(args) -> int:
    docs = _skill_docs(args.skills_dir)
    if not docs:
        print(f"ไม่พบไฟล์ skill ใน {args.skills_dir}", file=sys.stderr)
        return 1

    prompts = _real_prompts(args.pool)
    thai = [p for p in prompts if not _LATIN.search(p)]
    mixed = [p for p in prompts if _LATIN.search(p)]
    # สุ่มแบบ stratified ครึ่งต่อครึ่ง — ปัญหาอยู่ที่ฝั่งไทย ต้องมีตัวอย่างพอ
    half = args.n // 2
    picked = thai[:half] + mixed[: args.n - half]
    if not picked:
        print("ไม่มี prompt ใน DB", file=sys.stderr)
        return 1

    n_sem = 0
    pairs = []
    score_table: dict[str, dict[str, dict[str, float]]] = {}
    for prompt in picked:
        scores: dict[str, dict[str, float]] = {
            name: {f: fn(prompt, h) for f, h in docs.items()} for name, fn in SCORERS.items()
        }
        sem = semantic_scores(prompt)
        if sem:
            n_sem += 1
            scores["semantic"] = {f: sem.get(f, 0.0) for f in docs}

        score_table[prompt] = scores
        cands = pick_candidates(scores, top_k=args.top_k,
                                random_extra=args.random_extra, rng_seed=_seed(prompt))
        for f, src in sorted(cands.items()):
            pairs.append({
                "prompt": prompt,
                "skill_file": f,
                "thai_only": not _LATIN.search(prompt),
                "source": src,          # scorer = มี scorer ดันขึ้นมา · random = ตัววัดจุดบอด
                "scores": {n: round(scores[n][f], 4) for n in scores},
                "label": None,   # ← คนมาร์ค: true = ควรฉีดไฟล์นี้ให้ prompt นี้ / false = ไม่ควร
            })

    if os.path.exists(args.out):
        old = json.load(open(args.out, encoding="utf-8"))
        before = sum(1 for p in old if p.get("label") is not None)
        pairs = merge_pairs(old, pairs, score_table=score_table)
        print(f"รวมกับของเดิม — คง label ที่มาร์คไว้แล้ว {before} คู่")
    if not n_sem:
        print("⚠️ ChromaDB ใช้ไม่ได้ → ไม่มีคะแนน semantic (เทียบได้แค่ lexical)")

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(pairs, f, ensure_ascii=False, indent=2)
    print(f"เขียน {len(pairs)} คู่ ({len(picked)} prompt · ไทยล้วน "
          f"{sum(1 for p in picked if not _LATIN.search(p))}) → {args.out}")
    print('ขั้นต่อไป: เปิดไฟล์แล้วเติม "label": true/false ทีละคู่ (ปล่อย null = ข้าม)')
    return 0


# ── worksheet: กา [x] ในไฟล์ .md อ่านง่ายกว่าแก้ JSON 110 คู่ด้วยมือ ──────────────
_LINE = re.compile(r"^- \[(?P<mark>[ xX])\]\s+`(?P<file>[^`]+)`")
_HEAD = re.compile(r"^### \[(?P<idx>\d+)\].*<!--k:(?P<key>[0-9a-f]{10})-->")


def _seed(prompt: str) -> int:
    """seed ของการสุ่มที่ **ซ้ำได้ข้าม process**

    เดิมใช้ `hash(prompt)` ซึ่ง Python randomize ต่อ process (PYTHONHASHSEED)
    → รันใหม่ได้ candidate สุ่มคนละชุด = การทดลองวัดจุดบอดทำซ้ำไม่ได้
    """
    return int(hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:8], 16)


def _pkey(prompt: str) -> str:
    """key เสถียรของ prompt — ผูก label กับตัว prompt ไม่ใช่ลำดับในไฟล์
    (worksheet เรียงใหม่ได้ด้วย --by-importance → แมปด้วยเลขลำดับจะลงผิดตัวแบบเงียบๆ)"""
    return hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:10]


def _first_heading(path: str) -> str:
    """บรรทัดที่อ่านแล้วรู้ว่าไฟล์นี้เรื่องอะไร — ช่วยคนตัดสินโดยไม่ต้องเปิดไฟล์"""
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if line.startswith("#"):
                    return line.lstrip("#").strip()[:70]
    except OSError:
        pass
    return ""


def cmd_worksheet(args) -> int:
    all_pairs = json.load(open(args.pairs, encoding="utf-8"))
    pairs = [p for p in all_pairs if p.get("label") is None] if args.only_unlabeled else all_pairs
    if not pairs:
        print("ไม่มีคู่ที่ยังไม่ได้มาร์ค")
        return 0
    # เรียง prompt ตาม "คู่ที่คะแนนสูงสุด" — มาร์คบางส่วนแล้วหยุดก็ยังได้ข้อมูลที่มีน้ำหนัก
    if args.by_importance:
        rank = {}
        for p in pairs:
            v = max(p["scores"].values()) if p["scores"] else 0.0
            rank[p["prompt"]] = max(rank.get(p["prompt"], 0.0), v)
        pairs = sorted(pairs, key=lambda p: -rank[p["prompt"]])
    order: list[str] = []
    for p in pairs:
        if p["prompt"] not in order:
            order.append(p["prompt"])

    out = [
        "# มาร์ค ground truth ของ skills injection (backlog ข้อ 21)",
        "",
        "กา `[x]` = **ควร**ฉีดไฟล์นี้เข้า context ให้ prompt นี้ · ปล่อย `[ ]` = ไม่ควร",
        "ข้ามคู่ที่ไม่แน่ใจได้ด้วยการลบทั้งบรรทัดทิ้ง (จะถูกนับเป็น 'ยังไม่มาร์ค')",
        "บรรทัดที่มี 🎲 = ไฟล์สุ่ม ใส่ไว้วัดว่ายังมีไฟล์ที่ควรฉีดแต่ไม่มี scorer ไหนเห็นหรือเปล่า",
        "**มาร์คไม่ครบได้** — ที่ยังไม่มาร์คถูกข้าม ไม่ได้ถูกนับว่า 'ไม่ควร'",
        "",
        "เกณฑ์ตัดสิน: *ถ้าโมเดลจะตอบ prompt นี้ให้ดี มันต้องเห็นเนื้อไฟล์นี้ไหม*",
        "ไม่ใช่ 'ไฟล์นี้พูดถึงคำเดียวกันไหม' — ไฟล์ละ ~6,000 ตัวอักษรที่ฉีดผิดคือ noise",
        "",
        f"เสร็จแล้วรัน: `python scripts/skills_groundtruth.py import --pairs {args.pairs}`",
        "",
        "---",
        "",
    ]
    for i, prompt in enumerate(order, 1):
        rows = [p for p in pairs if p["prompt"] == prompt]
        tag = "ไทยล้วน" if rows[0]["thai_only"] else "มี Latin ปน"
        out.append(f"### [{i}] {tag} — {prompt.strip()[:160]} <!--k:{_pkey(prompt)}-->")
        out.append("")
        for r in sorted(rows, key=lambda x: -max(x["scores"].values() or [0])):
            mark = "x" if r.get("label") else " "
            desc = _first_heading(os.path.join(args.skills_dir, r["skill_file"]))
            sc = " · ".join(f"{n} {v:.2f}" for n, v in sorted(r["scores"].items()))
            tag = " 🎲" if r.get("source") == "random" else ""
            out.append(f"- [{mark}] `{r['skill_file']}`{tag}  ({sc})" + (f" — {desc}" if desc else ""))
        out.append("")

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print(f"เขียน worksheet {len(order)} prompt / {len(pairs)} คู่ → {args.out}")
    return 0


def cmd_import(args) -> int:
    pairs = json.load(open(args.pairs, encoding="utf-8"))
    order: list[str] = []
    for p in pairs:
        if p["prompt"] not in order:
            order.append(p["prompt"])

    by_key = {_pkey(q): q for q in order}
    marked: dict[tuple[str, str], bool] = {}
    cur = None
    for line in open(args.worksheet, encoding="utf-8"):
        h = _HEAD.match(line)
        if h:
            cur = by_key.get(h.group("key"))
            continue
        m = _LINE.match(line.strip())
        if m and cur is not None:
            marked[(cur, m.group("file"))] = m.group("mark").lower() == "x"

    n = 0
    for p in pairs:
        key = (p["prompt"], p["skill_file"])
        if key in marked:
            p["label"] = marked[key]
            n += 1
    with open(args.pairs, "w", encoding="utf-8") as f:
        json.dump(pairs, f, ensure_ascii=False, indent=2)
    yes = sum(1 for p in pairs if p.get("label") is True)
    print(f"อัปเดต label {n}/{len(pairs)} คู่ (ควรฉีด {yes} · ไม่ควร {n - yes}) → {args.pairs}")
    return 0


def sweep(pairs: list[dict], steps: int = 41) -> list[Metrics]:
    """เทียบทุก scorer ทุก threshold บนคู่ที่มาร์คแล้วเท่านั้น"""
    marked = [p for p in pairs if p.get("label") is not None]
    names = sorted({k for p in pairs for k in p.get("scores", {})})
    out = []
    for name in names:
        usable = [p for p in marked if name in p.get("scores", {})]
        skipped = len(marked) - len(usable)
        for i in range(steps):
            t = i / (steps - 1)
            tp = sum(1 for p in usable if p["label"] and p["scores"][name] >= t)
            fp = sum(1 for p in usable if not p["label"] and p["scores"][name] >= t)
            fn = sum(1 for p in usable if p["label"] and p["scores"][name] < t)
            out.append(Metrics(name, round(t, 3), tp, fp, fn, skipped))
    return out


def simulate_injection(pairs: list[dict], scorer: str, threshold: float,
                       cap: int = 3) -> tuple[int, int, float, float, float]:
    """จำลองพฤติกรรม prod: คะแนน >= threshold → เรียงลง → **เอาแค่ top-cap ต่อ prompt**

    `load_skills_relevant()` ตัดที่ `max_files=3` — ถ้าไม่จำลองการตัดนี้ ตัวเลขที่รายงาน
    จะไม่ใช่พฤติกรรมจริง (เจอจริง 2026-08-03: split ที่ไม่ cap ให้ P=0.170 R=0.818
    แต่ของจริงบน prod คือ P=0.109 R=0.455 เพราะไฟล์ที่ถูก 4 ใน 9 หลุด top-3)

    Returns: (จำนวนที่ฉีด, ถูก, precision, recall, f1)
    """
    marked = [p for p in pairs if p.get("label") is not None]
    positives = sum(1 for p in marked if p["label"])
    per: dict[str, list] = {}
    for p in marked:
        sc = p.get("scores", {}).get(scorer)
        if sc is None or sc < threshold:
            continue
        per.setdefault(p["prompt"], []).append((sc, p["skill_file"], bool(p["label"])))
    injected = [t for rows in per.values() for t in sorted(rows, reverse=True)[:cap]]
    tp = sum(1 for _, _, lab in injected if lab)
    P = tp / len(injected) if injected else 1.0
    R = tp / positives if positives else 1.0
    F = 2 * P * R / (P + R) if (P + R) else 0.0
    return len(injected), tp, P, R, F


def cmd_sweep(args) -> int:
    pairs = json.load(open(args.labeled, encoding="utf-8"))
    marked = [p for p in pairs if p.get("label") is not None]
    if not marked:
        print("ยังไม่มีคู่ที่มาร์คเลย — เติม label ก่อน (ห้ามเดาแทนคน)", file=sys.stderr)
        return 1
    print(f"มาร์คแล้ว {len(marked)}/{len(pairs)} คู่ "
          f"(ควรฉีด {sum(1 for p in marked if p['label'])} · "
          f"ไม่ควร {sum(1 for p in marked if not p['label'])})\n")

    names = sorted({k for p in marked for k in p.get("scores", {})})
    results = sweep(marked)
    for name in names:
        rows = [m for m in results if m.scorer == name]
        best = max(rows, key=lambda m: m.f1)
        # ความกว้างของ "ที่ราบ" บอกว่าเกณฑ์เชื่อได้แค่ไหน (บทเรียนจากข้อ 16/17)
        plateau = [m.threshold for m in rows if abs(m.f1 - best.f1) < 1e-9]
        print(f"[{name}] ดีสุด F1={best.f1:.3f} "
              f"(P={best.precision:.3f} R={best.recall:.3f}) ที่ threshold={best.threshold}")
        print(f"         ที่ราบกว้าง {min(plateau)}–{max(plateau)} "
              f"({len(plateau)} จุด) — ยิ่งแคบยิ่งเชื่อไม่ได้"
              + (f" · ข้าม {best.skipped} คู่ที่ไม่มีคะแนน" if best.skipped else ""))
    print()

    # ── จุดทำงานจริง: prod ตัด top-3 ต่อ prompt เสมอ (ตัวเลขนี้คือของที่ใช้ตัดสินใจ) ──
    print(f"จำลอง prod (คะแนน >= เกณฑ์ → เรียงลง → เอา top-{args.cap} ต่อ prompt):")
    print(f"  {'scorer':10s} {'เกณฑ์':>6s} {'ฉีด':>5s} {'ถูก':>4s} {'P':>7s} {'R':>7s} {'F1':>7s}")
    for name in names:
        for t in (1e-9, 0.35, 0.40, 0.45):
            n, tp, P, R, F = simulate_injection(marked, name, t, cap=args.cap)
            if n == 0:
                continue
            label = ">0" if t < 1e-6 else f"{t:.2f}"
            print(f"  {name:10s} {label:>6s} {n:5d} {tp:4d} {P:7.3f} {R:7.3f} {F:7.3f}")
    print()

    thai = [p for p in marked if p.get("thai_only")]
    if thai:
        print(f"เฉพาะ prompt ไทยล้วน ({len(thai)} คู่):")
        for name in names:
            rows = sweep(thai)
            best = max((m for m in rows if m.scorer == name), key=lambda m: m.f1)
            print(f"  [{name}] F1={best.f1:.3f} P={best.precision:.3f} "
                  f"R={best.recall:.3f} @ {best.threshold}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("pairs", help="สร้างไฟล์ให้คนมาร์ค")
    p.add_argument("--n", type=int, default=30, help="จำนวน prompt (ครึ่งไทยล้วน)")
    p.add_argument("--pool", type=int, default=600, help="ดึงจาก DB กี่แถวก่อนคัด")
    p.add_argument("--top-k", type=int, default=3, help="candidate ต่อ scorer ต่อ prompt")
    p.add_argument("--random-extra", type=int, default=2,
                   help="ไฟล์สุ่มเพิ่มต่อ prompt — ใช้วัดว่า candidate pool ยังมีจุดบอดไหม")
    p.add_argument("--skills-dir", default=os.getenv("SKILLS_DIR_OVERRIDE", "/app/skills"))
    p.add_argument("--out", default="data/skills_pairs.json")
    p.set_defaults(func=cmd_pairs)

    w = sub.add_parser("worksheet", help="แปลง pairs เป็นไฟล์ .md ให้คนกาช่อง")
    w.add_argument("--pairs", default="data/skills_pairs.json")
    w.add_argument("--skills-dir", default=os.getenv("SKILLS_DIR_OVERRIDE", "/app/skills"))
    w.add_argument("--out", default="data/skills_labeling.md")
    w.add_argument("--only-unlabeled", action="store_true", help="เอาเฉพาะคู่ที่ยังไม่มาร์ค")
    w.add_argument("--by-importance", action="store_true",
                   help="เรียง prompt ตามคะแนนสูงสุด — มาร์คไม่ครบก็ยังได้ข้อมูลที่มีน้ำหนัก")
    w.set_defaults(func=cmd_worksheet)

    i = sub.add_parser("import", help="อ่านช่องที่กาแล้วกลับเข้า pairs.json")
    i.add_argument("--pairs", default="data/skills_pairs.json")
    i.add_argument("--worksheet", default="data/skills_labeling.md")
    i.set_defaults(func=cmd_import)

    s = sub.add_parser("sweep", help="เทียบ scorer จากคู่ที่มาร์คแล้ว")
    s.add_argument("--labeled", default="data/skills_pairs.json")
    s.add_argument("--cap", type=int, default=3,
                   help="เท่ากับ max_files ของ load_skills_relevant() — จำลองการตัดของ prod")
    s.set_defaults(func=cmd_sweep)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
