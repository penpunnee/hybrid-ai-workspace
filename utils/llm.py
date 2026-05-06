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


_last_failover: dict = {"active": False}  # track failover state
_health_cache: dict = {"ok": None, "ts": 0.0, "msg": ""}  # cache health check 30s


def stream_response(messages: list[dict], provider: str = "ollama",
                    image_b64: str = "", image_mime: str = "",
                    agent_mode: bool = False):
    """
    Stream response จาก LLM ที่เลือก
    provider: 'ollama' (local) หรือ 'gemini' (cloud)
    ถ้า ollama offline จะแสดง error — ไม่ auto-failover ไป gemini
    """
    if provider == "gemini" or image_b64 or agent_mode:
        _last_failover["active"] = False
        yield from _stream_gemini(messages, image_b64, image_mime, agent_mode=agent_mode)
        return

    _last_failover["active"] = False
    yield from _stream_ollama(messages)



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
            yield "❌ Gemini API Key ไม่ถูกต้อง กรุณาตรวจสอบใน `.env`"
        elif "429" in err or "quota" in err.lower():
            logger.error(f"Gemini quota exceeded: {err}")
            yield "❌ Gemini quota หมด กรุณารอสักครู่หรือเปลี่ยนมาใช้ Local LLM"
        else:
            logger.error(f"Gemini stream error: {err}")
            yield f"❌ Gemini error: {e}"
