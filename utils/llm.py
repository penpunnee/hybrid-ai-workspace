"""
Utility module for LLM integration with Ollama (Local) and Gemini (Cloud)

Supports:
- Streaming responses from both providers
- Health check with caching
- Retry mechanism with exponential backoff
- Error classification and user-friendly messages
- Comprehensive logging

Configuration:
- OLLAMA_BASE_URL: Ollama server endpoint (default: http://localhost:11434/v1)
- OLLAMA_MODEL: Model to use (default: llama3)
- OLLAMA_TIMEOUT: Timeout in seconds (default: 120)
- OLLAMA_MAX_RETRIES: Number of retries (default: 2)
- OLLAMA_RETRY_DELAY: Initial retry delay in seconds (default: 2)
"""
import os, base64, time, logging
from openai import OpenAI
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()


class GeminiQuotaExhausted(Exception):
    """Raised เมื่อ Gemini quota หมด — ให้ caller ลอง fallback provider"""
    pass


class GeminiUnavailable(Exception):
    """Raised เมื่อ Gemini ไม่พร้อมใช้ (key ผิด, network, etc.)"""
    pass


class LMStudioUnavailable(Exception):
    """Raised เมื่อ LM Studio server ต่อไม่ได้ (PC ปิด/ยังไม่ Start Server)
    — ให้ caller cascade ไป Ollama ได้ (raise ก่อน yield chunk แรกเสมอ จึง cascade ปลอดภัย)"""
    pass


class ClaudeUnavailable(Exception):
    """Raised เมื่อ Claude (Anthropic) ไม่พร้อมใช้ (key ผิด / network)"""
    pass

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('server.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# --- Ollama (Local LLM) ---
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "120"))  # วินาที
OLLAMA_MAX_RETRIES = int(os.getenv("OLLAMA_MAX_RETRIES", "2"))  # จำนวนครั้งที่ retry
OLLAMA_RETRY_DELAY = int(os.getenv("OLLAMA_RETRY_DELAY", "2"))  # วินาที (initial delay)

ollama_client = OpenAI(
    base_url=OLLAMA_BASE_URL,
    api_key="ollama",
    timeout=OLLAMA_TIMEOUT,
)

# --- Gemini (Cloud LLM) ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
# โมเดล Gemini สำรองเมื่อตัวที่ขอ transient-fail (เช่น preview 3.1-flash-lite 503)
# default ว่าง = ไม่สลับโมเดล (retry-then-local) — กันเผา quota ตัวอื่นโดยไม่ตั้งใจ
# ตั้งเป็นตัว quota เยอะ (เช่น gemini-3.1-flash-lite) ถ้าอยากอยู่กับ Gemini ก่อนถอย local
GEMINI_FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "").strip()

gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# --- LM Studio (OpenAI-compatible local server) ---
# opt-in: default ว่าง — ถ้าไม่ตั้ง LMSTUDIO_BASE_URL จะไม่ถูกใช้ (local หลักคือ Ollama)
_LMSTUDIO_BASE_URL = os.getenv("LMSTUDIO_BASE_URL", "")
_LMSTUDIO_TIMEOUT  = int(os.getenv("LMSTUDIO_TIMEOUT", "180"))
# LM Studio รุ่นใหม่บังคับ API token — ตั้ง LMSTUDIO_API_KEY ให้ตรง (default dummy)
_LMSTUDIO_API_KEY  = os.getenv("LMSTUDIO_API_KEY", "lmstudio")

# client สร้างไว้เสมอ แต่จะถูกเรียกเฉพาะเมื่อ provider="lmstudio" เท่านั้น
# ถ้า base_url ว่าง ใช้ localhost (ถ้าเผลอเรียกจะ refuse แบบ clean ไม่ leak ไป api.openai.com)
lmstudio_client = OpenAI(
    base_url=_LMSTUDIO_BASE_URL or "http://localhost:1234/v1",
    api_key=_LMSTUDIO_API_KEY,
    timeout=_LMSTUDIO_TIMEOUT,
)

# --- Claude (Anthropic Cloud LLM) ---
# opt-in: ตั้ง ANTHROPIC_API_KEY ใน .env ถึงจะใช้ได้ (provider="claude")
try:
    import anthropic
except ImportError:          # ยังไม่ได้ pip install — provider claude จะแจ้ง error ชัดเจน
    anthropic = None

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL      = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")   # คุ้มกว่า opus; เปลี่ยนเป็น claude-opus-4-8 ถ้าอยากฉลาดสุด
CLAUDE_MAX_TOKENS = int(os.getenv("CLAUDE_MAX_TOKENS", "4096"))      # เพดานความยาวคำตอบ = คุม cost
# adaptive thinking: ปิดเป็น default เพื่อความเร็วของแชต — ตั้ง CLAUDE_THINKING=adaptive ถ้าอยากให้คิดลึก
CLAUDE_THINKING   = os.getenv("CLAUDE_THINKING", "off").lower()
CLAUDE_EFFORT     = os.getenv("CLAUDE_EFFORT", "high").lower()   # low|medium|high|xhigh|max (ใช้คู่ adaptive)

anthropic_client = (
    anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    if anthropic and ANTHROPIC_API_KEY else None
)

# --- Kimi (Moonshot Cloud LLM — OpenAI compatible) ---
# opt-in: ตั้ง MOONSHOT_API_KEY ใน .env ถึงจะใช้ได้ (provider="kimi")
MOONSHOT_API_KEY = os.getenv("MOONSHOT_API_KEY", "")
KIMI_BASE_URL    = os.getenv("KIMI_BASE_URL", "https://api.moonshot.ai/v1")
KIMI_MODEL       = os.getenv("KIMI_MODEL", "kimi-k2.6")
KIMI_TIMEOUT     = int(os.getenv("KIMI_TIMEOUT", "180"))

kimi_client = (
    OpenAI(base_url=KIMI_BASE_URL, api_key=MOONSHOT_API_KEY, timeout=KIMI_TIMEOUT)
    if MOONSHOT_API_KEY else None
)


