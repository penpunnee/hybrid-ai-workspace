"""Model Router — เลือก model ที่เหมาะสมตามประเภทคำถาม

Provider mapping:
  simple/normal  →  LM Studio chat model (Llama 3.1 — เร็ว)
  reasoning      →  LM Studio reason model (DeepSeek R1 — คิด)
  vision/agent   →  Gemini (cloud)
  ollama         →  Ollama fallback
"""
import logging
from dataclasses import dataclass

from core.env_registry import env_str

from .classifier import Complexity, classify

logger = logging.getLogger(__name__)

# ไฟล์นี้เป็นเจ้าของชื่อเดียว (ก้อน 4 · 2026-09-24) — เคยอ่านตอนเรียกทุกครั้ง ย้ายเป็นระดับโมดูล (env ใน prod นิ่ง ·
# เทส patch `router.CLAUDE_AUTO` แทน setenv) · ANTHROPIC_API_KEY/CLAUDE_MODEL เจ้าของ = utils.llm ·
# LMSTUDIO_API_KEY เจ้าของ = core.config (อ่าน "ค่าดิบ" ตอนเรียก — ดู `_lmstudio_headers`)
CLAUDE_AUTO = env_str("CLAUDE_AUTO", "off", group="Claude (Anthropic)", doc=(
    "ให้ provider=auto เลือก Claude — off | reasoning (เฉพาะคำถามยาก) | all (ทุก text) · ต้องมี ANTHROPIC_API_KEY\n"
    "internet/vision ยังไปทางเดิม (Claude ที่นี่ไม่มี web/search tool)")).lower()

_model_cache: dict[str, bool] = {}


def _lmstudio_headers() -> dict:
    """header สำหรับยิง LM Studio — แนบ Authorization ถ้าตั้ง LMSTUDIO_API_KEY
    (LM Studio รุ่นใหม่บังคับ token; ไม่งั้น probe 401 → auto-route หลบ lmstudio)"""
    headers = {"Content-Type": "application/json"}
    # แนบ Authorization เฉพาะเมื่อผู้ใช้ "ตั้งคีย์เอง" — อ่าน **ค่าดิบ** จาก config (เจ้าของ) ไม่ใช่
    # `LMSTUDIO_API_KEY` ที่ถอยไป placeholder "lmstudio" (ไฟล์ที่สร้าง client ต้องมีคีย์เสมอจึงใช้ตัวนั้น)
    # · import ตอนเรียกแบบเดียวกับ route() ⇒ เทส patch `core.config.LMSTUDIO_API_KEY_RAW` ได้
    from core.config import LMSTUDIO_API_KEY_RAW as key
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _is_model_available(base_url: str, model: str) -> bool:
    """ตรวจว่า model พร้อมใช้งานจริง (cache 60s)"""
    import time, urllib.request, json
    key = f"{base_url}:{model}"
    cached = _model_cache.get(key)
    if cached is not None and isinstance(cached, tuple):
        ok, ts = cached
        if time.time() - ts < 60:
            return ok

    try:
        req = urllib.request.Request(
            f"{base_url.rstrip('/v1').rstrip('/')}/v1/models",
            headers=_lmstudio_headers(),
        )
        resp = urllib.request.urlopen(req, timeout=3)
        data = json.loads(resp.read())
        available_ids = [m["id"] for m in data.get("data", [])]
        # ทดสอบจริงว่า load ได้ด้วยการ ping แบบสั้น
        ok = model in available_ids
        if ok:
            ok = _ping_model(base_url, model)
    except Exception:
        ok = False

    _model_cache[key] = (ok, time.time())
    logger.info(f"[Router] model check {model}: {'✅' if ok else '❌'}")
    return ok


def _ping_model(base_url: str, model: str) -> bool:
    """ส่ง request จริงเล็กๆ เพื่อตรวจว่า model load ได้"""
    import urllib.request, json
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1,
        "stream": False,
    }).encode()
    try:
        req = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=payload,
            headers=_lmstudio_headers(),
            method="POST",
        )
        urllib.request.urlopen(req, timeout=8)
        return True
    except Exception as e:
        logger.debug(f"[Router] ping {model} failed: {e}")
        return False


@dataclass
class RouteDecision:
    provider: str          # "lmstudio" | "gemini" | "ollama" | "claude"
    model: str             # ชื่อ model จริง
    complexity: Complexity
    reason: str            # เหตุผลที่เลือก (สำหรับ debug)


