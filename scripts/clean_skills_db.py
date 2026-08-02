#!/usr/bin/env python3
"""ล้าง entry กำพร้าใน skills_db.json (backlog ข้อ 18)

เกณฑ์ลบ: **entry ต้องมีไฟล์ .md คู่กันอยู่ใน SKILLS_DIR จริง** — เกณฑ์เดียวกับที่
`tests/test_skills_freshness.py` ใช้ตรวจ .md จงใจให้เกณฑ์เข้ากับเกณฑ์ออกเป็นตัวเดียวกัน
เหมือน `clean_episodic.py` ที่ใช้ `should_remember()` ทั้งสองทาง

ทำไมต้องล้าง — `skills_db.json` ป้อน `search_skills()` (semantic top-3) ที่ฉีดเข้า
volatile block ทุกเทิร์น ต่างจาก `skills/*.md` ที่ป้อน `load_skills_relevant()`
(keyword, stable block) · ล้าง .md ไปแล้วในข้อ 9 แต่คลังนี้ยังค้าง

สิ่งที่เจอบน prod 2026-08-03 (48 entry):
- 25 จาก `GUIDE.md` (repo root ไม่ใช่ skills/) — ตรวจแล้วซ้ำกับ `skills/*.md` **ครบทั้ง 25
  หัวข้อ ไม่มีความรู้ใหม่** และเป็นฉบับ เม.ย. ค่าเก่ากว่า · ใน 25 นี้มี 3 รายการที่ไม่ใช่
  หัวข้อเอกสารด้วยซ้ำ แต่เป็นคอมเมนต์ `#` ที่อยู่ใน ```env code block
  (ต้นเหตุแก้แล้วที่ `utils/skills.py:_fence_flags`)
- 7 จาก `schemas.md` — ไม่มีไฟล์นี้ในโปรเจกต์ เนื้อหาเป็นเอกสารของ `skill-creator` คนละระบบ

⚠️ ลบ entry แล้วต้อง sync ChromaDB ด้วย — `sync_skills_to_search()` ลบของที่หายจาก db ให้เอง
(restart container ก็ทริกเกอร์ sync ตอน boot)

ใช้:
    python scripts/clean_skills_db.py                 # dry-run (default)
    python scripts/clean_skills_db.py --apply         # ลบจริง (backup อัตโนมัติ)
"""
from __future__ import annotations

import argparse
import collections
import datetime
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def classify_entry(entry, skills_dir: str) -> str:
    """คืน "keep" หรือ "orphan"

    ⚠️ ทุกกรณีที่อ่านไม่ออก/ไม่แน่ใจ = "keep" — ความไม่แน่ใจต้องเอียงไปทาง conservative
    เสมอเมื่อสคริปต์ลบข้อมูล prod (กฎเดียวกับ `clean_episodic.py`)
    """
    if not isinstance(entry, dict):
        return "keep"
    source = (entry.get("source") or "").strip()
    if not source:
        return "keep"

    filename = source if source.endswith(".md") else f"{source}.md"
    # กัน path traversal: source ต้องเป็นชื่อไฟล์เปล่าๆ ที่อยู่ใน skills_dir เท่านั้น
    if os.path.basename(filename) != filename:
        return "orphan"
    return "keep" if os.path.isfile(os.path.join(skills_dir, filename)) else "orphan"


def _md_summary(path: str) -> str:
    """summary ที่ควรเป็น = หัวไฟล์ .md ตัดบรรทัดหัวข้อ `#` ออก (รูปแบบเดียวกับที่ ingest ใช้)"""
    with open(path, encoding="utf-8", errors="ignore") as f:
        text = f.read()
    body = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("# "))
    return body.strip()[:300]


def resync_summaries(db: dict, skills_dir: str) -> list:
    """เขียน `summary` ใหม่จากไฟล์ .md ปัจจุบัน — คืน list ของ key ที่เปลี่ยนจริง

    จำเป็นเพราะ `summary` เป็น **snapshot ตอน ingest ไม่ใช่ pointer** → แก้ .md แล้ว
    `search_skills()` ยังฉีดข้อความเก่า (เจอจริง 2026-08-03 หลังปิดข้อ 9)
    ⚠️ แก้ db ในที่ (in-place) ต่างจาก `plan_cleanup`
    """
    changed = []
    for key, entry in db.items():
        if not isinstance(entry, dict):
            continue
        if classify_entry(entry, skills_dir) != "keep":
            continue
        source = (entry.get("source") or "").strip()
        if not source:
            continue
        filename = source if source.endswith(".md") else f"{source}.md"
        path = os.path.join(skills_dir, filename)
        if not os.path.isfile(path):
            continue  # ไฟล์หาย = ไม่แตะ ดีกว่าเขียนทับด้วยค่าว่าง
        fresh = _md_summary(path)
        if fresh and fresh != entry.get("summary"):
            entry["summary"] = fresh
            changed.append(key)
    return changed


def plan_cleanup(db: dict, skills_dir: str) -> tuple[list, list]:
    """คืน (keys ที่เก็บ, keys ที่ลบ) — ไม่แก้ db ที่รับเข้ามา"""
    keep, drop = [], []
    for key, entry in db.items():
        (keep if classify_entry(entry, skills_dir) == "keep" else drop).append(key)
    return keep, drop


def main() -> int:
    from core.config import SKILLS_DB_PATH, SKILLS_DIR

    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="เขียนจริง (default = dry-run)")
    ap.add_argument("--resync", action="store_true",
                    help="เขียน summary ใหม่จาก .md ปัจจุบันด้วย (ต้องรันทุกครั้งที่แก้ skills/*.md)")
    ap.add_argument("--db", default=SKILLS_DB_PATH)
    ap.add_argument("--skills-dir", default=SKILLS_DIR)
    args = ap.parse_args()

    if not os.path.isfile(args.db):
        print(f"ไม่พบ {args.db}")
        return 1

    with open(args.db, encoding="utf-8") as f:
        db = json.load(f)

    keep, drop = plan_cleanup(db, args.skills_dir)

    by_source = collections.Counter(
        (db[k].get("source") if isinstance(db[k], dict) else "?") for k in drop
    )
    print(f"db        : {args.db}")
    print(f"skills dir: {args.skills_dir}")
    print(f"\n{len(db)} entries → เก็บ {len(keep)} · ลบ {len(drop)}\n")
    for source, n in by_source.most_common():
        print(f"  {n:>3}  {source}")
    if drop:
        print("\nรายการที่จะลบ:")
        for k in drop:
            print(f"  - {k}")

    stale = []
    if args.resync:
        preview = json.loads(json.dumps(db))  # deep copy — ไม่แตะของจริงตอน dry-run
        stale = resync_summaries(preview, args.skills_dir)
        print(f"\nsummary ที่ล้าสมัย (จะเขียนใหม่จาก .md): {len(stale)}")
        for k in stale:
            print(f"  ~ {k}")

    if not args.apply:
        print("\n(dry-run — ใส่ --apply เพื่อเขียนจริง)")
        return 0

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = f"{args.db}.bak-{stamp}"
    shutil.copy2(args.db, backup)

    for k in drop:
        del db[k]
    if args.resync:
        resync_summaries(db, args.skills_dir)
    with open(args.db, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

    print(f"\nลบแล้ว {len(drop)} · resync {len(stale)} · เหลือ {len(db)} · backup: {backup}")
    print("⚠️ restart container เพื่อให้ sync_skills_to_search() ลบของใน ChromaDB ตาม")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
