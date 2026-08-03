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

    python scripts/skills_groundtruth.py pairs --n 30 --out data/skills_pairs.json
    # ← คนเปิดไฟล์ แล้วเติม "label": true/false ทีละคู่
    python scripts/skills_groundtruth.py sweep --labeled data/skills_pairs.json

⚠️ คู่ที่ยังไม่มาร์ค (label=None) ถูกข้ามเสมอ — ห้ามเดาแทนคน (กติกาเดียวกับข้อ 12)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.lexical import lexical_score

# ส่วนของไฟล์ที่ scorer ปัจจุบันใช้เทียบ — ต้องตรงกับ load_skills_relevant()
HEAD_CHARS = 500
_LATIN = re.compile(r"[A-Za-z]")


# ── scorer ที่เอามาเทียบกัน ────────────────────────────────────────────────────
def score_split(query: str, haystack: str) -> float:
    """วิธีปัจจุบัน: นับคำจาก .split() ที่ไปโผล่ใน haystack (คืนเป็น float เพื่อ sweep ร่วมกัน)"""
    words = {w for w in query.lower().split() if len(w) > 1}
    if not words:
        return 0.0
    return sum(1 for w in words if w in haystack) / len(words)


def score_ngram(query: str, haystack: str) -> float:
    """character n-gram containment — ตัวเดียวกับที่ใช้ใน memory/lexical.py (ข้อ 16)"""
    return lexical_score(query, haystack)


SCORERS = {"split": score_split, "ngram": score_ngram}


@dataclass(frozen=True)
class Metrics:
    scorer: str
    threshold: float
    tp: int
    fp: int
    fn: int

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

    pairs = []
    for prompt in picked:
        # candidate = union ของ top-k จากทุก scorer → ไฟล์ที่ "ควรฉีดแต่ทุกวิธีพลาด"
        # ยังมีโอกาสถูกมาร์ค (ไม่งั้น recall ที่วัดได้จะสวยเกินจริงทุกวิธี)
        cands: set[str] = set()
        scores: dict[str, dict[str, float]] = {}
        for name, fn in SCORERS.items():
            ranked = sorted(((fn(prompt, h), f) for f, h in docs.items()), reverse=True)
            scores[name] = {f: s for s, f in ranked}
            cands.update(f for s, f in ranked[: args.top_k] if s > 0)
        for f in sorted(cands):
            pairs.append({
                "prompt": prompt,
                "skill_file": f,
                "thai_only": not _LATIN.search(prompt),
                "scores": {n: round(scores[n][f], 4) for n in SCORERS},
                "label": None,   # ← คนมาร์ค: true = ควรฉีดไฟล์นี้ให้ prompt นี้ / false = ไม่ควร
            })

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(pairs, f, ensure_ascii=False, indent=2)
    print(f"เขียน {len(pairs)} คู่ ({len(picked)} prompt · ไทยล้วน "
          f"{sum(1 for p in picked if not _LATIN.search(p))}) → {args.out}")
    print('ขั้นต่อไป: เปิดไฟล์แล้วเติม "label": true/false ทีละคู่ (ปล่อย null = ข้าม)')
    return 0


def sweep(pairs: list[dict], steps: int = 41) -> list[Metrics]:
    """เทียบทุก scorer ทุก threshold บนคู่ที่มาร์คแล้วเท่านั้น"""
    marked = [p for p in pairs if p.get("label") is not None]
    out = []
    for name in SCORERS:
        for i in range(steps):
            t = i / (steps - 1)
            tp = sum(1 for p in marked if p["label"] and p["scores"][name] >= t)
            fp = sum(1 for p in marked if not p["label"] and p["scores"][name] >= t)
            fn = sum(1 for p in marked if p["label"] and p["scores"][name] < t)
            out.append(Metrics(name, round(t, 3), tp, fp, fn))
    return out


def cmd_sweep(args) -> int:
    pairs = json.load(open(args.labeled, encoding="utf-8"))
    marked = [p for p in pairs if p.get("label") is not None]
    if not marked:
        print("ยังไม่มีคู่ที่มาร์คเลย — เติม label ก่อน (ห้ามเดาแทนคน)", file=sys.stderr)
        return 1
    print(f"มาร์คแล้ว {len(marked)}/{len(pairs)} คู่ "
          f"(ควรฉีด {sum(1 for p in marked if p['label'])} · "
          f"ไม่ควร {sum(1 for p in marked if not p['label'])})\n")

    results = sweep(marked)
    for name in SCORERS:
        rows = [m for m in results if m.scorer == name]
        best = max(rows, key=lambda m: m.f1)
        # ความกว้างของ "ที่ราบ" บอกว่าเกณฑ์เชื่อได้แค่ไหน (บทเรียนจากข้อ 16/17)
        plateau = [m.threshold for m in rows if abs(m.f1 - best.f1) < 1e-9]
        print(f"[{name}] ดีสุด F1={best.f1:.3f} "
              f"(P={best.precision:.3f} R={best.recall:.3f}) ที่ threshold={best.threshold}")
        print(f"         ที่ราบกว้าง {min(plateau)}–{max(plateau)} "
              f"({len(plateau)} จุด) — ยิ่งแคบยิ่งเชื่อไม่ได้\n")

    thai = [p for p in marked if p.get("thai_only")]
    if thai:
        print(f"เฉพาะ prompt ไทยล้วน ({len(thai)} คู่):")
        for name in SCORERS:
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
    p.add_argument("--skills-dir", default=os.getenv("SKILLS_DIR_OVERRIDE", "/app/skills"))
    p.add_argument("--out", default="data/skills_pairs.json")
    p.set_defaults(func=cmd_pairs)

    s = sub.add_parser("sweep", help="เทียบ scorer จากคู่ที่มาร์คแล้ว")
    s.add_argument("--labeled", default="data/skills_pairs.json")
    s.set_defaults(func=cmd_sweep)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