# map effort slider → Gemini thinking_budget (token งบสำหรับคิด)
_GEMINI_EFFORT_BUDGET = {
    "low": 2048, "medium": 8192, "high": 16384, "xhigh": 24576, "max": 32768,
}

_last_failover: dict = {"active": False}  # track failover state
_health_cache: dict = {"ok": None, "ts": 0.0, "msg": ""}  # cache health check 30s


def stream_response(messages: list[dict], provider: str = "auto",
                    image_b64: str = "", image_mime: str = "",
                    agent_mode: bool = False, model_override: str = "",
                    thinking: bool | None = None, effort: str = "",
                    web_grounding: bool = False, sources_sink: list | None = None,
                    usage_sink: dict | None = None):
    """
    Stream response จาก LLM ที่เลือก
    provider: 'ollama' | 'gemini' | 'lmstudio' | 'kimi' | 'claude' | 'auto'
    model_override: ใช้ model นี้แทน default (per-request จาก dropdown / router)
    thinking: เปิด/ปิดโหมดคิด (None = ใช้ค่า default ของ provider — ไม่ override)
    effort: ระดับการคิดเมื่อ thinking เปิด (low|medium|high|xhigh|max; "" = ใช้ default)
    usage_sink: dict ที่ provider จะเติม {"input_tokens","output_tokens"} จริง
      (out-param แพทเทิร์นเดียวกับ sources_sink — generator yield ได้แต่ str)
      ไม่ได้เติม = provider ไม่รายงาน ให้ผู้เรียกถอยไปใช้ค่าประมาณเอง
    """
    if provider == "gemini_agent":
        _last_failover["active"] = False
        yield from _stream_gemini(messages, image_b64, image_mime, agent_mode=True,
                                  model=model_override, thinking=thinking, effort=effort,
                                  usage_sink=usage_sink)
        return

    # Claude ต้องมาก่อน gemini catch-all — Claude จัดการ vision ของตัวเอง
    if provider in ("claude", "claude_agent"):
        _last_failover["active"] = False
        yield from _stream_claude(messages, image_b64, image_mime,
                                  model=model_override, thinking=thinking, effort=effort,
                                  usage_sink=usage_sink)
        return

    if provider == "kimi":
        _last_failover["active"] = False
        yield from _stream_kimi(messages, model=model_override, thinking=thinking,
                                effort=effort, image_b64=image_b64, image_mime=image_mime,
                                usage_sink=usage_sink)
        return

    if provider == "gemini" or agent_mode or (image_b64 and provider not in ("lmstudio", "auto", "claude", "claude_agent")):
        _last_failover["active"] = False
        yield from _stream_gemini(messages, image_b64, image_mime, agent_mode=agent_mode,
                                  model=model_override, thinking=thinking, effort=effort,
                                  web_grounding=web_grounding, sources_sink=sources_sink,
                                  usage_sink=usage_sink)
        return

    if provider in ("lmstudio", "lmstudio_web"):
        _last_failover["active"] = False
        yield from _stream_lmstudio_or_ollama(messages, model=model_override,
                                              image_b64=image_b64, image_mime=image_mime,
                                              usage_sink=usage_sink)
        return

    # provider == "ollama" → ใช้ Ollama เสมอ (ไม่ redirect ไป LM Studio อีกต่อไป)
    # ปุ่มแยกชัด: Ollama=Ollama, LM Studio=LM Studio, Gemini=Gemini
    if provider == "auto":
        # ดึงจาก reasoning router
        try:
            from reasoning.router import route
            from reasoning.parser import stream_with_thinking
            prompt = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
            decision = route(prompt, provider_hint="auto",
                             has_image=bool(image_b64), agent_mode=agent_mode)
            logger.info(f"[AutoRoute] {decision.reason} | model={decision.model}")
            if decision.provider in ("gemini", "gemini_agent"):
                use_agent = agent_mode or decision.provider == "gemini_agent"
                yield from _stream_gemini(messages, image_b64, image_mime, agent_mode=use_agent)
            elif decision.provider == "lmstudio":
                show = os.getenv("SHOW_THINKING", "false").lower() == "true"
                try:
                    raw_chunks = _stream_lmstudio(messages, model=decision.model,
                                                  image_b64=image_b64, image_mime=image_mime)
                    yield from stream_with_thinking(raw_chunks, show_thinking=show)
                except LMStudioUnavailable as e:
                    if image_b64:
                        yield (f"❌ เชื่อมต่อ LM Studio ไม่ได้ ({_LMSTUDIO_BASE_URL}) — "
                               f"โหมดรูปภาพใช้ Ollama แทนไม่ได้ กรุณาเปิด PC + Start Server")
                    else:
                        logger.warning(f"LM Studio ต่อไม่ได้ → cascade ไป Ollama ({e})")
                        yield "⚠️ LM Studio ต่อไม่ได้ — สลับไป Ollama ให้อัตโนมัติ\n\n"
                        yield from _stream_ollama(messages)
            else:
                yield from _stream_ollama(messages)
        except Exception as e:
            logger.warning(f"Auto-route failed ({e}), fallback ollama")
            yield from _stream_ollama(messages)
        return

    _last_failover["active"] = False
    yield from _stream_ollama(messages, model=model_override, usage_sink=usage_sink)


# ── token usage จริงจาก provider (2026-08-12) ────────────────────────────────
# OpenAI-compatible ทุกตัว (LM Studio/Ollama/Kimi): stream_options.include_usage
# → chunk ท้ายมี usage แต่ choices=[] — loop เดิม chunk.choices[0] จะ IndexError
# จึงต้อง guard choices ว่างทุกจุดที่เปิดฟีเจอร์นี้

def _capture_openai_usage(chunk, usage_sink: dict | None) -> None:
    """เก็บ usage จาก chunk (มีเฉพาะ chunk ท้ายเมื่อเปิด include_usage)"""
    if usage_sink is None:
        return
    u = getattr(chunk, "usage", None)
    if u is None:
        return
    it, ot = getattr(u, "prompt_tokens", None), getattr(u, "completion_tokens", None)
    if it is not None or ot is not None:
        usage_sink["input_tokens"] = int(it or 0)
        usage_sink["output_tokens"] = int(ot or 0)


