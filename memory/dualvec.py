"""Dual-vector index — เก็บ 2 vector ต่อ 1 memory แล้วเอา max ตอนค้น (backlog ข้อ 17)

**ปัญหา:** embedding เป็นค่าเฉลี่ยของทั้งข้อความ เราเก็บ "คำถาม+คำตอบ" เป็นก้อนเดียว
แล้วค้นด้วยคำถาม → คำตอบที่ยาวกว่ากลบสัญญาณของคำถามทิ้ง วัดจริงบน prod:

    หัวข้อบทเรียนอย่างเดียว   0.913
    + เนื้อ 40 ตัวอักษร        0.658
    + เนื้อ 80 ตัวอักษร        0.524
    doc เต็ม (ที่ใช้จริง)      0.490   ← ทั้งที่เป็นบทเรียนของคำถามนั้นเอง

**ทางที่ตกไปแล้ว:** "index แค่กุญแจ" — ทดสอบกับ ground truth 50 คู่ได้ P=0.75 R=0.83
*แย่กว่าเดิม* เพราะ 3 เคสที่คำถามใหม่ไม่ตรงกับคำถามเดิมแต่ตรงกับ *เนื้อคำตอบ*
(ค่าเฉลี่ยดีขึ้น +0.183 แต่จำนวนที่ผ่านเกณฑ์ลดลง 16/18 → 15/18 — ค่าเฉลี่ยหลอก)

**ที่ใช้จริง:** เก็บทั้งสอง vector แล้ว max → P=0.86 R=1.00 ที่เกณฑ์ 0.60
⚠️ ตัวเลข F1=1.00 ที่เกณฑ์ 0.625 ในการทดลอง **เชื่อไม่ได้** — ช่องว่างระหว่างกลุ่ม
กว้างแค่ 0.013 = overfit บน 50 คู่ · ที่เชื่อได้คือแนวโน้ม ไม่ใช่ทศนิยม

โครงสร้าง: collection คู่ขนาน `<name>__keys` เก็บ *ข้อความกุญแจ* ด้วย id เดียวกับ
ตัวหลัก — จงใจไม่แตะ collection เดิมเลย ของเก่าจึงยังค้นได้ปกติแม้ยังไม่ backfill
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_KEYS_SUFFIX = "__keys"

# โครงที่ระบบเขียนลงคลัง (ดู memory/store.py, utils/memory.py)
_QA_RE = re.compile(r"^Q:[ \t]*(.+?)[ \t]*(?:\n|$)")
_LESSON_RE = re.compile(r"^\[บทเรียน:\s*(.*?)\]")

# token ที่ปนตัวอักษรละตินกับตัวเลข/สัญลักษณ์ (รุ่น/รหัส/IP) — โมเดล multilingual
# แทบไม่เข้ารหัสของพวกนี้ แต่มันดึง vector เฉลี่ยออกจากพื้นที่ความหมาย
# วัดจริง: สองประโยคที่ต่างกันแค่ชื่อรุ่นได้คะแนนกันเอง 0.496 เท่านั้น
_IDENT_RE = re.compile(r"\S*[A-Za-z]+[-_+0-9][\w.+-]*\S*|\b\d[\d.:/]+\b")

_MIN_KEY_LEN = 8


def keys_collection(name: str) -> str:
    """ชื่อ collection คู่ขนานของ `name` (idempotent)"""
    return name if name.endswith(_KEYS_SUFFIX) else f"{name}{_KEYS_SUFFIX}"


def key_text(doc: str | None) -> str | None:
    """ข้อความ 'กุญแจ' ของ doc → None ถ้าไม่มีอะไรเพิ่มจากตัว doc เอง

    ลำดับ: คำถาม/หัวข้อ (สัญญาณแรงสุด) → ถอดตัวระบุออก (สำหรับ fact สั้นที่ไม่มีโครง)
    """
    if not doc:
        return None
    text = doc.strip()
    if not text:
        return None

    m = _LESSON_RE.match(text) or _QA_RE.match(text)
    if m:
        key = m.group(1).strip()
        return key if len(key) >= _MIN_KEY_LEN else None

    # ไม่มีโครง Q/A — ลองถอดตัวระบุ (รุ่น/รหัส/IP) ออก
    stripped = re.sub(r"\s+", " ", _IDENT_RE.sub(" ", text)).strip()
    if stripped == text:
        return None                      # ไม่มีตัวระบุ → กุญแจซ้ำกับตัวเอง ไม่ต้องเก็บ
    if len(stripped) < _MIN_KEY_LEN:
        return None                      # เหลือแต่เศษ = กุญแจไร้ความหมาย
    return stripped


def merge_max(primary: list[dict], key_scores: dict[str, float],
              key_docs: dict[str, str] | None = None) -> list[dict]:
    """รวมผลจากฝั่ง doc เต็มกับฝั่งกุญแจ โดยเอา score ที่สูงกว่าของแต่ละ id

    `key_docs` = เนื้อของรายการที่เจอจากฝั่งกุญแจอย่างเดียว (ไม่ติด top-N ฝั่งเต็ม
    เพราะ dilution) — ถ้าไม่มีเนื้อให้ฉีดเข้า context ก็ข้ามไป เพิ่มไปก็ไร้ประโยชน์
    """
    out = {r["id"]: dict(r) for r in primary if r.get("id")}
    for doc_id, score in (key_scores or {}).items():
        if doc_id in out:
            out[doc_id]["score"] = max(out[doc_id].get("score", 0.0), score)
        elif key_docs and doc_id in key_docs:
            # ต้องมี field ครบชุดเดียวกับฝั่งหลัก — ผู้เรียกปลายทาง (เช่น _rank_results
            # ใน store.py) อ่าน x["verified"] ตรงๆ ถ้าขาดจะ KeyError ทั้ง search
            out[doc_id] = {
                "id": doc_id, "content": key_docs[doc_id], "score": score,
                "confidence": 0.7, "verified": False,
                "type": "event", "source": "conversation", "timestamp": "",
                "from_key_only": True,
            }
    return sorted(out.values(), key=lambda r: r.get("score", 0.0), reverse=True)


def sync_key(client, col_name: str, doc_id: str, doc: str, metadata: dict | None = None) -> bool:
    """เขียนกุญแจของ doc ลง collection คู่ขนาน — เงียบเสมอเมื่อล้ม

    การเขียนกุญแจล้มไม่ควรทำให้การบันทึก memory หลักล้มตาม (ฝั่งกุญแจเป็นตัวเสริม
    ระบบยังทำงานได้ด้วย vector เดิมตัวเดียว)
    """
    key = key_text(doc)
    if not key:
        return False
    try:
        from utils.memory import get_or_create_collection

        col = get_or_create_collection(client, keys_collection(col_name))
        meta = dict(metadata or {})
        meta["parent_collection"] = col_name
        col.upsert(ids=[doc_id], documents=[key], metadatas=[meta])
        return True
    except Exception as e:
        logger.debug(f"[dualvec] sync_key ล้ม ({col_name}/{doc_id}): {e}")
        return False


def key_hits(client, col_name: str, query: str, n_results: int = 5) -> tuple[dict, dict]:
    """ค้นฝั่งกุญแจ → ({id: score}, {id: ข้อความกุญแจ})

    คืนค่าว่างเมื่อยังไม่มี collection กุญแจ (ยังไม่ backfill) — ระบบต้องทำงานได้เหมือนเดิม
    """
    try:
        from utils.memory import get_collection

        col = get_collection(client, keys_collection(col_name))
        if col.count() == 0:
            return {}, {}
        res = col.query(query_texts=[query], n_results=min(n_results, col.count()))
    except Exception as e:
        logger.debug(f"[dualvec] key_hits ข้าม ({col_name}): {e}")
        return {}, {}

    ids = (res.get("ids") or [[]])[0]
    docs = (res.get("documents") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]
    scores = {i: round(1 - d, 3) for i, d in zip(ids, dists)}
    texts = {i: t for i, t in zip(ids, docs)}
    return scores, texts


def delete_keys(client, col_name: str, ids: list[str]) -> None:
    """ลบกุญแจให้ตรงกับตัวหลัก — กัน orphan ค้างแล้วถูก recall ทั้งที่ของจริงถูกลบไปแล้ว"""
    if not ids:
        return
    try:
        from utils.memory import get_collection

        get_collection(client, keys_collection(col_name)).delete(ids=ids)
    except Exception as e:
        logger.debug(f"[dualvec] delete_keys ข้าม ({col_name}): {e}")
