"""dead-man's switch — ยิงสัญญาณ "ฉันยังทำงานอยู่" ไปให้ปลายทางเฝ้าแทนเรา

ทำไมต้องมี: งานที่ตั้งเวลาไว้ล้มเหลวได้แบบ **เงียบสนิท** — APScheduler thread ตาย,
container ถูก restart คาบเกี่ยวเวลา job, หรือ process ค้าง — ทั้งหมดนี้ไม่ผลิต
log error ใดๆ เลย มันคือ "ความเงียบ" ไม่ใช่ "ข้อผิดพลาด" และไม่มีใครสังเกตความเงียบได้
→ กลับด้านการเฝ้า: ให้บริการภายนอก (healthchecks.io) เป็นคนดังขึ้นมาเมื่อ
สัญญาณ *ไม่* มาตามกำหนด

⚠️ **status code เป็นแค่ ack ว่ารับ request แล้ว ไม่ได้บอกว่ารับรู้จริง**
วัดกับ hc-ping.com จริงเมื่อ 2026-08-05 ด้วย uuid สุ่มที่ไม่มีอยู่ในระบบ:

    POST https://hc-ping.com/<uuid ที่ไม่มีอยู่>
    → HTTP 200   body = 'OK (not found)'

**body ขึ้นต้นด้วย `OK`** ดังนั้นโค้ดที่ระวังตัวระดับหนึ่งแล้ว — เลิกเชื่อ status
code หันมาเช็ค body — ยังหลุดอยู่ดีถ้าใช้ `body.startswith("OK")`
ต้องเทียบ **เป๊ะ** (`body.lower() == "ok"`) เท่านั้นถึงจะแยก "ยิงเข้า check จริง"
ออกจาก "ยิงเข้าอากาศ" ได้ ไม่งั้นจะได้ระบบเฝ้าระวังที่รายงานว่าปกติตลอดไป
โดยไม่เคยเฝ้าอะไรเลย (uuid พิมพ์ผิดตัวเดียวก็พอ)

ตั้งค่า: HEARTBEAT_URL (เช่น https://hc-ping.com/<uuid>) — ไม่ตั้ง = ปิดเงียบ
"""
import logging
import time
from urllib.parse import urlsplit

import requests

from core.env_registry import env_float, env_int, env_str

logger = logging.getLogger(__name__)

# env ของ heartbeat — ไฟล์นี้เป็นเจ้าของ 4 ชื่อ (ก้อน 4 · 2026-09-24 · ตัวกัน: tests/test_env_registry.py)
# HEARTBEAT_URL เคยอ่านใน ping() ทุกครั้ง — env ใน prod นิ่ง จึงเป็นระดับโมดูล · เทส patch ค่าในโมดูล
_G = "Backup dead-man's switch"
HEARTBEAT_URL = env_str("HEARTBEAT_URL", "", group=_G, doc=(
    "ยิงหลัง DB backup 03:30 สำเร็จ *จริง* เท่านั้น (ของเปล่า/พังกลางคัน = ไม่ยิง → ปลายทางเตือนเมื่อสัญญาณขาด)\n"
    "สร้าง check ที่ https://healthchecks.io แล้วตั้ง period 1 วัน + grace 2 ชม. · ว่าง = ปิดเงียบ (ไม่มีใครเฝ้า)"))
HEARTBEAT_TIMEOUT = env_float("HEARTBEAT_TIMEOUT", 10.0, group=_G, doc="วินาที timeout ต่อการยิง")
# ยิงซ้ำเฉพาะความผิดพลาดชั่วคราว — งานนี้รันตี 3 ครึ่ง ไม่มีใครนั่งรอ
# หน่วงเพิ่มสูงสุด ~20 วิ แลกกับการไม่ถูกปลุกเพราะเน็ตกระตุกวินาทีเดียว
HEARTBEAT_ATTEMPTS = env_int("HEARTBEAT_ATTEMPTS", 3, group=_G, doc=(
    "ยิงซ้ำเฉพาะ \"พังชั่วคราว\" (ต่อไม่ติด / HTTP 5xx) — ไม่ยิงซ้ำเมื่อ body ผิดหรือ 4xx\n"
    "เพราะนั่นคือความผิดถาวร (uuid พิมพ์ผิด/check ถูกลบ) ยิงอีกกี่ครั้งก็ได้คำตอบเดิม"))
HEARTBEAT_RETRY_WAIT = env_float("HEARTBEAT_RETRY_WAIT", 10.0, group=_G, doc="วินาทีระหว่างการยิงซ้ำ")

# body ที่ถือว่าปลายทางรับรู้จริง — healthchecks.io ตอบ "OK" ตัวเดียวเป๊ะ
# (อย่าเปลี่ยนเป็น startswith เด็ดขาด — ดู docstring หัวไฟล์)
_OK_BODIES = {"ok"}


