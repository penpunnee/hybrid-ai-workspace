#!/usr/bin/env python3
"""กู้ metadata ของ episodic memory ที่ถูก `bump_access_count` สลับข้ามตัว (audit 2026-09-24 ข้อ 4)

`col.get(ids=[...])` ของ Chroma คืนเรียงตามลำดับ insert ไม่ใช่ลำดับที่ขอ — โค้ดเดิม zip กับ
ที่ขอแล้ว update กลับ ⇒ metadata ทั้งก้อนสลับข้าม memory ทุกเทิร์นตั้งแต่ 2026-05-27

กู้ได้เฉพาะสิ่งที่มีแหล่งความจริงอิสระ:
  · `created_at` / `timestamp` ← เวลาที่ฝังใน doc id `mem_YYYYMMDDHHMMSS_xxxxxx`
    (writer เดียว `memory/store.py:save_entry` ใช้ `datetime.now()` ตัวเดียวกับ created_at —
    เสียแค่ microsecond)
  · `last_accessed` ← ตั้งเท่า created_at ที่กู้ได้ · `access_count` ← 0
    (ค่าเดิมสลับไปแล้วและไม่มี snapshot ที่ถูกต้องที่ไหน — `__keys` ถูก backfill หลังสลับ —
    จึง "เริ่มนับใหม่จากความจริง" ดีกว่าเก็บตัวเลขของคนอื่น · จำลอง prune บน prod แล้ว: 0 ถูกลบ)
  · `confidence` แตะไม่ได้ (ไม่มีแหล่งความจริง) — ปล่อยไว้

หลังรัน --apply ให้ resync กุญแจ: `python scripts/backfill_keys.py --apply --collections memory_kwan`

    python scripts/restore_memory_created_at.py                 # dry-run
    python scripts/restore_memory_created_at.py --apply
    python scripts/restore_memory_created_at.py --collections memory_kwan memory_logic
⚠️ รันในคอนเทนเนอร์ (`docker exec ai-backend-1 …`) — ต้องเห็น ChromaDB + env ตัวจริง
"""
from __future__ import annotations

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ID_RE = re.compile(r"^mem_(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})_[0-9a-f]{6}$")
RESTORED_FIELDS = ("created_at", "timestamp", "last_accessed")


def created_at_from_id(doc_id: str) -> str | None:
    """`mem_20260527045354_636c8d` → `2026-05-27T04:53:54` · id รูปอื่นคืน None (ไม่เดา)"""
    m = _ID_RE.match(doc_id)
    if not m:
        return None
    y, mo, d, h, mi, s = m.groups()
    return f"{y}-{mo}-{d}T{h}:{mi}:{s}"


def plan_restore(ids: list[str], metas: list[dict | None]) -> tuple[list[str], list[dict], int]:
    """คืน (ids ที่จะเขียน, metadata ใหม่, จำนวนที่ข้าม) — pure ไม่แตะ Chroma

    เขียนเฉพาะตัวที่ `created_at` ไม่ตรงกับ id (ถึงวินาที) หรือ access_count/last_accessed
    ยังไม่ถูกรีเซ็ต · ตัวที่ id ไม่ใช่รูป mem_ ข้าม
    """
    out_ids, out_metas, skipped = [], [], 0
    for doc_id, meta in zip(ids, metas):
        truth = created_at_from_id(doc_id)
        if truth is None:
            skipped += 1
            continue
        m = dict(meta or {})
        target = {**m, "created_at": truth, "timestamp": truth, "last_accessed": truth, "access_count": 0}
        already = (
            (m.get("created_at") or "")[:19] == truth
            and (m.get("timestamp") or "")[:19] == truth
            and (m.get("last_accessed") or "")[:19] == truth
            and int(m.get("access_count", 0)) == 0
        )
        if already:
            skipped += 1
            continue
        out_ids.append(doc_id)
        out_metas.append(target)
    return out_ids, out_metas, skipped


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--collections", nargs="*", default=["memory_kwan"])
    args = ap.parse_args()

    from memory.store import _get_chroma_client
    from utils.memory import get_collection

    client = _get_chroma_client()
    if client is None:
        print("ต่อ ChromaDB ไม่ได้")
        return 1

    for name in args.collections:
        try:
            col = get_collection(client, name)
            r = col.get(include=["metadatas"])
        except Exception as e:
            print(f"{name:20} ข้าม ({type(e).__name__}: {e})")
            continue
        ids, metas = r["ids"], r.get("metadatas") or [None] * len(r["ids"])
        w_ids, w_metas, skipped = plan_restore(ids, metas)
        print(f"{name:20} ทั้งหมด {len(ids):4} · จะเขียน {len(w_ids):4} · ข้าม {skipped:4}")
        for i, m in list(zip(w_ids, w_metas))[:5]:
            old = next((x for x, y in zip(ids, metas) if x == i), None)
            cur = dict(metas[ids.index(old)] or {}) if old else {}
            print(f"{'':22}{i}: created_at {cur.get('created_at','')[:19]!r} → {m['created_at']!r}"
                  f" · access_count {cur.get('access_count')} → 0")
        if not args.apply or not w_ids:
            continue
        col.update(ids=w_ids, metadatas=w_metas)
        chk = col.get(ids=w_ids, include=["metadatas"])
        bad = [i for i, m in zip(chk["ids"], chk["metadatas"])
               if (m or {}).get("created_at") != created_at_from_id(i)]
        print(f"{'':22}เขียนแล้ว {len(w_ids)} · ตรวจกลับไม่ตรง {len(bad)}")
        if bad:
            print(f"{'':22}⚠️ {bad[:5]}")
            return 2

    if not args.apply:
        print("\n[dry-run] ยังไม่เขียนอะไร — ใส่ --apply เพื่อเขียนจริง")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
