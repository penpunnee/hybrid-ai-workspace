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
_CORRECTION_PATTERNS = [
    r"ผิด[นน]ะ",
    r"ไม่ถูก",
    r"ไม่ใช่แบบนั้น",
    r"ไม่ตรง",
    r"ที่ถูกคือ",
    r"จริงๆ แล้ว",
    r"แก้ให้ด้วย",
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
            confidence=0.95,       # user สอนโดยตรง = confidence สูง
            source="user_taught",
            verified=True,
        )
        ok = save_entry(entry)
        if ok:
            logger.info(f"[Teach] บันทึก {mem_type} จาก user: '{knowledge[:60]}...'")
        return ok

    # ถ้า user แก้ไข AI → ลด confidence ของ memory ที่เกี่ยวข้อง
    if detect_correction(user_text) and ai_response:
        update_confidence(assistant, ai_response[:200], new_confidence=0.3)
        logger.info(f"[Teach] ตรวจเจอการแก้ไข → ลด confidence ของ response ก่อนหน้า")
        # บันทึก correction เป็น memory ใหม่
        if len(user_text) > 10:
            entry = MemoryEntry(
                content=f"[การแก้ไข] {user_text[:300]}",
                assistant=assistant,
                type="correction",
                confidence=0.9,
                source="user_taught",
                verified=True,
            )
            save_entry(entry)
        return True

    return False
