#!/usr/bin/env python3
"""Backfill shadow log ย้อนหลังจาก prompt จริงที่มีใน DB แล้ว — backlog ข้อ 21

**ทำไมถึง backfill ได้ (และทำไมถึงควร backfill แทนที่จะรอเก็บสด):**
คะแนนของทุก scorer เป็นฟังก์ชันบริสุทธิ์ของ (prompt, ไฟล์ skill) — ไม่มีอะไรต้อง
"เก็บสด" เลย ส่วนแผนเดิม "log 1 สัปดาห์แล้วเทียบ 👍/👎" ตรวจแล้วพังสองชั้น:
  1. ตาราง `feedback` บน prod **ว่างเปล่า 0 แถว** ตั้งแต่ 2026-04-21 — ไม่มีอะไรให้เทียบ
  2. ทราฟฟิก ~4 เทิร์น/วัน → 1 สัปดาห์ได้ ~30 เทิร์น น้อยกว่า ground truth 110 คู่
     ที่เราสรุปเองว่า "ไม่มีพลังพอ" เสียอีก
backfill ให้ 447 เทิร์นทันทีโดยไม่ต้องรอ

⚠️ **ข้อจำกัดที่ต้องเขียนกำกับทุกครั้งที่อ้างตัวเลขจากไฟล์นี้:** ให้คะแนนด้วย **ไฟล์
skill ชุดวันนี้** ไม่ใช่ชุด ณ วันที่คุยจริง — ไฟล์ที่เพิ่งเพิ่มทีหลังจะดู "ควรถูกเลือก"
ในบทสนทนาเก่าได้ ตัวเลขนี้จึงตอบคำถาม *"ถ้าเปลี่ยน scorer วันนี้ จะฉีดต่างจากเดิมแค่ไหน"*
ได้เต็มปาก แต่ตอบ *"ตอนนั้นควรฉีดอะไร"* ไม่ได้

    python scripts/skills_shadow_backfill.py --dry-run          # รายงานอย่างเดียว
    python scripts/skills_shadow_backfill.py --apply            # เขียนลง skill_shadow
    python scripts/skills_shadow_backfill.py --report           # อ่านของที่เก็บไว้แล้ว

⚠️ ต้องรัน **ในคอนเทนเนอร์** เท่านั้น (เหตุผลเดียวกับ `clean_skills_db.py`):
    ssh nas 'sudo -n /usr/local/bin/docker exec ai-backend-1 \
      sh -c "cd /app && python scripts/skills_shadow_backfill.py --dry-run"'
บน Mac จะไปอ่าน `chat_history.db` คนละไฟล์กับ prod แล้วรายงานว่าสำเร็จ
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import SKILLS_DIR
from utils.history import _get_conn
from utils.skills_shadow import CAP, SCORERS, build_row, record


def _turns(limit: int | None) -> list[tuple[int, str, str, str]]:
    """(message_id ของคำตอบ AI, prompt ของ user, assistant, session_id)

    จับคู่ user→assistant ด้วย "คำตอบ AI แถวถัดไปใน session เดียวกัน" ซึ่งเป็นนิยาม
    เดียวกับที่ `feedback.message_id` ชี้ → join กันได้จริงเมื่อมี 👍/👎 ในอนาคต
    """
    conn = _get_conn()
    rows = conn.execute(
        """SELECT id, role, content, assistant, session_id
           FROM messages ORDER BY assistant, session_id, id"""
    ).fetchall()
    conn.close()

    out: list[tuple[int, str, str, str]] = []
    pending: str | None = None
    key: tuple | None = None
    for mid, role, content, asst, sess in rows:
        if key != (asst, sess):
            key, pending = (asst, sess), None
        if role == "user":
            pending = content
        elif role == "assistant" and pending:
            out.append((mid, pending, asst, sess))
            pending = None
    return out[-limit:] if limit else out


def apply_thresholds(rows: list[dict], mins: dict[str, float],
                     cap: int = CAP) -> list[dict]:
    """กรองตัวเลือกของ scorer ที่ระบุด้วยเกณฑ์ขั้นต่ำ — คืนสำเนา ไม่แก้ต้นฉบับ

    จำเป็นเพราะ **semantic ไม่กรองตัวเอง**: ChromaDB คืน top-N ทุกครั้งไม่ว่าจะเกี่ยว
    หรือไม่ ดังนั้น "semantic ฉีด 100% ของเทิร์น" ไม่ได้แปลว่ามันมั่นใจ — แปลว่าเรายัง
    ไม่ได้ตั้งเกณฑ์ ถ้าเอาเลขนี้ไปเทียบกับ split ตรงๆ = เข้าข้าง semantic ฟรี
    (ต่างจาก lexical ที่ 0 = ไม่มีคำตรงเลย จึงกรองตัวเองอยู่แล้ว)
    """
    out = []
    for r in rows:
        choices = {}
        for name, picks in r["choices"].items():
            t = mins.get(name)
            # กรอง → (เรียงมาแล้ว) → ตัดเป็น cap ของ prod: log เก็บลึกกว่าที่ฉีดจริง
            choices[name] = [p for p in picks if t is None or p[1] >= t][:cap]
        out.append({**r, "choices": choices})
    return out


def _summarize(rows: list[dict]) -> None:
    """รายงานที่ตอบคำถาม 'เปลี่ยน scorer แล้วของที่ฉีดต่างไปแค่ไหน' โดยไม่ต้องมี label"""
    names = sorted({n for r in rows for n in r["choices"]})
    thai = [r for r in rows if r["thai_only"]]
    print(f"\nเทิร์นทั้งหมด {len(rows)} (ไทยล้วน {len(thai)} · มี Latin ปน {len(rows) - len(thai)})")
    print(f"cap = top-{CAP} ต่อเทิร์น (เท่ากับ prod)\n")

    print(f"  {'scorer':10s} {'เทิร์นที่ฉีด':>12s} {'%':>6s} {'ไทยล้วนฉีด':>12s} {'%':>6s} {'ไฟล์เฉลี่ย':>10s}")
    for n in names:
        have = [r for r in rows if r["choices"].get(n)]
        th = [r for r in thai if r["choices"].get(n)]
        avg = sum(len(r["choices"][n]) for r in have) / len(have) if have else 0.0
        pct = 100 * len(have) / len(rows) if rows else 0
        tpct = 100 * len(th) / len(thai) if thai else 0
        print(f"  {n:10s} {len(have):12d} {pct:5.1f}% {len(th):12d} {tpct:5.1f}% {avg:10.2f}")

    # ── ของที่ต่างกันจริง: เซตไฟล์ที่แต่ละวิธีเลือก เทียบกับวิธีที่ prod ใช้อยู่ ──
    print("\nเทียบกับ `split` (วิธีที่ prod ใช้อยู่วันนี้) — นับเป็นราย (เทิร์น, ไฟล์):")
    base = {(i, f) for i, r in enumerate(rows) for f, _ in r["choices"].get("split", [])}
    for n in names:
        if n == "split":
            continue
        other = {(i, f) for i, r in enumerate(rows) for f, _ in r["choices"].get(n, [])}
        cover = [i for i, r in enumerate(rows) if n in r["choices"]]      # เทิร์นที่วิธีนี้วัดได้
        b = {x for x in base if x[0] in set(cover)}
        print(f"  {n:10s} เหมือนเดิม {len(b & other):5d} · เพิ่มมาใหม่ {len(other - b):5d} · "
              f"หายไป {len(b - other):5d}   (บนเทิร์นที่วัดได้ {len(cover)})")

    print("\nไฟล์ที่ถูกเลือกบ่อยสุด (top 8 ต่อ scorer):")
    for n in names:
        c = Counter(f for r in rows for f, _ in r["choices"].get(n, []))
        print(f"  [{n}] " + " · ".join(f"{f} {k}" for f, k in c.most_common(8)))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=None, help="เอาแค่ N เทิร์นล่าสุด")
    ap.add_argument("--semantic-min", type=float, default=0.40,
                    help="เกณฑ์ขั้นต่ำของ semantic ตอนรายงาน (ChromaDB คืน top-N เสมอ "
                         "ไม่กรองเอง) — 0.40 มาจาก ground truth 110 คู่ · ใส่ 0 = ไม่กรอง")
    ap.add_argument("--skills-dir", default=os.getenv("SKILLS_DIR_OVERRIDE", SKILLS_DIR))
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--apply", action="store_true", help="เขียนลงตาราง skill_shadow")
    g.add_argument("--dry-run", action="store_true", help="คำนวณ+รายงาน ไม่เขียน (default)")
    g.add_argument("--report", action="store_true", help="อ่านจากตารางที่เก็บไว้แล้ว")
    args = ap.parse_args()

    if args.report:
        conn = _get_conn()
        try:
            raw = conn.execute(
                "SELECT prompt, thai_only, injected, choices FROM skill_shadow"
            ).fetchall()
        finally:
            conn.close()
        if not raw:
            print("ตาราง skill_shadow ว่าง — รัน --apply ก่อน", file=sys.stderr)
            return 1
        rows = [{"prompt": p, "thai_only": bool(t),
                 "injected": json.loads(inj), "choices": json.loads(ch)}
                for p, t, inj, ch in raw]
        _summarize(apply_thresholds(rows, {"semantic": args.semantic_min}))
        return 0

    if not os.path.isdir(args.skills_dir):
        print(f"ไม่พบโฟลเดอร์ skill: {args.skills_dir}", file=sys.stderr)
        return 1
    n_files = len([f for f in os.listdir(args.skills_dir) if f.endswith(".md")])

    turns = _turns(args.limit)
    if not turns:
        print("ไม่มีเทิร์นใน DB", file=sys.stderr)
        return 1
    print(f"skills dir = {args.skills_dir} ({n_files} ไฟล์ .md) · เทิร์นที่จะประมวลผล {len(turns)}")
    print(f"scorer แบบ lexical: {sorted(SCORERS)} (+ semantic ถ้า ChromaDB ต่อได้)")

    rows, written, n_sem = [], 0, 0
    for mid, prompt, asst, sess in turns:
        row = build_row(prompt, args.skills_dir, injected=[])
        if "semantic" in row["choices"]:
            n_sem += 1
        rows.append(row)
        if args.apply and record(row, message_id=mid, assistant=asst, session_id=sess):
            written += 1

    if not n_sem:
        print("⚠️ ChromaDB ใช้ไม่ได้ → ไม่มีคอลัมน์ semantic (เทียบได้แค่ lexical)")
    elif n_sem < len(turns):
        print(f"⚠️ semantic วัดได้ {n_sem}/{len(turns)} เทิร์น — เทียบเฉพาะเทิร์นที่วัดได้")
    _summarize(apply_thresholds(rows, {"semantic": args.semantic_min}))
    print(f"\n{'เขียนลง skill_shadow ' + str(written) + ' แถว' if args.apply else 'dry-run — ไม่ได้เขียนอะไร'}")
    print("⚠️ ตัวเลขนี้ใช้ไฟล์ skill ชุดวันนี้กับ prompt เก่า — ตอบได้ว่า 'เปลี่ยนวันนี้จะต่างแค่ไหน'"
          " ไม่ใช่ 'ตอนนั้นควรฉีดอะไร'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