def _create_stream_with_usage(completions_create, create_kwargs: dict, want_usage: bool):
    """create() พร้อมขอ usage — เซิร์ฟเวอร์เก่าที่ไม่รู้จัก stream_options ให้ retry
    แบบไม่ขอ (คำตอบต้องมาก่อนตัวเลขสถิติ) · error เกิดที่ create() ก่อน chunk แรกเสมอ
    จึง retry ได้โดยไม่เสี่ยง yield ซ้ำ"""
    if not want_usage:
        return completions_create(**create_kwargs)
    try:
        return completions_create(**create_kwargs, stream_options={"include_usage": True})
    except Exception as e:
        if "stream_options" not in str(e).lower():
            raise
        logger.info("[LLM] เซิร์ฟเวอร์ไม่รู้จัก stream_options → ขอใหม่แบบไม่มี usage")
        return completions_create(**create_kwargs)


def _stream_lmstudio(messages: list[dict], model: str = "",
                     image_b64: str = "", image_mime: str = "",
                     usage_sink: dict | None = None):
    """Stream จาก LM Studio (OpenAI-compatible API) รองรับ vision"""
    if not model:
        model = os.getenv("LMSTUDIO_CHAT_MODEL", "meta-llama-3.2-11b-vision-instruct")

    # ถ้าใน system message มี grounded context → ลด temperature เพื่อให้ ground
    # (ป้องกัน hallucinate เพิ่มเติมจากความจำ model)
    sys_content = next((m["content"] for m in messages if m["role"] == "system"), "")
    is_grounded = any(k in sys_content for k in
                      ("INTERNET CONTEXT", "Wikipedia", "wttr.in", "ข้อมูลล่าสุดจากอินเตอร์เน็ต"))
    if is_grounded:
        temperature = 0.2
        logger.info("[LMStudio] grounded context detected → temp=0.2")
    else:
        temperature = float(os.getenv("OLLAMA_TEMPERATURE", "0.7"))

    # ถ้ามีรูป → แทรก image content เข้าไปใน user message ล่าสุด
    if image_b64:
        msgs = []
        for i, m in enumerate(messages):
            if m["role"] == "user" and i == len(messages) - 1:
                msgs.append({
                    "role": "user",
                    "content": [
                        {"type": "text", "text": m["content"]},
                        {"type": "image_url", "image_url": {
                            "url": f"data:{image_mime or 'image/jpeg'};base64,{image_b64}"
                        }},
                    ],
                })
            else:
                msgs.append(m)
    else:
        msgs = messages

    try:
        stream = _create_stream_with_usage(
            lmstudio_client.chat.completions.create,
            {"model": model, "messages": msgs, "stream": True, "temperature": temperature},
            want_usage=usage_sink is not None,
        )
        for chunk in stream:
            _capture_openai_usage(chunk, usage_sink)
            if not chunk.choices:
                continue  # chunk ท้ายจาก include_usage — มีแต่ตัวเลข ไม่มีข้อความ
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
        logger.info(f"LM Studio stream OK (model={model}, vision={'yes' if image_b64 else 'no'})")
    except Exception as e:
        err = str(e).lower()
        if "connection" in err or "refused" in err or "connect" in err:
            # raise แทน yield → ให้ caller (stream_response) cascade ไป Ollama ได้
            # connection error เกิดที่ create() ก่อน yield chunk แรกเสมอ → cascade ปลอดภัย
            logger.warning(f"LM Studio connection failed ({_LMSTUDIO_BASE_URL}): {e}")
            raise LMStudioUnavailable(str(e)) from e
        elif "model" in err or "not found" in err:
            yield f"❌ ไม่พบ model `{model}` ใน LM Studio — ตรวจสอบว่าโหลดแล้ว"
        elif "resources" in err or "memory" in err:
            yield f"❌ RAM/VRAM ไม่พอสำหรับ `{model}` — ลอง quantization ต่ำกว่านี้"
        else:
            logger.error(f"LM Studio error: {e}")
            yield f"❌ LM Studio error: {e}"


def _stream_lmstudio_or_ollama(messages: list[dict], model: str = "",
                               image_b64: str = "", image_mime: str = "",
                               usage_sink: dict | None = None):
    """LM Studio ก่อน; ถ้า server ต่อไม่ได้ (connection) → cascade ไป Ollama อัตโนมัติ

    ยกเว้นโหมดรูปภาพ — Ollama (llama3) ดูรูปไม่ได้ → แจ้ง error ตรงๆ ดีกว่า cascade เงียบๆ
    """
    try:
        yield from _stream_lmstudio(messages, model=model,
                                    image_b64=image_b64, image_mime=image_mime,
                                    usage_sink=usage_sink)
    except LMStudioUnavailable as e:
        if image_b64:
            yield (f"❌ เชื่อมต่อ LM Studio ไม่ได้ ({_LMSTUDIO_BASE_URL}) — "
                   f"โหมดรูปภาพใช้ Ollama แทนไม่ได้ (ดูรูปไม่ได้) "
                   f"กรุณาเปิด PC + Start Server")
            return
        logger.warning(f"LM Studio ต่อไม่ได้ → cascade ไป Ollama อัตโนมัติ ({e})")
        yield "⚠️ LM Studio ต่อไม่ได้ — สลับไป Ollama ให้อัตโนมัติ\n\n"
        yield from _stream_ollama(messages, usage_sink=usage_sink)


