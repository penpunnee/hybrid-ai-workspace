"""Teaching Detection — ตรวจจับเมื่อ user กำลังสอน AI

เมื่อตรวจเจอ → บันทึกเป็น memory type="fact", verified=True, confidence=0.95
เมื่อตรวจเจอการแก้ไข → ลด confidence ของ memory เดิม + บันทึก correction ใหม่
"""
import re
import logging
from .schema import MemoryEntry
from .store import save_entry, update_confidence

logger = logging.getLogger(__name__)

# pattern ตรวจจับการสอน
_TEACH_PATTERNS = [
    (r"จำไว้ว่า[:\s]+(.+)",         "fact"),
    (r"รู้ไว้ว่า[:\s]+(.+)",         "fact"),
    (r"จดไว้ว่า[:\s]+(.+)",          "fact"),
    (r"บันทึกว่า[:\s]+(.+)",         "fact"),
    (r"ข้อมูลคือ[:\s]+(.+)",         "fact"),
    (r"ที่ถูกต้องคือ[:\s]+(.+)",     "correction"),
    (r"แก้ไข[:\s]+(.+)",             "correction"),
    (r"ไม่ใช่.+แต่(?:เป็น)?[:\s]+(.+)", "correction"),
    (r"prefer\s+(.+)",               "preference"),
    (r"ชอบ(.+)มากกว่า",              "preference"),
    (r"remember[:\s]+(.+)",          "fact"),
    (r"note[:\s]+(.+)",              "fact"),
]

# pattern ตรวจจับการแก้ไข AI ที่ตอบผิด
#
# ⚠️ ตัวนี้ต่างจาก `learn_gate._REJECTION_KW` โดยตั้งใจ — ห้ามรวมเป็นชุดเดียวกัน
#    learn_gate เดาผิด = ไม่เก็บ lesson (เสียโอกาส, ย้อนกลับได้)
#    teach เดาผิด     = เขียนขยะลง user_facts ที่ถูกฉีดเข้า context ทุก prompt
#    → ตัวนี้ต้อง **precision สูงกว่า** ยอมพลาดบ้างดีกว่าจับมั่ว
#
# หลักฐานว่าชุดเดิมพัง (audit 2026-08-02): รันกับ prompt จริงบน prod 156 ข้อ ได้ 0 hit
#   - r"ผิด[นน]ะ" เขียนผิดในตัวเอง — [นน] คือ character class ของ น ตัวเดียว
#     ซ้ำเปล่าๆ จับได้แค่ "ผิดนะ" เป๊ะๆ ไม่จับ "ผิดแล้ว"
#   - ภาษาจริงที่พี่ปอยใช้คือ "ผิดแล้ว X ต่างหาก" / "ไม่ใช่มั้ง" / "ไม่ใช่ละ"
#
# เกณฑ์ผ่าน/ไม่ผ่านอยู่ที่ tests/test_user_facts.py
#   ::TestCorrectionDetectionMatchesRealSpeech (ตัวอย่างคัดจาก prod ไม่ได้แต่งขึ้น)
_CORRECTION_PATTERNS = [
    # "ไม่ใช่" + คำลงท้าย = ปฏิเสธสิ่งที่เพิ่งพูดไป
    # ผูกกับคำลงท้ายเพราะ "ไม่ใช่" เดี่ยวๆ ไปโดน "ไม่ใช่เรื่องด่วนนะ แต่ช่วยดู log"
    # ซึ่งเป็นคำถามปกติ — ตัวคั่นคือ *สิ่งที่ตามหลัง* ไม่ใช่ตัว "ไม่ใช่" เอง
    r"ไม่ใช่\s*(?:ละ|ล่ะ|มั้ง|มั๊ย|ป่ะ|เหรอ|หรอ|อ่ะ|นี่|สิ|ครับ|ค่ะ|คับ)",
    r"ไม่ใช่แบบนั้น",
    # "ผิด" + คำลงท้าย — กัน "โค้ดนี้ผิดตรงไหน" ที่เป็นคำถามปกติ
    # (เดิมเขียน r"ผิด[นน]ะ" ซึ่ง [นน] คือ character class ของ น ตัวเดียวซ้ำเปล่าๆ
    #  จับได้แค่ "ผิดนะ" เป๊ะๆ ไม่จับ "ผิดแล้ว" ที่พี่ปอยใช้จริง)
    r"ผิด\s*(?:แล้ว|นะ|น่ะ|ละ|ครับ|ค่ะ|คับ)",
    # คำที่บอกว่า "ของจริงคืออีกอัน" — สัญญาณแก้ไขที่ชัดที่สุด
    r"ต่างหาก",
    r"ที่ถูกคือ",
    r"ไม่ถูก",
    r"ไม่ตรง",
    r"แก้ให้ด้วย",
    # ถอด r"จริงๆ แล้ว" ออก — เป็นคำเชื่อมที่ใช้ขึ้นต้นประโยคทั่วไป
    # ("จริงๆ แล้วผมอยากถามว่า…") false positive สูงเกินกว่าจะคุ้ม เพราะของที่หลุด
    # filter นี้จะถูกฉีดเข้า context ทุก prompt
]


def detect_teaching(text: str) -> tuple[str | None, str]:
    """
    ตรวจจับว่า user กำลังสอน AI หรือไม่
    คืนค่า (knowledge_to_save, memory_type) หรือ (None, "")
    """
    for pattern, mem_type in _TEACH_PATTERNS:
        m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if m:
            knowledge = m.group(1).strip()
            if len(knowledge) > 5:
                return knowledge, mem_type
    return None, ""


def detect_correction(text: str) -> bool:
    """ตรวจว่า user กำลังแก้ไข AI ที่ตอบผิด"""
    for pattern in _CORRECTION_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def process_teaching(assistant: str, user_text: str, ai_response: str = "") -> bool:
    """
    ประมวลผล user message เพื่อหา teaching signal
    คืนค่า True ถ้าบันทึก memory ใหม่
    """
    knowledge, mem_type = detect_teaching(user_text)
    if knowledge:
        entry = MemoryEntry(
            content=knowledge,
            assistant=assistant,
            type=mem_type,         # type: ignore
            confidence=0.95,
            source="user_taught",
            verified=True,
        )
        ok = save_entry(entry, collection_name="user_facts")
        if ok:
            logger.info(f"[Teach] บันทึก {mem_type} → user_facts: '{knowledge[:60]}...'")
        return ok

    # ถ้า user แก้ไข AI → ลด confidence ของ memory ที่เกี่ยวข้อง
    if detect_correction(user_text) and ai_response:
        update_confidence(assistant, ai_response[:200], new_confidence=0.3)
        logger.info("[Teach] ตรวจเจอการแก้ไข → ลด confidence ของ response ก่อนหน้า")
        if len(user_text) > 10:
            entry = MemoryEntry(
                content=f"[การแก้ไข] {user_text[:300]}",
                assistant=assistant,
                type="correction",
                confidence=0.9,
                source="user_taught",
                verified=True,
            )
            save_entry(entry, collection_name="user_facts")
        return True

    return False
