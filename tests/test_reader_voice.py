"""โหมด "ขวัญอ่านหนังสือ" — ต่อ BookStore/next_block เข้า Gemini Live

user เคาะ 2026-08-11 หลังจูน 4 รอบ (วัดด้วยท่อนจริง 586 ตัวอักษรชุดเดียวกันทุกรอบ):

    ① เครื่องอ่านเรียบๆ      49.0 วิ  → เรียบไป
    ② กระชับ                39.5 วิ  → เร็วไป
    ③ นักพากย์ใส่อารมณ์      61.6 วิ  → ช้าไป (คำว่า "นักพากย์" ลากทุกอย่างช้าลง 56%)
    ④ กระชับ+อารมณ์ผ่านน้ำเสียง 40.9 วิ → ✅ user เคาะ
    ทุกรอบตรงต้นฉบับ 100.0% (difflib หลัง normalize ช่องว่าง)

🔑 บทเรียนจากการจูน: **สั่งสิ่งที่ห้ามทำให้ชัด ("ไม่ใช่ผ่านการชะลอ · คงจังหวะเท่าเดิม")
ได้ผลกว่าขอสิ่งที่อยากได้เพิ่ม** — รอบ ③ พังเพราะโมเดลตีความ อารมณ์=ทอดจังหวะ

ทำไมใช้ Live API ไม่ใช่ Gemini TTS: เสียง Aoede ตัวเดียวกัน แต่ TTS ติดเพดาน
10 req/วัน (อ่านทั้งเล่ม = ~9.7 ปี) ส่วน Live ไม่ชนโควตา (วัดจริง: คุย 35 นาทีรวด)
· ยืนยันแล้วว่า Live อ่านคำต่อคำได้ 100% ทั้งท่อน 256 และ 586-598 ตัวอักษร x3 ท่อนต่อเนื่อง
"""

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


class TestReaderConfig:
    @pytest.fixture()
    def cfg(self):
        from utils.voice import build_reader_config

        return build_reader_config(resume_handle=None)

    def test_uses_the_same_kwan_voice(self, cfg):
        """user เลือก "เสียงขวัญ_เดิม" — ต้องเป็น Aoede ตัวเดียวกับโหมดคุย ห้ามสลับคน"""
        from utils.voice import DEFAULT_VOICE

        assert cfg.speech_config.voice_config.prebuilt_voice_config.voice_name == DEFAULT_VOICE

    def test_no_tools_at_all(self, cfg):
        """🔴 ห้ามมี tool ค้นเว็บ — เจอมาแล้วตอนโหมดคุย: โมเดลเลือก "ค้น" แทน "ตอบ"
        ถ้าโหมดอ่านมี tool มันอาจเลือก "ค้น" แทน "อ่าน" แล้วเงียบไปทั้ง turn"""
        assert not cfg.tools

    def test_rendering_knobs_match_the_chat_voice(self, cfg):
        """seed/temperature ต้องตรงกับโหมดคุย — ไม่งั้นเสียงอ่านหนังสือเป็น "คนละคน"
        กับเสียงคุย ทั้งที่ user เลือกเพราะอยากได้เสียงเดิม"""
        from utils.voice import VOICE_SEED, VOICE_TEMPERATURE

        assert cfg.seed == VOICE_SEED
        assert cfg.temperature == VOICE_TEMPERATURE
        assert cfg.enable_affective_dialog is False

    def test_prompt_is_the_round4_narration(self, cfg):
        """คำกำกับที่ user เคาะ — สามชิ้นที่ขาดไม่ได้:
        อ่านครบทุกคำ · อารมณ์ผ่านน้ำเสียงไม่ใช่การชะลอ · ห้ามพูดนอกข้อความ"""
        text = cfg.system_instruction.parts[0].text
        assert "ครบทุกคำ" in text
        assert "ไม่ใช่ผ่านการชะลอ" in text
        assert "ห้ามสรุป" in text and "ห้ามพูดอะไรนอกจากข้อความที่ได้รับ" in text

    def test_resumption_handle_is_carried(self):
        """go_away มาทุก ~9 นาที — ไม่มี handle = เริ่มอ่านใหม่โดยเสียบริบทเสียง"""
        from utils.voice import build_reader_config

        cfg = build_reader_config(resume_handle="h-77")
        assert cfg.session_resumption.handle == "h-77"

    def test_transcription_still_on_for_verbatim_check(self, cfg):
        """output_transcription คือเครื่องมือเดียวที่ใช้ตรวจว่าอ่านตรงต้นฉบับจริง
        (เกณฑ์ 100% ที่ใช้จูนมาทั้ง 4 รอบวัดจากตัวนี้) — ปิดเมื่อไหร่ตาบอดทันที"""
        assert cfg.output_audio_transcription is not None


