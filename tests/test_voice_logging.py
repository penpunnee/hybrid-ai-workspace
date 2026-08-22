"""log วินิจฉัยที่ขาดไป — งานค้างข้อ 1 + 4 ของ 2026-08-17

🔑 เหตุที่ไฟล์นี้เกิด: อาการ **"คำตอบหลังค้นเว็บหาย เหลือแต่ข้อความ"** พิสูจน์ไม่ได้
*โดยโครงสร้าง* ไม่ใช่ "หาแล้วไม่เจอ" — `interrupted` ไม่เคยถูก log สักบรรทัดเดียว
ตั้งแต่มีระบบ และ `/ws/reader` มี log 3 บรรทัดใน 17 วัน
⇒ ก่อนจะแก้อาการ ต้องทำให้ **เครื่องมือวัดมีตา** ก่อน (บทเรียนแม่บท: เครื่องมือวัด
โกหกมาแล้ว 8+ ครั้ง · ที่แย่กว่าคือเครื่องมือที่ไม่เคยมองเห็นอะไรเลย)

สมมติฐานที่ log ชุดนี้ต้องหักล้างหรือยืนยันให้ได้:
  ตอนค้นเว็บ server เงียบ 15-45 วิ ⇒ `HalfDuplexGate` ฝั่ง client หมดอายุ
  (`playUntil` ผูกกับความยาวเสียงที่ *ได้รับ* เท่านั้น) ⇒ ไมค์เปิดกลาง turn ⇒
  เสียงอะไรก็ได้เข้าไป → `START_OF_ACTIVITY_INTERRUPTS` → `interrupted` →
  `flushPlayback()` ล้างเสียงทิ้งแต่ไม่แตะข้อความ = ลายเซ็นตรงกับที่ user เล่า

ถ้าสมมติฐานผิด log จะฟ้องเอง: บรรทัด `interrupted` จะโชว์ "เงียบมา 0.3s" ไม่ใช่ 20s
"""
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent


