import os, io, wave, re
from concurrent.futures import ThreadPoolExecutor, as_completed
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


def _split_sentences(text: str) -> list[str]:
    """ตัดข้อความเป็น sentences — จบที่ .!?… หรือขึ้นบรรทัดใหม่"""
    parts = re.split(r"(?<=[.!?…])\s+|(?<=\n)", text)
    return [p.strip() for p in parts if p.strip()]


def _concat_wavs(wavs: list[bytes]) -> bytes:
    """รวม WAV หลายไฟล์เป็นไฟล์เดียว — อ่าน PCM จากทุกไฟล์แล้วต่อกัน"""
    all_pcm = b""
    rate, channels, width = 24000, 1, 2
    for wav_bytes in wavs:
        with wave.open(io.BytesIO(wav_bytes)) as wf:
            rate = wf.getframerate()
            channels = wf.getnchannels()
            width = wf.getsampwidth()
            all_pcm += wf.readframes(wf.getnframes())
    return _pcm_to_wav(all_pcm, rate, channels, width)


def _generate_one(text: str, voice: str) -> bytes:
    """Generate audio สำหรับ 1 chunk — ใช้ใน ThreadPoolExecutor"""
    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(
        model=GEMINI_TTS_MODEL,
        contents=text[:2000],
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                )
            ),
        ),
    )
    pcm: bytes = response.candidates[0].content.parts[0].inline_data.data
    return _pcm_to_wav(pcm)


def generate_tts(text: str, assistant_slug: str = "") -> bytes:
    """TTS แบบ parallel-sentence — ลด latency โดยไม่ต้องแก้ frontend
    ข้อความสั้น (≤1 sentence): generate ตรงๆ
    ข้อความยาว: แบ่ง sentence → generate พร้อมกัน → concat WAV
    """
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not set — ไม่สามารถใช้ TTS ได้")

    text = text.strip()
    if not text:
        raise ValueError("text ว่างเปล่า")

    voice = VOICE_MAP.get(assistant_slug.lower(), DEFAULT_VOICE)
    sentences = _split_sentences(text)

    # ข้อความสั้นหรือมีแค่ 1 sentence: generate ตรงๆ
    if len(sentences) <= 1:
        return _generate_one(text[:2000], voice)

    # หลาย sentence: generate parallel (max 4 workers)
    results: dict[int, bytes] = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(_generate_one, s, voice): i for i, s in enumerate(sentences)}
        for future in as_completed(futures):
            idx = futures[future]
            results[idx] = future.result()

    ordered = [results[i] for i in range(len(sentences))]
    return _concat_wavs(ordered)
