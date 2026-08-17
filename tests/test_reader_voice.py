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

    def test_session_open_and_close_are_logged(self, handler):
        """🔑 ท่อนี้เคย log เฉพาะทางสายพัง — 17 วันได้ 3 บรรทัด (นับจริง 2026-08-17)

        ผลคือทุกอาการของโหมดอ่าน (สองเสียง · ที่คั่นวิ่ง · กดพักไม่หยุด) **พิสูจน์
        จาก log ไม่ได้เลยสักข้อ** — ไม่ใช่ "หาแล้วไม่เจอ" แต่ "มองไม่เห็นโดยโครงสร้าง"
        หนึ่งบรรทัดตอนเปิด + หนึ่งตอนปิด = ตอบได้ว่ามี session ทับช่วงเวลากันไหม
        """
        assert "เปิด {session_tag}" in handler, "ไม่ log ตอนเปิด session"
        assert "ปิด {session_tag}" in handler, "ไม่ log ตอนปิด session"
        assert "finally:" in handler, (
            "บรรทัด 'ปิด' ต้องอยู่ใน finally — ไม่งั้นทางที่ error จะไม่ถูกบันทึก "
            "แล้ว log จะเห็นแต่ 'เปิด' ค้างเป็นแถว"
        )

    def test_regen_flushes_stale_audio_before_rereading(self, handler):
        """ต่อ session ใหม่ = อ่านท่อนเดิมซ้ำตั้งแต่ต้น (ตั้งใจ: ฟังซ้ำดีกว่าเนื้อหาหาย)

        🔴 user ยืนยันด้วยหู 2026-08-14: "ประโยคเดิมซ้ำ" — เพราะ WebSocket เป็นสายเดิม
        เสียงท่อนเก่าที่ค้างใน jitter buffer ฝั่ง client เล่นต่อ แล้วตามด้วยท่อนเดิม
        ทั้งท่อนอีกรอบ ⇒ ถ้าจะอ่านซ้ำ **ต้องสั่งล้างของเก่าก่อนเสมอ**
        (บทเรียนเดียวกับปุ่มพักที่เขียนไว้แล้วใน bookreader.ts แต่ไม่ได้เอามาใช้ตรงนี้)

        ผูก assertion กับบล็อก regen จริง ไม่ใช่ "มีคำว่า flush ที่ไหนสักแห่งในไฟล์"
        """
        marker = "if regen.is_set() and not stop.is_set():"
        assert marker in handler, "ไม่พบบล็อก regen — โครงเปลี่ยนไปแล้ว ต้องแก้เทสนี้ด้วย"
        block = handler[handler.index(marker):]
        block = block[: block.index("continue")]
        assert '"flush"' in block, (
            "regen ต่อ session ใหม่แล้วอ่านท่อนซ้ำ โดยไม่สั่ง client ล้างเสียงค้าง "
            "→ ผู้ใช้ได้ยินท้ายท่อนเก่าต่อด้วยท่อนเดิมทั้งท่อน"
        )


