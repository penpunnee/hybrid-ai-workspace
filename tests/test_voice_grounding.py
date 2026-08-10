"""โหมดเสียงต้องค้นข้อมูลจริงได้ — user รายงาน 2026-08-09: "บอกให้หาข้อมูล แล้วมันแต่งเอา"

**อาการที่ user เจอ** (transcript จริง session `probe_item19` 2026-08-09 12:33–13:09):
ขอให้เล่านิยายตามต้นฉบับ → ได้เรื่องที่**แต่งขึ้นใหม่ทั้งหมด** และแต่ง**คนละเรื่องกัน
3 เรื่องภายใน 95 วินาที** (12:38:04 ป่าสมุนไพร · 12:38:28 นักสืบไขคดี · 12:39:43 ฝึกวิชา
เข้าประลอง) พร้อมยืนยันรายละเอียดปลอมอย่างมั่นใจ ("ในอนิเมะก็อยู่แถวๆ ตอนที่ 278
จริงๆ ด้วยค่ะ") · สั่งให้ "เรียบเรียงใหม่" กี่ครั้งก็ได้ของแต่งชุดใหม่ทุกครั้ง

**ต้นเหตุ:** `build_live_config()` ไม่เคยส่ง `tools=` เลยแม้แต่ตัวเดียว — โหมดเสียง
จึงไม่มีทางค้นอะไรได้ ขณะที่**ฝั่งพิมพ์มี Google Search grounding เต็ม**
(`routers/chat.py:400`) ⇒ ความสามารถสองโหมดไม่เท่ากันโดยไม่มีใครรู้

🔑 **ทำไมสั่ง "เรียบเรียงใหม่" ถึงไม่ช่วย:** ไม่มีต้นฉบับให้เรียบเรียง — คำสั่งนั้น
แปลว่า "แต่งใหม่อีกรอบ" เสมอ ⇒ **แก้ที่ prompt อย่างเดียวไม่พอ ต้องมีเครื่องมือให้มันใช้**

🔴 **ทางตรง (`tools=[Tool(google_search=...)]`) ใช้ไม่ได้ — และพังแบบเงียบที่สุด**
วัดจริงบน prod 2026-08-09 ยิงซ้ำ 3 ครั้ง ได้ผลเดิมทุกครั้ง:

    tool ที่ส่งไป                     | ผลจากการ connect จริง
    ----------------------------------|----------------------------------------
    google_search                     | 🔴 APIError 1011 "exceeded your quota" 3/3
    function_declarations             | ✅ ok (audio 51,870 ไบต์)
    ไม่ส่ง tools เลย (กลุ่มควบคุม)      | ✅ ok (audio 229,442–269,762 ไบต์)

⇒ ไม่ใช่โควตาหมดจริง (กลุ่มควบคุมยิงผ่านทั้งก่อนและหลัง) แต่คือ **Google Search
grounding บนสาย Live ถูกกั้นไว้ที่ tier ที่คีย์นี้ไม่มี** แล้วรายงานออกมาเป็น "quota"
🔑 **ถ้า merge ทางตรงไป = เสียงตายทั้งระบบ** เพราะ 1011 เกิดตอน `connect()`
ไม่ใช่ตอนค้น ⇒ ทุก session ตายตั้งแต่ยังไม่ทันพูด · เทสในไฟล์นี้เขียวหมดทุกข้อ
(รูปแบบเดียวกับ `temperature` บน 2.5-native-audio ที่บันทึกไว้ใน utils/voice.py:
"ไม่ error แต่คืน 0 ไบต์" — config ที่ SDK ยอมรับ ≠ ความสามารถที่ได้จริง)

**ทางที่เลือกแทน:** ประกาศเป็น `function_declarations` แล้วให้ **ฝั่งเราค้นเอง**
ด้วย `utils.llm.gemini_web_search` (วัดแล้วใช้ได้บนคีย์นี้: 311 ตัวอักษร 7 แหล่ง
ผ่าน gemini-2.5-flash) แล้วส่งผลกลับด้วย `session.send_tool_response()`

⚠️ **ข้อจำกัดของเทสไฟล์นี้ (อ่านก่อนเชื่อว่าเขียว):** พิสูจน์ได้แค่ว่า *เราส่ง tool ไปให้*
กับ *เราแปลง tool_call เป็นคำค้นถูก* — พิสูจน์ไม่ได้ว่า **โมเดลเลือกเรียก tool จริง
ตอนคุยเรื่องนิยาย** ตัวชี้ขาดคือ probe live ที่นับ tool_call กลับมา + หูของ user
"""