class TestInterruptLogLine:
    """บรรทัดตอนโดน `interrupted` ต้อง "ตอบคำถามได้ด้วยตัวเอง"

    คำถามเดียวที่ต้องตอบ: **ประตูไมค์เปิดเพราะ server เงียบยาว หรือ user พูดแทรกเอง**
    ⇒ ขาดตัวเลข "เงียบมากี่วินาที" ข้อเดียว บรรทัดนั้นก็ไร้ค่าเท่ากับไม่มี
    """

    def test_line_states_how_long_the_server_was_silent(self):
        from utils.voice import interrupt_log_line

        line = interrupt_log_line(silence_s=23.4, search_count=1, since_search_s=2.1)
        assert "23.4" in line, "ไม่บอกว่าเงียบมานานเท่าไร = แยกสองสาเหตุไม่ออก"

    def test_long_silence_is_flagged_as_the_suspected_cause(self):
        """เงียบเกินเกณฑ์ = เข้าเงื่อนไขสมมติฐาน — ต้องติดธงให้เห็นด้วยตาเปล่า
        (คนอ่าน log ทีหลังไม่จำเป็นต้องจำเลข 15 วิได้)"""
        from utils.voice import VOICE_SILENCE_SUSPECT_SEC, interrupt_log_line

        line = interrupt_log_line(
            silence_s=VOICE_SILENCE_SUSPECT_SEC + 0.1, search_count=1, since_search_s=1.0
        )
        assert "⚠️" in line

    def test_short_silence_is_not_flagged(self):
        """user พูดแทรกตอนขวัญกำลังพูดอยู่ = เงียบ ~0.2s — เป็นพฤติกรรมปกติ

        🔴 ถ้าติดธงทุกบรรทัด ธงจะไม่มีความหมาย = ตาบอดแบบใหม่ (ท่วม log จนไม่มีใครอ่าน)
        """
        from utils.voice import interrupt_log_line

        line = interrupt_log_line(silence_s=0.2, search_count=0, since_search_s=None)
        assert "⚠️" not in line

    def test_no_audio_yet_does_not_crash(self):
        """เพิ่งต่อ session แล้วโดนตัดเลย — ยังไม่เคยส่งเสียงสักไบต์

        `None` ต้องไม่ทำให้ log พัง: ตัว log เองล้มกลาง handler = เสีย turn ทั้ง turn
        เพื่อแลกกับบรรทัดวินิจฉัย = ขาดทุน
        """
        from utils.voice import interrupt_log_line

        line = interrupt_log_line(silence_s=None, search_count=0, since_search_s=None)
        assert isinstance(line, str) and line.strip()
        assert "⚠️" not in line, "ไม่รู้ค่า ≠ เข้าเงื่อนไข — ห้ามเดาว่าใช่"

    def test_line_says_when_mic_audio_last_arrived(self):
        """🔑 ตัวชี้ขาดที่ขาดมาตลอด — สองรอบที่ผ่านมาสรุปไม่ได้ว่าเสียงที่ตัด turn
        เข้ามา *ตอนไหน* ต้องเดาจากตำแหน่งเวลาของบรรทัด log แทน

        ที่ต้องแยกให้ออกหลังปิดช่องส่งไม้ต่อ (2026-08-22):
          · ไมค์เข้าเมื่อ ~0.0s ก่อน ⇒ client ยังส่งเสียงอยู่ตอนโดนตัด = ยังมีรูเหลือ
          · ไมค์เข้าเมื่อสิบ ๆ วินาทีก่อน ⇒ ประตูปิดได้จริง ต้นเหตุอยู่ที่อื่น
        ⇒ ไม่มีตัวเลขนี้ = วินิจฉัยรอบหน้าก็ยังเป็นการเดาเหมือนเดิม
        """
        from utils.voice import interrupt_log_line

        line = interrupt_log_line(
            silence_s=32.8, search_count=1, since_search_s=0.0, since_mic_s=0.3
        )
        assert "0.3" in line, "ไม่บอกว่าไมค์ส่งเสียงเข้ามาล่าสุดเมื่อไร = ชี้ขาดไม่ได้"

    def test_no_mic_audio_at_all_is_stated_not_guessed(self):
        """ไม่เคยมีเสียงไมค์เข้ามาเลย ≠ เพิ่งเข้ามา — ห้ามพิมพ์ 0.0 หลอกตา
        (กฎเดียวกับ silence_s=None: ไม่รู้ค่า ≠ เข้าเงื่อนไข)"""
        from utils.voice import interrupt_log_line

        line = interrupt_log_line(
            silence_s=5.0, search_count=0, since_search_s=None, since_mic_s=None
        )
        assert "0.0" not in line

    def test_mic_field_is_optional_so_old_callers_do_not_crash(self):
        from utils.voice import interrupt_log_line

        interrupt_log_line(silence_s=1.0, search_count=0, since_search_s=None)

    def test_search_context_is_included(self):
        """ต้องรู้ว่า turn นี้ค้นเว็บไปกี่ครั้ง + ค้นเสร็จไปนานแล้วเท่าไร"""
        from utils.voice import interrupt_log_line

        line = interrupt_log_line(silence_s=20.0, search_count=2, since_search_s=3.5)
        # ⚠️ เช็ค "2 ครั้ง" ไม่ใช่ "2" เฉยๆ — เลข 2 ไปโผล่ใน "20.0" ได้ฟรี
        # (assertion ที่ผ่านได้ด้วยตัวเลขจากที่อื่น = assertion ที่ไม่ได้ตรวจอะไรเลย)
        assert "2 ครั้ง" in line and "3.5" in line

    def test_no_search_this_turn_says_so_explicitly(self):
        """ไม่ได้ค้น = สมมติฐาน "เงียบเพราะค้นเว็บ" ใช้ไม่ได้กับบรรทัดนั้น
        ต้องเขียนออกมาตรงๆ ไม่ใช่เว้นว่างให้เดาว่า "ไม่มีข้อมูล" หรือ "เป็นศูนย์" """
        from utils.voice import interrupt_log_line

        line = interrupt_log_line(silence_s=0.3, search_count=0, since_search_s=None)
        assert "ไม่ได้ค้น" in line


