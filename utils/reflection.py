"""Reflection — critic LLM ตรวจคำตอบหลัง stream เสร็จ

Flow:
  1. คำตอบ (draft) ถูก stream ส่งให้ user ก่อน
  2. ถ้า reflect=True ในคำขอ → เรียก critic LLM หลังจาก stream เสร็จ
  3. ถ้า critic เจอปัญหา (score < threshold) → ส่ง revision เป็น SSE event แยก

ออกแบบให้ ไม่บล็อก streaming UX — user เห็นคำตอบเร็วเหมือนเดิม
"""
import json
import logging
import os
import re
from dataclasses import dataclass, field, asdict
from typing import Optional

from openai import OpenAI

logger = logging.getLogger(__name__)

_LMSTUDIO_BASE_URL = os.getenv("LMSTUDIO_BASE_URL", "http://192.168.51.235:1234/v1")
_REFLECT_MODEL = os.getenv("REFLECTION_MODEL", os.getenv("LMSTUDIO_REASON_MODEL", "deepseek/deepseek-r1-0528-qwen3-8b"))
_REFLECT_TIMEOUT = int(os.getenv("REFLECTION_TIMEOUT", "30"))
_REFLECT_THRESHOLD = float(os.getenv("REFLECTION_THRESHOLD", "0.7"))

_client = OpenAI(base_url=_LMSTUDIO_BASE_URL, api_key="lmstudio", timeout=_REFLECT_TIMEOUT)


@dataclass
class Reflection:
    """ผลการ reflect"""
    score: float = 1.0              # 0-1, > threshold = ผ่าน
    issues: list[str] = field(default_factory=list)
    revised: str = ""               # ถ้าว่าง = ไม่ต้องแก้
    verdict: str = "ok"             # ok | needs_revision | rejected
    used_llm: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def needs_revision(self) -> bool:
        return self.verdict == "needs_revision" and bool(self.revised.strip())


_CRITIC_PROMPT = """คุณคือ Critic ที่ตรวจคำตอบของ AI assistant ตอบเป็น JSON เท่านั้น ห้ามมีข้อความอื่น

หน้าที่: ประเมินคำตอบจาก 3 มิติ
1. **factual**: ตรงกับข้อมูลใน context ที่ให้ไหม / ไม่แต่ง?
2. **complete**: ตอบครบประเด็นของคำถามไหม?
3. **clarity**: อ่านเข้าใจ ไม่กำกวม?

ให้คะแนนรวม 0.0-1.0:
  - 0.9-1.0: ดี ไม่ต้องแก้
  - 0.7-0.89: พอใช้ ไม่ต้องแก้ แต่ระบุ issues
  - <0.7: ต้องเขียนใหม่ (ใส่ใน revised)

Schema: {"score": float, "issues": [str], "verdict": "ok"|"needs_revision", "revised": str}

กฎ:
- ถ้า verdict="ok": revised = ""
- ถ้า verdict="needs_revision": revised = คำตอบที่แก้แล้ว (ใช้ภาษาเดียวกับ original)
- issues: list สั้นๆ 1-3 ข้อ (ตอบไทย)"""


def _parse_json(text: str) -> Optional[dict]:
    """parse JSON จาก LLM response — ทนข้อความเสริม + think tags"""
    text = text.strip()
    # ลบ <think>...</think> ของ reasoning models
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def reflect_answer(
    prompt: str,
    draft: str,
    context: str = "",
    threshold: float = _REFLECT_THRESHOLD,
) -> Reflection:
    """ตรวจคำตอบ draft กับ critic LLM

    Args:
        prompt: คำถามต้นฉบับของ user
        draft: คำตอบ AI ที่กำลังจะส่ง
        context: context ที่ inject ตอน generate (สำหรับเช็ค grounding)
        threshold: คะแนนต่ำสุดที่ยอมรับได้

    Returns:
        Reflection — ถ้า fail/timeout คืน verdict="ok" (ไม่แก้ → safe default)
    """
    if not draft or len(draft.strip()) < 20:
        return Reflection(score=1.0, verdict="ok")

    user_block = (
        f"## Original Question\n{prompt}\n\n"
        f"## Context Given to AI\n{context[:1500] if context else '(ไม่มี context พิเศษ)'}\n\n"
        f"## Draft Answer\n{draft[:2000]}\n\n"
        f"ประเมินและตอบ JSON ตาม schema"
    )

    try:
        resp = _client.chat.completions.create(
            model=_REFLECT_MODEL,
            messages=[
                {"role": "system", "content": _CRITIC_PROMPT},
                {"role": "user", "content": user_block},
            ],
            temperature=0.3,
            max_tokens=800,
            stream=False,
        )
        text = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        logger.warning(f"[Reflection] LLM call failed: {e}")
        return Reflection(score=1.0, verdict="ok")

    data = _parse_json(text)
    if not data:
        logger.warning(f"[Reflection] non-JSON response: {text[:120]!r}")
        return Reflection(score=1.0, verdict="ok")

    try:
        score = float(data.get("score", 1.0))
    except (TypeError, ValueError):
        score = 1.0
    issues = [str(x) for x in (data.get("issues") or []) if x][:3]
    verdict = str(data.get("verdict", "ok")).strip().lower()
    revised = str(data.get("revised", "")).strip()

    # safety: ถ้า verdict="needs_revision" แต่ไม่มี revised หรือ score >= threshold → downgrade เป็น ok
    if verdict != "ok":
        if not revised or score >= threshold:
            verdict = "ok"
            revised = ""

    return Reflection(
        score=round(score, 3),
        issues=issues,
        verdict=verdict,
        revised=revised,
        used_llm=True,
    )


def should_reflect(prompt: str, draft: str) -> bool:
    """heuristic: ควร reflect ไหม — กัน latency กับคำตอบสั้นๆ"""
    if not draft or len(draft) < 100:
        return False
    if len(prompt) < 5:
        return False
    return True
