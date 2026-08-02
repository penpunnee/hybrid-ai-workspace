#!/usr/bin/env python3
"""Ground truth ของ recall — backlog ข้อ 12 (ตัวบล็อกของข้อ 3, 4, 16)

ปัญหา: ทุกที่ในระบบที่ค้น ChromaDB ตั้งเกณฑ์ (หรือไม่ตั้ง) โดยไม่มีข้อมูลว่า
"คำถามไหนควรดึงอะไรมาใช้" — เคยลองวัดด้วยคำถามที่แต่งเองแล้วพบว่า **คำถามที่ตั้งใจ
ให้ไม่เกี่ยว กลับเกี่ยวจริงเชิงความหมาย** (ประวัติศาสตร์อียิปต์ vs สรุปเนื้อเรื่อง
คัมภีร์วิถีเซียน) ตัวเลขที่ได้จึงเชื่อไม่ได้

วิธี: เอาคำถามจริงจาก prod → ดึง candidate จากแต่ละคลัง → **คนมาร์ค** ว่าคู่ไหน
ควรถูกดึงมาใช้ → ค่อยหาเกณฑ์จากข้อมูลที่มาร์คแล้ว (ไม่ใช่เดาเลขก่อนแล้วหาเหตุผลทีหลัง)

    python scripts/recall_groundtruth.py pairs  --questions FILE --out pairs.json
    python scripts/recall_groundtruth.py sweep  --labeled pairs.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

COLLECTIONS = ("lessons", "memory_kwan", "long_term_memory", "user_facts")


@dataclass(frozen=True)
class Metrics:
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


def sweep_threshold(pairs: list[dict], steps: int = 41) -> list[Metrics]:
    """ไล่เกณฑ์ตั้งแต่ 0.0-1.0 แล้ววัด precision/recall กับคู่ที่มาร์คไว้

    pair = {"score": float, "label": bool}  (label = "ควรถูกดึงมาใช้ไหม")
    คู่ที่ยังไม่มาร์ค (label=None) ถูกข้าม — ห้ามเดาแทนคน
    """
    marked = [p for p in pairs if p.get("label") is not None]
    out = []
    for i in range(steps):
        t = i / (steps - 1)
        tp = sum(1 for p in marked if p["label"] and p["score"] >= t)
        fp = sum(1 for p in marked if not p["label"] and p["score"] >= t)
        fn = sum(1 for p in marked if p["label"] and p["score"] < t)
        out.append(Metrics(round(t, 3), tp, fp, fn))
    return out


def best_threshold(pairs: list[dict], steps: int = 41) -> Metrics | None:
    """เกณฑ์ที่ F1 สูงสุด — เสมอกันเลือกตัวที่ recall สูงกว่า (เกณฑ์ต่ำกว่า)

    เหตุผลที่เอียงไปทาง recall: การพลาดข้อเท็จจริงที่ user สอนไว้ (false negative)
    ผู้ใช้เห็นเป็น "AI ลืม" ซึ่งแย่กว่าการแถม context ที่ไม่เกี่ยวมาหนึ่งชิ้น
    """
    marked = [p for p in pairs if p.get("label") is not None]
    if not marked:
        return None
    return max(sweep_threshold(marked, steps), key=lambda m: (m.f1, m.recall))


def _chroma():
    import chromadb

    return chromadb.HttpClient(host=os.getenv("CHROMA_HOST", "192.168.51.49"),
                               port=int(os.getenv("CHROMA_PORT", "8000")))


def cmd_pairs(args) -> int:
    client = _chroma()
    questions = [q.strip() for q in open(args.questions, encoding="utf-8") if q.strip()]
    questions = questions[: args.limit]

    pairs = []
    for q in questions:
        for name in COLLECTIONS:
            try:
                col = client.get_collection(name)
            except Exception:
                continue
            if col.count() == 0:
                continue
            r = col.query(query_texts=[q], n_results=min(args.top, col.count()))
            for doc, dist in zip(r["documents"][0], r["distances"][0]):
                pairs.append({
                    "question": q,
                    "collection": name,
                    "doc": doc[:200],
                    "score": round(1 - dist, 3),
                    "label": None,          # ← คนมาร์ค: true=ควรดึงมาใช้ / false=ไม่ควร
                })

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(pairs, f, ensure_ascii=False, indent=1)
    print(f"เขียน {len(pairs)} คู่ → {args.out}  (ยังไม่มาร์คสักคู่)")
    return 0


def cmd_sweep(args) -> int:
    pairs = json.load(open(args.labeled, encoding="utf-8"))
    marked = [p for p in pairs if p.get("label") is not None]
    print(f"คู่ที่มาร์คแล้ว {len(marked)}/{len(pairs)}"
          f"  (ควรดึง {sum(1 for p in marked if p['label'])} · ไม่ควร {sum(1 for p in marked if not p['label'])})")
    if not marked:
        print("ยังไม่มีใครมาร์ค — หาเกณฑ์ไม่ได้")
        return 1

    print(f"\n{'เกณฑ์':>6} {'precision':>10} {'recall':>8} {'F1':>7}   TP/FP/FN")
    for m in sweep_threshold(marked):
        if m.threshold % 0.05 < 0.001 or m.threshold in (0.6,):
            print(f"{m.threshold:>6.2f} {m.precision:>10.2f} {m.recall:>8.2f} {m.f1:>7.2f}   {m.tp}/{m.fp}/{m.fn}")

    b = best_threshold(marked)
    print(f"\nดีที่สุด: {b.threshold:.2f}  (P={b.precision:.2f} R={b.recall:.2f} F1={b.f1:.2f})")
    cur = next(m for m in sweep_threshold(marked) if abs(m.threshold - 0.6) < 0.02)
    print(f"ของเดิม : 0.60  (P={cur.precision:.2f} R={cur.recall:.2f} F1={cur.f1:.2f})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("pairs")
    p.add_argument("--questions", required=True)
    p.add_argument("--out", default="data/recall_pairs.json")
    p.add_argument("--limit", type=int, default=25)
    p.add_argument("--top", type=int, default=2)
    p.set_defaults(func=cmd_pairs)

    s = sub.add_parser("sweep")
    s.add_argument("--labeled", default="data/recall_pairs.json")
    s.set_defaults(func=cmd_sweep)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