class TestReaderBlockLogLines:
    """log ต่อท่อนของโหมดอ่าน — ~1 บรรทัด/นาที (ท่อนละราว 1 นาทีของเสียง)

    เป้าหมาย: ให้ "ตายเงียบกลางท่อน" ฟ้องตัวเองจาก log โดยไม่ต้องถาม user
    ลายเซ็นคือ **บรรทัด "ป้อนท่อน" ที่ไม่มีบรรทัด "ท่อนจบ" ตามมา**
    ⇒ จึงต้องมีสองบรรทัดคู่กัน มีแค่บรรทัดเดียวพิสูจน์อะไรไม่ได้
    """

    def test_feed_line_carries_tag_pos_and_length(self):
        from utils.voice import reader_feed_log_line

        line = reader_feed_log_line(tag="xianni#3f2a", pos=30251, block_len=742)
        assert "xianni#3f2a" in line and "30251" in line and "742" in line

    def test_turn_line_reports_audio_seconds_not_just_bytes(self):
        """ไบต์ดิบเทียบกับนาฬิกาไม่ได้ด้วยตาเปล่า — ต้องแปลงเป็นวินาทีของเสียง

        PCM 16-bit mono 24kHz = 48,000 ไบต์/วินาที ⇒ 2,400,000 ไบต์ = 50.0 วิ
        การเทียบ "เสียง 50 วิ ใช้เวลาจริง 55 วิ" คือสิ่งเดียวที่บอกได้ว่าท่อนนั้นปกติ
        """
        from utils.voice import reader_turn_log_line

        line = reader_turn_log_line(
            tag="xianni#3f2a", pos=30993, block_len=742, elapsed_s=55.0,
            audio_bytes=2_400_000,
        )
        assert "50.0" in line, "ไม่แปลงไบต์เป็นวินาทีของเสียง = เทียบกับนาฬิกาไม่ได้"
        assert "55.0" in line, "ไม่บอกเวลาจริง = ไม่มีอะไรให้เทียบ"

    def test_turn_that_produced_no_audio_is_flagged(self):
        """turn จบสมบูรณ์แต่ไม่มีเสียงเลย = โมเดลไม่ยอมอ่าน (คนละอาการกับตายเงียบ)
        ที่คั่นจะเลื่อนผ่านท่อนนี้ไปเงียบๆ ⇒ เนื้อหาหายไปหนึ่งท่อนโดยไม่มีใครรู้"""
        from utils.voice import reader_turn_log_line

        line = reader_turn_log_line(
            tag="xianni#3f2a", pos=30993, block_len=742, elapsed_s=1.2, audio_bytes=0
        )
        assert "⚠️" in line

    def test_healthy_turn_is_not_flagged(self):
        from utils.voice import reader_turn_log_line

        line = reader_turn_log_line(
            tag="xianni#3f2a", pos=30993, block_len=742, elapsed_s=55.0,
            audio_bytes=2_400_000,
        )
        assert "⚠️" not in line

    def test_both_lines_carry_the_tag(self):
        """🔴 เหตุผลที่ต้องมี tag: ตัวอ่านซ้อน (บั๊ก 08-15) ทำให้สอง session
        ป้อนท่อนสลับกันใน log เดียว — ไม่มี tag = อ่านไม่ออกว่าใครป้อนอะไร
        ซึ่งเป็นสาเหตุที่รอบนั้นต้องใช้หูของ user แทน log"""
        from utils.voice import reader_feed_log_line, reader_turn_log_line

        a = reader_feed_log_line(tag="pw#0001", pos=1, block_len=1)
        b = reader_turn_log_line(
            tag="pw#0002", pos=1, block_len=1, elapsed_s=1.0, audio_bytes=48_000
        )
        assert "pw#0001" in a and "pw#0002" in b