import pytest


@pytest.fixture()
def cfg():
    from utils.voice import build_live_config

    return build_live_config(slug="kwan", system_instruction="ทดสอบ", resume_handle=None)


class TestVoiceHasSearchTool:
    """ขาดข้อนี้ = "ไปหาข้อมูลมา" กลายเป็น "แต่งมาให้" ทุกครั้งโดยไม่มี error"""

    def test_tools_is_not_empty(self, cfg):
        assert cfg.tools, "โหมดเสียงไม่มี tool เลย → ค้นข้อมูลไม่ได้ ได้แต่แต่ง"

    def test_search_function_is_declared(self, cfg):
        """ต้องเป็นฟังก์ชันค้นจริงๆ ไม่ใช่ Tool เปล่าที่ผ่านการนับแต่ไม่ทำอะไร

        เทสก่อนหน้านับแค่ "ลิสต์ไม่ว่าง" — `types.Tool()` เปล่าๆ ก็ผ่าน
        (ตรงกับบทเรียน "ตัวเลขรวมผ่านแล้วยังต้องเปิดดูทีละอัน")
        """
        from utils.voice import WEB_SEARCH_TOOL_NAME

        names = [
            fd.name
            for t in cfg.tools
            for fd in (getattr(t, "function_declarations", None) or [])
        ]
        assert names.count(WEB_SEARCH_TOOL_NAME) == 1, (
            f"ต้องประกาศ {WEB_SEARCH_TOOL_NAME} พอดี 1 ตัว แต่เจอ {names}"
        )

    def test_does_not_use_the_tier_gated_google_search_tool(self, cfg):
        """🔴 ratchet กันคนกลับไปใช้ทางตรงเพราะ "มันดูสะอาดกว่า"

        `Tool(google_search=...)` ทำให้ `connect()` ตาย 1011 ทุก session บนคีย์นี้
        = เสียงดับทั้งระบบ · วัดซ้ำ 3 ครั้งแล้ว ไม่ใช่ของชั่วคราว
        ถ้าวันหนึ่งอัปเกรด tier แล้วอยากกลับไปใช้ ให้ยิง probe ยืนยันก่อนแล้วค่อยลบเทสนี้
        """
        gated = [t for t in cfg.tools if getattr(t, "google_search", None) is not None]
        assert not gated, (
            "ใส่ google_search กลับเข้ามา → connect() จะได้ 1011 ทุกครั้ง เสียงดับทั้งระบบ"
        )

    def test_search_function_takes_a_query_argument(self, cfg):
        """ประกาศฟังก์ชันไว้แต่ไม่มีพารามิเตอร์ = โมเดลเรียกได้แต่บอกไม่ได้ว่าจะค้นอะไร"""
        from utils.voice import WEB_SEARCH_TOOL_NAME

        fd = next(
            fd
            for t in cfg.tools
            for fd in (getattr(t, "function_declarations", None) or [])
            if fd.name == WEB_SEARCH_TOOL_NAME
        )
        props = (fd.parameters.properties or {}) if fd.parameters else {}
        assert "query" in props, f"ไม่มีพารามิเตอร์ query — เจอ {list(props)}"