def check_ollama_health(force: bool = False) -> tuple[bool, str]:
    """
    ตรวจสอบสุขภาพของ Ollama server
    
    Logic:
    1. ตรวจสอบ cache (30 วินาที) เพื่อลดภาระการเช็คซ้ำ
    2. เชื่อมต่อกับ /api/tags เพื่อตรวจว่า Ollama รันอยู่
    3. ดึงรายชื่อ models ทั้งหมด
    4. ตรวจสอบว่า OLLAMA_MODEL ที่ตั้งค่าไว้มีอยู่จริงหรือไม่
    5. คืนค่า (ok, message) โดย message จะมีรายละเอียดเมื่อ error
    
    Args:
        force: บังคับให้เช็คใหม่โดยไม่สนใจ cache
    
    Returns:
        tuple[bool, str]: (สถานะ ok, error message)
    """
    import urllib.request, time, json
    if not force and _health_cache["ok"] is not None:
        if time.time() - _health_cache["ts"] < 30:
            return _health_cache["ok"], _health_cache.get("msg", "")
    try:
        base = OLLAMA_BASE_URL.replace("/v1", "")
        # ตรวจสอบว่า Ollama service รันอยู่
        response = urllib.request.urlopen(f"{base}/api/tags", timeout=8)
        data = json.loads(response.read().decode())
        
        # ตรวจสอบว่า model ที่ตั้งค่ามีอยู่จริงหรือไม่
        models = data.get("models", [])
        model_names = [m.get("name", "").split(":")[0] for m in models]
        
        if OLLAMA_MODEL not in model_names:
            msg = (
                f"❌ Model `{OLLAMA_MODEL}` ไม่พบใน Ollama\n\n"
                f"Models ที่มีอยู่: {', '.join(model_names[:5])}\n"
                f"กรุณา pull model ด้วยคำสั่ง:\n```\nollama pull {OLLAMA_MODEL}\n```"
            )
            logger.error(f"Ollama model not found: {OLLAMA_MODEL} (available: {model_names[:5]})")
            _health_cache["ok"] = False
            _health_cache["ts"] = time.time()
            _health_cache["msg"] = msg
            return False, msg
        
        _health_cache["ok"] = True
        _health_cache["ts"] = time.time()
        _health_cache["msg"] = ""
        return True, ""
    except urllib.error.URLError as e:
        msg = (
            f"❌ ไม่สามารถเชื่อมต่อ Ollama ได้ ({e.reason})\n\n"
            f"กรุณาเปิด Ollama ก่อนด้วยคำสั่ง:\n```\nollama serve\n```\n"
            f"หรือตรวจสอบ OLLAMA_BASE_URL ใน .env: {OLLAMA_BASE_URL}"
        )
        logger.error(f"Ollama connection error: {e.reason} (URL: {OLLAMA_BASE_URL})")
        _health_cache["ok"] = False
        _health_cache["ts"] = time.time()
        _health_cache["msg"] = msg
        return False, msg
    except Exception as e:
        msg = f"❌ Ollama health check error: {str(e)}"
        logger.error(f"Ollama health check error: {str(e)}")
        _health_cache["ok"] = False
        _health_cache["ts"] = time.time()
        _health_cache["msg"] = msg
        return False, msg


_lm_health_cache: dict = {"ok": None, "ts": 0.0, "msg": ""}  # cache 30s แบบเดียวกับ ollama


def check_lmstudio_health(force: bool = False) -> tuple[bool, str]:
    """ตรวจสุขภาพ LM Studio (local หลักตอนนี้ = DeepSeek R1 ผ่าน LM Studio)

    GET {LMSTUDIO_BASE_URL}/models พร้อม Bearer LMSTUDIO_API_KEY
    - ไม่ได้ตั้ง LMSTUDIO_BASE_URL → (False, แจ้งยังไม่ตั้งค่า)
    - ตอบ 200 + มี model → (True, "")
    - ตอบ 200 แต่ list ว่าง = ไม่มี model โหลด/JIT → (False, ...)
    - ต่อไม่ได้/token ผิด → (False, ...)
    """
    import urllib.request, time, json
    if not _LMSTUDIO_BASE_URL:
        return False, "ยังไม่ได้ตั้งค่า LMSTUDIO_BASE_URL ใน .env"
    if not force and _lm_health_cache["ok"] is not None:
        if time.time() - _lm_health_cache["ts"] < 30:
            return _lm_health_cache["ok"], _lm_health_cache.get("msg", "")

    def _save(ok: bool, msg: str) -> tuple[bool, str]:
        _lm_health_cache["ok"] = ok
        _lm_health_cache["ts"] = time.time()
        _lm_health_cache["msg"] = msg
        return ok, msg

    try:
        req = urllib.request.Request(
            f"{_LMSTUDIO_BASE_URL.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {_LMSTUDIO_API_KEY}"},
        )
        response = urllib.request.urlopen(req, timeout=8)
        data = json.loads(response.read().decode())
        models = [m.get("id", "") for m in data.get("data", [])]
        if not models:
            msg = "❌ LM Studio รันอยู่แต่ไม่มี model โหลด — เปิด model ใน LM Studio ก่อน"
            logger.warning("LM Studio health: no models loaded")
            return _save(False, msg)
        return _save(True, "")
    except Exception as e:
        msg = (f"❌ เชื่อมต่อ LM Studio ไม่ได้ ({e}) — "
               f"ตรวจสอบว่า PC เปิด + LM Studio Start Server ({_LMSTUDIO_BASE_URL})")
        logger.error(f"LM Studio health check error: {e}")
        return _save(False, msg)


