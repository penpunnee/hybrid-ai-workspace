"""บันทึก turn ของโหมดเสียง (`/ws/voice`) ลง episodic memory — user เคาะ 2026-09-29

สืบแล้ว: 88% ของบทสนทนา (224/254 turn ตั้งแต่ 08-18) มาจากโหมดเสียง ซึ่งเดิมบันทึกแค่ประวัติแชท ไม่เคยเรียก `remember()`
⇒ memory แทบไม่โต · Dream REM ไม่มีข้อมูลให้วิเคราะห์

เงื่อนไข (user เคาะ): ผ่าน `should_remember` เหมือนแชทพิมพ์ · ข้าม turn ที่ถูกพูดแทรก (คำตอบไม่ครบ = เทียบ Stop ในแชท) ·
ข้าม turn ที่ใช้ web search (ข้อมูลสด = หลักเดียวกับ realtime_home_tool) · **ไม่กรองข้อความสั้น** (คำตอบ AI ยังมีเนื้อหา)
⚠️ โหมดอ่านนิยาย (`/ws/reader`) ห้ามเรียกโมดูลนี้ (มีเทส ast คุม) · ไฟล์นี้ไม่แตะค่าเสียงใดๆ (🔒 utils/voice.py)
"""
import logging
import threading

from memory.operations import remember
from reasoning.learn_gate import should_remember

logger = logging.getLogger(__name__)


def voice_memory_decision(user_text: str, ai_text: str, *, interrupted: bool = False,
                          searched: bool = False) -> tuple[bool, str]:
    """ควรบันทึก turn เสียงนี้ไหม → (ok, reason) · pure (ไม่มี IO)"""
    if not (user_text or "").strip():
        return False, "no_user_text"          # auto-continue: AI เล่าต่อเองโดยไม่มีคำถาม
    if not (ai_text or "").strip():
        return False, "no_ai_text"
    if interrupted:
        return False, "interrupted"
    if searched:
        return False, "searched"
    return should_remember(user_text.strip(), ai_text.strip())


def _remember_safe(assistant: str, prompt: str, response: str) -> None:
    try:
        remember(assistant, prompt, response)
    except Exception as e:                    # ห้ามโยนกลับ — อยู่ใน thread แยกจากลูปเสียง
        logger.warning(f"[Voice/memory] บันทึกไม่สำเร็จ: {e}")


def remember_voice_turn(assistant: str, user_text: str, ai_text: str, *, interrupted: bool = False,
                        searched: bool = False) -> bool:
    """ตัดสิน แล้วยิง `remember()` ใน daemon thread (ไม่ await) — embed ผ่าน Ollama 0.56–6.73 วิ
    ถ้ารันในลูปเสียงจะหน่วง turn ถัดไป · log แค่ผล/เหตุผล **ไม่มีเนื้อหาบทสนทนา** · คืน True ถ้ายิงบันทึก"""
    ok, reason = voice_memory_decision(user_text, ai_text, interrupted=interrupted, searched=searched)
    if not ok:
        logger.info(f"[Voice/memory] ข้าม reason={reason}")
        return False
    threading.Thread(target=_remember_safe, args=(assistant, user_text.strip(), ai_text.strip()),
                     daemon=True, name="voice-remember").start()
    logger.info("[Voice/memory] บันทึก")
    return True
