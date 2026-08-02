"""Lexical signal — ตัวเสริม semantic search สำหรับสิ่งที่ embedding จับไม่ได้ (ข้อ 16)

**ปัญหาที่แก้:** embedding แบบ multilingual แทบไม่เข้ารหัสตัวระบุ (รุ่น/รหัส/IP)
วัดจริงบน prod:
    "เราเตอร์ที่บ้านคือ ASUS RT-BE92U" vs "เราเตอร์ที่บ้านคือ TP-Link Archer C7"
    → 0.496 ทั้งที่ต่างกันแค่ชื่อรุ่น
    "เราเตอร์ที่บ้านยี่ห้ออะไร" ↔ fact ข้างบน → 0.447 (ตกเกณฑ์ ไม่ถูก recall)
ทั้งที่สองข้อความ **ซ้อนกันตรงๆ ที่คำว่า "เราเตอร์ที่บ้าน"** — สิ่งที่ lexical จับได้ทันที
โดยไม่ต้องพึ่งโมเดลเลย

**ทำไม character n-gram:** ภาษาไทยไม่มีช่องว่างระหว่างคำ tokenizer แบบ split() ใช้ไม่ได้
n-gram ระดับตัวอักษรทนต่อการตัดคำผิดและรูปคำที่ต่างกันเล็กน้อย

**ทำไม containment ไม่ใช่ Jaccard:** doc ยาวกว่าคำถามเสมอ Jaccard จะหารด้วย union
ทำให้ fact ที่มีบริบทเยอะเสียเปรียบฟรีๆ ทั้งที่บริบทเป็นสิ่งที่เราอยากได้
"""
from __future__ import annotations

import os

_NGRAM = 3

# เกณฑ์จากการวัด ground truth 50 คู่ (เดียวกับที่ใช้หา RECALL_MIN_SCORE):
#     semantic 0.55 อย่างเดียว           P=0.89 R=0.89 F1=0.89
#     OR lex>=0.45 / 0.50 / 0.60 / 0.70  P=0.90 R=1.00 F1=0.95  ← เท่ากันหมด
# ที่ราบกว้าง 0.45-0.70 เพราะ **ค่าสูงสุดของคู่ "ไม่ควรดึง" ที่วัดได้คือ 0.409**
# เลือก 0.50 = กลางที่ราบ เหนือ noise ที่สังเกตได้จริงพอมีระยะเผื่อ
# (ต่างจากจุดดีที่สุดของ dual-vector ที่กว้างแค่ 0.013 = overfit เชื่อไม่ได้)
LEXICAL_MIN_SCORE = float(os.getenv("LEXICAL_MIN_SCORE", "0.50"))


def _ngrams(text: str, n: int = _NGRAM) -> set[str]:
    """character n-gram โดยตัดช่องว่างทิ้งก่อน (ไทยเขียนติดกัน ช่องว่างเป็นเรื่องบังเอิญ)"""
    t = "".join((text or "").split())
    if len(t) < n:
        return set()
    return {t[i:i + n] for i in range(len(t) - n + 1)}


def lexical_score(query: str | None, doc: str | None, n: int = _NGRAM) -> float:
    """สัดส่วน n-gram ของ *คำถาม* ที่ไปปรากฏใน doc → 0.0-1.0

    คำถามที่สั้นกว่า n ตัวอักษรคืน 0.0 (ไม่มีข้อมูลพอจะตัดสิน — และการคืน 1.0
    จะทำให้ทุก doc ผ่านหมด)
    """
    qg = _ngrams(query, n)
    if not qg:
        return 0.0
    return len(qg & _ngrams(doc, n)) / len(qg)


def passes_lexical(query: str | None, doc: str | None,
                   min_score: float | None = None) -> bool:
    """คำถามกับ doc นี้ซ้อนกันมากพอที่จะถือว่าเกี่ยวข้องไหม"""
    floor = LEXICAL_MIN_SCORE if min_score is None else min_score
    return lexical_score(query, doc) >= floor
