#!/usr/bin/env python
"""CLI ซ่อมโรคกระจายตระกูลที่ 6 (utils/thaiscatter.py) — แยก compute/apply สองเครื่อง

ทำไมสองโหมด: compute ต้องมี pythainlp (ห้ามยัดเข้า prod image) · apply รันใน
คอนเทนเนอร์ prod ได้เพราะไม่มี dependency — ส่งกันด้วยไฟล์ JSON ที่พก md5 ของ
ข้อความต้นทาง กันข้อความใน DB เคลื่อนระหว่างสองขั้น (เช่น user import เล่มใหม่ทับ)

    # เครื่อง dev (มี pythainlp):
    python scripts/fix_scatter_dict.py compute book.txt removals.json
    # ในคอนเทนเนอร์ (หลัง backup DB แล้วเท่านั้น):
    python scripts/fix_scatter_dict.py apply /app/data/reader.db perfectworld.pdf removals.json
"""

import hashlib
import json
import sqlite3
import sys

sys.path.insert(0, ".")
from utils.thaiscatter import apply_removals, compute_removals, shift_bookmark  # noqa: E402


def md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def cmd_compute(text_path: str, out_path: str) -> None:
    text = open(text_path, encoding="utf-8").read()
    removed = compute_removals(text)
    json.dump({"md5": md5(text), "chars": len(text), "removed": removed}, open(out_path, "w"))
    print(f"compute: {len(removed)} ตำแหน่ง · md5={md5(text)} · chars={len(text)}")


def cmd_apply(db_path: str, source: str, json_path: str) -> None:
    plan = json.load(open(json_path))
    db = sqlite3.connect(db_path)
    text = db.execute("SELECT text FROM books WHERE source=?", (source,)).fetchone()[0]
    if md5(text) != plan["md5"]:
        raise SystemExit(f"❌ md5 ไม่ตรง ({md5(text)} != {plan['md5']}) — ข้อความใน DB เคลื่อนจากตอน compute ห้าม apply")
    fixed = apply_removals(text, plan["removed"])  # ตำแหน่งไหนไม่ใช่วรรค = ValueError เอง
    assert text.replace(" ", "") == fixed.replace(" ", ""), "ตัวอักษรอื่นถูกแตะ!"
    pos = db.execute("SELECT pos FROM reading_progress WHERE source=?", (source,)).fetchone()[0]
    new_pos = shift_bookmark(pos, plan["removed"])
    db.execute("UPDATE books SET text=?, chars=? WHERE source=?", (fixed, len(fixed), source))
    db.execute("UPDATE reading_progress SET pos=? WHERE source=?", (new_pos, source))
    db.commit()
    print(f"apply {source}: {len(text)} -> {len(fixed)} (-{len(text) - len(fixed)}) · pos {pos} -> {new_pos}")


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "compute":
        cmd_compute(sys.argv[2], sys.argv[3])
    elif len(sys.argv) == 5 and sys.argv[1] == "apply":
        cmd_apply(sys.argv[2], sys.argv[3], sys.argv[4])
    else:
        raise SystemExit(__doc__)
