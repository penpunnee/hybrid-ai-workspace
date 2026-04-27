import os, base64
from openai import OpenAI
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

# --- Ollama (Local LLM) ---
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")

ollama_client = OpenAI(
    base_url=OLLAMA_BASE_URL,
    api_key="ollama",
)

# --- Gemini (Cloud LLM) ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None


_last_failover: dict = {"active": False}  # track failover state


def stream_response(messages: list[dict], provider: str = "ollama",
                    image_b64: str = "", image_mime: str = "",
                    agent_mode: bool = False):
    """
    Stream response จาก LLM ที่เลือก
    provider: 'ollama' (local) หรือ 'gemini' (cloud)
    Auto-failover: ถ้า ollama offline และมี gemini key จะสลับไป gemini อัตโนมัติ
    """
    if provider == "gemini" or image_b64 or agent_mode:
        _last_failover["active"] = False
        yield from _stream_gemini(messages, image_b64, image_mime, agent_mode=agent_mode)
        return

    # ตรวจ ollama ก่อน
    ok, _ = check_ollama_health()
    if not ok:
        if gemini_client:
            _last_failover["active"] = True
            yield "⚠️ **Ollama offline** — สลับไปใช้ Gemini อัตโนมัติ\n\n"
            yield from _stream_gemini(messages, image_b64, image_mime, agent_mode=False)
        else:
            _last_failover["active"] = False
            yield (
                "❌ **Ollama offline** และไม่มี Gemini API Key\n\n"
                "กรุณาเปิด LM Studio หรือตั้งค่า `GEMINI_API_KEY` ใน `.env`"
            )
        return

    _last_failover["active"] = False
    yield from _stream_ollama(messages)



def check_ollama_health() -> tuple[bool, str]:
    """ตรวจสอบว่า Ollama รันอยู่หรือไม่ คืนค่า (ok, message)"""
    import urllib.request
    try:
        base = OLLAMA_BASE_URL.replace("/v1", "")
        urllib.request.urlopen(f"{base}/api/tags", timeout=8)
        return True, ""
    except Exception:
        return False, (
            f"❌ ไม่สามารถเชื่อมต่อ Ollama ได้\n\n"
            f"กรุณาเปิด Ollama ก่อนด้วยคำสั่ง:\n```\nollama serve\n```\n"
            f"หรือตรวจสอบว่า model `{OLLAMA_MODEL}` ได้ pull แล้ว:\n```\nollama pull {OLLAMA_MODEL}\n```"
        )


def _stream_ollama(messages: list[dict]):
    """Stream จาก Ollama local พร้อม error handling"""
    try:
        stream = ollama_client.chat.completions.create(
            model=OLLAMA_MODEL,
            messages=messages,
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
    except Exception as e:
        yield f"❌ Ollama error: {e}"


def _stream_gemini(messages: list[dict], image_b64: str = "", image_mime: str = "",
                   agent_mode: bool = False):
    """Stream จาก Gemini Cloud ด้วย google-genai SDK ใหม่"""
    if not gemini_client:
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

    except Exception as e:
        err = str(e)
        if "API_KEY_INVALID" in err or "401" in err:
            yield "❌ Gemini API Key ไม่ถูกต้อง กรุณาตรวจสอบใน `.env`"
        elif "429" in err or "quota" in err.lower():
            yield "❌ Gemini quota หมด กรุณารอสักครู่หรือเปลี่ยนมาใช้ Local LLM"
        else:
            yield f"❌ Gemini error: {e}"
