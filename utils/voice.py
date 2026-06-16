import os

# ให้ default ตรงกับ core/config.py — รุ่นเก่า (gemini-live-2.0-flash-001) ถูกถอดจาก Live API แล้ว
GEMINI_LIVE_MODEL = os.getenv("GEMINI_LIVE_MODEL", "gemini-2.5-flash-native-audio-latest")

VOICE_MAP: dict[str, str] = {
    "fa":   "Kore",
    "kwan": "Aoede",
    "khim": "Zephyr",
}
DEFAULT_VOICE = "Aoede"