def _redact(url: str) -> str:
    """ตัด path/query ทิ้ง เหลือแค่ host — ping URL คือความลับ

    uuid ท้าย URL = สิทธิ์ยิง check นั้น ใครได้ไปก็ยืนยันแทนเราได้ (= ปิดปาก
    ตัวเฝ้าได้) และ log ของ prod ถูกอ่าน/ก๊อปไปแปะเวลาดีบั๊กเป็นปกติ
    """
    try:
        parts = urlsplit(url)
        return f"{parts.scheme}://{parts.netloc}/…" if parts.netloc else "<ไม่ใช่ URL>"
    except ValueError:
        return "<ไม่ใช่ URL>"


def ping(url: str | None = None, timeout: float | None = None,
         attempts: int | None = None) -> bool:
    """ยิง heartbeat — คืน True เฉพาะเมื่อปลายทาง **ยืนยันใน body** ว่ารับแล้ว

    ยิงซ้ำเฉพาะ "พังชั่วคราว" (ต่อไม่ติด / HTTP 5xx) เพราะเน็ตกระตุกตอนตี 3 ครึ่ง
    ไม่ควรกลายเป็นอีเมลเตือนตอนตี 5 ทั้งที่ backup สำเร็จ — false alarm สอนให้
    คนเลิกฟังเสียงเตือน ซึ่งอันตรายกว่าไม่มีเสียงเตือน

    **ไม่ยิงซ้ำ** เมื่อ body ผิดหรือ HTTP 4xx เพราะนั่นคือความผิดถาวร
    (uuid พิมพ์ผิด / check ถูกลบ) ยิงอีกกี่ครั้งก็ได้คำตอบเดิม มีแต่หน่วงเวลาเปล่า

    ไม่เคย raise: heartbeat ที่ยิงไม่ออกต้องไม่ทำให้งานที่สำเร็จแล้วกลายเป็นล้มเหลว
    แต่ต้อง log ระดับ error เสมอ เพราะ "เฝ้าไม่ได้" ก็เป็นปัญหาที่ต้องรู้
    """
    target = (url or HEARTBEAT_URL).strip()
    if not target:
        # ไม่ได้ตั้งค่า (เครื่อง dev) — เงียบ ไม่ใช่ error
        return False

    tries = attempts if attempts is not None else HEARTBEAT_ATTEMPTS
    last = ""

    for n in range(1, tries + 1):
        try:
            resp = requests.post(target, timeout=timeout or HEARTBEAT_TIMEOUT)
        except Exception as e:
            last = f"ต่อไม่ติด: {e}"
            if n < tries:
                logger.warning("[heartbeat] %s (ครั้งที่ %d/%d) — รอ %.0f วิแล้วลองใหม่",
                               last, n, tries, HEARTBEAT_RETRY_WAIT)
                time.sleep(HEARTBEAT_RETRY_WAIT)
                continue
            break

        body = (resp.text or "").strip()

        if resp.status_code >= 500:
            last = f"HTTP {resp.status_code} body={body!r}"
            if n < tries:
                logger.warning("[heartbeat] ปลายทางขัดข้อง %s (ครั้งที่ %d/%d) — "
                               "รอ %.0f วิแล้วลองใหม่", last, n, tries,
                               HEARTBEAT_RETRY_WAIT)
                time.sleep(HEARTBEAT_RETRY_WAIT)
                continue
            break

        if resp.status_code >= 400:
            # ความผิดถาวร — URL ผิดรูป/ถูกปฏิเสธ ยิงซ้ำไม่ช่วย
            logger.error("[heartbeat] ปลายทางตอบ HTTP %s body=%r — ไม่ยิงซ้ำ "
                         "(ความผิดถาวร ตรวจ HEARTBEAT_URL)", resp.status_code, body)
            return False

        if body.lower() not in _OK_BODIES:
            # HTTP 200 แต่ไม่ใช่ OK = check ไม่มีอยู่จริง — เคสที่หลอกที่สุด
            # ของจริงที่วัดได้: body='OK (not found)' ซึ่ง startswith("OK") = True
            logger.error(
                "[heartbeat] ได้ HTTP %s แต่ body=%r (ต้องเป็น 'OK' เป๊ะ) — "
                "check อาจถูกลบหรือ uuid ผิด → ถือว่ายิงไม่สำเร็จ ไม่ยิงซ้ำ",
                resp.status_code, body)
            return False

        logger.info("[heartbeat] ok → %s%s", _redact(target),
                    f" (ครั้งที่ {n})" if n > 1 else "")
        return True

    logger.error("[heartbeat] ยิงไม่สำเร็จหลังลอง %d ครั้ง (%s): %s",
                 tries, _redact(target), last)
    return False