def _stream_ollama(messages: list[dict], model: str = "", usage_sink: dict | None = None):
    """
    Stream จาก Ollama local พร้อม retry mechanism และ error handling ที่ละเอียด
    
    Logic:
    1. Loop retry สูงสุด OLLAMA_MAX_RETRIES ครั้ง (default: 2)
    2. ในแต่ละ attempt:
       - เชื่อมต่อกับ Ollama ด้วย timeout OLLAMA_TIMEOUT
       - Stream response ทีละ chunk
       - ถ้าสำเร็จ ให้ log และ return
    3. Error Classification:
       - Model not found: ไม่ retry (จะไม่สำเร็จอยู่ดี)
       - Timeout: retry พร้อม exponential backoff (2s, 4s)
       - Connection error: retry พร้อม exponential backoff (2s, 4s)
       - อื่นๆ: ไม่ retry และแสดง error
    4. แสดงสถานะ retry ให้ user เห็นเฉพาะครั้งแรก
    5. เมื่อ retry ครบแล้วยังไม่สำเร็จ แสดง error message ที่ชัดเจน
    
    Args:
        messages: รายการ messages สำหรับ chat
    
    Yields:
        str: ข้อความ response ทีละ chunk หรือ error message
    """
    max_retries = OLLAMA_MAX_RETRIES
    retry_delay = OLLAMA_RETRY_DELAY
    model = model or OLLAMA_MODEL

    for attempt in range(max_retries):
        try:
            stream = _create_stream_with_usage(
                ollama_client.chat.completions.create,
                {
                    "model": model,
                    "messages": messages,
                    "stream": True,
                    "timeout": OLLAMA_TIMEOUT,
                    "temperature": float(os.getenv("OLLAMA_TEMPERATURE", "0.7")),
                    "top_p": float(os.getenv("OLLAMA_TOP_P", "0.85")),
                    "extra_body": {
                        "options": {
                            "num_ctx": int(os.getenv("OLLAMA_NUM_CTX", "4096")),
                            "repeat_penalty": float(os.getenv("OLLAMA_REPEAT_PENALTY", "1.1")),
                        }
                    },
                },
                want_usage=usage_sink is not None,
            )
            for chunk in stream:
                _capture_openai_usage(chunk, usage_sink)
                if not chunk.choices:
                    continue  # chunk ท้ายจาก include_usage
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
            logger.info(f"Ollama stream successful (model: {model})")
            return  # Success - exit retry loop
        except Exception as e:
            err_str = str(e).lower()

            # ถ้าเป็น model not found error ไม่ต้อง retry (จะไม่สำเร็จอยู่ดี)
            if "model" in err_str or "not found" in err_str:
                logger.error(f"Ollama model not found: {model} - {str(e)}")
                yield (
                    f"❌ Model `{model}` ไม่พบใน Ollama\n\n"
                    f"กรุณา pull model ด้วยคำสั่ง:\n"
                    f"```bash\nollama pull {model}\n```\n"
                    f"หรือตรวจสอบรายชื่อ model ที่มี:\n"
                    f"```bash\nollama list\n```"
                )
                return
            
            # ถ้าเป็น timeout error และยังมี retry อยู่ ให้ retry
            if "timeout" in err_str and attempt < max_retries - 1:
                logger.warning(f"Ollama timeout (attempt {attempt + 1}/{max_retries}), retrying...")
                if attempt == 0:
                    yield f"⏳ Ollama timeout กำลังลองใหม่ ({attempt + 1}/{max_retries})...\n"
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
                continue
            
            # ถ้าเป็น connection error และยังมี retry อยู่ ให้ retry
            if ("connection" in err_str or "refused" in err_str or "connect" in err_str) and attempt < max_retries - 1:
                logger.warning(f"Ollama connection error (attempt {attempt + 1}/{max_retries}), retrying... - {str(e)}")
                if attempt == 0:
                    yield f"⏳ ไม่สามารถเชื่อมต่อ Ollama ได้ กำลังลองใหม่ ({attempt + 1}/{max_retries})...\n"
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
                continue
            
            # ถ้า retry ครบแล้วหรือ error อื่นๆ ให้แสดง error message
            if "connection" in err_str or "refused" in err_str or "connect" in err_str:
                logger.error(f"Ollama connection failed after {max_retries} retries: {str(e)}")
                yield (
                    f"❌ ไม่สามารถเชื่อมต่อ Ollama ได้ (ลอง {max_retries} ครั้งแล้ว)\n\n"
                    f"กรุณาตรวจสอบว่า Ollama กำลังรันอยู่:\n"
                    f"```bash\nollama serve\n```\n"
                    f"หรือตรวจสอบ OLLAMA_BASE_URL ใน .env: {OLLAMA_BASE_URL}"
                )
            elif "timeout" in err_str:
                logger.error(f"Ollama timeout after {max_retries} retries: {str(e)}")
                yield (
                    f"❌ Ollama timeout - การตอบสนองช้าเกินไป (ลอง {max_retries} ครั้งแล้ว)\n\n"
                    f"ลองใหม่อีกครั้ง หรือลดความยาวของข้อความ\n"
                    f"หรือเพิ่ม OLLAMA_TIMEOUT ใน .env (ปัจจุบัน: {OLLAMA_TIMEOUT} วินาที)"
                )
            else:
                logger.error(f"Ollama stream error after {max_retries} retries: {str(e)}")
                yield f"❌ Ollama error (ลอง {max_retries} ครั้งแล้ว): {e}"
            return


def _extract_grounding_sources(candidate) -> list[dict]:
    """ดึงแหล่งอ้างอิงจาก grounding_metadata ของ Gemini response → shape ที่
    citations.add_web_results ใช้ได้ (title/href/body). pure + ทนทุก field หาย"""
    out: list[dict] = []
    gm = getattr(candidate, "grounding_metadata", None)
    if not gm:
        return out
    for ch in (getattr(gm, "grounding_chunks", None) or []):
        web = getattr(ch, "web", None)
        if not web:
            continue
        uri = getattr(web, "uri", "") or ""
        title = getattr(web, "title", "") or ""
        if uri:
            out.append({"title": title or uri, "href": uri, "body": title or uri})
    return out


