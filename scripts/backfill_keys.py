#!/usr/bin/env python3
"""สร้าง vector ที่สอง (กุญแจ) ให้ memory เดิมที่บันทึกไว้ก่อนมี dual-vector (backlog ข้อ 17)

ของใหม่เขียนกุญแจเองอัตโนมัติแล้ว (`memory/store.py`, `utils/memory.py`) — สคริปต์นี้
ไล่เก็บของเก่า **ไม่แตะ collection หลักเลย** ทำซ้ำได้ปลอดภัย (upsert ด้วย id เดิม)

    python scripts/backfill_keys.py            # dry-run
    python scripts/backfill_keys.py --apply
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEFAULT_COLLECTIONS = ("lessons", "memory_kwan", "memory_logic", "long_term_memory", "user_facts")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--collections", nargs="*", default=list(DEFAULT_COLLECTIONS))
    args = ap.parse_args()

    import chromadb

    from memory.dualvec import key_text, keys_collection, sync_key

    client = chromadb.HttpClient(host=os.getenv("CHROMA_HOST", "192.168.51.49"),
                                 port=int(os.getenv("CHROMA_PORT", "8000")))

    for name in args.collections:
        try:
            col = client.get_collection(name)
        except Exception as e:
            print(f"{name:20} ข้าม ({type(e).__name__})")
            continue

        r = col.get(include=["documents", "metadatas"])
        ids, docs = r["ids"], r["documents"]
        metas = r.get("metadatas") or [None] * len(ids)

        keyed = [(i, d, m) for i, d, m in zip(ids, docs, metas) if key_text(d)]
        print(f"{name:20} {len(ids):4} รายการ → มีกุญแจ {len(keyed):4}"
              f"  (ไม่มี {len(ids) - len(keyed)})")
        if keyed[:1]:
            print(f"{'':22}ตัวอย่าง: {key_text(keyed[0][1])[:70]!r}")

        if not args.apply:
            continue
        ok = sum(1 for i, d, m in keyed if sync_key(client, name, i, d, metadata=m))
        cnt = client.get_collection(keys_collection(name)).count() if ok else 0
        print(f"{'':22}เขียนแล้ว {ok}/{len(keyed)} · {keys_collection(name)} มี {cnt} รายการ")

    if not args.apply:
        print("\n[dry-run] ยังไม่เขียนอะไร — ใส่ --apply เพื่อเขียนจริง")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
