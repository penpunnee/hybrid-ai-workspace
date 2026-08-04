import math
import os
import struct
import time

# ── เสียงของระบบ — **ที่นิยามที่เดียว** ────────────────────────────────────────
# เดิมตารางนี้ถูกก๊อปไว้ 2 ที่ (ที่นี่ + `utils/tts.py`) และตัวที่ `server.py` ใช้จริง
# คือของ `tts.py` → ใครแก้ไฟล์ชื่อ `voice.py` เพื่อเปลี่ยนเสียงจะแก้แล้วไม่มีอะไรเกิดขึ้น
# (รูปแบบเดียวกับ alias `_SKILLS_DB` ที่ถอดไปตอนปิดข้อ 2)
#
# ⚠️ `fa`/`khim` ถูกถอดออกแล้ว — เหลือผู้ช่วยตัวเดียวคือ `kwan` ตั้งแต่ 2026-06-16
# fallback ต้องเป็น **เสียงเดียวกับ slug ที่รู้จัก** ไม่ใช่เสียงตัวอื่น: วันที่ frontend
# ส่ง slug เพี้ยน (ส่งชื่อแทน slug) ผู้ใช้จะได้ยิน "คนละคน" ทันทีโดยไม่มี error โผล่เลย
DEFAULT_VOICE = "Aoede"          # เสียงผู้หญิงตัวเดียวของระบบ
VOICE_MAP: dict[str, str] = {
    "kwan": DEFAULT_VOICE,
}


def resolve_voice(slug: str) -> str:
    """slug → ชื่อเสียง Gemini · ไม่รู้จัก/ว่าง ก็ได้เสียงเดิม (ห้ามสลับคน)"""
    return VOICE_MAP.get((slug or "").lower(), DEFAULT_VOICE)


# ── ตรึง "วิธีเรนเดอร์เสียง" ให้ session ใหม่ฟังเหมือน session เดิม ──────────────
# user รายงาน 2026-08-04: "เหมือนสลับเป็นคนละคน" ทั้งที่ voice_name ไม่เคยเปลี่ยน
#
# โมเดล native-audio/live **สังเคราะห์น้ำเสียงใหม่ทุกครั้งที่เปิด session** — ชื่อเสียง
# เป็นแค่จุดตั้งต้น ไม่ใช่ไฟล์เสียงสำเร็จรูป ถ้าไม่ตรึง `seed`/`temperature` ทุกครั้งที่
# ต่อ session ใหม่ (go_away regen ฝั่ง server **หรือ** retry ฝั่ง client) = สุ่มโทนใหม่
#
# ⚠️ ตรึงได้ "เท่าที่ API ให้ตรึง" — Gemini ไม่รับประกัน determinism ของเสียง
# ตัวชี้ขาดคือหูของ user หลังคุยข้ามนาทีที่ 10 ไม่ใช่เทสในไฟล์นี้
VOICE_SEED = 20260804            # ค่าคงที่ตายตัว — เปลี่ยนเมื่อไหร่ = ยอมให้เสียงเปลี่ยน
VOICE_TEMPERATURE = 0.6          # ต่ำกว่า default (~1.0) = ความแปรปรวนของน้ำเสียงน้อยลง

