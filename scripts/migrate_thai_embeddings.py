#!/usr/bin/env python
"""Migrate ChromaDB collections → Ollama multilingual embedding function

ChromaDB default embedder (MiniLM) มองอักษรไทยเป็น UNK ทั้งหมด → ทุกประโยคไทยได้
vector เดียวกัน (cosine score = 1.000 ทุกคู่) → semantic recall ภาษาไทยเป็น noise
ล้วนมาตั้งแต่ day 1 (พิสูจน์แล้วในโปรเจกต์ JARVIS 2026-07-08, ดู wiki
concepts/thai-embedding-chromadb.md). utils/memory.py แก้ด้วย EMBEDDING_MODEL env
แล้ว แต่เปลี่ยน embedder = dimension vector เปลี่ยน → collection เดิม query ไม่ได้
ต้อง re-embed ทุก collection ใหม่

สคริปต์นี้: อ่าน documents+metadatas เดิมทั้งหมด (ทิ้ง vector เดิมที่เป็น noise อยู่
แล้ว) → เปลี่ยนชื่อ collection เดิมเป็น backup กันข้อมูลหาย → สร้าง collection ใหม่
ชื่อเดิมด้วย embedding function ใหม่ → re-add (chromadb re-embed ให้อัตโนมัติ)

Idempotent: ถ้าเจอ backup ของ collection นั้นอยู่แล้ว (ชื่อ {name}__minilm_backup_*)
ถือว่า migrate ไปแล้ว ข้าม ไม่ทำซ้ำ

Usage:
    ./.venv/bin/python scripts/migrate_thai_embeddings.py --dry-run
    ./.venv/bin/python scripts/migrate_thai_embeddings.py
    ./.venv/bin/python scripts/migrate_thai_embeddings.py --only memory_kwan  # ทดสอบทีละตัว
"""
import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.memory import _get_client, _get_embedding_function, EMBEDDING_MODEL

# "documents" ไม่รวม — ใช้ embedding pipeline แยกของตัวเอง (utils/embed.py,
# LM Studio/Ollama nomic-embed-text, precomputed vectors) ไม่ใช่ chroma default EF
FIXED_COLLECTIONS = [
    "long_term_memory", "user_facts", "lessons", "preferences",
    "obsidian_notes", "skills_collection",
]
BATCH_SIZE = 200


def _col_name(col_info) -> str:
    return col_info.name if hasattr(col_info, "name") else str(col_info)


def _target_collections(client, only: str | None) -> list[str]:
    names = []
    for col_info in client.list_collections():
        name = _col_name(col_info)
        if name.startswith("memory_") or name in FIXED_COLLECTIONS:
            names.append(name)
    if only:
        names = [n for n in names if n == only]
    return names


def _already_migrated(client, name: str) -> bool:
    prefix = f"{name}__minilm_backup_"
    return any(_col_name(c).startswith(prefix) for c in client.list_collections())


def migrate_collection(client, ef, name: str, dry_run: bool) -> dict:
    try:
        old_col = client.get_collection(name)
    except Exception:
        return {"name": name, "count": 0, "action": "skip-not-found"}

    count = old_col.count()
    if count == 0:
        return {"name": name, "count": 0, "action": "skip-empty"}

    if _already_migrated(client, name):
        return {"name": name, "count": count, "action": "skip-already-migrated"}

    if dry_run:
        return {"name": name, "count": count, "action": "would-migrate"}

    # 1) ดึงข้อมูลเดิมทั้งหมด (documents+metadatas เท่านั้น — vector เดิมทิ้งได้เลย
    #    เพราะเป็น noise อยู่แล้ว จาก default MiniLM ที่มองอักษรไทยเป็น UNK)
    all_ids: list[str] = []
    all_docs: list[str] = []
    all_metas: list[dict] = []
    offset = 0
    while True:
        res = old_col.get(include=["documents", "metadatas"], limit=BATCH_SIZE, offset=offset)
        ids = res.get("ids", [])
        if not ids:
            break
        all_ids.extend(ids)
        all_docs.extend(res.get("documents", []))
        all_metas.extend(res.get("metadatas", []))
        offset += len(ids)
        if len(ids) < BATCH_SIZE:
            break

    # 2) เปลี่ยนชื่อ collection เดิมเป็น backup กันข้อมูลหายถ้า migrate พังกลางทาง
    backup_name = f"{name}__minilm_backup_{datetime.now().strftime('%Y%m%d')}"
    old_col.modify(name=backup_name)

    # 3) สร้าง collection ใหม่ชื่อเดิม ด้วย embedding function ใหม่
    new_col = client.get_or_create_collection(
        name, metadata={"hnsw:space": "cosine"}, embedding_function=ef,
    )

    # 4) re-add เป็น batch — ไม่ส่ง embeddings= → chroma re-embed ให้อัตโนมัติด้วย ef ใหม่
    for i in range(0, len(all_ids), BATCH_SIZE):
        new_col.add(
            ids=all_ids[i:i + BATCH_SIZE],
            documents=all_docs[i:i + BATCH_SIZE],
            metadatas=[m if m else {} for m in all_metas[i:i + BATCH_SIZE]],
        )

    return {"name": name, "count": count, "action": "migrated", "backup": backup_name}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="แสดงแผนโดยไม่แก้ข้อมูลจริง")
    parser.add_argument("--only", default=None, help="migrate collection เดียว (ทดสอบก่อนรันทั้งหมด)")
    args = parser.parse_args()

    if not EMBEDDING_MODEL:
        print("EMBEDDING_MODEL ยังไม่ตั้งใน .env — ตั้งเป็น paraphrase-multilingual ก่อนรัน migration นี้")
        sys.exit(1)

    client = _get_client()
    if client is None:
        print(f"ต่อ ChromaDB ไม่ได้ ({os.getenv('CHROMA_HOST')}:{os.getenv('CHROMA_PORT')})")
        sys.exit(1)

    ef = _get_embedding_function()
    if ef is None:
        print("สร้าง embedding function ไม่สำเร็จ — เช็คแพ็กเกจ ollama ติดตั้งแล้ว + "
              "OLLAMA_BASE_URL ต่อได้ + pull model นี้ไว้แล้ว: " + EMBEDDING_MODEL)
        sys.exit(1)

    names = _target_collections(client, args.only)
    tag = "[DRY RUN] " if args.dry_run else ""
    print(f"{tag}EMBEDDING_MODEL={EMBEDDING_MODEL} — พบ {len(names)} collections: {names}")

    results = []
    for name in names:
        try:
            r = migrate_collection(client, ef, name, args.dry_run)
        except Exception as e:
            r = {"name": name, "action": "error", "error": str(e)}
        results.append(r)
        extra = f" → backup {r['backup']}" if "backup" in r else ""
        extra += f" ({r['error']})" if "error" in r else ""
        print(f"  {name}: {r['action']} ({r.get('count', 0)} docs){extra}")

    migrated = sum(1 for r in results if r["action"] == "migrated")
    errors = [r for r in results if r["action"] == "error"]
    print(f"\nสรุป: migrated {migrated}/{len(names)}" + (f", errors {len(errors)}" if errors else ""))
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
