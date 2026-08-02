"""Re-embed collection `documents` ด้วย embedding model ปัจจุบัน

ทำไมต้องมี: vector ที่ index ไว้เดิมสร้างจาก `text-embedding-nomic-embed-text-v1.5`
ซึ่งแมปประโยคภาษาไทย**ทุกประโยค**เป็น vector เดียวกัน (พิสูจน์บน prod 2026-08-02:
cosine ระหว่างประโยคไทยคนละเรื่อง = 1.0000 เป๊ะ) พอสลับตัวหลักเป็น
paraphrase-multilingual แล้ว query vector อยู่คนละ space กับที่ persist ไว้
→ similarity เหลือ ~0.04 ถูก threshold ตัดทิ้งหมด = ค้นเอกสารไม่เจออะไรเลย

สคริปต์นี้ **ไม่ต้องใช้ไฟล์ต้นฉบับ** — อ่าน text ของ chunk ที่เก็บไว้ใน ChromaDB
อยู่แล้วมา embed ใหม่ด้วยโมเดลปัจจุบัน แล้ว upsert ทับด้วย id เดิม (metadata คงเดิม)

ใช้:
    python scripts/reembed_documents.py --dry-run     # ดูว่าจะทำอะไรบ้าง
    python scripts/reembed_documents.py               # ลงมือจริง
"""
import argparse
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("reembed")

BATCH = 64


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="ไม่เขียนจริง แค่รายงาน")
    ap.add_argument("--batch", type=int, default=BATCH)
    args = ap.parse_args()

    from utils.documents import _get_collection
    from utils.embed import embed_texts, _EMBED_MODEL, cosine_similarity

    col = _get_collection()
    if col is None:
        logger.error("ChromaDB ไม่พร้อม")
        return 1

    got = col.get(include=["documents", "metadatas"])
    ids = got.get("ids", []) or []
    docs = got.get("documents", []) or []
    metas = got.get("metadatas", []) or []
    logger.info(f"พบ {len(ids)} chunks · embedding model ปัจจุบัน = {_EMBED_MODEL}")

    if not ids:
        logger.info("ไม่มีอะไรให้ทำ")
        return 0

    # sanity check ก่อนแตะข้อมูล: โมเดลปัจจุบันต้องแยกภาษาไทยได้จริง
    probe = embed_texts(["ราคาทองวันนี้เท่าไหร่", "สุนัขน่ารักมาก"])
    if len(probe) != 2:
        logger.error("embed ไม่สำเร็จ — ยกเลิก (ไม่เขียนอะไรทั้งนั้น)")
        return 1
    sim = cosine_similarity(probe[0], probe[1])
    logger.info(f"probe cosine (2 ประโยคไทยคนละเรื่อง) = {sim:.4f}")
    if sim > 0.95:
        logger.error(
            f"โมเดลปัจจุบันยังแยกภาษาไทยไม่ได้ (cosine {sim:.4f}) — ยกเลิก "
            "ไม่งั้น re-embed ไปก็ได้ vector มั่วเหมือนเดิม"
        )
        return 1

    if args.dry_run:
        by_src: dict[str, int] = {}
        for m in metas:
            by_src[(m or {}).get("source", "?")] = by_src.get((m or {}).get("source", "?"), 0) + 1
        for s, n in by_src.items():
            logger.info(f"  [dry-run] จะ re-embed {n} chunks จาก {s}")
        logger.info("[dry-run] ไม่ได้เขียนอะไร")
        return 0

    done = 0
    failed = 0
    for i in range(0, len(ids), args.batch):
        b_ids = ids[i:i + args.batch]
        b_docs = docs[i:i + args.batch]
        b_metas = metas[i:i + args.batch]
        try:
            vecs = embed_texts(b_docs)
            if len(vecs) != len(b_docs):
                raise RuntimeError(f"embed คืน {len(vecs)} ไม่เท่า input {len(b_docs)}")
            col.upsert(ids=b_ids, documents=b_docs, metadatas=b_metas, embeddings=vecs)
            done += len(b_ids)
            logger.info(f"  re-embed {done}/{len(ids)}")
        except Exception as e:
            failed += len(b_ids)
            logger.error(f"  batch {i}-{i+len(b_ids)} ล้ม (ข้าม): {e}")

    logger.info(f"เสร็จ: สำเร็จ {done} · ล้ม {failed} · รวม {len(ids)}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