class TestVoiceHandlerWiring:
    """กัน "ฟังก์ชันถูกแต่ไม่มีใครเรียก" — ผูกกับ handler จริงใน server.py"""

    @pytest.fixture()
    def voice_ws(self):
        src = (REPO / "server.py").read_text(encoding="utf-8")
        marker = '@app.websocket("/ws/voice/{assistant_slug}")'
        assert marker in src, "ไม่มี endpoint /ws/voice"
        ws = src[src.index(marker):]
        return ws[: ws.index("\n@app.")] if "\n@app." in ws else ws

    @pytest.fixture()
    def send_loop(self, voice_ws):
        return voice_ws[voice_ws.index("async def send_loop"):]

    @pytest.fixture()
    def tool_calls(self, voice_ws):
        return voice_ws[
            voice_ws.index("async def answer_tool_calls"): voice_ws.index("async def send_loop")
        ]

    def test_interrupted_event_is_logged(self, send_loop):
        """หัวใจของงานนี้ — 17 วันที่ผ่านมาเหตุการณ์นี้ผ่านไปโดยไม่ทิ้งร่องรอยเลย"""
        assert "interrupt_log_line(" in send_loop, (
            "send_loop ไม่ log ตอนโดน interrupted — อาการ 'คำตอบหลังค้นเว็บหาย' "
            "จะพิสูจน์ไม่ได้ต่อไปอีกเรื่อยๆ"
        )

    def test_logging_is_bound_to_the_interrupted_event_itself(self, send_loop):
        """ต้องยิงเมื่อ *เห็น event interrupted จริง* ไม่ใช่ยิงทุก turn

        (mutation ที่ย้ายไป log ทุก server_content จะทำให้ log ท่วมจนหาไม่เจอ
        = ตาบอดแบบใหม่ ซึ่งเทสต้องจับได้)
        """
        region = send_loop[send_loop.index("live_server_content_events(sc)"):]
        region = region[: region.index("turn_complete")]
        assert '"interrupted"' in region and "interrupt_log_line(" in region, (
            "ตัว log ไม่ได้ผูกกับ event interrupted — ต้องเช็ค event ก่อนแล้วค่อย log"
        )

    def test_time_of_last_audio_chunk_is_tracked(self, send_loop):
        """ตัวเลข "เงียบมากี่วินาที" มาจากที่เดียว: เวลาที่ส่ง audio chunk ล่าสุด
        ⇒ ต้องจดตรงจุดที่ส่งจริง ไม่ใช่ที่อื่น (จดผิดที่ = ตัวเลขสวยแต่ไม่จริง)"""
        block = send_loop[send_loop.index("if response.data:"): send_loop.index("sc = getattr(")]
        assert "last_audio_at" in block, (
            "ไม่ได้จดเวลาส่งเสียงล่าสุดในบล็อกที่ส่งเสียงจริง"
        )

    def test_voice_handler_does_not_reference_the_readers_reread_flag(self, voice_ws):
        """🔴 CI แดงติดกัน 3 commit ตั้งแต่ `f4e62e8` (2026-08-17) เพราะบรรทัดเดียวนี้
        — `ruff check .` ฟ้อง F821 `reread` แต่ไม่มีใครเปิดดูเพราะ prod deploy ผ่าน

        ต้นเหตุ: ก๊อป `elif t == "reread"` มาจาก `/ws/reader` แต่ธง `reread` ถูกประกาศ
        เฉพาะใน handler ของ **โหมดอ่าน** ⇒ ถ้า client ยิง {"type":"reread"} เข้ามาที่
        **สายเสียง** จะได้ NameError → ตกลง `except Exception` → `stop.set()`
        = ตัดสาย session เสียงทิ้งทั้งเส้น

        ตอนนี้ยังไม่มีใครยิง (ปุ่ม 🔁 อยู่ที่โหมดอ่าน) = บั๊กแฝงที่ lint จับได้ก่อนหู
        ⚠️ ถ้าวันหนึ่งโหมดเสียงต้องมี reread จริง ให้ **ประกาศธงก่อน** แล้วค่อยแก้เทสนี้

        🔑 ตรวจด้วย AST ไม่ใช่ substring: เขียนครั้งแรกเป็น `"reread" not in src` แล้ว
        มันไปโดน**คอมเมนต์ที่อธิบายบั๊กนี้เอง** ⇒ เทสแดงทั้งที่โค้ดถูกแล้ว
        (เครื่องมือวัดที่อ่านตัวหนังสือแทนที่จะอ่านโค้ด = วัดผิดสิ่ง)
        """
        import ast

        src = (REPO / "server.py").read_text(encoding="utf-8")
        fn = next(
            n for n in ast.walk(ast.parse(src))
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "voice_websocket"
        )
        used = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
        assert "reread" not in used, (
            "handler เสียงอ้างถึงธง `reread` ที่ไม่มีในสโคปนี้ — NameError จะฆ่า session"
        )

    def test_mic_audio_arrival_is_recorded(self):
        """กัน "ฟังก์ชันถูกแต่ไม่มีใครเรียก" — `interrupt_log_line` รับ since_mic_s ได้
        ไม่แปลว่ามีใครจดเวลาให้มัน · ถ้า recv_loop ไม่จด บรรทัด log จะบอก
        "ไม่มีเสียงไมค์เข้ามาเลย" ทุกครั้ง = ตาบอดแบบใหม่ที่ดูเหมือนมีข้อมูล

        เดิน `ast` จากทั้งไฟล์ ไม่ตัดซอร์สเป็นสตริง — ซอร์สที่ตัดมาเป็นบล็อกย่อหน้า
        `ast.parse` แปลไม่ได้ และ `dedent` ก็ไม่ช่วยเพราะบรรทัดแรกไม่มีย่อหน้าติดมา
        """
        import ast
        tree = ast.parse((REPO / "server.py").read_text(encoding="utf-8"))
        voice = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "voice_websocket"
        )
        recv = next(
            n for n in ast.walk(voice)
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "recv_loop"
        )
        assigned = {
            t.id
            for n in ast.walk(recv)
            if isinstance(n, ast.Assign)
            for t in n.targets
            if isinstance(t, ast.Name)
        }
        declared = {
            name for n in ast.walk(recv)
            if isinstance(n, ast.Nonlocal) for name in n.names
        }
        assert "last_mic_at" in assigned, "recv_loop ไม่จดเวลาเสียงไมค์"
        assert "last_mic_at" in declared, (
            "จดใส่ตัวแปร local ของ recv_loop เอง — send_loop จะไม่มีวันเห็นค่า"
        )

    def test_interrupt_line_is_given_the_mic_timing(self, send_loop):
        assert "since_mic_s=" in send_loop, (
            "จดเวลาไว้แต่ไม่ได้ส่งเข้าบรรทัด log = ชี้ขาดรอบหน้าไม่ได้เหมือนเดิม"
        )

    def test_search_window_has_a_left_edge(self, tool_calls):
        """เดิม log แค่ตอนค้น *เสร็จ* ⇒ รู้ว่าจบเมื่อไรแต่ไม่รู้ว่าเริ่มเมื่อไร
        = วัดความยาวช่วงเงียบไม่ได้ ซึ่งเป็นตัวเลขทั้งหมดของสมมติฐานนี้"""
        assert "เริ่มค้น" in tool_calls, "ไม่ log ตอนเริ่มค้น = ไม่รู้ขอบซ้ายของช่วงเงียบ"