class TestPauseStopsAudioMidBlock:
    """🔴 user รายงาน 2026-08-15 ตี 1: **"กดพักแล้วไม่พักเลย พูดต่อไปอีก"**

    ต้นเหตุ: ลูปสตรีมเสียงข้างใน (`async for r in session.receive()`) เช็คแต่
    `stop.is_set()` — **ไม่เคยเช็ค `paused` เลย** · ธง `paused` ถูกอ่านที่หัว
    feed_loop ผ่าน `next_read_action` เท่านั้น = "จบท่อนแล้วค่อยพัก"
    ท่อนละ READ_BLOCK_CHARS (600 ตัวอักษร ≈ ราว 1 นาทีของเสียง)
    ⇒ กดพักกลางท่อน = ยังพูดต่ออีกเป็นนาที ตรงกับที่ user ได้ยินเป๊ะ

    ℹ️ ตัวแก้ชุดนี้ร่างไว้ตั้งแต่ 08-15 แต่ผูกกับตัวคุมจังหวะของ 55b8594 ซึ่งถูก
    revert ไปแล้ว (2670c8e) — รอบนี้เอาเฉพาะส่วนที่แยกออกจาก pacing ได้
    """

    def test_pause_mid_block_aborts_instead_of_streaming_on(self):
        from utils.voice import reader_stream_action

        assert reader_stream_action(stopped=False, paused=True) == "abort"

    def test_normal_chunk_is_sent(self):
        from utils.voice import reader_stream_action

        assert reader_stream_action(stopped=False, paused=False) == "send"

    def test_stop_beats_pause(self):
        """ปิด WS ระหว่างพักอยู่ — ต้องเลิกทั้งหมด ไม่ใช่ค้างรออ่านต่อ"""
        from utils.voice import reader_stream_action

        assert reader_stream_action(stopped=True, paused=True) == "stop"

    def test_streaming_loop_actually_consults_paused(self):
        """กัน "ฟังก์ชันถูกแต่ไม่มีใครเรียก" — ผูกกับลูปสตรีมจริง ไม่ใช่แค่มีคำนี้ในไฟล์

        ช่วงที่ตรวจคือตั้งแต่เปิด iterator ของ session.receive() จนถึง `if turn_done:`
        = ลูปที่ยิง chunk ออก WS · ถ้าไม่มีการเช็คพักในนี้ = พักไม่ทันท่อน
        """
        src = (REPO / "server.py").read_text(encoding="utf-8")
        ws = src[src.index('@app.websocket("/ws/reader")'):]
        feed = ws[ws.index("async def feed_loop"):]
        loop = feed[feed.index("session.receive()"): feed.index("if turn_done:")]
        assert "paused" in loop, (
            "ลูปสตรีมเสียงไม่เคยดูธง paused — กดพักแล้วเสียงจะไหลต่อจนจบท่อน"
        )

    def test_aborting_does_not_advance_the_bookmark(self):
        """พักกลางท่อนแล้วที่คั่นต้องไม่ขยับ — กดอ่านต่อได้ยินท่อนนี้ใหม่ตั้งแต่ต้น
        (ดีลเดียวกับทั้งระบบ: ฟังซ้ำดีกว่าเนื้อหาหาย)"""
        src = (REPO / "server.py").read_text(encoding="utf-8")
        ws = src[src.index('@app.websocket("/ws/reader")'):]
        feed = ws[ws.index("async def feed_loop"):]
        loop = feed[feed.index("session.receive()"): feed.index("if turn_done:")]
        assert "_marks.set(" not in loop, (
            "มีตัวเลื่อนที่คั่นอยู่ในลูปสตรีม — พักกลางท่อนแล้วเนื้อหาจะหาย"
        )


class TestRereadCurrentBlock:
    """🔁 "อ่านท่อนนี้ใหม่" (user เคาะ 2026-08-17)

    บริบท: ตอนนิยายอ่านอยู่ **ไมค์ปิด** (user เคาะวันเดียวกัน) ⇒ สั่งด้วยเสียงไม่ได้
    จึงต้องมีปุ่ม · ฟังไม่ทันตรงไหนกดแล้วได้ยินท่อนนั้นใหม่ตั้งแต่ต้น

    ใช้เส้นทางเดียวกับ abort ของปุ่มพัก: ทิ้ง turn ปัจจุบัน **ไม่เลื่อนที่คั่น** แล้ว
    regen — ซึ่ง regen สั่ง flush ให้อยู่แล้ว (ดู test_regen_flushes_stale_audio)
    ต่างกันตรงไม่ตั้งธง paused จึงป้อนท่อนเดิมต่อทันทีแทนที่จะรอกดอ่านต่อ
    """

    def test_reread_restarts_the_block(self):
        from utils.voice import reader_stream_action

        assert reader_stream_action(stopped=False, paused=False, reread=True) == "restart"

    def test_pause_beats_reread(self):
        """กดพักแล้วกด 🔁 ตามติด — ต้องพักไว้ก่อน ไม่ใช่วิ่งอ่านต่อเอง"""
        from utils.voice import reader_stream_action

        assert reader_stream_action(stopped=False, paused=True, reread=True) == "abort"

    def test_stop_beats_everything(self):
        from utils.voice import reader_stream_action

        assert reader_stream_action(stopped=True, paused=True, reread=True) == "stop"

    def test_reread_defaults_off(self):
        """ค่าปริยายต้องไม่เปลี่ยนพฤติกรรมเดิม"""
        from utils.voice import reader_stream_action

        assert reader_stream_action(stopped=False, paused=False) == "send"

    def test_recv_loop_accepts_the_reread_command(self):
        src = (REPO / "server.py").read_text(encoding="utf-8")
        ws = src[src.index('@app.websocket("/ws/reader")'):]
        recv = ws[ws.index("async def recv_loop"): ws.index("async def feed_loop")]
        assert '"reread"' in recv, "recv_loop ไม่รับคำสั่ง reread — ปุ่มจะกดแล้วเงียบ"

    def test_stream_loop_consults_reread(self):
        """กัน "ฟังก์ชันถูกแต่ไม่มีใครเรียก" — ผูกกับลูปสตรีมจริง"""
        src = (REPO / "server.py").read_text(encoding="utf-8")
        ws = src[src.index('@app.websocket("/ws/reader")'):]
        feed = ws[ws.index("async def feed_loop"):]
        loop = feed[feed.index("session.receive()"): feed.index("if turn_done:")]
        assert "reread" in loop, "ลูปสตรีมไม่ดูธง reread — กดปุ่มแล้วต้องรอจนจบท่อน"
