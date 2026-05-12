"""Active Learning — ตรวจว่าข้อมูลพอจะตอบไหม ถ้าไม่ ให้ AI ถามกลับก่อน

หลักการ:
  ตรวจ 2 มิติ
    1. Ambiguity signals: prompt สั้น/มี pronoun/ไม่มี entity ที่ระบุชัด
    2. Context strength: retrieval ได้ผลน้อย/score ต่ำ
  → ถ้าทั้งคู่อ่อน + ไม่มี history → inject instruction ให้ AI ถามกลับ

ไม่ใช้ LLM ในการตัดสินใจ (เพื่อ latency) — heuristic ล้วน
"""
from __future__ import annotations
import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# คำที่บ่งชี้ ambiguity — ไทยใช้ substring (word boundary \b ไม่ทำงานกับไทย)
_THAI_VAGUE = ("มัน", "นั่น", "อันนั้น", "อันนี้", "ตัวนั้น", "พวกนั้น",
               "เรื่องนั้น", "อย่างนั้น", "แบบนั้น", "อันเก่า", "ของเดิม",
               "อธิบายต่อ", "ต่ออีก", "เพิ่มเติม", "ขยายความ")
_ENG_VAGUE = re.compile(
    r"\b(?:it|this|that|those|these|them|the thing|same|explain more|continue)\b",
    re.IGNORECASE,
)

# คำที่บ่งชี้ user ต้องการคำตอบทันที — ไม่ควรถามกลับ
_THAI_DIRECT = ("ตอบเลย", "ตอบมา", "บอกหน่อย", "สั้นๆ", "ด่วน", "เอาคำตอบ")
_ENG_DIRECT = re.compile(r"(?:just answer|tldr|tl;dr|short answer)", re.IGNORECASE)

# มีตัวเลข/ชื่อเฉพาะอังกฤษ → มี entity ที่ระบุได้
_ENG_NUM_ENTITY = re.compile(r"\d{2,}|[a-zA-Z]{4,}")
# สำหรับไทย: นับเป็น entity เมื่อมี proper noun marker หรือคำเฉพาะ ไม่ใช่แค่ตัวอักษรยาว
_THAI_GENERIC_WORDS = {"ทำงาน", "ยังไง", "อย่างไร", "อะไร", "เป็นไง",
                       "เป็นอะไร", "ทำอะไร", "ไหน", "ที่ไหน", "เมื่อไหร่"}


def _has_thai_substring(text: str, needles: tuple[str, ...]) -> bool:
    return any(n in text for n in needles)


def _has_entity(text: str) -> bool:
    """heuristic: text มีคำที่ระบุชัดเจนพอจะ retrieve ไหม"""
    if _ENG_NUM_ENTITY.search(text):
        return True
    # มีคำไทยที่ไม่ใช่ generic question words
    # นับ unique 4+ char Thai chunks ที่ไม่อยู่ใน generic list
    thai_chunks = re.findall(r"[฀-๿]{4,}", text)
    specific = [c for c in thai_chunks if not any(g in c for g in _THAI_GENERIC_WORDS)]
    return len(specific) >= 1


@dataclass
class ActiveLearningDecision:
    should_ask: bool = False
    reason: str = ""                                    # debug log
    instruction: str = ""                               # inject เพิ่มใน system prompt
    signals: dict = field(default_factory=dict)        # raw signals สำหรับ telemetry

    def to_dict(self) -> dict:
        from dataclasses import asdict
        return asdict(self)


def _ambiguity_score(prompt: str) -> tuple[float, list[str]]:
    """0-1, สูง = กำกวมมาก + list เหตุผล"""
    reasons: list[str] = []
    score = 0.0

    if not prompt:
        return 1.0, ["empty"]

    text = prompt.strip()
    n_chars = len(text)

    if n_chars < 10:
        score += 0.4
        reasons.append("too_short")

    if _has_thai_substring(text, _THAI_VAGUE) or _ENG_VAGUE.search(text):
        score += 0.35
        reasons.append("vague_pronoun")

    if not _has_entity(text):
        score += 0.3
        reasons.append("no_entity")

    # คำถามแบบ open-ended สั้นๆ
    if re.match(r"^(?:อะไร|ไง|ทำไม|why|how|what)\??\s*$", text, re.IGNORECASE):
        score = 1.0
        reasons.append("bare_question_word")

    return min(score, 1.0), reasons


