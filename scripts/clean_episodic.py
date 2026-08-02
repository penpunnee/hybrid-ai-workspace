#!/usr/bin/env python3
"""ล้าง episodic memory ที่เน่าแล้วออกจาก ChromaDB (backlog ข้อ 14)

เกณฑ์ลบ = `reasoning.learn_gate.should_remember()` **ตัวเดียวกับ gate ที่กันของใหม่
ไม่ให้เข้า** (commit 2ecc6d4) — จงใจให้เกณฑ์เข้ากับเกณฑ์ออกเป็นตัวเดียวกัน ถ้าแยกกัน
คลังจะเพี้ยนอีกในอนาคตด้วยเหตุผลใหม่ที่ไม่มีใครจำได้

⚠️ episodic ต่างจาก lessons/skills — **ห้ามล้างยกคลัง** มันควรเป็นบันทึกบทสนทนา
ตามหน้าที่ ลบเฉพาะข้อมูลสดที่หมดอายุ + ข้อความ error

ใช้:
    python scripts/clean_episodic.py                      # dry-run (default)
    python scripts/clean_episodic.py --apply              # ลบจริง
    python scripts/clean_episodic.py --apply --backup-dir data/chroma_export
"""
from __future__ import annotations

import argparse
import collections
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# รูปแบบที่ `memory/store.py` เขียนลงคลัง: "Q: ...\nA: ..." (A กินยาวถึงท้าย doc)
_QA_RE = re.compile(r"^Q:[ \t]*(.*?)\nA:[ \t]*(.*)$", re.S)

EPISODIC_COLLECTIONS = ("memory_kwan", "memory_logic")


def split_qa(doc: str | None) -> tuple[str, str] | None:
    """แยก doc เป็น (prompt, response) — คืน None ถ้าไม่ใช่รูปแบบ Q/A

    `.*?` ของฝั่ง Q ไม่ข้ามบรรทัดเพราะมี `\\nA:` คั่น ส่วนฝั่ง A ใช้ `.*$` กับ
    re.S จึงกิน "Q:" ที่บังเอิญโผล่กลางคำตอบไปด้วย (ไม่ตัดผิดที่)
    """
    if not doc:
        return None
    m = _QA_RE.match(doc)
    if not m:
        return None
    return m.group(1).strip(), m.group(2).strip()


def classify_doc(doc: str | None) -> tuple[bool, str]:
    """doc นี้ควรเก็บไว้ไหม → (keep, reason)

    กฎความปลอดภัย: doc ที่ parse ไม่ออก = **เก็บไว้** ไม่ใช่ลบ — สคริปต์นี้ลบข้อมูล
    prod ที่กู้ยาก ความไม่แน่ใจต้องเอียงไปทาง conservative เสมอ
    """
    qa = split_qa(doc)
    if qa is None:
        return True, "unparsed"
    from reasoning.learn_gate import should_remember

    ok, reason = should_remember(*qa)
    return ok, reason


def delete_with_keys(client, col_name: str, ids: list[str]) -> None:
    """ลบทั้งตัวหลักและ vector ที่สอง (ข้อ 17)

    ถ้าลบแต่ตัวหลัก กุญแจจะค้างเป็น orphan แล้วยัง recall ขึ้นมาได้ทั้งที่ของจริงหายไปแล้ว
    """
    if not ids:
        return
    from memory.dualvec import delete_keys

    client.get_collection(col_name).delete(ids=ids)
    delete_keys(client, col_name, ids)


def _client():
    import chromadb

    host = os.getenv("CHROMA_HOST", "192.168.51.49")
    port = int(os.getenv("CHROMA_PORT", "8000"))
    return chromadb.HttpClient(host=host, port=port)


def _backup(collections_data: dict, backup_dir: str) -> str:
    os.makedirs(backup_dir, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(backup_dir, f"episodic_backup_{stamp}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(collections_data, f, ensure_ascii=False)
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="ลบจริง (default = dry-run)")
    ap.add_argument("--backup-dir", default="data/chroma_export")
    ap.add_argument("--collections", nargs="*", default=list(EPISODIC_COLLECTIONS))
    args = ap.parse_args()

    client = _client()
    dump: dict = {}
    plan: dict[str, list[str]] = {}
    grand = collections.Counter()

    for name in args.collections:
        col = client.get_collection(name)
        r = col.get(include=["documents", "metadatas", "embeddings"])
        embeddings = r.get("embeddings")
        dump[name] = {
            "ids": r["ids"],
            "documents": r["documents"],
            "metadatas": r["metadatas"],
            "embeddings": [list(map(float, e)) for e in embeddings] if embeddings is not None else None,
        }

        drop_ids, counts = [], collections.Counter()
        for doc_id, doc in zip(r["ids"], r["documents"]):
            keep, reason = classify_doc(doc)
            counts["KEEP" if keep else reason] += 1
            if not keep:
                drop_ids.append(doc_id)
        plan[name] = drop_ids
        grand.update(counts)

        total = len(r["ids"])
        print(f"--- {name}: {total} → {total - len(drop_ids)}  (ลบ {len(drop_ids)})")
        for reason, n in counts.most_common():
            print(f"      {reason:20} {n:4}")

    if not args.apply:
        print("\n[dry-run] ยังไม่ลบอะไร — ใส่ --apply เพื่อลบจริง")
        return 0

    path = _backup(dump, args.backup_dir)
    print(f"\nbackup → {path}")

    for name, drop_ids in plan.items():
        if not drop_ids:
            continue
        delete_with_keys(client, name, drop_ids)
        print(f"ลบแล้ว {name}: {len(drop_ids)} รายการ · เหลือ {client.get_collection(name).count()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
