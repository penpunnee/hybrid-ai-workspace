"""dead-man's switch — ยิงสัญญาณ "ฉันยังทำงานอยู่" ไปให้ปลายทางเฝ้าแทนเรา

ทำไมต้องมี: งานที่ตั้งเวลาไว้ล้มเหลวได้แบบ **เงียบสนิท** — APScheduler thread ตาย,
container ถูก restart คาบเกี่ยวเวลา job, หรือ process ค้าง — ทั้งหมดนี้ไม่ผลิต
log error ใดๆ เลย มันคือ "ความเงียบ" ไม่ใช่ "ข้อผิดพลาด" และไม่มีใครสังเกตความเงียบได้
→ กลับด้านการเฝ้า: ให้บริการภายนอก (healthchecks.io) เป็นคนดังขึ้นมาเมื่อ
สัญญาณ *ไม่* มาตามกำหนด

⚠️ กับดักที่เคยโดนในโปรเจกต์ phrae: healthchecks.io ตอบ **HTTP 200 แม้ check
ที่ระบุไม่มีอยู่จริง** (uuid ผิด/ถูกลบ) — status code เป็นแค่ ack ว่ารับ request แล้ว
เท่านั้น ความจริงอยู่ใน **body** ซึ่งต้องเป็น "OK" เป๊ะ ถ้าเชื่อ status code
จะได้ระบบเฝ้าระวังที่รายงานว่าปกติตลอดไปโดยไม่เคยเฝ้าอะไรเลย

ตั้งค่า: HEARTBEAT_URL (เช่น https://hc-ping.com/<uuid>) — ไม่ตั้ง = ปิดเงียบ
"""
import logging
import os

import requests

logger = logging.getLogger(__name__)

HEARTBEAT_TIMEOUT = float(os.getenv("HEARTBEAT_TIMEOUT", "10"))

# body ที่ถือว่าปลายทางรับรู้จริง — healthchecks.io ตอบ "OK" ตัวเดียว
_OK_BODIES = {"ok"}


def ping(url: str | None = None, timeout: float | None = None) -> bool:
    """ยิง heartbeat หนึ่งครั้ง — คืน True เฉพาะเมื่อปลายทาง **ยืนยันใน body** ว่ารับแล้ว

    ไม่เคย raise: heartbeat ที่ยิงไม่ออกต้องไม่ทำให้งานที่สำเร็จแล้วกลายเป็นล้มเหลว
    แต่ต้อง log ระดับ error เสมอ เพราะ "เฝ้าไม่ได้" ก็เป็นปัญหาที่ต้องรู้
    """
    target = (url or os.getenv("HEARTBEAT_URL", "")).strip()
    if not target:
        # ไม่ได้ตั้งค่า (เครื่อง dev) — เงียบ ไม่ใช่ error
        return False

    try:
        resp = requests.post(target, timeout=timeout or HEARTBEAT_TIMEOUT)
    except Exception as e:
        logger.error("[heartbeat] ยิงไม่ออก (%s): %s", target, e)
        return False

    body = (resp.text or "").strip()
    if resp.status_code >= 400:
        logger.error("[heartbeat] ปลายทางตอบ HTTP %s body=%r", resp.status_code, body)
        return False

    if body.lower() not in _OK_BODIES:
        # HTTP 200 แต่ไม่ใช่ OK = check ไม่มีอยู่จริง — เคสที่หลอกที่สุด
        logger.error(
            "[heartbeat] ได้ HTTP %s แต่ body=%r (ไม่ใช่ OK) — check อาจถูกลบหรือ uuid ผิด "
            "→ ถือว่ายิงไม่สำเร็จ", resp.status_code, body)
        return False

    logger.info("[heartbeat] ok → %s", target)
    return True
