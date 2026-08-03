#!/usr/bin/env python3
"""ประเมิน "กฎการตัด" ของ skills injection กับคู่ที่คนมาร์คไว้ — backlog ข้อ 21

ตอบคำถามเดียว: **กฎสัมพัทธ์ (นำอันดับถัดไปเท่าไร) แม่นกว่าเกณฑ์สัมบูรณ์จริงไหม**
หลังจากที่ backfill 432 เทิร์นชี้ว่าเกณฑ์สัมบูรณ์ 0.40 ตัด prompt ไทยทิ้งเกือบหมด
(ฉีดได้ 5.9% แย่กว่า `.split()` เดิมที่ 29.7%) ทั้งที่ *อันดับ* ถูก

    python scripts/skills_rule_eval.py --pairs data/skills_pairs.json

⚠️ **สิ่งที่สคริปต์นี้ตอบไม่ได้ และคอลัมน์ "ไม่รู้" มีไว้เพื่อการนี้:**
label มีเฉพาะคู่ที่ scorer เคยเสนอให้คนมาร์ค (297 คู่ · มาร์คแล้ว 110 · positives 11)
ถ้ากฎใหม่หยิบไฟล์ที่ไม่เคยถูกเสนอ = **ไม่มีใครเคยตัดสินว่ามันถูกหรือผิด** การนับมัน
เป็น "ไม่ถูก" ก็ผิด นับเป็น "ถูก" ก็ผิด → รายงานแยกเป็นคอลัมน์ `ไม่รู้` เสมอ
**precision ที่พิมพ์ออกมาคำนวณจากเฉพาะคู่ที่มี label** ดังนั้นยิ่ง `ไม่รู้` เยอะ
ตัวเลข P ยิ่งเชื่อได้น้อย — นี่คือบั๊กเดิมที่ทำให้เซสชันก่อนสรุปว่า "ใช้ semantic" (ดู
vault `wiki/concepts/threshold-vs-ranking-calibration.md`)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import SKILLS_DIR
from utils.skills_shadow import (
    CAP, SCORERS, rule_absolute, rule_margin, semantic_scores, skill_haystacks,
)


@dataclass(frozen=True)
class Result:
    rule: str
    injected: int          # (เทิร์น, ไฟล์) ที่กฎนี้จะฉีด
    tp: int                # ฉีด + คนบอกว่าควรฉีด
    fp: int                # ฉีด + คนบอกว่าไม่ควร
    unknown: int           # ฉีด + **ไม่มีใครเคยมาร์ค** → ตัดสินไม่ได้
    positives: int         # ของที่คนบอกว่าควรฉีดทั้งหมด (ตัวหารของ recall)
    turns_fired: int
    turns_total: int

    @property
    def precision(self) -> float:
        got = self.tp + self.fp
        return self.tp / got if got else float("nan")

    @property
    def recall(self) -> float:
        return self.tp / self.positives if self.positives else float("nan")


def _rank(prompt: str, scorer: str, hays: dict[str, str],
          sem_cache: dict[str, dict[str, float]]) -> list[tuple[str, float]]:
    """อันดับเต็มของทุกไฟล์สำหรับ prompt นี้ (ไม่ตัด) — กฎค่อยไปตัดเอง"""
    if scorer == "semantic":
        if prompt not in sem_cache:
            sem_cache[prompt] = semantic_scores(prompt, n_results=50)
        scores = {f: sem_cache[prompt].get(f, 0.0) for f in hays}
        if not sem_cache[prompt]:
            return []
    else:
        fn = SCORERS[scorer]
        scores = {f: fn(prompt, h) for f, h in hays.items()}
    return sorted(scores.items(), key=lambda kv: -kv[1])


def evaluate(pairs: list[dict], hays: dict[str, str], rules: list[tuple[str, str, callable]],
             sem_cache: dict) -> list[Result]:
    labeled = [p for p in pairs if p.get("label") is not None]
    label_of = {(p["prompt"], p["skill_file"]): bool(p["label"]) for p in labeled}
    prompts = sorted({p["prompt"] for p in labeled})
    positives = sum(1 for v in label_of.values() if v)

    out = []
    for name, scorer, apply in rules:
        tp = fp = unk = fired = 0
        injected = 0
        for prompt in prompts:
            ranked = _rank(prompt, scorer, hays, sem_cache)
            if not ranked:
                continue
            picks = apply(ranked)
            if picks:
                fired += 1
            for f, _ in picks:
                injected += 1
                lab = label_of.get((prompt, f))
                if lab is None:
                    unk += 1
                elif lab:
                    tp += 1
                else:
                    fp += 1
        out.append(Result(name, injected, tp, fp, unk, positives, fired, len(prompts)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pairs", default="data/skills_pairs.json")
    ap.add_argument("--skills-dir", default=os.getenv("SKILLS_DIR_OVERRIDE", SKILLS_DIR))
    args = ap.parse_args()

    pairs = json.load(open(args.pairs, encoding="utf-8"))
    hays = skill_haystacks(args.skills_dir)
    if not hays:
        print(f"ไม่พบไฟล์ skill ใน {args.skills_dir}", file=sys.stderr)
        return 1

    rules: list[tuple[str, str, callable]] = [
        ("split (ของเดิมบน prod)", "split", lambda r: rule_absolute(r, 1e-9, CAP)),
        ("ngram >0", "ngram", lambda r: rule_absolute(r, 1e-9, CAP)),
    ]
    for t in (0.30, 0.35, 0.40, 0.45):
        rules.append((f"semantic สัมบูรณ์ >= {t:.2f}", "semantic",
                      lambda r, t=t: rule_absolute(r, t, CAP)))
    for m in (0.02, 0.03, 0.05, 0.08, 0.10):
        rules.append((f"semantic สัมพัทธ์ นำ >= {m:.2f}", "semantic",
                      lambda r, m=m: rule_margin(r, m, CAP)))

    sem_cache: dict[str, dict[str, float]] = {}
    results = evaluate(pairs, hays, rules, sem_cache)
    if not any(sem_cache.values()):
        print("⚠️ ChromaDB ใช้ไม่ได้ → แถว semantic ทั้งหมดไม่มีความหมาย", file=sys.stderr)

    labeled = [p for p in pairs if p.get("label") is not None]
    print(f"คู่ที่มาร์คแล้ว {len(labeled)} · ควรฉีด {sum(1 for p in labeled if p['label'])} "
          f"· prompt {len({p['prompt'] for p in labeled})} · cap top-{CAP}\n")
    print(f"  {'กฎ':28s} {'เทิร์นที่ฉีด':>11s} {'ฉีด':>5s} {'ถูก':>4s} {'ผิด':>4s} "
          f"{'ไม่รู้':>6s} {'P':>7s} {'R':>7s}")
    for r in results:
        p = "  n/a  " if r.precision != r.precision else f"{r.precision:7.3f}"
        rc = "  n/a  " if r.recall != r.recall else f"{r.recall:7.3f}"
        print(f"  {r.rule:28s} {r.turns_fired:5d}/{r.turns_total:<5d} {r.injected:5d} "
              f"{r.tp:4d} {r.fp:4d} {r.unknown:6d} {p} {rc}")

    print("\n⚠️ คอลัมน์ 'ไม่รู้' = ไฟล์ที่กฎหยิบมาแต่ไม่มีใครเคยมาร์ค — P คำนวณจากคู่ที่มี label")
    print("   เท่านั้น ยิ่ง 'ไม่รู้' เยอะ P ยิ่งเชื่อได้น้อย (นี่คือกับดักที่ทำให้สรุปผิดรอบก่อน)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
