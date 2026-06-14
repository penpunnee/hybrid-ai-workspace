"""Active Learning — ตรวจว่าข้อมูลพอจะตอบไหม ถ้าไม่ ให้ AI ถามกลับก่อน

หลักการ:
  ตรวจ 2 มิติ
    1. Ambiguity signals: prompt สั้น/มี pronoun/ไม่มี entity ที่ระบุชัด
    2. Context strength: retrieval ได้ผลน้อย/score ต่ำ
  → ถ้าทั้งคู่อ่อน + ไม่มี history → inject instruction ให้ AI ถามกลับ

  Domain-specific (session 2026-06-14): คำถาม "อากาศ/ฝน/พยากรณ์" ที่ไม่มี
  location → ตอบไม่ได้จริง (Gemini grounding ค้นไม่ได้ว่า "ฝนที่ไหน" แล้วกุ
  ชื่อสถานที่ขึ้นมา). generic ambiguity จับไม่ได้เพราะ chunk ไทยยาว = "มี entity"
  → เพิ่ม rule เฉพาะ: weather + ไม่มี location → clarify_directly (chat router
  short-circuit ถามกลับแบบ deterministic ไม่เรียก LLM = กุไม่ได้เลย)

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


# ── Weather domain (ต้องมี location เสมอ) ───────────────────────────────────
# keyword ที่บอกว่าเป็นคำถามเรื่องสภาพอากาศ
_WEATHER_KW = ("ฝนตก", "ฝนจะตก", "ฝน", "อากาศ", "พยากรณ์", "อุณหภูมิ",
               "ร้อนไหม", "ร้อนมั้ย", "หนาวไหม", "หนาวมั้ย", "ฝนฟ้าคะนอง",
               "แดดออก", "น้ำท่วม", "ลมแรง", "พายุ",
               "weather", "rain", "forecast", "temperature", "humid")
# intent ที่บ่งชี้ว่าเป็น "พยากรณ์/ถาม" ไม่ใช่ประโยคบอกเล่า (กัน false-positive)
_FORECAST_INTENT = ("ไหม", "มั้ย", "วันนี้", "พรุ่งนี้", "คืนนี้", "เย็นนี้",
                    "เช้านี้", "ตอนนี้", "จะตก", "กี่องศา", "เท่าไหร่", "เท่าไร",
                    "?", "พยากรณ์", "ยังไง", "เป็นไง", "เป็นยังไง")

# จังหวัดไทย 77 (ตัด "เลย"/"ตาก" ออกจาก bare list เพราะเป็นคำไทยทั่วไป
# "ฝนตกไหมเลย"/"ตากผ้า" → false-positive; ถ้าจะระบุจริงมักมี marker "จังหวัด"/"จ." อยู่แล้ว)
_PROVINCES = (
    "กรุงเทพ", "สมุทรปราการ", "นนทบุรี", "ปทุมธานี", "พระนครศรีอยุธยา", "อยุธยา",
    "อ่างทอง", "ลพบุรี", "สิงห์บุรี", "ชัยนาท", "สระบุรี", "ชลบุรี", "ระยอง",
    "จันทบุรี", "ตราด", "ฉะเชิงเทรา", "ปราจีนบุรี", "นครนายก", "สระแก้ว",
    "นครราชสีมา", "บุรีรัมย์", "สุรินทร์", "ศรีสะเกษ", "อุบลราชธานี", "ยโสธร",
    "ชัยภูมิ", "อำนาจเจริญ", "หนองบัวลำภู", "ขอนแก่น", "อุดรธานี", "หนองคาย",
    "มหาสารคาม", "ร้อยเอ็ด", "กาฬสินธุ์", "สกลนคร", "นครพนม", "มุกดาหาร",
    "บึงกาฬ", "เชียงใหม่", "ลำพูน", "ลำปาง", "อุตรดิตถ์", "แพร่", "น่าน",
    "พะเยา", "เชียงราย", "แม่ฮ่องสอน", "นครสวรรค์", "อุทัยธานี", "กำแพงเพชร",
    "สุโขทัย", "พิษณุโลก", "พิจิตร", "เพชรบูรณ์", "ราชบุรี", "กาญจนบุรี",
    "สุพรรณบุรี", "นครปฐม", "สมุทรสาคร", "สมุทรสงคราม", "เพชรบุรี",
    "ประจวบคีรีขันธ์", "นครศรีธรรมราช", "กระบี่", "พังงา", "ภูเก็ต",
    "สุราษฎร์ธานี", "ระนอง", "ชุมพร", "สงขลา", "สตูล", "ตรัง", "พัทลุง",
    "ปัตตานี", "ยะลา", "นราธิวาส",
    # ชื่อเล่น/เมืองที่คนเรียกบ่อย
    "กทม", "บางกอก", "โคราช", "พัทยา", "หาดใหญ่", "ศรีราชา",
    "bangkok", "phuket", "chiang mai", "chiangmai", "pattaya",
)
# marker ที่ตามด้วยชื่อพื้นที่ = มี location แน่ๆ
_LOC_MARKERS = ("จังหวัด", "อำเภอ", "ตำบล", "จ.", "อ.", "ต.")


def _has_thai_substring(text: str, needles: tuple[str, ...]) -> bool:
    return any(n in text for n in needles)


def _is_weather_query(text: str) -> bool:
    """เป็นคำถามพยากรณ์อากาศไหม (มี weather keyword + intent ถาม/พยากรณ์)"""
    if not text:
        return False
    low = text.lower()
    if not any(k in low for k in _WEATHER_KW):
        return False
    return any(i in low for i in _FORECAST_INTENT)


def _has_location(text: str) -> bool:
    """มีการระบุพื้นที่ (จังหวัด/อำเภอ/ชื่อเมือง/marker) ไหม"""
    if not text:
        return False
    low = text.lower()
    if any(p.lower() in low for p in _PROVINCES):
        return True
    if any(m in text for m in _LOC_MARKERS):
        return True
    return False


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
    clarify_directly: bool = False                      # chat router → short-circuit ถามกลับเอง (ไม่เรียก LLM)
    clarify_message: str = ""                           # ข้อความถามกลับ deterministic (ใช้คู่ clarify_directly)
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


def _wants_direct(prompt: str) -> bool:
    return _has_thai_substring(prompt or "", _THAI_DIRECT) or bool(_ENG_DIRECT.search(prompt or ""))


def decide(
    prompt: str,
    retrieval_scores: list[float] | None = None,
    history_length: int = 0,
    enabled: bool = True,
    recent_user_text: str = "",
) -> ActiveLearningDecision:
    """ตัดสินใจว่าควรให้ AI ถามกลับไหม

    Args:
        prompt: คำถามล่าสุดของ user
        retrieval_scores: similarity scores จาก citations/chunks/memory (0-1)
        history_length: จำนวน turns ใน session (ถ้ามาก → user มี context แล้ว)
        enabled: feature flag — ปิดได้ผ่าน request
        recent_user_text: ข้อความ user ก่อนหน้าใน session (ใช้หา location ที่เคยบอกแล้ว)

    Returns:
        ActiveLearningDecision
    """
    if not enabled:
        return ActiveLearningDecision(should_ask=False, reason="disabled")

    # ── Weather domain rule (มาก่อน generic ambiguity) ─────────────────────
    # คำถามอากาศ/ฝน ที่ไม่มี location ทั้งใน prompt และ history → ถามกลับเลย
    if _is_weather_query(prompt):
        has_loc = _has_location(prompt) or _has_location(recent_user_text)
        if not has_loc and not _wants_direct(prompt):
            msg = ("บอกจังหวัดหรืออำเภอที่อยากรู้หน่อยได้ไหม "
                   "จะได้เช็คพยากรณ์อากาศให้ตรงพื้นที่จริง ๆ ไม่เดามั่ว 😊")
            return ActiveLearningDecision(
                should_ask=True,
                reason="weather_no_location → clarify",
                clarify_directly=True,
                clarify_message=msg,
                signals={"weather_no_location": True, "weather_query": True},
            )

    ambig, ambig_reasons = _ambiguity_score(prompt)
    ctx_strength = _context_strength(retrieval_scores)

    signals = {
        "ambiguity": round(ambig, 3),
        "ambiguity_reasons": ambig_reasons,
        "context_strength": ctx_strength,
        "history_length": history_length,
    }

    # ห้ามถามกลับถ้า user สั่งให้ตอบตรงๆ
    if _wants_direct(prompt):
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
