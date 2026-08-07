"""เสียงผู้ช่วยต้องเป็น "คนเดิม" ทุกครั้ง — user รายงาน 2026-08-04: "เหมือนสลับเป็นคนละคน"

**สิ่งที่ตรวจแล้วพบว่า *ไม่ใช่* ต้นเหตุ (บันทึกไว้กันขุดซ้ำ):**
- ไม่ใช่ `utils/tts.py` — `/api/tts` ถูกเรียก **0 ครั้ง** ในล็อก prod ทั้งไฟล์
  (2026-07-31 → 2026-08-04) เสียงที่ user ได้ยินมาจาก `/ws/voice/{slug}` เส้นเดียว
- ไม่ใช่ชื่อเสียงถูกสลับกลางทาง — `voice` ถูกคำนวณครั้งเดียวนอกลูป reconnect
- ไม่ใช่ session regeneration ที่เพิ่งเพิ่มใน `e6b486d` — voice session สุดท้ายใน prod คือ
  2026-08-03 21:52 ส่วน `e6b486d` ขึ้น 2026-08-04 05:03 → user ยังไม่เคยเจอโค้ดนั้น

**ต้นเหตุจริงที่เหลือ 2 ข้อ (ทั้งคู่ทำให้ "ชื่อเสียงเดิม แต่เสียงคนละคน"):**

1. **`GEMINI_LIVE_MODEL` ชี้ alias ลอย `-latest`** — ถามจาก API จริงบน prod: alias นี้มี
   snapshot จริงอยู่ข้างหลังอย่างน้อย 2 ตัว (`-preview-09-2025`, `-preview-12-2025`)
   Google เลื่อน alias เมื่อไหร่ เสียงเปลี่ยนทันทีโดยฝั่งเราไม่มีอะไรเปลี่ยนเลย
   → **เปลี่ยนแปลงที่มองไม่เห็นทั้งใน diff และใน log** = เข้าเกณฑ์ "เครื่องมือวัดโกหก"

2. **ไม่มีอะไรตรึง "วิธีเรนเดอร์เสียง" ข้าม session** — native-audio โมเดลสังเคราะห์น้ำเสียง
   ใหม่ทุกครั้งที่เปิด session ถ้า `seed`/`temperature` ไม่ถูกตั้ง ทุกครั้งที่ต่อ session ใหม่
   (go_away regen ฝั่ง server **หรือ** retry ฝั่ง client) = สุ่มโทนใหม่ทั้งที่ voice_name เท่าเดิม

3. (กับดักที่ยังไม่ออกอาการ) `VOICE_MAP` มี **2 ก๊อป** — `utils/voice.py` กับ `utils/tts.py`
   และตัวที่ `server.py` ใช้จริงคือของ `tts.py` → คนที่แก้ไฟล์ชื่อ `voice.py` เพื่อเปลี่ยนเสียง
   จะแก้แล้วไม่มีอะไรเกิดขึ้น (รูปแบบเดียวกับ alias `_SKILLS_DB` ที่เพิ่งถอดไป)

⚠️ **ข้อจำกัดของเทสชุดนี้:** พิสูจน์ได้แค่ว่า "เราตรึงค่าที่ตรึงได้แล้ว" — พิสูจน์ไม่ได้ว่า
หูคนจะได้ยินว่าเหมือนเดิม เพราะ Gemini ไม่รับประกัน determinism ของ audio ต่อให้ seed ตรง
ตัวชี้ขาดจริงคือ user คุยยาวเกิน 10 นาที (ข้าม go_away) แล้วบอกว่ายังสลับคนอีกไหม
"""

import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


class TestSingleSourceOfTruth:
    """เสียงต้องมีที่นิยามที่เดียว — สองที่เมื่อไหร่ก็หลุดเมื่อนั้น"""

    def test_tts_does_not_define_its_own_voice_map(self):
        src = (REPO / "utils" / "tts.py").read_text(encoding="utf-8")
        assert "VOICE_MAP: dict" not in src and "VOICE_MAP = {" not in src, (
            "utils/tts.py ยังนิยาม VOICE_MAP เอง — ต้อง import จาก utils/voice.py "
            "ไม่งั้นแก้ไฟล์หนึ่งแล้วอีกไฟล์ไม่ตาม"
        )

    def test_server_resolves_voice_from_voice_module(self):
        src = (REPO / "server.py").read_text(encoding="utf-8")
        ws = src[src.index('@app.websocket("/ws/voice/'):]
        ws = ws[: ws.index("\n@app.")] if "\n@app." in ws else ws
        assert "from utils.tts import" not in ws, (
            "voice handler ยังดึงค่าเสียงจาก utils.tts — เสียงของ voice ต้องมาจาก utils.voice"
        )

    def test_no_dead_slugs_in_voice_map(self):
        """slug ที่ไม่มีผู้ช่วยจริงแล้วต้องไม่ค้างในตาราง (fa/khim ถอดไปตั้งแต่ 2026-06-16)"""
        from assistants.config import ASSISTANTS
        from utils.voice import VOICE_MAP

        real = {a.get("slug") for a in ASSISTANTS.values()}
        dead = set(VOICE_MAP) - real
        assert not dead, f"VOICE_MAP มี slug ที่ไม่มีผู้ช่วยแล้ว: {sorted(dead)}"


