import os, io, wave
from google import genai
from google.genai import types

GEMINI_API_KEY  = os.getenv("GEMINI_API_KEY", "")
GEMINI_TTS_MODEL = os.getenv("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-native-audio-dialog")

# Voice ต่าง assistant slug
VOICE_MAP: dict[str, str] = {
    "fa":   "Kore",
    "kwan": "Aoede",
    "khim": "Zephyr",
}
DEFAULT_VOICE = "Aoede"


def _pcm_to_wav(pcm: bytes, rate: int = 24000, channels: int = 1, width: int = 2) -> bytes:
    """แปลง raw PCM → WAV bytes"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(width)
        wf.setframerate(rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def generate_tts(text: str, assistant_slug: str = "") -> bytes:
    """
    สร้าง TTS audio (WAV) จาก Gemini 2.5 Flash Native Audio Dialog
    คืนค่า WAV bytes พร้อมเล่น
    """
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not set — ไม่สามารถใช้ TTS ได้")

    # ตัด text ยาวเกิน (Gemini รับได้ไม่เกิน ~2000 chars ต่อ request)
    text = text.strip()[:2000]
    if not text:
        raise ValueError("text ว่างเปล่า")

    voice = VOICE_MAP.get(assistant_slug.lower(), DEFAULT_VOICE)

    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(
        model=GEMINI_TTS_MODEL,
        contents=text,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=voice
                    )
                )
            ),
        ),
    )

    part = response.candidates[0].content.parts[0]
    pcm_bytes: bytes = part.inline_data.data  # SDK คืน bytes โดยตรง
    return _pcm_to_wav(pcm_bytes)
