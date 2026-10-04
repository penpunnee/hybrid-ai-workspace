"""บันทึก turn ของโหมดเสียง (`/ws/voice`) ลง episodic memory — user เคาะ 2026-09-29

สืบแล้ว: 88% ของบทสนทนา (224/254 turn ตั้งแต่ 08-18) มาจากโหมดเสียง ซึ่งเดิมบันทึกแค่ประวัติแชท ไม่เคยเรียก `remember()`
⇒ memory แทบไม่โต · Dream REM ไม่มีข้อมูลให้วิเคราะห์

เงื่อนไข (user เคาะ): ผ่าน `should_remember` เหมือนแชทพิมพ์ · ข้าม turn ที่ถูกพูดแทรก (คำตอบไม่ครบ = เทียบ Stop ในแชท) ·
**ไม่กรองข้อความสั้น** (คำตอบ AI ยังมีเนื้อหา)
· ⚠️ เดิมข้าม turn ที่ใช้ web search ด้วย — **ถอดแล้ว** (user เคาะ 09-29 หลังทดสอบจริง: 4/9 turn ถูกข้าม เช่น "คำว่า แม้ว่า
เป็นภาษาราชการไหม" ที่โมเดลเลือกค้นเอง) · ข้อมูลสดให้ `should_remember` (`realtime_query` ดูจากคำถาม) กรองแทน
⚠️ โหมดอ่านนิยาย (`/ws/reader`) ห้ามเรียกโมดูลนี้ (มีเทส ast คุม) · ไฟล์นี้ไม่แตะค่าเสียงใดๆ (🔒 utils/voice.py)
"""
import asyncio
import logging
import re
import threading
import time

from core.env_registry import env_float
from memory.operations import recall, remember
from reasoning.learn_gate import should_remember

logger = logging.getLogger(__name__)

# อักษรไทยเท่านั้น (ลาว U+0E80– อยู่นอกช่วง) — user พูดไทยเสมอ ⇒ ข้อความที่ไม่มีอักษรไทยเลย = ASR ฟังผิด/เสียงทีวี
# (prod 06-18→10-04: เกาหลี/ญี่ปุ่น/ลาว/ฝรั่งเศส/อิตาลี 40+ turn · 10 รายการหลุดเข้า memory_kwan · "ขวัญ" → "Juan")
_THAI_CHARS = re.compile(r"[\u0E00-\u0E7F]")


def voice_memory_decision(user_text: str, ai_text: str, *, interrupted: bool = False,
                          recalled: bool = False) -> tuple[bool, str]:
    """ควรบันทึก turn เสียงนี้ไหม → (ok, reason) · pure (ไม่มี IO)

    `recalled` = turn นี้นึกความจำเก่า → ไม่จดกลับ (คำตอบสร้างจากความจำ = จดซ้ำทับถม · ความจำผิดถูกขยาย)"""
    if not (user_text or "").strip():
        return False, "no_user_text"          # auto-continue: AI เล่าต่อเองโดยไม่มีคำถาม
    if not (ai_text or "").strip():
        return False, "no_ai_text"
    if not _THAI_CHARS.search(user_text):
        return False, "no_thai_text"
    if interrupted:
        return False, "interrupted"
    if recalled:
        return False, "recalled"
    return should_remember(user_text.strip(), ai_text.strip())


def _remember_safe(assistant: str, prompt: str, response: str) -> None:
    try:
        remember(assistant, prompt, response)
    except Exception as e:                    # ห้ามโยนกลับ — อยู่ใน thread แยกจากลูปเสียง
        logger.warning(f"[Voice/memory] บันทึกไม่สำเร็จ: {e}")


def remember_voice_turn(assistant: str, user_text: str, ai_text: str, *, interrupted: bool = False,
                        recalled: bool = False) -> bool:
    """ตัดสิน แล้วยิง `remember()` ใน daemon thread (ไม่ await) — embed ผ่าน Ollama 0.56–6.73 วิ
    ถ้ารันในลูปเสียงจะหน่วง turn ถัดไป · log แค่ผล/เหตุผล **ไม่มีเนื้อหาบทสนทนา** · คืน True ถ้ายิงบันทึก"""
    ok, reason = voice_memory_decision(user_text, ai_text, interrupted=interrupted, recalled=recalled)
    if not ok:
        logger.info(f"[Voice/memory] ข้าม reason={reason}")
        return False
    threading.Thread(target=_remember_safe, args=(assistant, user_text.strip(), ai_text.strip()),
                     daemon=True, name="voice-remember").start()
    logger.info("[Voice/memory] บันทึก")
    return True