class TestToolCallExtraction:
    """แปลง `tool_call` ที่โมเดลส่งมา → คำค้น (pure → เทสได้โดยไม่ต้องต่อ Gemini)

    แยกออกมาเป็นฟังก์ชันบริสุทธิ์ด้วยเหตุผลเดียวกับ `live_control_signals`:
    ถ้าฝังไว้ใน `send_loop` จะตรวจได้แค่ด้วยการ grep ซอร์ส ซึ่งพิสูจน์อะไรไม่ได้เลย
    """

    def test_no_tool_call_returns_empty(self):
        from utils.voice import live_tool_call_queries

        assert live_tool_call_queries(None) == []

    def test_extracts_id_and_query(self):
        from utils.voice import WEB_SEARCH_TOOL_NAME, live_tool_call_queries

        class FC:
            id, name, args = "c-1", WEB_SEARCH_TOOL_NAME, {"query": "นิยาย Perfect World"}

        class R:
            tool_call = type("T", (), {"function_calls": [FC()]})()

        assert live_tool_call_queries(R()) == [("c-1", WEB_SEARCH_TOOL_NAME, "นิยาย Perfect World")]

    def test_ignores_unknown_function_names(self):
        """โมเดลเรียกฟังก์ชันที่เราไม่ได้ประกาศได้ — ต้องไม่ไปค้นตามคำสั่งนั้น"""
        from utils.voice import live_tool_call_queries

        class FC:
            id, name, args = "c-2", "rm_rf", {"query": "x"}

        class R:
            tool_call = type("T", (), {"function_calls": [FC()]})()

        assert live_tool_call_queries(R()) == []

    def test_skips_calls_without_a_query(self):
        """args ว่าง → ค้นสตริงว่าง = เผาโควตาแล้วได้ผลลัพธ์หลอก"""
        from utils.voice import WEB_SEARCH_TOOL_NAME, live_tool_call_queries

        class FC:
            id, name, args = "c-3", WEB_SEARCH_TOOL_NAME, {}

        class R:
            tool_call = type("T", (), {"function_calls": [FC()]})()

        assert live_tool_call_queries(R()) == []


class TestVoicePromptForbidsFabrication:
    """เครื่องมืออย่างเดียวไม่พอ — persona เดิมสั่งให้ "เล่าต่อเนื่องยาวๆ จนจบ"
    ซึ่งเมื่อไม่มีข้อมูลจริงจะกลายเป็นแรงกดดันให้แต่งต่อ (นี่คือสิ่งที่เกิดขึ้นวันที่ 08-09)

    🔴 **กติกา "ห้ามแต่ง" มีอยู่แล้วตั้งแต่แรก และไม่ได้ช่วยเลย** — ของเดิมเขียนเป็น
    **บัญชีรายชื่อหัวข้อปิด**: "ผล ping/เช็คเครือข่าย/IP, ราคาหุ้น/คริปโต/ทอง/น้ำมัน,
    ผลค้นเว็บ, เนื้อหาไฟล์หรือลิงก์, ข้อมูล real-time, เวลา/วันที่, สภาพอากาศ,
    สถานะอุปกรณ์/NAS" — **"เนื้อเรื่องของนิยาย" ไม่อยู่ในลิสต์** โมเดลจึงถือว่าเป็น
    ความรู้ทั่วไปที่พูดลื่นๆ ได้ ⇒ ทำตามกติกาครบทุกข้อ แล้วยังแต่งนิยายได้สบายมาก

    🔑 นี่คือรูปแบบ **"ตรวจในที่ที่นึกออก แล้วสรุปว่าครบ"** ที่บันทึกไว้ใน CLAUDE.md
    ซ้ำอีกครั้ง — คราวนี้อยู่ในตัว prompt เอง ไม่ใช่ในเทส

    ⚠️ เทสชุดนี้จึงต้องยืนยัน **กติกาตัวใหม่ที่ครอบเนื้อหาจากต้นฉบับ** ไม่ใช่แค่ว่ามี
    คำว่า "ห้ามแต่ง" อยู่ในไฟล์ — ตอนเขียนรอบแรกใช้ `"ห้ามแต่ง" in prompt` แล้ว
    **เขียวทันทีทั้งที่ยังไม่ได้แก้อะไร** เพราะไปแมตช์ของเดิมที่คนละความหมาย
    """

    @pytest.fixture()
    def prompt(self):
        from assistants.config import voice_system_prompt

        return voice_system_prompt("kwan")

    def test_tells_model_it_has_a_search_tool_in_voice_mode(self, prompt):
        """ของเดิมบอกให้ "ไปเปิด Agent mode" ซึ่งในโหมดเสียงทำไม่ได้ = ทางตัน

        (คำว่า "ค้น" เฉยๆ ใช้เป็นเกณฑ์ไม่ได้ — persona เดิมมี "ผลค้นเว็บ" อยู่แล้ว)
        """
        assert "[ค้นก่อนตอบ]" in prompt, "ไม่มีอะไรบอกโมเดลว่าโหมดเสียงมีเครื่องมือค้นแล้ว"

    def test_forbids_inventing_source_material_specifically(self, prompt):
        """ต้องเป็นกติกาที่ครอบ "เนื้อเรื่อง" โดยเฉพาะ ไม่ใช่ "ห้ามแต่งข้อมูล" ตัวเดิม"""
        assert "ห้ามแต่งเนื้อเรื่อง" in prompt, (
            "กติกาเดิมเป็นบัญชีหัวข้อปิดที่ไม่มีนิยายอยู่ในนั้น → แต่งได้โดยไม่ผิดกติกา"
        )

    def test_names_the_media_kinds_that_got_fabricated(self, prompt):
        """ระบุชนิดสื่อให้ชัด — "เนื้อเรื่อง" ลอยๆ จะโดนตีความแคบเหมือนรอบที่แล้ว"""
        for kind in ("นิยาย", "อนิเมะ"):
            assert kind in prompt, f"ไม่ได้ระบุ {kind} → เสี่ยงหลุดแบบเดียวกับบัญชีหัวข้อเดิม"

    def test_tells_model_to_admit_when_it_cannot_find(self, prompt):
        """ทางออกที่ยอมรับได้ต้องมีอยู่จริง ไม่งั้น "ห้ามแต่ง" คือคำสั่งที่ทำตามไม่ได้"""
        assert "หาไม่เจอ" in prompt, "ห้ามแต่งแต่ไม่บอกว่าให้ทำอะไรแทน = สั่งให้เงียบ"

    def test_narration_rule_survives(self, prompt):
        """กลุ่มควบคุม: กติกาเดิม (ห้ามถามขออนุญาตกลางเรื่อง) ต้องไม่ถูกเขียนทับ

        กติกานี้แก้อาการคนละอันที่ user รายงาน 2026-08-04 — ถ้าหายไปพร้อมกับ
        การแก้รอบนี้ อาการเก่าจะกลับมาโดยไม่มีใครสังเกต
        """
        assert "ห้ามถามขออนุญาตกลางเรื่อง" in prompt


