import os

# ให้ default ตรงกับ core/config.py — รุ่นเก่า (gemini-live-2.0-flash-001) ถูกถอดจาก Live API แล้ว
GEMINI_LIVE_MODEL = os.getenv("GEMINI_LIVE_MODEL", "gemini-2.5-flash-native-audio-latest")

VOICE_MAP: dict[str, str] = {
    "fa":   "Kore",
    "kwan": "Aoede",
    "khim": "Zephyr",
}
DEFAULT_VOICE = "Aoede"


def speakable_part_text(part) -> str | None:
    """คืน text ของ Gemini Live part เฉพาะส่วนที่ "พูดออกมา" จริง.

    Live thinking model (เช่น gemini-2.5-flash-native-audio-latest) ส่ง part
    ที่ `part.thought is True` = chain-of-thought ภายใน — ห้ามหลุดเข้า
    transcript ที่เซฟหรือ UI. ตัดทิ้งที่นี่ที่เดียว (pure → unit-testable).
    """
    if getattr(part, "thought", False):
        return None
    text = getattr(part, "text", None)
    return text or None