# ── ⚠️ ค่าพวกนี้ "ขึ้นกับโมเดล" — วัดจริงบน prod 2026-08-04 ก่อนตั้ง ────────────
# ยิง Live session จริง เคสละ 2 รอบ นับ **ไบต์เสียงที่ได้กลับมา** (ไม่ใช่ "ไม่ throw"
# — เกณฑ์นั้นทำให้เคสที่คืน 0 ไบต์ขึ้นว่าผ่าน แล้วเกือบสรุปผิด):
#
#   โมเดล                        | temperature | seed         | affective=True
#   -----------------------------|-------------|--------------|----------------
#   2.5-native-audio-preview-12  | 🔴 0 ไบต์   | ไม่ตรึง (ต่าง) | ok
#   3.1-flash-live-preview       | ok          | ✅ ตรึงได้     | 🔴 APIError 1011
#
# 🔴 **`temperature` บน 2.5-native-audio ทำให้เสียงหายแบบเงียบสนิท** — ไม่ error,
#    transcript มาครบ, จอขึ้นว่าตอบแล้ว ขาดแค่เสียง = failure mode ที่แย่ที่สุด
#    (ตอนแรกตั้งใจจะ pin ไป 2.5 เพราะมันปักวันที่ได้ ถ้าทำไปเสียงจะดับทั้งระบบโดยเทสเขียวหมด)
#
# ✅ **เลือก 3.1 เพราะ `seed` ตรึงได้จริงบนตัวนี้ตัวเดียว** — ใส่ seed แล้วได้ไบต์เท่ากันเป๊ะ
#    ทั้ง 2 รอบ (67230, 67230) ส่วน baseline ที่ไม่ใส่ ได้ 67202 กับ 62882
#    และเป็นตัวที่ prod ใช้อยู่แล้วตั้งแต่ `369f18e` → user ไม่ต้องเจอเสียงเปลี่ยนอีกรอบ
#
# ⚠️ **ความเสี่ยงที่ยังเหลืออยู่ ไม่ได้ปิด:** `-preview` ถูก Google อัปเดตทับในที่ได้
#    และสาย 3.1-live **ยังไม่มี snapshot ปักวันที่ให้เลือกเลย** (เช็คจาก ListModels แล้ว)
#    ถ้าวันหนึ่งเสียงเปลี่ยนอีกโดยเราไม่ได้แตะอะไร ให้สงสัยตัวนี้ก่อนเป็นอันดับแรก
#    ⛔ อย่าเผลอ "แก้" ด้วยการถอยไป 2.5 โดยไม่รันตารางข้างบนใหม่ — ดูช่อง temperature
#
# ⚠️ ไบต์เท่ากัน = หลักฐานว่า *การสุ่มถูกตรึง* เท่านั้น **ไม่ใช่หลักฐานว่าหูคนได้ยินเหมือนกัน**
#    ตัวชี้ขาดคือ user คุยข้ามนาทีที่ 10 (จุดที่ go_away ตัด session) แล้วบอกว่ายังสลับคนไหม
GEMINI_LIVE_MODEL_DEFAULT = "gemini-3.1-flash-live-preview"
GEMINI_LIVE_MODEL = os.getenv("GEMINI_LIVE_MODEL", GEMINI_LIVE_MODEL_DEFAULT)


def build_live_config(slug: str, system_instruction: str, resume_handle: str | None):
    """ประกอบ `LiveConnectConfig` ทั้งก้อน — ที่เดียวที่รู้ว่าเสียงถูกตั้งยังไง

    แยกออกจาก `server.py` เพื่อให้ **เทสค่าที่ตรึงไว้ได้จริง** (เดิมเป็น closure ในตัว
    handler → ตรวจได้แค่ด้วยการ grep ซอร์ส ซึ่งพิสูจน์ไม่ได้ว่าค่าที่ส่งออกไปคืออะไร)

    `types` import ข้างในโดยตั้งใจ — โมดูลนี้ถูก `core/config.py` import จึงต้องไม่ลาก
    google-genai เข้ามาตอน import time
    """
    from google.genai import types

    return types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=resolve_voice(slug))
            )
        ),
        # ตรึงการสุ่ม — หัวใจของ "session ใหม่ต้องฟังเหมือนเดิม"
        seed=VOICE_SEED,
        temperature=VOICE_TEMPERATURE,
        # ปล่อย None = ยอมให้ค่า default ของโมเดลเปลี่ยนทีหลังโดยเราไม่รู้ตัว
        # affective dialog ปรับน้ำเสียงตามอารมณ์บทสนทนา = ตรงข้ามกับ "สม่ำเสมอ"
        enable_affective_dialog=False,
        system_instruction=types.Content(parts=[types.Part(text=system_instruction)]),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        # hands-free: เปิด automatic VAD → Gemini จับเริ่ม/หยุดพูดจากเสียงเอง (พูดได้เลยไม่ต้องกด)
        # กัน echo ที่ฝั่ง client (half-duplex: ปิดไมค์ตอน AI พูด) แทนการพึ่ง manual VAD.
        # NO_INTERRUPTION = เผื่อ echo หลุดขอบ tail ก็ไม่ตัดคำตอบ AI กลางคัน (belt-and-suspenders)
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(),
            activity_handling=types.ActivityHandling.NO_INTERRUPTION,
        ),
        # ⚠️ คอมเมนต์เดิมเขียนว่า compression ทำให้ "session ไม่มีลิมิตอายุ → ไม่มี go_away
        # จาก duration" — **ไม่จริง** log prod เจอ go_away 2 ครั้ง (2026-08-03 18:14:14
        # และ 21:33:32 UTC ทั้งคู่ราวนาทีที่ 10) compression ช่วยเรื่อง context ยาว
        # แต่ไม่ได้ยกเลิก go_away → ต้องรับมือเอง
        context_window_compression=types.ContextWindowCompressionConfig(
            sliding_window=types.SlidingWindow(),
        ),
        # ขอ handle ไว้ต่อ session ใหม่ตอนโดน go_away — ไม่มีอันนี้ = ต่อใหม่ได้แต่
        # ความจำหายหมด (เล่านิยายอยู่แล้วเริ่มเรื่องใหม่)
        session_resumption=types.SessionResumptionConfig(handle=resume_handle),
    )


