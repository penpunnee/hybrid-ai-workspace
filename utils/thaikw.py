"""เทียบ keyword ภาษาไทยแบบทนวรรณยุกต์พิมพ์ผิด (2026-10-04 · devlog ต่อ 81)

prod: "เช็คเครื่อข่าย" (เติมไม้เอก) ไม่ติด "เครือข่าย" → ไม่ดึง ping จริง + หลุด gate ความจำ ·
ตัดวรรณยุกต์/ทัณฑฆาตทั้งสองฝั่งแล้วเทียบ — **เฉพาะ keyword ยาว ≥ 6 ตัวหลังตัด** เพราะคำสั้นชนคำทั่วไป
("ว่าง"→"วาง" = "วางแผน" · "ข่าว"→"ขาว") · คำสั้นยังเทียบตรงตัวเหมือนเดิม
"""
import re

_TONES = re.compile("[่-์]")   # ่ ้ ๊ ๋ ์ (ไม่แตะ ็ — เปลี่ยนเสียงสระ)
_FUZZY_MIN = 6


def _strip(s: str) -> str:
    return _TONES.sub("", s)


def contains_kw(text: str, keywords) -> bool:
    """`text` (lower แล้ว) มี keyword ใดไหม — ตรงตัว หรือไม่สนวรรณยุกต์สำหรับคำยาว"""
    if any(kw in text for kw in keywords):
        return True
    loose = _strip(text)
    return any(len(k) >= _FUZZY_MIN and k in loose for k in map(_strip, keywords))
