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


def live_server_content_events(sc) -> tuple[list[dict], str, str]:
    """แปลง Gemini Live `server_content` → (events, user_delta, ai_delta) — pure → testable.

    คืน:
      - events: list ของ dict ที่ส่งให้ UI ผ่าน WebSocket
          * input_transcription  → {"type": "user_text", "text": ...}
          * output_transcription → {"type": "text", "text": ...}  ← เสียงที่โมเดลพูดจริง
          * model_turn parts      → {"type": "text", "text": ...}  ← เฉพาะ text ที่พูดได้
                                      (กรอง thought ผ่าน speakable_part_text) สำหรับโมเดล
                                      text-modality ที่ไม่มี output_transcription
      - user_delta / ai_delta: ข้อความสะสมเพื่อเซฟลง history เมื่อ turn จบ

    ทำไมต้องส่ง output_transcription ให้ UI: โมเดล native-audio ส่งข้อความที่พูดจริง
    มาทาง output_transcription (model_turn เป็น audio + thought). ถ้าไม่ส่ง → bubble
    ผู้ช่วยว่างเปล่าหลังกรอง thought (regression ต่อจาก 6335c1e).
    """
    events: list[dict] = []
    user_delta = ""
    ai_delta = ""

    # barge-in / ตัดจังหวะ: Gemini Live ส่ง interrupted=True เมื่อผู้ใช้พูดแทรก
    # หรือโมเดลถูกตัดจังหวะ — บอก UI ให้ flush คิวเสียงเก่าทันที (กันเสียง turn
    # ถัดไปต่อท้ายคิวเก่า เล่นช้า/ทับกัน → รู้สึกเหมือนค้าง). ส่งก่อน text ของ
    # turn ใหม่เสมอ เพื่อให้ client หยุดเสียงเก่าก่อน schedule เสียงใหม่
    if getattr(sc, "interrupted", False):
        events.append({"type": "interrupted"})

    it = getattr(sc, "input_transcription", None)
    if it and getattr(it, "text", None):
        user_delta += it.text
        events.append({"type": "user_text", "text": it.text})

    ot = getattr(sc, "output_transcription", None)
    if ot and getattr(ot, "text", None):
        ai_delta += ot.text
        events.append({"type": "text", "text": ot.text})

    mt = getattr(sc, "model_turn", None)
    if mt:
        for part in getattr(mt, "parts", []):
            txt = speakable_part_text(part)
            if txt:
                ai_delta += txt
                events.append({"type": "text", "text": txt})

    return events, user_delta, ai_delta


def live_control_signals(response) -> tuple[bool, float | None, str | None]:
    """ดึงสัญญาณควบคุม session ออกจาก `LiveServerMessage` — pure → เทสได้

    คืน `(ได้รับ go_away, วินาทีที่เหลือถ้าอ่านได้, resumption handle ใหม่ถ้าใช้ได้)`

    **ทำไมต้องมี:** `send_loop` เดิมอ่านแค่ `response.data` กับ `response.server_content`
    ส่วน `go_away` / `session_resumption_update` เป็น field คนละตัวระดับบน → ไม่มีใครอ่าน
    → Gemini เตือนว่าใกล้หมดอายุ session แล้วเราเงียบ มันเลยตัดทิ้งเองด้วย 1008
    (ยืนยันจาก prod 2 ครั้ง: 2026-08-03 18:14:14 และ 21:33:32 UTC — ทั้งคู่ราวนาทีที่ 10)

    **"ไม่รู้เวลาที่เหลือ" ต้องไม่ถูกตีความเป็น "ไม่มี go_away"** — ถ้า `time_left`
    อ่านไม่ออก ยังต้องคืน `True` เพราะสิ่งที่ต้องทำ (ต่อ session ใหม่) ไม่ได้ขึ้นกับตัวเลขนั้น
    · handle ที่ `resumable=False` ถือว่าใช้ไม่ได้ ต้องไม่เก็บไปใช้ต่อ
    """
    if response is None:
        return False, None, None

    go_away = getattr(response, "go_away", None)
    got_go_away = go_away is not None

    seconds: float | None = None
    if got_go_away:
        left = getattr(go_away, "time_left", None)
        total = getattr(left, "total_seconds", None)
        if callable(total):
            try:
                seconds = float(total())
            except Exception:
                seconds = None

    handle: str | None = None
    upd = getattr(response, "session_resumption_update", None)
    if upd is not None and getattr(upd, "resumable", False):
        new_handle = getattr(upd, "new_handle", None)
        if new_handle:
            handle = new_handle

    return got_go_away, seconds, handle