class TestExistingVoiceConfigUntouched:
    """กลุ่มควบคุม — เติม tools แล้วต้องไม่ทำของเดิมหล่น

    ค่าพวกนี้แต่ละตัวมีที่มาจากบั๊กจริงคนละตัว (ดู utils/voice.py) การเพิ่ม tool
    ไม่ควรแตะอะไรในนี้เลย
    """

    def test_audio_and_pinned_rendering_survive(self, cfg):
        from utils.voice import DEFAULT_VOICE

        assert cfg.response_modalities == ["AUDIO"]
        assert cfg.speech_config.voice_config.prebuilt_voice_config.voice_name == DEFAULT_VOICE
        assert cfg.seed is not None
        assert cfg.temperature is not None
        assert cfg.enable_affective_dialog is False

    def test_transcription_and_session_knobs_survive(self, cfg):
        assert cfg.input_audio_transcription is not None
        assert cfg.output_audio_transcription is not None
        assert cfg.context_window_compression is not None
        assert cfg.realtime_input_config is not None
        assert cfg.session_resumption is not None


class TestSearchLoopHasACeiling:
    """🔴 อุบัติเหตุจริงบน prod 2026-08-10 12:37 — โมเดลค้น 5 ครั้งใน 53 วินาที
    แล้ว **ไม่พูดอะไรเลยสักคำ**

    หลักฐาน: `[VoiceLevel]` วันนั้น 0 บรรทัด (= Gemini ไม่ส่งเสียงกลับมาเลย) ·
    ข้อความที่เซฟมีแต่ของ user 2 แถว ไม่มีของผู้ช่วย · และค้นคำเดิมซ้ำ
    ('หลักทรัพย์ประกันตัว เกณฑ์' สองรอบ) = ลายเซ็นของการวนลูป

    **ทำไมเทสเดิมจับไม่ได้:** probe ตอน verify ใช้คำถามที่ค้นครั้งเดียวจบ
    ("Perfect World พระเอกชื่ออะไร") · คำถามกว้างๆ ที่ตอบยากต่างหากที่ทำให้วน

    🔑 บทเรียน: ผมใส่เบรก 3 ชั้นให้ "เล่าต่ออัตโนมัติ" อย่างระวัง แต่**ลืมใส่ให้ tool
    ค้นเว็บเลยสักชั้น** ทั้งที่เป็นลูปโครงสร้างเดียวกัน (โมเดลสั่ง → เราทำให้ → สั่งอีก)
    """

    def test_ceiling_exists_and_is_small(self):
        from utils.voice import SEARCH_MAX_PER_TURN

        assert 1 <= SEARCH_MAX_PER_TURN <= 4, (
            "เพดานต้องเล็ก — ค้นครั้งละ 11-16 วินาที เกิน 3 ครั้งผู้ใช้ก็เงียบเกิน 45 วิแล้ว"
        )

    def test_under_the_ceiling_the_search_runs(self):
        from utils.voice import SEARCH_MAX_PER_TURN, should_run_search

        assert should_run_search(0) is True
        assert should_run_search(SEARCH_MAX_PER_TURN - 1) is True

    def test_at_the_ceiling_the_search_is_refused(self):
        from utils.voice import SEARCH_MAX_PER_TURN, should_run_search

        assert should_run_search(SEARCH_MAX_PER_TURN) is False
        assert should_run_search(SEARCH_MAX_PER_TURN + 5) is False

    def test_refusal_message_tells_the_model_to_answer_now(self):
        """ปฏิเสธเฉยๆ ไม่พอ — ต้องสั่งให้มัน **ตอบด้วยของที่มี** ไม่งั้นมันจะเงียบต่อ

        นี่คือจุดต่างจากการไม่ตอบ function_call เลย (ซึ่งทำให้โมเดลรอค้าง)
        """
        from utils.voice import SEARCH_LIMIT_REPLY

        assert "ตอบ" in SEARCH_LIMIT_REPLY
        assert "ห้ามค้น" in SEARCH_LIMIT_REPLY