class TestVoiceIsStable:
    def test_every_assistant_and_unknown_slug_get_the_same_voice(self):
        """ระบบนี้มีผู้ช่วยเสียงเดียว — fallback ต้องไม่ใช่เสียงคนละตัวกับ slug ที่รู้จัก

        ถ้า fallback ต่างจากตัวจริง วันที่ frontend ส่ง slug เพี้ยน (เช่นส่งชื่อแทน slug)
        ผู้ใช้จะได้ยิน "คนละคน" ทันทีโดยไม่มี error อะไรโผล่เลย
        """
        from assistants.config import ASSISTANTS
        from utils.voice import DEFAULT_VOICE, resolve_voice

        voices = {resolve_voice(a["slug"]) for a in ASSISTANTS.values()}
        voices.add(resolve_voice("slug-ที่-ไม่มีจริง"))
        voices.add(resolve_voice(""))
        assert len(voices) == 1, f"ได้เสียงหลายตัว: {voices} — ต้องเป็นเสียงเดียวทั้งระบบ"
        assert voices == {DEFAULT_VOICE}

    def test_resolve_voice_is_case_insensitive(self):
        from utils.voice import resolve_voice

        assert resolve_voice("KWAN") == resolve_voice("kwan")


class TestModelIsPinned:
    """alias ลอยคือการเปลี่ยนโมเดลโดยไม่มีใครกด deploy"""

    def test_default_live_model_is_not_a_floating_alias(self):
        from utils.voice import GEMINI_LIVE_MODEL_DEFAULT

        assert not GEMINI_LIVE_MODEL_DEFAULT.endswith("-latest"), (
            f"{GEMINI_LIVE_MODEL_DEFAULT!r} เป็น alias ลอย — Google เลื่อนเมื่อไหร่ "
            "เสียงเปลี่ยนทันทีโดย diff ของเราว่างเปล่า"
        )

    def test_core_config_and_voice_module_agree(self):
        """default 2 ที่ต้องตรงกัน ไม่งั้น WS กับที่อื่นใช้คนละโมเดล"""
        import core.config as cfg
        from utils.voice import GEMINI_LIVE_MODEL_DEFAULT

        default_in_config = cfg.GEMINI_LIVE_MODEL if not os.getenv("GEMINI_LIVE_MODEL") else None
        if default_in_config is not None:
            assert default_in_config == GEMINI_LIVE_MODEL_DEFAULT


class TestModelFieldCompatibility:
    """ตรึงผลที่ **วัดจริงบน prod** ไว้เป็นกฎ ไม่ใช่คอมเมนต์ที่ไม่มีใครกลับมาอ่าน

    วัด 2026-08-04 (Live session จริง เคสละ 2 รอบ นับไบต์เสียงที่ได้กลับ):
      · `temperature` บน `2.5-native-audio-*` → **0 ไบต์ เงียบสนิท ไม่ error**
      · `enable_affective_dialog=True` บน `3.1-flash-live` → APIError 1011
      · `seed` ตรึงการสุ่มได้จริงเฉพาะบน `3.1-flash-live`

    เทสนี้ยิง API ไม่ได้ (ไม่มี key ใน CI + เสียเงิน) จึงทำได้แค่กันการจับคู่ที่รู้แล้วว่าพัง
    ถ้าจะเปลี่ยน default ไปสายอื่น **ต้องรันตารางวัดใหม่ก่อน** อย่าเชื่อเทสนี้ว่าครอบคลุม
    """

    def test_temperature_is_not_set_on_models_that_go_silent_with_it(self):
        from utils.voice import GEMINI_LIVE_MODEL_DEFAULT, VOICE_TEMPERATURE

        if "native-audio" in GEMINI_LIVE_MODEL_DEFAULT:
            assert VOICE_TEMPERATURE is None, (
                f"{GEMINI_LIVE_MODEL_DEFAULT} + temperature = เสียงหายเงียบๆ (วัดแล้ว 0 ไบต์ 2 รอบ) "
                "— ถ้าจะใช้โมเดลสายนี้ต้องตั้ง VOICE_TEMPERATURE = None"
            )

    def test_affective_dialog_never_enabled(self):
        """True พัง 1011 บน 3.1 · และ 'ปรับน้ำเสียงตามอารมณ์' ขัดกับ 'สม่ำเสมอ' อยู่แล้ว"""
        from utils.voice import build_live_config

        cfg = build_live_config(slug="kwan", system_instruction="x", resume_handle=None)
        assert cfg.enable_affective_dialog is False