# ── นึกความจำให้โหมดเสียง (เครื่องมือ `recall_memory` · user เคาะ 2026-10-02) ─────────────
# embed ผ่านเครื่อง .235 (Ollama) ⇒ ต้องมีเพดานเหมือนค้นเว็บ (ระหว่างนึก ขวัญเงียบสนิท)
VOICE_MEMORY_TIMEOUT_DEFAULT = 10.0
VOICE_MEMORY_TIMEOUT = env_float("VOICE_MEMORY_TIMEOUT", VOICE_MEMORY_TIMEOUT_DEFAULT, group="Voice", doc=(
    "วินาทีสูงสุดที่โหมดเสียงรอนึกความจำ (recall_memory) — เกินแล้วบอกโมเดลว่านึกไม่ทัน"))
VOICE_MEMORY_GUIDE = (
    "[คำสั่งตอนใช้ความจำนี้]\n"
    "1. นี่คือบทสนทนาเก่าที่ระบบจดไว้ ใช้เพื่อรู้ว่าเคยคุยอะไรกับพี่ปอย\n"
    "2. ความจำอาจผิด — บางคำตอบในอดีตเป็นการเดา ห้ามยืนยันชื่อเฉพาะ ตัวเลข ราคา ปุ่มกด จากความจำ"
    "ว่าเป็นความจริง ถ้าต้องใช้ข้อมูลจริงให้ค้นเว็บหรือบอกพี่ปอยว่าไม่แน่ใจ\n"
    "3. ถ้าความจำด้านล่างไม่เกี่ยวกับที่พี่ปอยถาม ให้บอกตรงๆ ว่าจำเรื่องนี้ไม่ได้\n\n"
)
VOICE_MEMORY_EMPTY = "ไม่พบความจำที่เกี่ยวข้อง ให้บอกพี่ปอยตรงๆ ว่าจำเรื่องนี้ไม่ได้ ห้ามแต่งความจำ"
VOICE_MEMORY_FAILED = "ระบบความจำขัดข้องชั่วคราว (ไม่ใช่ว่าไม่เคยคุย) ให้บอกพี่ปอยตรงๆ ว่าตอนนี้นึกไม่ได้ ห้ามแต่ง"
VOICE_MEMORY_TIMED_OUT = "นึกความจำนานเกินกำหนดจึงยกเลิก (ไม่ใช่ว่าไม่เคยคุย) ให้บอกพี่ปอยว่าตอนนี้นึกไม่ทัน ห้ามแต่ง"


def _recall(assistant: str, query: str, session_id: str) -> str:
    return recall(assistant, query, session_id=session_id)


async def voice_recall_payload(assistant: str, query: str, session_id: str = "") -> dict:
    """นึกความจำ → payload ของ FunctionResponse · ตอบทันทีเมื่อชนเพดาน · ล้ม ≠ ไม่เจอ"""
    t0 = time.monotonic()
    try:
        text = await asyncio.wait_for(asyncio.to_thread(_recall, assistant, query, session_id),
                                      timeout=VOICE_MEMORY_TIMEOUT)
    except asyncio.TimeoutError:
        logger.error(f"[Voice WS] นึกความจำ {query!r} เกินเพดาน {VOICE_MEMORY_TIMEOUT:.0f}s")
        return {"error": VOICE_MEMORY_TIMED_OUT}
    except Exception as e:
        logger.error(f"[Voice WS] นึกความจำ {query!r} ล้ม {type(e).__name__}: {e}")
        return {"error": VOICE_MEMORY_FAILED}
    text = (text or "").strip()
    logger.info(f"[Voice WS] นึกความจำ {query!r} → {len(text)} ตัวอักษร · {time.monotonic() - t0:.1f}s")
    if not text:
        return {"error": VOICE_MEMORY_EMPTY}
    return {"result": VOICE_MEMORY_GUIDE + text}