def gemini_web_search(query: str, model: str = "") -> tuple[str, list[dict]]:
    """ค้นเว็บด้วย Gemini + Google Search grounding (Google จริง) แล้วคืน (สรุป, แหล่ง)
    ให้โมเดลอื่น (local/Claude/Kimi) เอาไป inject — แทน DDG. คืน ("", []) ถ้า Gemini ไม่พร้อม/ล้ม.
    ⚠️ กิน Gemini quota ต่อการค้น 1 ครั้ง (ตั้ง GEMINI_SEARCH_MODEL เป็นตัว quota สูงได้)"""
    if not gemini_client:
        return "", []
    try:
        prompt = (
            f"ค้นข้อมูลล่าสุดจากอินเทอร์เน็ตเกี่ยวกับ: {query}\n"
            "สรุปข้อเท็จจริงที่เกี่ยวข้องเป็นภาษาไทยสั้นๆ ตรงประเด็น เน้นตัวเลข/วันที่/ชื่อที่เป็น"
            "ข้อมูลจริง ห้ามแต่ง ถ้าไม่พบให้บอกว่าไม่พบ"
        )
        cfg = types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())])
        search_model = model or os.getenv("GEMINI_SEARCH_MODEL", "") or GEMINI_MODEL
        resp = gemini_client.models.generate_content(model=search_model, contents=prompt, config=cfg)
        text = (getattr(resp, "text", "") or "").strip()
        cands = getattr(resp, "candidates", None) or []
        results = _extract_grounding_sources(cands[0]) if cands else []
        if text:
            logger.info(f"[gemini_web_search] grounded {len(text)} chars, {len(results)} sources (model={search_model})")
        return text, results
    except Exception as e:
        logger.warning(f"[gemini_web_search] {type(e).__name__}: {e}")
        return "", []


def _stream_gemini(messages: list[dict], image_b64: str = "", image_mime: str = "",
                   agent_mode: bool = False, model: str = "",
                   thinking: bool | None = None, effort: str = "",
                   web_grounding: bool = False, sources_sink: list | None = None,
                   usage_sink: dict | None = None):
    """
    Stream จาก Gemini Cloud ด้วย google-genai SDK ใหม่

    sources_sink: list ที่จะถูกเติมด้วยแหล่งอ้างอิงจาก grounding_metadata (ถ้ามี)
    — generator yield ได้แต่ str จึงต้องส่งออกทาง out-param (แพทเทิร์นเดียวกับ
    citations accumulator ใน routers/chat.py) ไม่ส่งมา = ไม่เก็บ (backward compat)

    Logic:
    1. ตรวจสอบว่า gemini_client ถูก initialize หรือไม่
    2. แยก system prompt ออกจาก messages
    3. แปลง messages เป็น format ของ Gemini (Content และ Part)
    4. ถ้ามีรูปภาพ (image_b64): ใส่เข้าไปใน user message ล่าสุด
    5. ถ้า agent_mode=True: เปิดใช้ tools (Google Search, Code Execution)
    6. เรียก generate_content_stream พร้อม config
    7. Stream response ทีละ chunk
    8. Error Classification:
       - API key invalid: แจ้งให้ตรวจสอบ .env
       - Quota exceeded: แจ้งให้รอหรือเปลี่ยนใช้ local LLM
       - อื่นๆ: แสดง error message
    
    Args:
        messages: รายการ messages สำหรับ chat
        image_b64: รูปภาพใน base64 (optional)
        image_mime: MIME type ของรูปภาพ (optional)
        agent_mode: เปิดใช้ Agent Mode (Google Search + Code Execution)
    
    Yields:
        str: ข้อความ response ทีละ chunk หรือ error message
    """
    if not gemini_client:
        logger.error("Gemini client not initialized (GEMINI_API_KEY not set)")
        yield (
            "⚠️ ยังไม่ได้ตั้งค่า GEMINI_API_KEY\n\n"
            "เปิดไฟล์ `.env` แล้วใส่:\n```\nGEMINI_API_KEY=your_key_here\n```\n"
            "ขอ key ได้ฟรีที่ https://aistudio.google.com/"
        )
        return

    try:
        system_prompt = next((m["content"] for m in messages if m["role"] == "system"), None)
        history = []
        for m in messages:
            if m["role"] == "system":
                continue
            role = "user" if m["role"] == "user" else "model"
            # coerce content เป็น str — content ที่เป็น list/dict ทำ types.Part crash ด้วย
            # pydantic "valid part type" (None ผ่านได้ แต่ list/dict ไม่ผ่าน)
            c = m.get("content")
            text = c if isinstance(c, str) else ("" if c is None else str(c))
            history.append(types.Content(role=role, parts=[types.Part(text=text)]))

        # ถ้ามีรูปภาพ ใส่เข้าไปใน parts ของ user message ล่าสุด
        if image_b64 and history and history[-1].role == "user":
            img_bytes = base64.b64decode(image_b64)
            last = history[-1]
            history[-1] = types.Content(
                role="user",
                parts=list(last.parts) + [types.Part(inline_data=types.Blob(data=img_bytes, mime_type=image_mime or "image/jpeg"))]
            )

        tools = None
        if agent_mode:
            tools = [
                types.Tool(google_search=types.GoogleSearch()),
                types.Tool(code_execution=types.ToolCodeExecution()),
            ]
        elif web_grounding:
            # คำถาม real-time → ใช้ Google Search grounding ในตัว Gemini (real Google)
            # เฉพาะ search ไม่เปิด code_execution
            tools = [types.Tool(google_search=types.GoogleSearch())]

        use_model = model or GEMINI_MODEL
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=tools,
        )
        # thinking toggle (Gemini 3/2.5): None = ไม่แตะ (default ของโมเดล)
        # ปิด = thinking_budget 0 · เปิด = budget ตาม effort. guard: SDK เก่าอาจไม่มี ThinkingConfig
        if thinking is not None:
            try:
                budget = 0 if not thinking else _GEMINI_EFFORT_BUDGET.get(effort, 8192)
                config.thinking_config = types.ThinkingConfig(thinking_budget=budget)
            except Exception as te:
                logger.warning(f"[Gemini] thinking_config ไม่รองรับ ({te}) — ข้าม")
        # transient (503/500/UNAVAILABLE/INTERNAL ฯลฯ) = Google ล่มชั่วคราว
        # ห้ามนับ 429/quota/key-invalid เป็น transient — ปล่อยให้ except ชั้นนอก classify
        _TRANSIENT = ("503", "500", "unavailable", "internal", "deadline", "overloaded", "try again")
        _MAX_ATTEMPTS = 3

        def _is_transient(exc):
            s = str(exc).lower()
            return (any(t in s for t in _TRANSIENT) and "429" not in s and "quota" not in s
                    and "resource_exhausted" not in s and "api_key_invalid" not in s)

        # ลองตามลำดับ: โมเดลที่ขอ → Gemini สำรอง (GEMINI_FALLBACK_MODEL) ก่อนถอย local
        # default GEMINI_FALLBACK_MODEL ว่าง = ไม่สลับ (retry-then-local) — กันเผา quota
        # ตัวอื่นโดยไม่ตั้งใจ (เคยตั้งเป็น GEMINI_MODEL=2.5-flash ซึ่ง quota/วันต่ำ → ผิด)
        _models = [use_model] + ([GEMINI_FALLBACK_MODEL]
                                 if GEMINI_FALLBACK_MODEL and GEMINI_FALLBACK_MODEL != use_model else [])
        yielded = False
        for _mi, _mdl in enumerate(_models):
            _has_next = _mi < len(_models) - 1
            try:
                for _attempt in range(_MAX_ATTEMPTS):
                    try:
                        response = gemini_client.models.generate_content_stream(
                            model=_mdl,
                            contents=history,
                            config=config,
                        )
                        for chunk in response:
                            if chunk.text:
                                yielded = True
                                yield chunk.text
                            # usage_metadata มากับ chunk ท้ายๆ เช่นกัน — เก็บชุดล่าสุดที่มีตัวเลข
                            if usage_sink is not None:
                                um = getattr(chunk, "usage_metadata", None)
                                pt = getattr(um, "prompt_token_count", None) if um else None
                                ct = getattr(um, "candidates_token_count", None) if um else None
                                if pt is not None or ct is not None:
                                    usage_sink["input_tokens"] = int(pt or 0)
                                    usage_sink["output_tokens"] = int(ct or 0)
                            # grounding_metadata มักมากับ chunk ท้ายๆ — เก็บทุกครั้งที่เจอ
                            # (เก็บชุดล่าสุดที่ไม่ว่าง) เพื่อส่งออกเป็น citation ให้ผู้ใช้
                            # ตรวจสอบที่มาของตัวเลขได้ — ไม่งั้น Gemini = เส้นที่แม่นสุด
                            # แต่ตรวจสอบไม่ได้เลย (audit 2026-08-02)
                            if sources_sink is not None:
                                try:
                                    for cand in (getattr(chunk, "candidates", None) or []):
                                        found = _extract_grounding_sources(cand)
                                        if found:
                                            sources_sink.clear()
                                            sources_sink.extend(found)
                                except Exception as ge:
                                    logger.debug(f"[Gemini] grounding extract skipped: {ge}")
                        logger.info(f"Gemini stream successful (model: {_mdl}, agent_mode: {agent_mode}, thinking: {thinking})")
                        return
                    except Exception as se:
                        # retry โมเดลเดิม เฉพาะ transient + ยังไม่ yield (กัน duplicate กลาง stream)
                        if _is_transient(se) and not yielded and _attempt < _MAX_ATTEMPTS - 1:
                            logger.warning(f"[Gemini] {_mdl} transient ({str(se)[:70]}) — retry {_attempt+1}/{_MAX_ATTEMPTS-1}")
                            time.sleep(0.6 * (_attempt + 1))
                            continue
                        raise
            except Exception as me:
                # หมด retry ของ _mdl — ถ้า transient + ยังไม่ yield + มีตัวเสถียรให้ลอง → สลับโมเดล
                if _is_transient(me) and not yielded and _has_next:
                    logger.warning(f"[Gemini] {_mdl} ล่ม (transient) → สลับไป {_models[_mi+1]} ก่อนถอย local")
                    continue
                raise  # non-transient / yield ไปแล้ว / หมดเชน → ให้ except ชั้นนอก classify

    except Exception as e:
        err = str(e)
        if "API_KEY_INVALID" in err or "401" in err:
            logger.error(f"Gemini API key invalid: {err}")
            raise GeminiUnavailable("API key invalid") from e
        elif "429" in err or "quota" in err.lower() or "resource_exhausted" in err.lower():
            logger.error(f"Gemini quota exceeded: {err}")
            raise GeminiQuotaExhausted("quota exhausted") from e
        else:
            logger.error(f"Gemini stream error: {err}")
            raise GeminiUnavailable(err) from e


