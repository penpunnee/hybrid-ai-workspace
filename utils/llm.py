import os
from openai import OpenAI
import google.generativeai as genai
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
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)


def stream_response(messages: list[dict], provider: str = "ollama"):
    """
    Stream response จาก LLM ที่เลือก
    provider: 'ollama' (local) หรือ 'gemini' (cloud)
    """
    if provider == "gemini":
        yield from _stream_gemini(messages)
    else:
        yield from _stream_ollama(messages)


def check_ollama_health() -> tuple[bool, str]:
    """ตรวจสอบว่า Ollama รันอยู่หรือไม่ คืนค่า (ok, message)"""
    import urllib.request
    try:
        base = OLLAMA_BASE_URL.replace("/v1", "")
        urllib.request.urlopen(f"{base}/api/tags", timeout=3)
        return True, ""
    except Exception:
        return False, (
            f"❌ ไม่สามารถเชื่อมต่อ Ollama ได้\n\n"
            f"กรุณาเปิด Ollama ก่อนด้วยคำสั่ง:\n```\nollama serve\n```\n"
            f"หรือตรวจสอบว่า model `{OLLAMA_MODEL}` ได้ pull แล้ว:\n```\nollama pull {OLLAMA_MODEL}\n```"
        )


def _stream_ollama(messages: list[dict]):
    """Stream จาก Ollama local พร้อม error handling"""
    ok, err_msg = check_ollama_health()
    if not ok:
        yield err_msg
        return

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


def _stream_gemini(messages: list[dict]):
    """Stream จาก Gemini Cloud — แปลง messages format ก่อนส่ง พร้อม error handling"""
    if not GEMINI_API_KEY:
        yield (
            "⚠️ ยังไม่ได้ตั้งค่า GEMINI_API_KEY\n\n"
            "เปิดไฟล์ `.env` แล้วใส่:\n```\nGEMINI_API_KEY=your_key_here\n```\n"
            "ขอ key ได้ฟรีที่ https://aistudio.google.com/"
        )
        return

    try:
        model = genai.GenerativeModel(
            model_name=GEMINI_MODEL,
            system_instruction=next(
                (m["content"] for m in messages if m["role"] == "system"), None
            ),
        )

        # แปลง messages เป็น Gemini format (ไม่รวม system)
        history = []
        for m in messages:
            if m["role"] == "system":
                continue
            role = "user" if m["role"] == "user" else "model"
            history.append({"role": role, "parts": [m["content"]]})

        last_user = history[-1]["parts"][0] if history else ""
        chat_history = history[:-1] if len(history) > 1 else []

        chat = model.start_chat(history=chat_history)
        response = chat.send_message(last_user, stream=True)
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
