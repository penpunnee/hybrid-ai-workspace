"""Correction Record — แปลง "การแก้ไข" ของ user เป็นข้อเท็จจริงที่อ่านรู้เรื่อง

เดิม `teach.py` เก็บข้อความดิบลง `user_facts` ตรงๆ:
    [การแก้ไข] ผิดแล้ว ds923+ ต่างหาก
ซึ่งไม่มีบริบทว่า ds923+ คืออะไร — และก้อนนี้ถูกฉีดเข้า context **ทุก prompt**
ตลอดไป จึงต้องอ่านแล้วเข้าใจได้ด้วยตัวเอง

วิธี: ให้ LLM สกัดประโยคสมบูรณ์ โดยป้อน *คำตอบที่ผิด* เป็นบริบท (เป็นตัวเดียวที่
บอกว่า "ds923+" หมายถึงอะไร) — ถ้า LLM ล่ม/คายขยะ ให้ fallback เป็นการจับคู่
ข้อความดิบกับคำตอบที่ผิด **ห้ามคืนค่าว่าง** เพราะจะทำให้ของที่ user อุตส่าห์แก้ให้
หายไปเงียบๆ (บทเรียน "ล้มเหลว → ยอด 0" จาก audit)
"""
from __future__ import annotations

import logging
import os
import re
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# เข้า context ทุก prompt — ยาวเกินไปกินที่ของ memory/skills ตัวอื่น
MAX_RECORD_LEN = 600
_MIN_FACT_LEN = 12

# สัญญาณว่า LLM ไม่ได้สกัดอะไรออกมาจริง (ยืมนิยามเดียวกับ learn_gate.clean_lesson)
_ERROR_PREFIX = ("⚠️", "❌", "🚫", "error:", "exception:")
_REFUSAL_KW = (
    "ไม่สามารถช่วยเหลือในกรณีนี้ได้",
    "ไม่สามารถสกัด",
    "ไม่มีข้อเท็จจริง",
    "โมเดลไม่ได้ให้คำตอบ",
)

_EXTRACT_PROMPT = """คุณคือตัวสกัดข้อเท็จจริง หน้าที่เดียวคือแปลง "ข้อความที่ผู้ใช้แก้ไข AI"
ให้เป็นประโยคบอกเล่าสั้นๆ ที่อ่านแล้วเข้าใจได้ทันทีโดยไม่ต้องเห็นบทสนทนา

กฎ:
- ใช้ข้อมูลจาก "คำตอบที่ผิด" เพื่อรู้ว่าผู้ใช้กำลังพูดถึงเรื่องอะไร
- เขียนเป็นประโยคเดียว ภาษาไทย ไม่เกิน 200 ตัวอักษร
- เขียนเฉพาะข้อเท็จจริงที่ถูกต้อง **ห้ามใส่คำบ่น** ("ผิดแล้ว", "ไม่ใช่")
- ห้ามแต่งข้อมูลที่ไม่มีในสองข้อความนั้น
- ถ้าสกัดไม่ได้จริงๆ ตอบว่า SKIP

ตัวอย่าง:
คำตอบที่ผิด: NAS ที่บ้านคือ Synology DS918+
ผู้ใช้แก้ว่า: ผิดแล้ว ds923+ ต่างหาก
→ NAS ที่บ้านคือ Synology DS923+"""


def _looks_like_garbage(text: str) -> bool:
    low = text.lower()
    if len(text) < _MIN_FACT_LEN:
        return True
    if any(low.startswith(p.lower()) for p in _ERROR_PREFIX):
        return True
    if re.search(r"\bskip\b", text, re.IGNORECASE):
        return True
    return any(kw in text for kw in _REFUSAL_KW)


def _fallback(correction: str, wrong_answer: str) -> str:
    """จับคู่ข้อความดิบกับคำตอบที่ผิด — ใช้เมื่อ LLM ใช้ไม่ได้

    ยังดีกว่าเก็บ correction เดี่ยวๆ เพราะอย่างน้อยมีบริบทว่าแก้เรื่องอะไร
    """
    correction = correction.strip()
    wrong = (wrong_answer or "").strip()
    if not wrong:
        return f"[การแก้ไข] {correction}"[:MAX_RECORD_LEN]
    budget = MAX_RECORD_LEN - len(correction) - 40
    if budget < 40:
        return f"[การแก้ไข] {correction}"[:MAX_RECORD_LEN]
    return f"[การแก้ไข] {correction}\n(แก้จากคำตอบเดิม: {wrong[:budget]})"[:MAX_RECORD_LEN]