def _stream_claude(messages: list[dict], image_b64: str = "", image_mime: str = "",
                   model: str = "", thinking: bool | None = None, effort: str = "",
                   usage_sink: dict | None = None):
    """Stream จาก Claude (Anthropic) ด้วย official SDK + prompt caching

    - system prompt → cached block (cache_control ephemeral, stable-first) ลด cost เมื่อ context ซ้ำ
    - vision: image_b64 → image block ใน user message ล่าสุด
    - adaptive thinking: เปิดด้วย CLAUDE_THINKING=adaptive (default off เพื่อความเร็วของแชต)
    Yields: text delta (str) หรือ error message ที่อ่านเข้าใจ
    """
    if anthropic_client is None:
        if anthropic is None:
            yield "⚠️ ยังไม่ได้ติดตั้ง anthropic SDK — รัน `pip install anthropic`"
        else:
            yield ("⚠️ ยังไม่ได้ตั้งค่า ANTHROPIC_API_KEY\n\n"
                   "เปิด `.env` แล้วใส่:\n```\nANTHROPIC_API_KEY=sk-ant-...\n```\n"
                   "ขอ key ที่ https://console.anthropic.com/")
        return

    # แยก system ออก + map เป็น user/assistant ของ Claude
    system_text = next((m["content"] for m in messages if m["role"] == "system"), "")
    claude_messages: list[dict] = []
    for m in messages:
        if m["role"] == "system":
            continue
        role = "assistant" if m["role"] == "assistant" else "user"
        claude_messages.append({"role": role, "content": m["content"]})

    # vision: แทรก image ลง user message ล่าสุด (content → list ของ content blocks)
    if image_b64 and claude_messages and claude_messages[-1]["role"] == "user":
        last = claude_messages[-1]
        claude_messages[-1] = {
            "role": "user",
            "content": [
                {"type": "text", "text": last["content"]},
                {"type": "image", "source": {
                    "type": "base64",
                    "media_type": image_mime or "image/jpeg",
                    "data": image_b64,
                }},
            ],
        }

    # Claude ต้องเริ่มด้วย user message เสมอ
    if not claude_messages or claude_messages[0]["role"] != "user":
        claude_messages.insert(0, {"role": "user", "content": "(เริ่มสนทนา)"})

    kwargs: dict = {
        "model": model or CLAUDE_MODEL,
        "max_tokens": CLAUDE_MAX_TOKENS,
        "messages": claude_messages,
    }
    if system_text:
        kwargs["system"] = [{
            "type": "text",
            "text": system_text,
            "cache_control": {"type": "ephemeral"},
        }]
    # thinking: None = ใช้ค่า env (CLAUDE_THINKING) เดิม · True/False = override per-request
    _think_on = (CLAUDE_THINKING == "adaptive") if thinking is None else bool(thinking)
    if _think_on:
        kwargs["thinking"] = {"type": "adaptive"}
        kwargs["output_config"] = {"effort": effort or CLAUDE_EFFORT}

    try:
        with anthropic_client.messages.stream(**kwargs) as stream:
            for text in stream.text_stream:
                yield text
            # log cache hit เพื่อ verify prompt caching ทำงาน (cache_read > 0 = ประหยัด)
            try:
                u = stream.get_final_message().usage
                if usage_sink is not None:
                    usage_sink["input_tokens"] = int(u.input_tokens or 0)
                    usage_sink["output_tokens"] = int(u.output_tokens or 0)
                logger.info(
                    f"[Claude] {CLAUDE_MODEL} ok | in={u.input_tokens} "
                    f"cache_write={getattr(u, 'cache_creation_input_tokens', 0)} "
                    f"cache_read={getattr(u, 'cache_read_input_tokens', 0)} "
                    f"out={u.output_tokens}"
                )
            except Exception:
                pass
    except Exception as e:
        # typed exceptions (ไม่ string-match) ตาม guideline
        if anthropic and isinstance(e, anthropic.AuthenticationError):
            logger.error(f"Claude auth error: {e}")
            yield "❌ ANTHROPIC_API_KEY ไม่ถูกต้อง — ตรวจสอบใน .env"
        elif anthropic and isinstance(e, anthropic.RateLimitError):
            logger.error(f"Claude rate limited: {e}")
            yield "⏳ Claude โดน rate limit — รอสักครู่แล้วลองใหม่ หรือสลับ provider"
        elif anthropic and isinstance(e, anthropic.APIStatusError) and e.status_code >= 500:
            logger.error(f"Claude server error: {e}")
            yield f"❌ Claude server error ({e.status_code}) — ลองใหม่ภายหลัง"
        else:
            logger.error(f"Claude stream error: {e}")
            yield f"❌ Claude error: {e}"


