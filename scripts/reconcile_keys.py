#!/usr/bin/env python3
"""กวาดกุญแจกำพร้าใน collection เงา `<name>__keys`

ทำไมต้องมีทั้งที่ cascade แล้ว — คู่มือ Qdrant (Keeping Postgres and Qdrant in Sync)
สรุปไว้ตรงๆ ว่า *"Every sync architecture drifts eventually. The reconciliation
script is what catches the residue."* · ChromaDB ไม่มี transaction ข้าม collection
⇒ `delete_with_keys()` ลบเงาก่อนแล้วล้มกลางทางได้เสมอ (log ERROR ไว้แล้ว) และของ
ที่กำพร้าไปแล้ว**ก่อน**มี cascade ก็ไม่มีใครตามเก็บ

กติกา: **collection หลักคือความจริง** เงาที่ไม่มีเจ้าของ = ลบ
(กลับกันไม่จริง — main ที่ไม่มีกุญแจเป็นสถานะปกติ `key_text()` คืน None ได้)

    python scripts/reconcile_keys.py              # รายงานอย่างเดียว
    python scripts/reconcile_keys.py --fix        # ลบกำพร้าจริง

⚠️ รันในคอนเทนเนอร์ (`docker exec ai-backend-1 …`) — เครื่อง dev ต่อ ChromaDB
คนละตัว/ไม่มี EMBEDDING_MODEL
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from memory.dualvec import _KEYS_SUFFIX  # noqa: E402


def _client():
    import chromadb

    return chromadb.HttpClient(host=os.getenv("CHROMA_HOST", "chromadb"),
                               port=int(os.getenv("CHROMA_PORT", "8000")))


def find_orphans(client) -> dict[str, list[str]]:
    """{ชื่อ collection เงา: [id ที่ไม่มีเจ้าของ]} — อ่านอย่างเดียว"""
    names = [c.name if hasattr(c, "name") else str(c) for c in client.list_collections()]
    out: dict[str, list[str]] = {}
    for keys_name in [n for n in names if n.endswith(_KEYS_SUFFIX)]:
        parent = keys_name[: -len(_KEYS_SUFFIX)]
        if parent not in names:
            # เงาที่ตัวหลักหายทั้ง collection — กำพร้าทั้งใบ
            out[keys_name] = list(client.get_collection(keys_name).get()["ids"])
            continue
        main_ids = set(client.get_collection(parent).get()["ids"])
        orphans = [i for i in client.get_collection(keys_name).get()["ids"] if i not in main_ids]
        if orphans:
            out[keys_name] = orphans
    return out


def main() -> int:
    fix = "--fix" in sys.argv
    client = _client()
    orphans = find_orphans(client)
    total = sum(len(v) for v in orphans.values())
    if not total:
        print("✅ ไม่มีกุญแจกำพร้า — เงาตรงกับตัวหลักทุกใบ")
        return 0
    print(f"พบกุญแจกำพร้า {total} รายการใน {len(orphans)} collection:")
    for name, ids in orphans.items():
        print(f"  {name}: {len(ids)} → {ids[:5]}{' …' if len(ids) > 5 else ''}")
    if not fix:
        print("\n(dry-run — ใส่ --fix เพื่อลบจริง)")
        return 0
    for name, ids in orphans.items():
        client.get_collection(name).delete(ids=ids)
        print(f"  ลบแล้ว {len(ids)} จาก {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