class TestReadingTurnDecision:
    """ตรรกะ "จบท่อนแล้วไปต่อไหม" — pure → เทสได้โดยไม่ต้องต่อ Gemini/WS"""

    def test_advances_to_next_block_when_playing(self):
        from utils.voice import next_read_action

        act = next_read_action(paused=False, block="ก" * 500, at_end=False)
        assert act == "read"

    def test_pausing_stops_the_feed(self):
        """พัก = แค่หยุดป้อน ไม่ต้องรื้อ session — resume กลับมาอ่านต่อได้ทันที"""
        from utils.voice import next_read_action

        assert next_read_action(paused=True, block="x", at_end=False) == "wait"

    def test_end_of_book_finishes(self):
        from utils.voice import next_read_action

        assert next_read_action(paused=False, block="", at_end=True) == "finish"

    def test_empty_block_midbook_skips_forward(self):
        """ท่อนว่าง (ช่วงที่มีแต่ขึ้นบรรทัด) — ต้องข้ามไปท่อนถัดไป ไม่ใช่ป้อนความว่าง
        ให้โมเดล (ป้อนข้อความว่างแล้วโมเดลจะตอบอะไรก็ได้ = หลุดจากการอ่าน)"""
        from utils.voice import next_read_action

        assert next_read_action(paused=False, block="   \n ", at_end=False) == "skip"


class TestReaderPacing:
    """ตัวคุมจังหวะป้อนท่อน — เจอ 2026-08-14: Gemini ผลิตเสียงเร็วกว่า realtime มาก
    เซิร์ฟเวอร์ป้อนรัวจนที่คั่นวิ่ง 3,535→48,141 ใน ~4 นาที (หูจริงฟังถึงแค่ ~7,000)
    พอ session ล่มกลางทาง user เปิดใหม่ = ข้ามเนื้อเรื่องหลายสิบนาที

    หลัก: เสียงที่ผลิตแล้ว (วัดจาก byte ที่ส่ง) นำ "เวลาฟังจริง" (นาฬิกาเดินเฉพาะ
    ตอนไม่พัก) ได้ไม่เกิน READER_MAX_LEAD_SECONDS — pure function เทสได้ตรงๆ"""

    def test_no_wait_when_behind_or_within_lead(self):
        from utils.voice import reader_pacing_wait

        assert reader_pacing_wait(audio_seconds_sent=10.0, listened_seconds=30.0) == 0.0
        assert reader_pacing_wait(audio_seconds_sent=30.0, listened_seconds=10.0, lead=25.0) == 0.0

    def test_waits_by_the_excess_beyond_lead(self):
        from utils.voice import reader_pacing_wait

        assert reader_pacing_wait(audio_seconds_sent=100.0, listened_seconds=10.0, lead=25.0) == 65.0

    def test_default_lead_bounds_how_far_bookmark_outruns_ears(self):
        from utils.voice import READER_MAX_LEAD_SECONDS, reader_pacing_wait

        at_limit = reader_pacing_wait(READER_MAX_LEAD_SECONDS, 0.0)
        assert at_limit == 0.0
        assert reader_pacing_wait(READER_MAX_LEAD_SECONDS + 1.0, 0.0) == 1.0