class TestSearchWindowClosesTheMicGate:
    """ประตูไมค์ต้องปิดตลอดช่วง tool call — ยืนยันบน prod 2026-08-21 07:43:45/07:43:53 UTC
    (= 14:43 ไทย) `interrupted` สองครั้งพร้อม "ค้น 1 ครั้งใน turn นี้ · เงียบมา 22.4s/30.3s"
    คือ turn ยังเปิดอยู่ตอนโดนตัด ⇒ ประตูฝั่ง client หมดอายุระหว่างที่เราเงียบ

    🔑 เดินด้วย `ast` ไม่ใช่ค้นสตริงในซอร์ส — บทเรียน 2026-08-18: เทส `"reread" not in src`
    เคยแดงเพราะไปโดน**คอมเมนต์ที่อธิบายบั๊กนั้นเอง** · `ast` ไม่เห็นคอมเมนต์
    """

    @pytest.fixture()
    def tool_call_fn(self):
        import ast
        src = (REPO / "server.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "answer_tool_calls":
                return node
        pytest.fail("ไม่เจอ answer_tool_calls ใน server.py")

    @staticmethod
    def _send_json_lines(fn, event: str) -> list[int]:
        """บรรทัดของ `websocket.send_json({"type": <event>})` ทุกจุดในฟังก์ชัน"""
        import ast
        out = []
        for n in ast.walk(fn):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)):
                continue
            if n.func.attr != "send_json" or not n.args:
                continue
            arg = n.args[0]
            if not isinstance(arg, ast.Dict):
                continue
            for k, v in zip(arg.keys, arg.values):
                if (isinstance(k, ast.Constant) and k.value == "type"
                        and isinstance(v, ast.Constant) and v.value == event):
                    out.append(n.lineno)
        return out

    @staticmethod
    def _call_lines(fn, attr: str) -> list[int]:
        import ast
        return [
            n.lineno for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == attr
        ]

    def test_client_is_told_the_search_started(self, tool_call_fn):
        assert self._send_json_lines(tool_call_fn, "searching"), (
            "ไม่ส่ง event `searching` ⇒ ประตูฝั่ง client ตัดสินจาก playUntil อย่างเดียว "
            "ซึ่งหมดอายุตั้งแต่วินาทีแรกของช่วงค้น = บั๊กเดิมกลับมาทั้งดุ้น"
        )

    def test_client_is_told_the_search_finished(self, tool_call_fn):
        assert self._send_json_lines(tool_call_fn, "search_done"), (
            "ไม่ส่ง event `search_done` ⇒ ประตูปิดจนกว่าจะชนเพดาน 60s ทุกครั้งที่ค้น"
        )

    def test_gate_opens_only_after_the_answer_is_handed_back(self, tool_call_fn):
        """ปลดล็อกก่อนส่งผลค้นกลับ = ไมค์เปิดในช่วงที่โมเดลยังไม่เริ่มพูด = ช่องเดิมเป๊ะ"""
        start = min(self._send_json_lines(tool_call_fn, "searching"))
        done = max(self._send_json_lines(tool_call_fn, "search_done"))
        handoff = self._call_lines(tool_call_fn, "send_tool_response")
        assert handoff, "ไม่เจอ send_tool_response — โครงฟังก์ชันเปลี่ยนไป เทสนี้วัดผิดที่แล้ว"
        assert start < min(handoff), "ปิดประตูช้าไป ต้องปิดก่อนเริ่มค้น"
        assert done > max(handoff), "ปลดประตูเร็วไป ต้องปลดหลังส่งผลค้นกลับให้โมเดลแล้ว"