def _context_strength(retrieval_scores: list[float] | None) -> float:
    """0-1, สูง = context แข็งแกร่ง"""
    if not retrieval_scores:
        return 0.0
    top = max(retrieval_scores)
    avg = sum(retrieval_scores) / len(retrieval_scores)
    # weighted: top score มีน้ำหนักกว่า
    return round(0.7 * top + 0.3 * avg, 3)


def decide(
    prompt: str,
    retrieval_scores: list[float] | None = None,
    history_length: int = 0,
    enabled: bool = True,
) -> ActiveLearningDecision:
    """ตัดสินใจว่าควรให้ AI ถามกลับไหม

    Args:
        prompt: คำถามล่าสุดของ user
        retrieval_scores: similarity scores จาก citations/chunks/memory (0-1)
        history_length: จำนวน turns ใน session (ถ้ามาก → user มี context แล้ว)
        enabled: feature flag — ปิดได้ผ่าน request

    Returns:
        ActiveLearningDecision
    """
    if not enabled:
        return ActiveLearningDecision(should_ask=False, reason="disabled")

    ambig, ambig_reasons = _ambiguity_score(prompt)
    ctx_strength = _context_strength(retrieval_scores)

    signals = {
        "ambiguity": round(ambig, 3),
        "ambiguity_reasons": ambig_reasons,
        "context_strength": ctx_strength,
        "history_length": history_length,
    }

    # ห้ามถามกลับถ้า user สั่งให้ตอบตรงๆ
    if _has_thai_substring(prompt or "", _THAI_DIRECT) or _ENG_DIRECT.search(prompt or ""):
        return ActiveLearningDecision(
            should_ask=False, reason="user_wants_direct", signals=signals
        )

    # ถ้ามี history พอสมควร (≥4 turns) → user น่าจะมี context กับ AI แล้ว
    # ผ่อนเงื่อนไข
    history_factor = 0.5 if history_length >= 4 else 1.0
    threshold = 0.55 * history_factor

    # decision: ambiguity สูง AND context อ่อน
    score = ambig * (1.0 - ctx_strength)
    should_ask = score >= threshold
    signals["combined_score"] = round(score, 3)
    signals["threshold"] = round(threshold, 3)

    instruction = ""
    reason = ""
    if should_ask:
        reason = (
            f"ambig={ambig:.2f}({','.join(ambig_reasons)}) "
            f"ctx={ctx_strength:.2f} → ask"
        )
        instruction = (
            "\n\n=== Active Learning Mode ===\n"
            "ข้อมูลใน context อาจไม่พอตอบคำถามนี้ให้แม่นยำ ก่อนตอบให้ทำตามนี้:\n"
            "1. ระบุสั้นๆ ว่าต้องการข้อมูลเพิ่มอะไร (สิ่งที่กำกวม/ยังไม่ระบุ)\n"
            "2. ถามกลับ 1-2 คำถามที่ชัดเจน เพื่อ disambiguate\n"
            "3. ถ้า user น่าจะหมายถึงอะไรชัดเจน ให้สมมติ แต่บอกสมมติฐานก่อนตอบ\n"
            "ห้ามเดามั่ว หรือตอบกว้างๆ ที่ไม่ตรงเป้า"
        )
    else:
        reason = (
            f"ambig={ambig:.2f} ctx={ctx_strength:.2f} score={score:.2f} < {threshold:.2f}"
        )

    return ActiveLearningDecision(
        should_ask=should_ask,
        reason=reason,
        instruction=instruction,
        signals=signals,
    )