def _stream_kimi(messages: list[dict], model: str = "",
                 thinking: bool | None = None, effort: str = "",
                 image_b64: str = "", image_mime: str = "",
                 usage_sink: dict | None = None):
    """Stream จาก Kimi (Moonshot, OpenAI-compatible) — provider="kimi"

    - model: default KIMI_MODEL (kimi-k2.6)
    - thinking: None = ปล่อย default · True/False = เปิด/ปิด reasoning ผ่าน extra_body
      (Kimi: {"thinking": {"type": "enabled"/"disabled"}}). ปิดเป็นปกติของแชต = เร็ว/ไม่หลุด
    - vision: K2.6 มี MoonViT — แทรกรูปแบบ OpenAI image_url ได้
    Yields: text delta (str) หรือ error message
    """
    if kimi_client is None:
        yield ("⚠️ ยังไม่ได้ตั้งค่า MOONSHOT_API_KEY\n\n"
               "เปิด `.env` แล้วใส่:\n```\nMOONSHOT_API_KEY=sk-...\n```\n"
               "ขอ key ที่ https://platform.moonshot.ai/")
        return

    use_model = model or KIMI_MODEL

    # vision: แทรก image ลง user message ล่าสุด (เหมือน LM Studio)
    if image_b64:
        msgs = []
        for i, m in enumerate(messages):
            if m["role"] == "user" and i == len(messages) - 1:
                msgs.append({"role": "user", "content": [
                    {"type": "text", "text": m["content"]},
                    {"type": "image_url", "image_url": {
                        "url": f"data:{image_mime or 'image/jpeg'};base64,{image_b64}"}},
                ]})
            else:
                msgs.append(m)
    else:
        msgs = messages

    create_kwargs: dict = {"model": use_model, "messages": msgs, "stream": True}
    # thinking None = ไม่ส่ง (ใช้ default ของ Kimi) — ส่งเฉพาะเมื่อ override ชัดเจน
    if thinking is not None:
        create_kwargs["extra_body"] = {
            "thinking": {"type": "enabled" if thinking else "disabled"}
        }

    try:
        stream = _create_stream_with_usage(
            kimi_client.chat.completions.create, create_kwargs,
            want_usage=usage_sink is not None,
        )
        for chunk in stream:
            _capture_openai_usage(chunk, usage_sink)
            if not chunk.choices:
                continue  # chunk ท้ายจาก include_usage
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
        logger.info(f"Kimi stream OK (model={use_model}, thinking={thinking})")
    except Exception as e:
        err = str(e).lower()
        if "401" in err or "auth" in err or "api key" in err or "invalid" in err:
            logger.error(f"Kimi auth error: {e}")
            yield "❌ MOONSHOT_API_KEY ไม่ถูกต้อง — ตรวจสอบใน .env"
        elif "429" in err or "rate" in err or "quota" in err:
            logger.error(f"Kimi rate/quota: {e}")
            yield "⏳ Kimi โดน rate limit / quota — รอสักครู่หรือสลับ provider"
        else:
            logger.error(f"Kimi stream error: {e}")
            yield f"❌ Kimi error: {e}"