class TestReaderHandlerWiring:
    @pytest.fixture()
    def feed(self):
        src = (REPO / "server.py").read_text(encoding="utf-8")
        ws = src[src.index('@app.websocket("/ws/reader")'):]
        ws = ws[: ws.index("\n@app.")] if "\n@app." in ws else ws
        return ws[ws.index("async def feed_loop"):]

    def test_each_block_fed_is_logged(self, feed):
        """ต้องอยู่ *ก่อน* เข้าลูปรับเสียง — ไม่งั้นท่อนที่ตายเงียบจะไม่มีบรรทัดเลย
        ซึ่งคือเคสเดียวที่เราอยากเห็น"""
        head = feed[: feed.index("session.receive()")]
        assert "reader_feed_log_line(" in head, (
            "ไม่ log ตอนป้อนท่อน — 'ตายเงียบกลางท่อน' จะยังต้องถาม user อยู่ดี"
        )

    def test_turn_result_is_logged_only_when_the_turn_completed(self, feed):
        """บรรทัด "ท่อนจบ" ต้องอยู่ใน `if turn_done:` เท่านั้น — ถ้าหลุดออกมาข้างนอก
        ท่อนที่ถูกทิ้งกลางคัน (พัก/🔁/go_away) จะขึ้นว่า "จบ" ทั้งที่ไม่จบ = log โกหก"""
        guard = feed.index("if turn_done:")
        assert "reader_turn_log_line(" not in feed[:guard], (
            "มีบรรทัด 'ท่อนจบ' อยู่นอกเงื่อนไข turn_done — จะรายงานว่าจบทั้งที่ถูกตัดกลางคัน"
        )
        assert "reader_turn_log_line(" in feed[guard:], "ไม่ log ผลของท่อนที่อ่านจบ"

    def test_audio_bytes_are_counted_where_they_are_sent(self, feed):
        """นับไบต์ตรงจุดที่ส่งออก WS จริง — นับที่อื่นคือนับสิ่งที่ผู้ใช้ไม่ได้ยิน"""
        loop = feed[feed.index("session.receive()"): feed.index("if turn_done:")]
        assert "audio_bytes" in loop