class TestLiveConfigPinsRendering:
    """สิ่งที่ทำให้ session ใหม่ฟังเหมือน session เดิม"""

    @pytest.fixture()
    def cfg(self):
        from utils.voice import build_live_config

        return build_live_config(slug="kwan", system_instruction="ทดสอบ", resume_handle=None)

    def test_voice_name_is_set(self, cfg):
        from utils.voice import DEFAULT_VOICE

        assert cfg.speech_config.voice_config.prebuilt_voice_config.voice_name == DEFAULT_VOICE

    def test_seed_and_temperature_are_pinned(self, cfg):
        assert cfg.seed is not None, "ไม่ตั้ง seed → session ใหม่สุ่มโทนใหม่ทุกครั้ง"
        assert cfg.temperature is not None, "ไม่ตั้ง temperature → ความแปรปรวนของน้ำเสียงสูงสุด"
        assert 0.0 <= cfg.temperature <= 1.0

    def test_speaking_can_be_interrupted(self, cfg):
        """พูดแทรกตอนโมเดลกำลังพูดต้องตัด turn ได้จริง (user เคาะ 2026-08-07)

        เดิมตั้ง `NO_INTERRUPTION` ไว้เป็น "เข็มขัดเส้นที่สอง" คู่กับ half-duplex gate
        ฝั่ง client — ผลคือถอด gate ฝั่ง client แล้วก็ยังแทรกไม่ได้ เพราะ server
        สั่งโมเดลไว้ว่าห้ามตัดคำตอบตัวเอง (พิมพ์แทรกได้เพราะไปคนละเส้น:
        `send_client_content(turn_complete=True)` = เริ่ม turn ใหม่ ไม่ผ่าน VAD)

        ⚠️ ยังปลอดภัยเพราะ **ค่าเริ่มต้นฝั่ง client ยังปิดไมค์ตอน AI พูด**
        (`micShouldSend` → `gate.micOpen`) ⇒ ไม่มีเสียงไปถึงโมเดลให้ใช้ตัด turn เลย
        ความเสี่ยง echo จะเกิดเฉพาะกับคนที่เปิดสวิตช์ "พูดแทรกได้" ซึ่งคือเจตนา
        """
        from google.genai import types

        handling = cfg.realtime_input_config.activity_handling
        assert handling == types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS, (
            f"activity_handling = {handling} → พูดแทรกไม่ได้"
        )

    def test_automatic_vad_still_on(self, cfg):
        """กลุ่มควบคุม: ถ้า VAD ถูกปิดไปด้วย hands-free จะพังทั้งโหมด ไม่ใช่แค่แทรกไม่ได้"""
        assert cfg.realtime_input_config.automatic_activity_detection is not None

    def test_affective_dialog_is_explicitly_off(self, cfg):
        """ปล่อย None = ยอมให้ค่า default ของโมเดลเปลี่ยนทีหลังโดยเราไม่รู้"""
        assert cfg.enable_affective_dialog is False

    def test_two_builds_produce_identical_rendering_knobs(self):
        """สร้างซ้ำต้องได้ค่าเดิมเป๊ะ — นี่คือสิ่งที่ทำให้ reconnect ไม่เปลี่ยนเสียง"""
        from utils.voice import build_live_config

        a = build_live_config(slug="kwan", system_instruction="x", resume_handle=None)
        b = build_live_config(slug="kwan", system_instruction="x", resume_handle="handle-abc")
        assert (a.seed, a.temperature) == (b.seed, b.temperature)
        assert (
            a.speech_config.voice_config.prebuilt_voice_config.voice_name
            == b.speech_config.voice_config.prebuilt_voice_config.voice_name
        )

    def test_resume_handle_is_carried_through(self):
        from utils.voice import build_live_config

        cfg = build_live_config(slug="kwan", system_instruction="x", resume_handle="h-1")
        assert cfg.session_resumption.handle == "h-1"

    def test_keeps_existing_behaviour(self, cfg):
        """กันการรื้อ config เดิมทิ้งโดยไม่ตั้งใจ (transcription/VAD/compression)"""
        assert cfg.response_modalities == ["AUDIO"]
        assert cfg.output_audio_transcription is not None
        assert cfg.input_audio_transcription is not None
        assert cfg.context_window_compression is not None
        assert cfg.realtime_input_config is not None


class TestServerUsesBuilder:
    def test_server_delegates_live_config(self):
        src = (REPO / "server.py").read_text(encoding="utf-8")
        ws = src[src.index('@app.websocket("/ws/voice/'):]
        ws = ws[: ws.index("\n@app.")] if "\n@app." in ws else ws
        assert "build_live_config(" in ws, "voice handler ไม่ได้ใช้ build_live_config()"
        assert "PrebuiltVoiceConfig(" not in ws, (
            "voice handler ยังประกอบ speech_config เอง — ค่าจะหลุดจาก utils/voice.py ได้อีก"
        )
