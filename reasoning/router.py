"""Model Router — เลือก model ที่เหมาะสมตามประเภทคำถาม

Provider mapping:
  simple/normal  →  LM Studio chat model (Llama 3.1 — เร็ว)
  reasoning      →  LM Studio reason model (DeepSeek R1 — คิด)
  vision/agent   →  Gemini (cloud)
  ollama         →  Ollama fallback
"""
import logging
from dataclasses import dataclass
from .classifier import Complexity, classify

logger = logging.getLogger(__name__)


@dataclass
class RouteDecision:
    provider: str          # "lmstudio" | "gemini" | "ollama"
    model: str             # ชื่อ model จริง
    complexity: Complexity
    reason: str            # เหตุผลที่เลือก (สำหรับ debug)


def route(
    prompt: str,
    provider_hint: str = "auto",
    has_image: bool = False,
    agent_mode: bool = False,
) -> RouteDecision:
    """
    ตัดสินใจว่าจะส่ง request ไปหา provider/model ไหน

    Args:
        prompt: ข้อความของ user
        provider_hint: "auto" | "ollama" | "gemini" | "lmstudio"
        has_image: มีรูปภาพแนบมาไหม
        agent_mode: เปิด agent mode ไหม
    """
    from core.config import (
        LMSTUDIO_CHAT_MODEL, LMSTUDIO_REASON_MODEL, LMSTUDIO_BASE_URL,
        OLLAMA_MODEL, GEMINI_API_KEY,
    )

    # ── Forced providers ────────────────────────────────────────────────────
    if has_image or agent_mode:
        return RouteDecision("gemini", "", Complexity.NORMAL,
                             "vision/agent → Gemini เสมอ")

    if provider_hint == "gemini":
        return RouteDecision("gemini", "", Complexity.NORMAL, "user เลือก Gemini")

    if provider_hint == "ollama":
        return RouteDecision("ollama", OLLAMA_MODEL, Complexity.NORMAL,
                             "user เลือก Ollama")

    if provider_hint == "lmstudio":
        return RouteDecision("lmstudio", LMSTUDIO_CHAT_MODEL, Complexity.NORMAL,
                             "user เลือก LM Studio")

    # ── Auto routing ────────────────────────────────────────────────────────
    complexity = classify(prompt)

    # ถ้า LM Studio ไม่ได้ตั้งค่า → fallback Ollama
    if not LMSTUDIO_BASE_URL:
        return RouteDecision("ollama", OLLAMA_MODEL, complexity,
                             "LM Studio ไม่ได้ตั้งค่า → fallback Ollama")

    if complexity == Complexity.REASONING:
        if LMSTUDIO_REASON_MODEL:
            return RouteDecision("lmstudio", LMSTUDIO_REASON_MODEL, complexity,
                                 f"reasoning → DeepSeek R1")
        # ถ้าไม่มี reason model → ใช้ chat model + CoT prompt
        return RouteDecision("lmstudio", LMSTUDIO_CHAT_MODEL, complexity,
                             "reasoning แต่ไม่มี reason model → chat + CoT")

    # simple/normal → chat model
    return RouteDecision("lmstudio", LMSTUDIO_CHAT_MODEL, complexity,
                         f"{complexity.value} → Llama 3.1")


def get_cot_prompt(complexity: Complexity) -> str:
    """Chain-of-Thought prompt สำหรับ model ที่ไม่มี native reasoning"""
    if complexity != Complexity.REASONING:
        return ""
    return (
        "\n\n[คำแนะนำ: คิดทีละขั้นก่อนตอบ — "
        "1) ทำความเข้าใจคำถาม "
        "2) วิเคราะห์ข้อมูลที่มี "
        "3) สรุปคำตอบที่ดีที่สุด]"
    )