class TestSearchCeilingIsActuallyWired:
    """ฟังก์ชันถูกแต่ไม่มีใครเรียก = ฟีเจอร์ตายสนิทโดยไม่มีอะไรแดง (เจอมาแล้วกับ fix_thai_pua)"""

    @pytest.fixture()
    def handler(self):
        from pathlib import Path

        src = (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")
        ws = src[src.index('@app.websocket("/ws/voice/'):]
        return ws[: ws.index("\n@app.")] if "\n@app." in ws else ws

    def test_handler_checks_the_ceiling(self, handler):
        assert "should_run_search(" in handler

    def test_handler_counts_each_search(self, handler):
        assert "search_count += 1" in handler

    def test_handler_replies_when_refusing(self, handler):
        """ปฏิเสธแล้วต้องส่ง SEARCH_LIMIT_REPLY กลับ ไม่ใช่เงียบ (เงียบ = โมเดลรอค้าง)"""
        assert "SEARCH_LIMIT_REPLY" in handler

    def test_counter_resets_each_turn(self, handler):
        """ไม่รีเซ็ต = คุยยาวๆ ชนเพดานถาวร ค้นไม่ได้อีกทั้ง session

        นับ 3 ที่: ประกาศตัวแปร · เพิ่มค่า · รีเซ็ตตอน turn จบ
        (บทเรียนจาก auto_count ที่ `in handler` ผ่านฟรีเพราะมีหลายที่)
        """
        assert handler.count("search_count = 0") == 2, "ต้องมี 2 ที่ — ประกาศ และรีเซ็ตตอน turn จบ"
        after_done = handler[handler.index('"type": "done"'):]
        assert "search_count = 0" in after_done, "ตัวรีเซ็ตไม่ได้อยู่ในสาย turn_complete"
