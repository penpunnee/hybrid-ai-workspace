import os

GEMINI_LIVE_MODEL = os.getenv("GEMINI_LIVE_MODEL", "gemini-live-2.0-flash-001")

VOICE_MAP: dict[str, str] = {
    "fa":   "Kore",
    "kwan": "Aoede",
    "khim": "Zephyr",
}
DEFAULT_VOICE = "Aoede"