def route(
    prompt: str,
    provider_hint: str = "auto",
    has_image: bool = False,
    agent_mode: bool = False,
    exclude_gemini: bool = False,
) -> RouteDecision:
    """
    ตัดสินใจว่าจะส่ง request ไปหา provider/model ไหน

    Args:
        prompt: ข้อความของ user
        provider_hint: "auto" | "ollama" | "gemini" | "lmstudio"
        has_image: มีรูปภาพแนบมาไหม
        agent_mode: เปิด agent mode ไหม
        exclude_gemini: ห้ามเลือก Gemini/Gemini Agent เด็ดขาด — ใช้ตอน re-route
            หลัง Gemini เพิ่ง fail มา (quota/unavailable) กัน route() เลือก Gemini
            ซ้ำเพราะ GEMINI_API_KEY ยังตั้งอยู่ (แค่ quota หมด ไม่ใช่ key หาย)
    """
    from core.config import (
        LMSTUDIO_CHAT_MODEL, LMSTUDIO_REASON_MODEL, LMSTUDIO_VISION_MODEL,
        LMSTUDIO_BASE_URL, OLLAMA_MODEL, GEMINI_API_KEY,
    )

    # ── Forced providers ────────────────────────────────────────────────────
    if agent_mode and not exclude_gemini:
        return RouteDecision("gemini", "", Complexity.NORMAL, "agent mode → Gemini")

    # ── Internet search detection ─────────────────────────────────────────
    from reasoning.classifier import needs_internet
    if needs_internet(prompt):
        # Gemini Agent มี Google Search ในตัว — quality ดีกว่า DDG+Gemma มาก
        # ใช้ Gemini ก่อน fallback เป็น local+web search เมื่อไม่มี API key
        if GEMINI_API_KEY and not exclude_gemini:
            return RouteDecision("gemini_agent", "", Complexity.NORMAL,
                                 "🌐 internet search → Gemini Agent (Google Search)")
        if LMSTUDIO_BASE_URL and LMSTUDIO_CHAT_MODEL and _is_model_available(
            LMSTUDIO_BASE_URL, LMSTUDIO_CHAT_MODEL
        ):
            return RouteDecision("lmstudio_web", LMSTUDIO_CHAT_MODEL, Complexity.NORMAL,
                                 "🌐 web search → DDG + local (no Gemini key)")
        return RouteDecision("ollama", OLLAMA_MODEL, Complexity.NORMAL,
                             "🌐 no internet provider available → fallback")

    if has_image:
        # ใช้ vision model โดยเฉพาะถ้าพร้อม → ไม่ต้องใช้ Gemini
        vision_model = LMSTUDIO_VISION_MODEL or LMSTUDIO_CHAT_MODEL
        if LMSTUDIO_BASE_URL and vision_model and _is_model_available(
            LMSTUDIO_BASE_URL, vision_model
        ):
            return RouteDecision("lmstudio", vision_model, Complexity.NORMAL,
                                 f"vision → {vision_model.split('/')[-1]} (local)")
        if exclude_gemini:
            return RouteDecision("ollama", OLLAMA_MODEL, Complexity.NORMAL,
                                 "vision → Ollama (vision model + Gemini ทั้งคู่ใช้ไม่ได้)")
        return RouteDecision("gemini", "", Complexity.NORMAL, "vision → Gemini (vision model unavailable)")

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

    # Claude (opt-in) — CLAUDE_AUTO=reasoning ใช้ Claude เฉพาะคำถามยาก, =all ใช้ทุก text
    # ต้องมี ANTHROPIC_API_KEY. ปิด default → พฤติกรรมเดิมไม่เปลี่ยน + ไม่เปลือง cost เงียบๆ
    # หมายเหตุ: internet/vision ถูกจัดการไปก่อนหน้าแล้ว (Claude ที่นี่ไม่มี web/search tool)
    # คีย์/โมเดล Claude อ่าน attribute ของ utils.llm (เจ้าของ) ตอนเรียก (แบบเดียวกับ has_anthropic ใน
    # routers/system) — ไม่ import ระดับโมดูล เพราะ llm สร้าง client ตอน import (หนัก) และ router ถูกใช้
    # จาก dream/summarize ด้วย · ไม่ใช่เรื่อง cycle (ตรวจแล้ว llm import router เฉพาะในฟังก์ชัน)
    # · เทส patch `utils.llm.ANTHROPIC_API_KEY`/`CLAUDE_MODEL` ได้
    import utils.llm as _llm
    if _llm.ANTHROPIC_API_KEY and (
        CLAUDE_AUTO == "all"
        or (CLAUDE_AUTO == "reasoning" and complexity == Complexity.REASONING)
    ):
        return RouteDecision("claude", _llm.CLAUDE_MODEL, complexity,
                             f"{complexity.value} → Claude (CLAUDE_AUTO={CLAUDE_AUTO})")

    # ถ้า LM Studio ไม่ได้ตั้งค่า → fallback Ollama
    if not LMSTUDIO_BASE_URL:
        return RouteDecision("ollama", OLLAMA_MODEL, complexity,
                             "LM Studio ไม่ได้ตั้งค่า → fallback Ollama")

    if complexity == Complexity.REASONING:
        if LMSTUDIO_REASON_MODEL and _is_model_available(LMSTUDIO_BASE_URL, LMSTUDIO_REASON_MODEL):
            return RouteDecision("lmstudio", LMSTUDIO_REASON_MODEL, complexity,
                                 "reasoning → DeepSeek R1")
        # reason model ไม่พร้อม → chat model + CoT prompt
        chat_label = LMSTUDIO_CHAT_MODEL.split("/")[-1]
        return RouteDecision("lmstudio", LMSTUDIO_CHAT_MODEL, complexity,
                             f"reasoning → {chat_label} + CoT (DeepSeek unavailable)")

    # simple/normal → chat model
    chat_label = LMSTUDIO_CHAT_MODEL.split("/")[-1]
    return RouteDecision("lmstudio", LMSTUDIO_CHAT_MODEL, complexity,
                         f"{complexity.value} → {chat_label}")


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
