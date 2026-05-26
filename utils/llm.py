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

gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# --- LM Studio (OpenAI-compatible local server) ---
# opt-in: default ว่าง — ถ้าไม่ตั้ง LMSTUDIO_BASE_URL จะไม่ถูกใช้ (local หลักคือ Ollama)
_LMSTUDIO_BASE_URL = os.getenv("LMSTUDIO_BASE_URL", "")
_LMSTUDIO_TIMEOUT  = int(os.getenv("LMSTUDIO_TIMEOUT", "180"))

# client สร้างไว้เสมอ แต่จะถูกเรียกเฉพาะเมื่อ provider="lmstudio" เท่านั้น
# ถ้า base_url ว่าง ใช้ localhost (ถ้าเผลอเรียกจะ refuse แบบ clean ไม่ leak ไป api.openai.com)
lmstudio_client = OpenAI(
    base_url=_LMSTUDIO_BASE_URL or "http://localhost:1234/v1",
    api_key="lmstudio",
    timeout=_LMSTUDIO_TIMEOUT,
)


_last_failover: dict = {"active": False}  # track failover state
_health_cache: dict = {"ok": None, "ts": 0.0, "msg": ""}  # cache health check 30s


def stream_response(messages: list[dict], provider: str = "ollama",
                    image_b64: str = "", image_mime: str = "",
                    agent_mode: bool = False, model_override: str = ""):
    """
    Stream response จาก LLM ที่เลือก
    provider: 'ollama' | 'gemini' | 'lmstudio' | 'auto'
    model_override: ใช้ model นี้แทน default (สำหรับ LM Studio)
    """
    if provider == "gemini_agent":
        _last_failover["active"] = False
        yield from _stream_gemini(messages, image_b64, image_mime, agent_mode=True)
        return

    if provider == "gemini" or agent_mode or (image_b64 and provider not in ("lmstudio", "auto")):
        _last_failover["active"] = False
        yield from _stream_gemini(messages, image_b64, image_mime, agent_mode=agent_mode)
        return

    if provider in ("lmstudio", "lmstudio_web"):
        _last_failover["active"] = False
        yield from _stream_lmstudio(messages, model=model_override,
                                    image_b64=image_b64, image_mime=image_mime)
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
                raw_chunks = _stream_lmstudio(messages, model=decision.model,
                                              image_b64=image_b64, image_mime=image_mime)
                yield from stream_with_thinking(raw_chunks, show_thinking=show)
            else:
                yield from _stream_ollama(messages)
        except Exception as e:
            logger.warning(f"Auto-route failed ({e}), fallback ollama")
            yield from _stream_ollama(messages)
        return

    _last_failover["active"] = False
    yield from _stream_ollama(messages)


def _stream_lmstudio(messages: list[dict], model: str = "",
                     image_b64: str = "", image_mime: str = ""):
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
        logger.info(f"[LMStudio] grounded context detected → temp=0.2")
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
        stream = lmstudio_client.chat.completions.create(
            model=model,
            messages=msgs,
            stream=True,
            temperature=temperature,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
        logger.info(f"LM Studio stream OK (model={model}, vision={'yes' if image_b64 else 'no'})")
    except Exception as e:
        err = str(e).lower()
        if "connection" in err or "refused" in err:
            yield f"❌ เชื่อมต่อ LM Studio ไม่ได้ ({_LMSTUDIO_BASE_URL})"
        elif "model" in err or "not found" in err:
            yield f"❌ ไม่พบ model `{model}` ใน LM Studio — ตรวจสอบว่าโหลดแล้ว"
        elif "resources" in err or "memory" in err:
            yield f"❌ RAM/VRAM ไม่พอสำหรับ `{model}` — ลอง quantization ต่ำกว่านี้"
        else:
            logger.error(f"LM Studio error: {e}")
            yield f"❌ LM Studio error: {e}"



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


def _stream_ollama(messages: list[dict]):
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
    
    for attempt in range(max_retries):
        try:
            stream = ollama_client.chat.completions.create(
                model=OLLAMA_MODEL,
                messages=messages,
                stream=True,
                timeout=OLLAMA_TIMEOUT,
                temperature=float(os.getenv("OLLAMA_TEMPERATURE", "0.7")),
                top_p=float(os.getenv("OLLAMA_TOP_P", "0.85")),
                extra_body={
                    "options": {
                        "num_ctx": int(os.getenv("OLLAMA_NUM_CTX", "4096")),
                        "repeat_penalty": float(os.getenv("OLLAMA_REPEAT_PENALTY", "1.1")),
                    }
                },
            )
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
            logger.info(f"Ollama stream successful (model: {OLLAMA_MODEL})")
            return  # Success - exit retry loop
        except Exception as e:
            err_str = str(e).lower()
            
            # ถ้าเป็น model not found error ไม่ต้อง retry (จะไม่สำเร็จอยู่ดี)
            if "model" in err_str or "not found" in err_str:
                logger.error(f"Ollama model not found: {OLLAMA_MODEL} - {str(e)}")
                yield (
                    f"❌ Model `{OLLAMA_MODEL}` ไม่พบใน Ollama\n\n"
                    f"กรุณา pull model ด้วยคำสั่ง:\n"
                    f"```bash\nollama pull {OLLAMA_MODEL}\n```\n"
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


def _stream_gemini(messages: list[dict], image_b64: str = "", image_mime: str = "",
                   agent_mode: bool = False):
    """
    Stream จาก Gemini Cloud ด้วย google-genai SDK ใหม่
    
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
            history.append(types.Content(role=role, parts=[types.Part(text=m["content"])]))

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

        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=tools,
        )
        response = gemini_client.models.generate_content_stream(
            model=GEMINI_MODEL,
            contents=history,
            config=config,
        )
        for chunk in response:
            if chunk.text:
                yield chunk.text
        logger.info(f"Gemini stream successful (model: {GEMINI_MODEL}, agent_mode: {agent_mode})")

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