def build_correction_record(
    correction: str,
    wrong_answer: str = "",
    extractor: Optional[Callable[[str, str], Optional[str]]] = None,
) -> str:
    """สร้างข้อความที่จะเก็บลง user_facts → "" ถ้าไม่มีอะไรให้เก็บ

    `extractor(correction, wrong_answer) -> str | None` แยกออกมาเป็น argument
    เพื่อให้เทสได้โดยไม่ต้องมี LLM จริง (และเพื่อให้เห็นชัดว่าเส้นทางล้มเหลว
    ทุกเส้นจบที่ `_fallback` ไม่ใช่คืนค่าว่าง)
    """
    correction = (correction or "").strip()
    if not correction:
        return ""

    if extractor is not None:
        failed = False
        try:
            fact = extractor(correction, wrong_answer or "")
        except Exception as e:
            logger.warning(f"[Correction] extractor ล้ม ใช้ fallback: {e}")
            fact, failed = None, True
        if fact:
            fact = fact.strip()
            if not _looks_like_garbage(fact):
                return fact[:MAX_RECORD_LEN]
            logger.info(f"[Correction] ผลจาก LLM ใช้ไม่ได้ ({fact[:60]!r}) → fallback")
        elif not failed:
            # เส้นทางนี้เคยเงียบสนิท → เห็นแค่ว่าได้ fallback แต่ไม่รู้ว่าทำไม
            # (ความล้มเหลวที่หน้าตาเหมือนสำเร็จ — บทเรียนข้อ 7 ของ audit)
            logger.info("[Correction] extractor ไม่คืนข้อความ → fallback")

    return _fallback(correction, wrong_answer)


def clean_extraction(text: Optional[str]) -> Optional[str]:
    """ทำความสะอาดผลดิบจาก LLM → None ถ้าไม่เหลืออะไรที่ใช้ได้

    ⚠️ `<think>` ที่ **ยังไม่ปิด** = โมเดลคิดยังไม่จบแล้วโดน max_tokens ตัด
    (Qwen3.5 ปิด thinking ผ่าน API ไม่ได้ — ดู CLAUDE.md) ข้อความที่เหลือเป็น
    บทครุ่นคิด ไม่ใช่คำตอบ ต้องทิ้งทั้งก้อน ห้ามเก็บเป็น "ข้อเท็จจริง"
    """
    if not text:
        return None
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    if "<think>" in text:
        return None
    text = text.lstrip("→").strip()
    return text or None


def last_assistant_answer(buffer: Optional[list]) -> str:
    """คำตอบล่าสุดของ assistant จาก working-memory buffer → "" ถ้าไม่มี

    ⚠️ ต้องเรียก **ก่อน** push เทิร์นปัจจุบันลง working memory ไม่งั้นจะได้
    คำตอบของเทิร์นนี้เอง (ซึ่งคือคำตอบที่ *รับทราบ* การแก้ไข ไม่ใช่คำตอบที่ผิด)
    """
    for item in reversed(buffer or []):
        if (item or {}).get("role") == "assistant":
            return (item.get("content") or "").strip()
    return ""


def llm_extractor(correction: str, wrong_answer: str) -> Optional[str]:
    """extractor จริงที่ยิง LM Studio — pattern เดียวกับ utils/reflection.py

    แยกจาก `build_correction_record` เพื่อให้ตรรกะ fallback เทสได้โดยไม่แตะเครือข่าย
    """
    base_url = os.getenv("LMSTUDIO_BASE_URL", "")
    if not base_url:
        return None
    from openai import OpenAI

    model = os.getenv("LMSTUDIO_REASON_MODEL", "qwen/qwen3.5-9b")
    # timeout กว้างได้เพราะผู้เรียกอยู่ในเธรดเบื้องหลัง (ดู routers/chat.py) —
    # ผู้ใช้ไม่ได้รอผลนี้ · โมเดล reasoning ใช้เวลาจริง ~40-60 วิ
    timeout = float(os.getenv("CORRECTION_EXTRACT_TIMEOUT", "60"))
    client = OpenAI(base_url=base_url, api_key=os.getenv("LMSTUDIO_API_KEY", "lmstudio"), timeout=timeout)
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _EXTRACT_PROMPT},
            {"role": "user", "content": f"คำตอบที่ผิด: {(wrong_answer or '(ไม่มี)')[:1200]}\n"
                                        f"ผู้ใช้แก้ว่า: {correction[:500]}\n→"},
        ],
        temperature=0.2,
        # เผื่อ reasoning trace — Qwen3.5 ปิด thinking ผ่าน API ไม่ได้ ถ้าตั้งแค่ 200
        # โควตาจะถูก <think> กินหมดจนไม่เหลือคำตอบ (เจอจริงบน prod 2026-08-02)
        max_tokens=900,
        stream=False,
    )
    return clean_extraction(resp.choices[0].message.content)