class TestServerWiring:
    """กัน "ฟังก์ชันถูกแต่ไม่มีใครเรียก" — แบบเดียวกับ TestServerUsesBuilder"""

    @pytest.fixture()
    def handler(self):
        src = (REPO / "server.py").read_text(encoding="utf-8")
        assert '@app.websocket("/ws/reader")' in src, "ไม่มี endpoint /ws/reader"
        ws = src[src.index('@app.websocket("/ws/reader")'):]
        return ws[: ws.index("\n@app.")] if "\n@app." in ws else ws

    def test_handler_uses_the_reader_config(self, handler):
        assert "build_reader_config(" in handler

    def test_handler_is_gated_by_auth(self, handler):
        """WS ไม่ผ่าน middleware (บทเรียน BaseHTTPMiddleware) — ต้อง gate เองก่อน accept"""
        assert "websocket_authorized(" in handler

    def test_bookmark_advances_only_after_turn_completes(self, handler):
        """ที่คั่นหน้าเลื่อนเมื่อโมเดลอ่านท่อนจบเท่านั้น — เลื่อนตอนป้อนแล้วแอปดับ
        กลางท่อน = ท่อนนั้นหายถาวร · เลื่อนหลังจบ = แค่ฟังซ้ำบางส่วน (ยอมได้)"""
        # 🔴 เขียนครั้งแรกเช็คแค่ "_marks.set อยู่หลังคำว่า turn_complete ที่ไหนสักแห่ง"
        # → mutation ที่ย้ายตัวเลื่อนไป *ก่อน* `if turn_done:` ยังผ่านสบาย (มันก็ยังอยู่
        # "หลังคำว่า turn_complete" ในไฟล์อยู่ดี) ⇒ ต้องผูกกับบล็อกเงื่อนไขจริง:
        # ตัวเลื่อนใน feed_loop ต้องอยู่ *ข้างใน* `if turn_done:` เท่านั้น
        feed = handler[handler.index("async def feed_loop"):]
        guard = feed.index("if turn_done:")
        sets_before_guard = feed[:guard].count("_marks.set(source, new_pos)")
        assert sets_before_guard == 1, (
            "ต้องมีตัวเลื่อนก่อน guard แค่ตัวเดียว (สาย skip ท่อนว่าง) — "
            f"เจอ {sets_before_guard} = มีตัวเลื่อนหลุดออกนอกเงื่อนไข turn_done"
        )
        after_guard = feed[guard:guard + 300]
        assert "_marks.set(source, new_pos)" in after_guard, (
            "ใน `if turn_done:` ไม่มีตัวเลื่อนที่คั่น — ท่อนอ่านจบแล้วที่คั่นไม่ขยับ"
        )

    def test_handler_handles_go_away(self, handler):
        """อ่านยาวเป็นชั่วโมง — go_away มาทุก ~9 นาทีแน่นอน ไม่รับมือ = ตายทุก 9 นาที"""
        assert "live_control_signals(" in handler

    def test_feed_is_paced_by_listening_clock(self, handler):
        """เหตุการณ์จริง 2026-08-14 10:15-10:19: ป้อนไม่คุมจังหวะ → ที่คั่นนำหู ~40k
        ตัวอักษร · feed_loop ต้องถาม reader_pacing_wait ก่อนป้อนทุกท่อน"""
        feed = handler[handler.index("async def feed_loop"):]
        assert "reader_pacing_wait(" in feed, "ไม่มีตัวคุมจังหวะ — ที่คั่นจะวิ่งนำหูอีก"

    def test_stall_watchdog_reconnects_instead_of_hanging_forever(self, handler):
        """เหตุการณ์จริง 2026-08-14 10:19:30: Gemini หยุดส่งเฉยๆ (ไม่ error ไม่
        turn_complete ไม่ go_away) → feed_loop รอไปตลอดกาล = "ฟังอยู่ ก็เงียบไปเลย"
        และไม่มี log สักบรรทัด · ต้องมีเพดานรอ แล้วต่อ session ใหม่อ่านท่อนนี้ซ้ำ"""
        feed = handler[handler.index("async def feed_loop"):]
        assert "READER_STALL_TIMEOUT" in feed, "ไม่มี watchdog — เงียบค้างได้ไม่จำกัด"
        assert "TimeoutError" in feed

    def test_silent_turn_end_reconnects_too(self, handler):
        """receive() จบเองโดยไม่มี turn_complete (session ตายเงียบ) ต้อง reconnect
        ไม่ใช่วนไปป้อนท่อนเดิมบน session ที่ตายแล้ว — และต้องมี log ให้สืบย้อนได้"""
        feed = handler[handler.index("async def feed_loop"):]
        guard = feed.index("if turn_done:")
        after = feed[guard:guard + 900]
        assert "regen.set()" in after, "จบ turn เงียบแล้วไม่ reconnect — ค้างเหมือนเดิม"