# ── ตัววัดระดับเสียงที่ "เราได้รับมา" (ชั่วคราว — ตั้งใจถอดออกได้) ───────────────
# user รายงานว่าคุยนานๆ แล้ว "เสียงเบาลง" · วินิจฉัยผิดมาแล้ว 2 รอบเพราะแปลง
# *ความรู้สึก* เป็น *กลไก* ทันที (vault: symptom-vs-interpretation)
#
# ตัวนี้ตอบคำถามเดียวที่ตัดได้ขาด — วัด PCM ตรงจุดที่รับจาก Gemini **ก่อน**ส่งเข้าเบราว์เซอร์:
#   · ตัวเลขแบนราบ แต่ user ได้ยินว่าเบาลง → ปัญหาอยู่ปลายทาง (OS/AEC/Bluetooth HFP)
#   · ตัวเลขลดลงตามเวลา                   → Gemini ส่งเสียงเบาลงจริง ไม่เกี่ยวกับหูฟัง
#
# ⚠️ พิสูจน์ได้แค่ว่า "สิ่งที่เราได้รับ" ดังเท่าไหร่ — ตัวเลขแบนราบ **ไม่ได้แปลว่าไม่มีปัญหา**
# แปลว่า "ปัญหาไม่ได้อยู่ก่อนจุดนี้" เท่านั้น
VOICE_LEVEL_LOG = os.getenv("VOICE_LEVEL_LOG", "on").strip().lower() not in ("off", "0", "false")
VOICE_LEVEL_WINDOW_SEC = float(os.getenv("VOICE_LEVEL_WINDOW_SEC", "10"))


class AudioLevelMeter:
    """สะสม PCM 16-bit LE แล้วสรุป RMS/peak ทุกๆ `window_sec` **วินาทีของเสียง**

    รายงานทั้ง `audio_sec` (เวลาเสียงสะสม) และ `wall_sec` (นาฬิกาจริง) เพราะ user
    เล่าอาการเป็น "นาทีที่ 5" ตามนาฬิกา แต่ช่องว่างระหว่าง turn ทำให้สองค่านี้ต่างกันมาก
    — ต้องมีทั้งคู่ถึงจะจับคู่ตัวเลขกับสิ่งที่หูได้ยินได้
    """

    def __init__(self, rate: int = 24000, window_sec: float | None = None,
                 enabled: bool | None = None):
        self.rate = rate
        self.window = max(1, int(rate * (VOICE_LEVEL_WINDOW_SEC if window_sec is None
                                         else window_sec)))
        self.enabled = VOICE_LEVEL_LOG if enabled is None else enabled
        self._buf = bytearray()      # ไบต์เศษที่ยังประกอบเป็น sample ไม่ครบ
        self._sq = 0                 # ผลรวมกำลังสอง (int — ไม่มีปัญหา precision)
        self._peak = 0
        self._n = 0
        self._audio_samples = 0
        self._t0 = time.monotonic()

    def add(self, pcm: bytes) -> dict | None:
        """ป้อน PCM · คืน dict สรุปเมื่อหน้าต่างเต็ม ไม่งั้นคืน None"""
        if not self.enabled or not pcm:
            return None
        self._buf += pcm
        usable = len(self._buf) - (len(self._buf) % 2)      # ไบต์เศษต้องเก็บไว้รอบหน้า
        if usable:
            for (s,) in struct.iter_unpack("<h", bytes(self._buf[:usable])):
                self._sq += s * s
                a = -s if s < 0 else s
                if a > self._peak:
                    self._peak = a
                self._n += 1
            del self._buf[:usable]

        if self._n < self.window:
            return None

        n = self._n
        rms = math.sqrt(self._sq / n)
        self._audio_samples += n
        out = {
            "rms": rms,
            "peak": self._peak,
            # เงียบสนิท → -inf ทำให้ format พัง/อ่านไม่รู้เรื่อง → ปักพื้นที่ -100
            "dbfs": max(-100.0, 20 * math.log10(rms / 32767.0)) if rms > 0 else -100.0,
            "samples": n,
            "audio_sec": self._audio_samples / self.rate,
            "wall_sec": time.monotonic() - self._t0,
        }
        self._sq = 0
        self._peak = 0
        self._n = 0
        return out

    @staticmethod
    def format_line(r: dict) -> str:
        return (
            f"[VoiceLevel] {r['dbfs']:.1f} dBFS (rms {r['rms']:.0f} · peak {r['peak']}) "
            f"· เสียงสะสม {r['audio_sec'] / 60:.1f} นาที · ตั้งแต่เริ่ม {r['wall_sec'] / 60:.1f} นาที"
        )


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
