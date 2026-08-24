import asyncio
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


# ── ค้นเว็บในโหมดเสียง (เพิ่ม 2026-08-09) ──────────────────────────────────────
# เดิม `build_live_config()` **ไม่ส่ง `tools` เลยแม้แต่ตัวเดียว** → โหมดเสียงค้นอะไร
# ไม่ได้ ทั้งที่ฝั่งพิมพ์มี Google Search grounding เต็ม (`routers/chat.py:400`)
# ความต่างนี้ไม่มี error/log อะไรบอกเลยสักตัว
#
# อาการที่ user เจอ (transcript จริง 2026-08-09 12:33–13:09): ขอให้เล่านิยายตามต้นฉบับ
# → ได้ของแต่งล้วน และแต่ง**คนละเรื่องกัน 3 เรื่องภายใน 95 วินาที** · สั่ง "เรียบเรียงใหม่"
# กี่ครั้งก็ได้ของแต่งชุดใหม่ทุกครั้ง เพราะไม่มีต้นฉบับให้เรียบเรียงตั้งแต่แรก
# ⇒ **แก้ที่ prompt อย่างเดียวไม่มีทางพอ ต้องมีเครื่องมือให้มันใช้**
#
# 🔴 **ทางตรง `Tool(google_search=...)` ใช้ไม่ได้บนคีย์นี้** — วัดจริง 3/3 ครั้ง:
# `connect()` ตายด้วย APIError 1011 "exceeded your current quota" ตั้งแต่ยังไม่ทันพูด
# ขณะที่กลุ่มควบคุม (ไม่ส่ง tools) และ `function_declarations` ผ่านทั้งคู่ในนาทีเดียวกัน
# ⇒ ไม่ใช่โควตาหมด แต่คือ grounding บนสาย Live ถูกกั้นที่ tier ที่คีย์นี้ไม่มี
# **ถ้าใส่ทางตรงไป = เสียงดับทั้งระบบ ไม่ใช่แค่ค้นไม่ได้** (มี ratchet ที่
# `tests/test_voice_grounding.py::test_does_not_use_the_tier_gated_google_search_tool`)
#
# ทางที่ใช้ได้: ประกาศเป็นฟังก์ชัน แล้ว **ฝั่งเราค้นเอง** ด้วย `utils.llm.gemini_web_search`
# (ตัวเดียวกับที่ฝั่งพิมพ์ใช้ · วัดแล้วได้ 7 แหล่งบนคีย์นี้ผ่าน gemini-2.5-flash)
# แล้วส่งผลกลับด้วย `session.send_tool_response()` — ดู `server.py` send_loop
WEB_SEARCH_TOOL_NAME = "search_web"


def web_search_tool():
    """ประกาศฟังก์ชันค้นเว็บให้โมเดล live เรียก

    ชื่อพารามิเตอร์ `query` ถูกผูกไว้กับ `live_tool_call_queries()` — เปลี่ยนที่เดียว
    ไม่พอ ต้องเปลี่ยนคู่กัน (มีเทสจับ)
    """
    from google.genai import types

    return types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name=WEB_SEARCH_TOOL_NAME,
                description=(
                    "ค้นข้อมูลจริงจากเว็บ ใช้เมื่อผู้ใช้ถามถึงสิ่งที่ต้องอ้างของจริง เช่น "
                    "เนื้อเรื่องนิยาย/อนิเมะ/ซีรีส์ ข่าว ขั้นตอนวิธีทำ สเปก ราคา งานวิจัย "
                    "หรือข้อมูลที่เปลี่ยนตามเวลา "
                    "⚠️ ค้น **ครั้งเดียวต่อคำถาม** แล้วตอบเลย — อย่าค้นซ้ำเพื่อหาข้อมูลให้ครบกว่าเดิม "
                    "ผู้ใช้กำลังรอฟังเสียงอยู่ ทุกครั้งที่ค้นคือความเงียบ 10-15 วินาที"
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "query": types.Schema(
                            type="STRING",
                            description="คำค้น เขียนให้ตรงประเด็นที่สุด ใส่ชื่อเฉพาะให้ครบ",
                        )
                    },
                    required=["query"],
                ),
            )
        ]
    )


# ── เล่าต่ออัตโนมัติ (เพิ่ม 2026-08-09) ────────────────────────────────────────
# user: "เว้นช่วงถามบ่อยเกิน ว่าให้เล่าต่อไปไหม ต้องมาคอยตอบว่าต่อไปตลอด"
#
# 🔴 **ทำไมไม่แก้ที่ prompt:** `_VOICE_MODE` สั่งห้ามไว้ตรงๆ อยู่แล้ว —
# "ห้ามถามขออนุญาตกลางเรื่อง เช่น 'จะให้เล่าต่อเลยไหมคะ' 'อยากฟังต่อไหมคะ'"
# **แล้วโมเดลพูดประโยคในบัญชีห้ามนั้นคำต่อคำ** (prod 08-09 18:30:04 · 18:31:39
# "อยากให้เล่าต่อเลยไหมคะ") · นับจริงช่วง 18:20–18:37: จบด้วยคำถาม 16/26 = 62%
# 🔑 **โมเดลละเมิดคำสั่งที่เขียนชัดอยู่แล้ว ⇒ เขียนให้ชัดกว่าเดิมคือดันลูกโยกที่ไม่ได้
# ต่อกับอะไร** ต้องย้ายมาบังคับฝั่ง server
#
# ⚠️ ฟีเจอร์นี้ยิงคำสั่งเข้าไปเองโดยผู้ใช้ไม่ได้พูด = **ถ้าไม่มีเบรกจะวิ่งหนีและเผาโควตา**
# เบรกมี 3 ชั้น: (1) ปิดเป็นค่าเริ่มต้น เปิดเองเท่านั้น (2) user พูดเมื่อไหร่หยุดทันที
# (3) เพดานจำนวนครั้งติดกัน
AUTO_CONTINUE_MAX = 20           # ยิงติดกันได้สูงสุดกี่ครั้งก่อนปล่อยให้เงียบ
AUTO_CONTINUE_TEXT = "เล่าต่อจากที่ค้างไว้เลย ห้ามถาม ห้ามสรุป ห้ามทวนของเดิม"


def should_auto_continue(enabled: bool, user_spoke: bool, count: int,
                         cap: int = AUTO_CONTINUE_MAX) -> bool:
    """turn จบแล้ว — ควรยิง "เล่าต่อ" ให้เองไหม (pure → เทสได้)

    · `user_spoke` = มี input_transcription ใน turn นี้ ⇒ พี่ปอยสั่งเองแล้ว
      ยิงทับจะกลายเป็นเถียงกับคำสั่งของ user · นี่คือเบรกเส้นหลัก
    · `count` = ยิงติดกันมาแล้วกี่ครั้ง (รีเซ็ตเมื่อ user พูด)
    """
    if not enabled or user_spoke:
        return False
    return count < cap


# ── เพดานจำนวนครั้งที่ยอมให้ค้นต่อหนึ่ง turn (เพิ่ม 2026-08-10) ────────────────
#
# 🔴 **อุบัติเหตุจริงบน prod 2026-08-10 12:37** — user ถามเรื่องหลักทรัพย์ประกันตัว
# โมเดลค้น **5 ครั้งใน 53 วินาที** (ซ้ำคำเดิม 2 ครั้ง) แล้ว **ไม่พูดอะไรเลยสักคำ**
# `[VoiceLevel]` วันนั้น 0 บรรทัด = Gemini ไม่ส่งเสียงกลับมาเลยแม้แต่ไบต์เดียว
#
# ต้นเหตุ: ใส่ tool ค้นเว็บโดยไม่มีเพดาน + prompt แรงเกิน ("ให้ค้นก่อนเสมอ" +
# "ห้ามเดาคำตอบเองถ้าเรียกเครื่องมือนี้ได้") ⇒ โมเดลเลือกค้นซ้ำแทนที่จะตอบ
#
# 🔑 บทเรียน: ใส่เบรก 3 ชั้นให้ `should_auto_continue` อย่างระวัง แต่**ลืมใส่ให้
# tool ค้นเลยสักชั้น** ทั้งที่เป็นลูปโครงสร้างเดียวกัน (โมเดลสั่ง → เราทำให้ → สั่งอีก)
#
# ⚠️ ปฏิเสธเฉยๆ ไม่พอ — **ต้องสั่งให้มันตอบด้วยของที่มี** ไม่งั้นมันจะเงียบต่อ
# (ต่างจากการไม่ตอบ function_call เลย ซึ่งทำให้โมเดลรอค้างจนหมดเวลา)
SEARCH_MAX_PER_TURN = 2
SEARCH_LIMIT_REPLY = (
    "ค้นครบจำนวนที่อนุญาตแล้ว ห้ามค้นเพิ่มอีก "
    "ให้ตอบพี่ปอยทันทีด้วยข้อมูลที่ได้มาแล้ว ถ้าข้อมูลไม่พอให้บอกตรงๆ ว่าเท่าที่หาได้มีแค่นี้"
)


def should_run_search(done_this_turn: int, cap: int = SEARCH_MAX_PER_TURN) -> bool:
    """ยังยอมให้ค้นอีกไหมใน turn นี้ — pure → เทสได้

    นับต่อ turn ไม่ใช่ต่อ session: ถามคำถามใหม่แล้วเริ่มนับใหม่เสมอ
    """
    return done_this_turn < cap


def live_tool_call_queries(response) -> list[tuple[str, str, str]]:
    """ดึง `(call_id, ชื่อฟังก์ชัน, คำค้น)` ออกจาก `LiveServerMessage` — pure → เทสได้

    เหตุผลที่แยกออกมาเหมือน `live_control_signals`: ฝังไว้ใน `send_loop` แล้วจะ
    ตรวจได้แค่ด้วยการ grep ซอร์ส ซึ่งพิสูจน์ไม่ได้ว่าค่าที่ไหลออกไปคืออะไร

    ทิ้ง 2 กรณีโดยตั้งใจ:
      · ชื่อฟังก์ชันที่เราไม่ได้ประกาศ — โมเดลกุชื่อขึ้นมาเรียกได้ ต้องไม่ทำตาม
      · ไม่มี `query` — ค้นสตริงว่างคือเผาโควตาแล้วได้ผลหลอกกลับมา
    ทั้งสองกรณียังต้องตอบกลับด้วย (ไม่งั้นโมเดลค้าง) — คนเรียกเป็นคนจัดการ
    """
    tc = getattr(response, "tool_call", None) if response is not None else None
    if tc is None:
        return []
    out: list[tuple[str, str, str]] = []
    for fc in (getattr(tc, "function_calls", None) or []):
        name = getattr(fc, "name", "") or ""
        if name != WEB_SEARCH_TOOL_NAME:
            continue
        query = ((getattr(fc, "args", None) or {}).get("query") or "").strip()
        if not query:
            continue
        out.append((getattr(fc, "id", "") or "", name, query))
    return out


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
        tools=[web_search_tool()],
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
        #
        # 🔄 เปลี่ยน NO_INTERRUPTION → START_OF_ACTIVITY_INTERRUPTS (user เคาะ 2026-08-07)
        # เดิม NO_INTERRUPTION เป็น "เข็มขัดเส้นที่สอง" คู่กับ half-duplex gate ฝั่ง client
        # ผลข้างเคียงที่ไม่ได้ตั้งใจ: **ถอด gate ฝั่ง client แล้วก็ยังพูดแทรกไม่ได้**
        # เพราะโมเดลถูกสั่งไว้ว่าห้ามตัดคำตอบตัวเอง — ไมค์ส่งเสียงไปถึงจริงแต่ไม่มีผล
        # (พิมพ์แทรกได้เพราะไปคนละเส้น: `send_client_content(turn_complete=True)`
        #  = เริ่ม turn ใหม่ ไม่ผ่าน VAD)
        #
        # ⚠️ ยังปลอดภัยโดยโครงสร้าง: **ค่าเริ่มต้นฝั่ง client ยังปิดไมค์ตอน AI พูด**
        # (`micShouldSend()` → `gate.micOpen()`) ⇒ ไม่มีเสียงไปถึงโมเดลให้ใช้ตัด turn เลย
        # ความเสี่ยง echo ตัดคำตอบตัวเองจะเกิดเฉพาะกับคนที่เปิดสวิตช์ "พูดแทรกได้"
        # ซึ่งเป็นเจตนาของสวิตช์นั้นพอดี · ถ้าเจอปัญหาให้ปิดสวิตช์ ไม่ต้องแก้ไฟล์นี้
        realtime_input_config=types.RealtimeInputConfig(
            # 🔴 ต้องระบุ sensitivity เอง — `AutomaticActivityDetection()` เปล่าๆ
            # **ไม่ใช่ "ค่ากลาง"** แต่คือ `START_SENSITIVITY_HIGH` ("The default is
            # START_SENSITIVITY_HIGH" · "detect the start of speech more often")
            # ⇒ เราสั่ง VAD ให้ไวที่สุดมาตลอดโดยไม่รู้ตัว แล้วไปกันเสียงรบกวนเอาเอง
            # ด้วยประตูไมค์ฝั่ง client ซึ่งกันได้เฉพาะช่วงที่รู้ล่วงหน้าว่าจะเงียบ
            # (ช่วงค้นเว็บ) แต่กันไม่ได้ตอนที่ปิดประตูไม่ได้ — เช่นจังหวะที่ผู้ใช้
            # เพิ่งพูดจบก่อนโมเดลเริ่มตอบ
            #
            # LOW = "requires clear, sustained speech" ⇒ คนพูดจริงยังแทรกได้
            # เสียงจาม/เก้าอี้/ป๊อกจากการ flush บัฟเฟอร์ไม่ผ่าน
            # (อาการจริง 2026-08-22 03:29:57: เสียงแวดล้อมตัด turn → คำตอบหาย)
            #
            # ⚠️ **จงใจไม่แตะอีก 3 ตัว:**
            # · `end_of_speech_sensitivity` — ไม่เกี่ยวกับบั๊กนี้ และ LOW จะทำให้
            #   turn จบช้าลง = รอนานขึ้นทุกประโยค
            # · `silence_duration_ms` — คู่มือเตือนเองว่าค่าต่ำ "split a single
            #   utterance into multiple small audio fragments"
            # · `prefix_padding_ms` — API reference ("required duration of detected
            #   speech before start-of-speech is committed") กับบทความภายนอก
            #   ("look-back audio") **นิยามขัดกัน** ให้ผลตรงข้ามเรื่องกันเสียงรบกวน
            #   ⇒ ยังไม่มีหลักฐานพอ อย่าเดา
            automatic_activity_detection=types.AutomaticActivityDetection(
                start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_LOW,
            ),
            # คงไว้ — user เคาะว่าให้ลด sensitivity ไม่ใช่ตัด barge-in ทิ้ง
            # (`NO_INTERRUPTION` จะทำให้สวิตช์พูดแทรกฝั่ง client กลายเป็นสวิตช์หลอก)
            activity_handling=types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS,
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


# ── โหมดขวัญอ่านหนังสือ (เพิ่ม 2026-08-11) ─────────────────────────────────────
# user เคาะให้ "อ่านนิยายด้วยเสียงขวัญ_เดิม" — เสียง Aoede ตัวเดียวกับโหมดคุย
#
# **ทำไม Live API ไม่ใช่ Gemini TTS:** เสียงเดียวกัน แต่ TTS ติดเพดาน 10 req/วัน
# (อ่านทั้งเล่ม = ~9.7 ปี) ส่วน Live ไม่ชนโควตา (วัดจริง: user คุย 35 นาทีรวด)
# · พิสูจน์แล้วว่าอ่านคำต่อคำได้ 100.0% — ท่อนจริง 586-598 ตัวอักษร x3 ท่อนต่อเนื่อง
#
# **คำกำกับนี้ผ่านการจูน 4 รอบกับ user** (ท่อนทดสอบชุดเดียวกันทุกรอบ วัดเวลาจริง):
#   ① เครื่องอ่านเรียบ 49.0วิ → เรียบไป · ② กระชับ 39.5วิ → เร็วไป
#   ③ "นักพากย์" 61.6วิ → ช้าไป (คำเดียวลากทุกอย่างช้าลง 56%)
#   ④ ตัวนี้ 40.9วิ → ✅ เคาะ
# 🔑 บทเรียน: **สั่งสิ่งที่ห้ามทำให้ชัด ได้ผลกว่าขอสิ่งที่อยากได้เพิ่ม** — อารมณ์กับ
# จังหวะเป็นของที่มาด้วยกันในหัวโมเดล ต้องแยกให้มันเห็นตรงๆ ว่าเอาอารมณ์แต่ไม่เอาชะลอ
# ⚠️ แก้ข้อความนี้ = จังหวะ/อารมณ์เปลี่ยนทั้งระบบ ต้องวัดใหม่แบบ 4 รอบข้างบนก่อนเคาะ
READER_PROMPT = (
    "คุณเป็นนักอ่านหนังสือเสียงมืออาชีพ อ่านข้อความที่ได้รับออกเสียงให้ครบทุกคำ "
    "อ่านด้วยจังหวะกระฉับกระเฉง มีชีวิตชีวา ไม่ยานยืด ไม่ลากเสียงท้ายคำ "
    "เว้นจังหวะสั้นๆ ตามเครื่องหมายวรรคตอนเท่านั้น "
    "ใส่อารมณ์ผ่านน้ำเสียง ไม่ใช่ผ่านการชะลอ — ฉากตึงเครียดเสียงเข้มขึ้น "
    "บทพูดตัวละครมีน้ำเสียงเหมือนพูดจริง แต่คงจังหวะการอ่านเท่าเดิมตลอด "
    "ห้ามสรุป ห้ามย่อ ห้ามเพิ่มคำทักทาย ห้ามถามอะไรทั้งสิ้น ห้ามพูดอะไรนอกจากข้อความที่ได้รับ"
)

# ข้อความนำหน้าท่อนที่ป้อน — ตัวเดียวกับที่ใช้ตอน probe (อย่าเปลี่ยนเล่นๆ:
# เกณฑ์ 100% ทั้งหมดวัดด้วย prefix นี้)
READER_FEED_PREFIX = "อ่านข้อความนี้:\n"


def build_reader_config(resume_handle: str | None):
    """config สำหรับ session อ่านหนังสือ — ฐานเดียวกับโหมดคุยแต่ต่างตรงที่ตั้งใจ:

    · system prompt = READER_PROMPT (ไม่ใช่ persona ขวัญ — persona สั่ง "กระชับ/ถามไถ่"
      ซึ่งตรงข้ามกับการอ่านยาวๆ)
    · **tools = None** — โหมดคุยเคยเจอโมเดลเลือก "ค้น" แทน "ตอบ" จนเงียบทั้ง turn
      ถ้าโหมดอ่านมี tool มันอาจเลือก "ค้น" แทน "อ่าน" แบบเดียวกัน
    · seed/temperature/voice คงเดิมทุกตัว — user เลือกโหมดนี้เพราะอยากได้ "เสียงขวัญเดิม"
    """
    cfg = build_live_config("kwan", READER_PROMPT, resume_handle)
    cfg.tools = None
    return cfg


def reader_stream_action(stopped: bool, paused: bool, reread: bool = False) -> str:
    """ระหว่างสตรีมเสียง **กลางท่อน** — ทำอะไรกับ chunk ถัดไป (pure → เทสได้)

    คืน: "stop" (ปิดไปเลย) · "abort" (พัก → ทิ้งท่อนที่เหลือ ไม่เลื่อนที่คั่น)
         · "restart" (🔁 อ่านท่อนนี้ใหม่ตั้งแต่ต้น) · "send"

    🔴 มีเพราะบั๊กจริง 2026-08-15: ลูปสตรีมเช็คแต่ `stop` ⇒ กดพักกลางท่อนแล้ว
    เสียงไหลต่อจนจบท่อน (600 ตัวอักษร ≈ ราว 1 นาที) · ธง `paused` เดิมถูกอ่านที่
    หัว feed_loop ผ่าน `next_read_action` เท่านั้น = "พักได้เมื่อจบท่อน" ซึ่งช้าเกินไป
    สำหรับปุ่มที่ผู้ใช้กดแล้วคาดหวังว่าจะเงียบทันที

    ⚠️ `stop` ต้องชนะ `paused` เสมอ — ปิด WS ระหว่างพักอยู่ต้องเลิก ไม่ใช่ค้างรอ
    """
    if stopped:
        return "stop"
    if paused:
        return "abort"
    if reread:
        return "restart"
    return "send"


def next_read_action(paused: bool, block: str, at_end: bool) -> str:
    """จบท่อนแล้วทำอะไรต่อ — pure → เทสได้

    คืน: "read" (ป้อนท่อนนี้) · "skip" (ท่อนว่าง ข้ามไป) · "wait" (พักอยู่) · "finish" (จบเล่ม)

    ท่อนว่างต้อง skip ไม่ใช่ read — ป้อนความว่างให้โมเดลแล้วมันจะตอบอะไรก็ได้
    = หลุดจากการอ่าน (โหมดนี้ไม่มีทางให้ผู้ใช้ดึงกลับนอกจาก restart)
    """
    if paused:
        return "wait"
    if at_end:
        return "finish"
    if not block.strip():
        return "skip"
    return "read"


# ── log วินิจฉัย (2026-08-18) — "ทำให้เครื่องมือวัดมีตา" ก่อนจะแก้อาการ ─────────
# ทั้งสามฟังก์ชันข้างล่างไม่เปลี่ยนพฤติกรรมอะไรเลย มีหน้าที่เดียวคือทำให้เหตุการณ์ที่
# **เคยผ่านไปโดยไม่ทิ้งร่องรอย** อ่านย้อนหลังได้จาก log อย่างเดียว โดยไม่ต้องถาม user

# เกณฑ์ "เงียบนานพอจนประตูไมค์ฝั่ง client น่าจะหมดอายุ" — มาจากช่วงที่วัดได้จริง
# ตอนค้นเว็บ (15-45 วิ) ⚠️ เป็นเกณฑ์ **สำหรับติดธงใน log เท่านั้น** ไม่มีโค้ดไหน
# ตัดสินใจจากค่านี้ — เปลี่ยนได้อิสระโดยไม่กระทบพฤติกรรมของเสียง
VOICE_SILENCE_SUSPECT_SEC = 15.0
# ช่วงหลังค้นเสร็จที่ยัง "น่าสงสัย" อยู่ — วัดจาก prod 2026-08-22 ว่า `search_done`
# (server ส่งผลค้นให้โมเดล) ห่างจากเสียงชิ้นแรกของโมเดล **1-4 วินาทีสม่ำเสมอ** (6 รอบ:
# 3/3/1/3/4/3) · เผื่อเป็น 8s ⇒ ครอบทั้งลายเซ็นเดิม (interrupt วินาทีเดียวกับค้นเสร็จ)
# และช่องส่งไม้ต่อ โดยไม่กวาด interrupt ที่เกิดตอน user คิดนาน ๆ เข้ามาด้วย
VOICE_POST_SEARCH_SUSPECT_SEC = 8.0


def interrupt_log_line(silence_s: float | None, search_count: int,
                       since_search_s: float | None,
                       since_mic_s: float | None = None) -> str:
    """บรรทัด log ตอน Gemini ส่ง `interrupted` — pure → เทสได้

    🔴 เหตุการณ์นี้ **ไม่เคยถูก log เลย** จนถึง 2026-08-18 ⇒ อาการ "คำตอบหลังค้นเว็บ
    หาย เหลือแต่ข้อความ" พิสูจน์ไม่ได้โดยโครงสร้าง (`flushPlayback()` ล้างเสียงทิ้ง
    แต่ไม่แตะข้อความ = ลายเซ็นที่ user เล่า แต่ไม่มีบรรทัดไหนยืนยันได้ว่าเกิดจริง)

    บรรทัดนี้ต้องแยกสองสาเหตุออกจากกันให้ได้ด้วยตัวเอง:
      1. user พูดแทรกเอง ⇒ เงียบมาแค่เศษวินาที (ขวัญกำลังพูดอยู่)
      2. ประตูไมค์หมดอายุกลาง turn ⇒ เงียบมาสิบ ๆ วินาที มักตามหลังการค้นเว็บ
    ⇒ ขาด "เงียบมากี่วินาที" ข้อเดียวบรรทัดนี้ก็ไร้ค่าเท่าไม่มี

    `silence_s=None` = ยังไม่เคยส่งเสียงเลยใน session นี้ — **ห้ามติดธง**
    (ไม่รู้ค่า ≠ เข้าเงื่อนไข · เดาว่าใช่คือวิธีที่ทำให้เสียเวลาไป 4 รอบเมื่อ 08-16)

    `since_mic_s` (เพิ่ม 2026-08-22) = เสียงจาก**ไมค์ผู้ใช้**เข้ามาล่าสุดเมื่อกี่วินาทีก่อน
    🔑 ทำไมต้องมี: สองรอบแรกของงานนี้ (08-21 และ 08-22 เช้า) ชี้ขาดไม่ได้ว่าเสียงที่
    ตัด turn เข้ามา*ตอนไหน* — ต้องอนุมานจากตำแหน่งเวลาของบรรทัด log แทน เพราะ
    **ไม่มีอะไรใน server ที่ log เสียงขาเข้าเลย** (`[VoiceLevel]` วัด `response.data`
    = เสียงที่ขวัญพูด ไม่ใช่ไมค์) · หลังปิดช่องส่งไม้ต่อแล้ว ตัวเลขนี้แยกได้ทันที:
      · ~0.0s ⇒ client ยังส่งเสียงอยู่ตอนโดนตัด = ยังมีรูเหลือ
      · สิบ ๆ วินาที ⇒ ประตูปิดได้จริง ต้นเหตุอยู่ที่อื่น
    `None` = ไม่เคยมีเสียงไมค์เข้ามาเลย — ต้องพิมพ์ต่างจาก 0.0 ไม่งั้นหลอกตาเหมือนเดิม
    """
    silence = f"{silence_s:.1f}s" if silence_s is not None else "?"
    if search_count > 0:
        search = f"ค้น {search_count} ครั้งใน turn นี้"
        if since_search_s is not None:
            search += f" (เสร็จเมื่อ {since_search_s:.1f}s ก่อน)"
    else:
        search = "ไม่ได้ค้นใน turn นี้"
    # 🔴 ธงต้องแคบพอที่จะยังมีความหมาย (แก้ 2026-08-23)
    # เดิมดู `silence_s` อย่างเดียว ⇒ หลังปิดรูแล้ว ธงขึ้นกับ interrupt ปกติที่
    # "ขวัญตอบจบ → user คิด 22 วิ → user พูด" (เจอจริง 08-23 12:31:38 · ค้นเสร็จไป
    # 33.4s แล้ว = คนละกลไก) · ถ้าติดธงทุกบรรทัด ธงจะไม่มีความหมาย = ตาบอดแบบใหม่
    # (กฎเดียวกับที่เขียนไว้ใน test_short_silence_is_not_flagged)
    #
    # ลายเซ็นจริงต้องครบ **สามอย่าง**: เงียบยาว + มีการค้นใน turn นี้ + interrupt
    # มาติดกับวินาทีที่ค้นเสร็จ (ทั้ง 3 ครั้งที่บันทึกได้ since_search = 0.0s)
    suspect = (
        silence_s is not None
        and silence_s >= VOICE_SILENCE_SUSPECT_SEC
        and search_count > 0
        and since_search_s is not None
        and since_search_s <= VOICE_POST_SEARCH_SUSPECT_SEC
    )
    flag = ' ⚠️ เข้าเงื่อนไข "ประตูไมค์หมดอายุ"' if suspect else ""
    mic = (f" · ไมค์เข้าเมื่อ {since_mic_s:.1f}s ก่อน" if since_mic_s is not None
           else " · ไม่มีเสียงไมค์เข้ามาเลยใน session นี้")
    return f"[Voice WS] interrupted — เงียบมา {silence} · {search}{mic}{flag}"


# ── watchdog กัน Gemini ตายเงียบกลางท่อน (คืนมา 2026-08-23 จาก 55b8594) ──────
# เจอจริง 2026-08-14 10:19:30: โมเดลหยุดส่งเฉยๆ **ไม่มี error ไม่มี go_away**
# ⇒ `async for ... session.receive()` รอ chunk ที่ไม่มีวันมาตลอดกาล
# watchdog ตัวเดิมยิงจริงบน prod: `18:27:11 ERROR Gemini เงียบเกิน 45s กลางท่อน`
#
# 🔒 **ตัวเดิมถูก revert (`2670c8e`) เพราะมัดรวมกับ pacing** — รอบนี้เอากลับ
# **เฉพาะ watchdog** · `reader_pacing_wait` / `LIVE_AUDIO_BYTES_PER_SECOND` /
# `READER_MAX_LEAD_SECONDS` / นาฬิกาการฟัง **ห้ามเอากลับ** (user เคาะปิดคดี 08-17
# + พิสูจน์แล้วว่าที่คั่นวิ่งเกิดจากตัวอ่านซ้อน ไม่ใช่ป้อนเร็ว: 13.8 ตัว/วิ vs 185.9)
#
# 45s มาจากของเดิม: chunk ปกติห่างกัน <5s ⇒ เกิน 45s = ตายเงียบแน่นอน ไม่ใช่ช้า
READER_STALL_TIMEOUT = float(os.getenv("READER_STALL_TIMEOUT", "45"))

# PCM 16-bit mono 24kHz = ฟอร์แมตเสียงขาออกของ Live API (ดู AudioLevelMeter.rate)
READER_AUDIO_BYTES_PER_SEC = 24000 * 2


def reader_feed_log_line(tag: str, pos: int, block_len: int) -> str:
    """บรรทัดตอนป้อนท่อนให้โมเดลอ่าน — คู่กับ `reader_turn_log_line`

    🔑 คู่กันถึงมีความหมาย: ลายเซ็นของ "Gemini ตายเงียบกลางท่อน" คือ **บรรทัด
    ป้อนท่อนที่ไม่มีบรรทัดท่อนจบตามมา** (ลูป `session.receive()` ค้างรอ chunk ที่
    ไม่มีวันมา ⇒ ไม่มี exception ไม่มีอะไรให้ log ในทางอื่นเลย)

    `tag` = session tag เดียวกับบรรทัดเปิด/ปิด — ตอนตัวอ่านซ้อน (บั๊ก 08-15)
    สอง session จะป้อนสลับกันใน log เดียว ไม่มี tag = อ่านไม่ออกว่าใครป้อนอะไร
    """
    return f"[Reader WS] ป้อนท่อน {tag} @{pos} ({block_len} ตัว)"


def reader_turn_log_line(tag: str, pos: int, block_len: int, elapsed_s: float,
                         audio_bytes: int) -> str:
    """บรรทัดตอนโมเดลอ่านท่อนจบจริง (turn_complete) — pure → เทสได้

    รายงาน **วินาทีของเสียง** ไม่ใช่ไบต์ดิบ เพราะไบต์เทียบกับนาฬิกาด้วยตาเปล่าไม่ได้
    · เสียง ≈ เวลาจริง = ปกติ · เสียงน้อยกว่าเวลาจริงมาก = โมเดลอืด/เกือบตาย
    · เสียง 0 = turn จบสมบูรณ์แต่ไม่ยอมอ่าน ⇒ ที่คั่นเลื่อนผ่านท่อนนี้ไปเงียบ ๆ
      = เนื้อหาหายหนึ่งท่อนโดยไม่มีใครรู้ ⇒ ต้องติดธง
    """
    audio_s = audio_bytes / READER_AUDIO_BYTES_PER_SEC
    flag = " ⚠️ ไม่มีเสียงเลย" if audio_bytes <= 0 else ""
    return (
        f"[Reader WS] ท่อนจบ {tag} @{pos} ({block_len} ตัว) "
        f"· เสียง {audio_s:.1f}s ใน {elapsed_s:.1f}s{flag}"
    )


# ── ปิด Gemini Live session ที่ค้าง เมื่อ browser หลุดตอนโมเดลเงียบ (2026-08-17) ──
#
# 🔴 **อุบัติเหตุจริงบน prod 13:10:56** — `1011 Resource has been exhausted (quota)`
# ครั้งแรกในทั้งไฟล์ log · เกิดจากมี **2 Live session พร้อมกันบน key เดียว**:
# หน้าเว็บถูกโหลดใหม่ตอน 13:10:09 ขณะสายเสียงของหน้าเก่ายังเปิดอยู่ ⇒ สายเก่ากลายเป็นผี
#
# ต้นเหตุคือ `asyncio.gather()` **ไม่ cancel พี่น้องเมื่อตัวหนึ่งจบปกติ — มันรอครบทุกตัว**
# ส่วน `send_loop` ค้างอยู่ใน `async for ... session.receive()` ที่ไม่มี timeout จึงเห็นธง
# `stop` ได้เฉพาะ **เมื่อมีข้อความเข้ามาจาก Gemini** ⇒ ตอน browser หลุดกลางช่วงที่โมเดล
# เงียบ (ค้นเว็บใช้ 15-45 วิ) ไม่มีใครปลุกมัน ⇒ `gather` ไม่คืน ⇒ `async with` ไม่ออก
# ⇒ session ค้างกิน slot จนกระทั่ง Gemini เอง reap ทิ้ง = **คือ 1008 ที่ ~151 วินาที**
#
# ⚠️ **ห้ามส่ง coroutine เข้า `asyncio.wait()` ตรงๆ** — Python 3.11 (prod = 3.11.15) โยน
# `TypeError: Passing coroutines is forbidden, use tasks explicitly.` = พังทุกการเชื่อมต่อ
# โดยที่เทสที่มีอยู่จับไม่ได้ (ไม่มีเทสไหนเคยเดินมาถึง `gather` เลยแม้แต่ตัวเดียว)
#
# 🔑 `asyncio.CancelledError` สืบจาก **`BaseException` ไม่ใช่ `Exception`** (วัดบน 3.11.15)
# ⇒ `except Exception` ใน `send_loop` **ไม่กลืนมัน** จึงไม่มี log error ปลอมตอนปิดปกติ
# (ต่างจากทางเลือก `session.close()` ซึ่งจะทำให้ `recv()` โยน `APIError` เข้า except นั้น
#  แล้วพิมพ์ ERROR ทุกครั้งที่ปิดหน้าเว็บ = ไปปนกับสัญญาณ 1008/1011 ที่เราใช้ตามบั๊กอยู่)
LOOP_EXIT_GRACE_SEC = float(os.getenv("VOICE_LOOP_EXIT_GRACE_SEC", "1.5"))


async def run_until_both_done(*coros, grace: float = LOOP_EXIT_GRACE_SEC) -> int:
    """รันลูป recv/send คู่กันแทน `asyncio.gather()` — คืน**จำนวนลูปที่ต้อง cancel**

    กติกา: ใครจบก่อน อีกตัวได้เวลา `grace` จบเอง **ไม่จบแล้วค่อย cancel**

    🔴 กฎนี้ไม่สมมาตรโดยตั้งใจ เพราะ 2 ลูปคุณสมบัติไม่เท่ากัน:
      · `recv_loop` มีจุดตื่นเอง (`wait_for(receive_json(), timeout=1.0)`) ⇒ จบเองได้ ≤1 วิ
      · `send_loop` ไม่มีจุดตื่น (`async for` บน stream ที่เงียบได้ไม่จำกัด) ⇒ ต้องมีคน cancel
    ⇒ **เส้น `go_away`/regen เดินทางเดิมบิตต่อบิต**: ที่นั่น `send_loop` จบก่อนแล้ว
    `recv_loop` เห็นธงเองใน ≤1 วิ < `grace` ⇒ **ไม่มีการ cancel เกิดขึ้นเลย** ซึ่งสำคัญ
    เพราะเส้นนั้นวิ่งทุก ~10 นาทีและทำงานถูกอยู่แล้ว — cancel มันกลาง `receive_json()`
    เสี่ยงทิ้งเฟรมเสียงจาก client ทั้งที่ไม่ได้มีอะไรเสีย (จึงมีเทสตรึงข้อนี้ไว้)

    ⚠️ ต้อง `await` ตัวที่ cancel ให้เสร็จ **ก่อน**คืน ไม่งั้น caller จะออกจาก
    `async with client.aio.live.connect(...)` ไปปิด ws ทับตอนที่ยังยกเลิกไม่จบ
    """
    tasks = {asyncio.ensure_future(c) for c in coros}
    await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

    still = {t for t in tasks if not t.done()}
    if still:
        _, still = await asyncio.wait(still, timeout=grace)
    for t in still:
        t.cancel()
    if still:
        await asyncio.gather(*still, return_exceptions=True)

    # ทั้งสองลูปดัก `Exception` ของตัวเองอยู่แล้ว — ถ้ามีตัวไหนหลุดมาถึงที่นี่ **ห้ามกลืน**
    # (พฤติกรรมเดิมของ `gather` คือโยนต่อให้ handler ข้างนอก log + ส่ง error ให้ client
    #  กลืนที่นี่ = สายตายเงียบโดยไม่มีบรรทัดไหนบอก ซึ่งคือกับดักที่เพิ่งเสียเวลาไปทั้งวัน)
    for t in tasks - still:
        if not t.cancelled() and t.exception() is not None:
            raise t.exception()

    return len(still)


# ── เครื่องมือวัดสภาพไมค์ฝั่ง client (2026-08-24) ──────────────────────────────
# ชั้น**วัด**เท่านั้น ไม่ใช่ตัวกู้ — งาน ค. (ปุ่มกู้ไมค์) รอผลจากบรรทัดนี้ก่อน
#
# คำถามที่ต้องการคำตอบ: บนเครื่อง user จริง `track.muted` / event `mute`,`unmute`
# ยิงไหม · หลักฐานจากภายนอกขัดกันเอง (Twilio issue #941 บอกใช้ไม่ได้ แต่โค้ด
# production ของ Twilio เอง + LiveKit + Amazon Chime ใช้อยู่ทั้งสามเจ้า)
# ดู vault `wiki/concepts/ios-audio-interruption-recovery.md`
_MIC_PROBE_FIELDS = (
    ("reason", "reason"),        # 'zeros' (track ตาย) | 'no-callback' (context ค้าง)
    ("track_muted", "muted"),    # 🎯 ค่าที่ต้องการรู้ที่สุด
    ("track_ready", "ready"),    # live | ended
    ("track_enabled", "enabled"),
    ("cap_state", "cap"),        # AudioContext ขาไมค์
    ("play_state", "play"),      # AudioContext ขาเล่น
    ("silent_ms", "silent_ms"),
    ("since_mute_ms", "since_mute_ms"),
)


def mic_probe_log_line(payload: dict) -> str:
    """บรรทัด log ของ probe จาก client — pure → เทสได้

    🔴 **ค่าที่ยังไม่รู้พิมพ์เป็น `?` ห้ามพิมพ์เป็น `False`/`0`** — ไม่งั้นเราจะ
    สรุปว่า "iOS ไม่ตั้งธง muted" ทั้งที่จริงคือฝั่ง client อ่านค่าไม่ได้
    (บทเรียนเดียวกับ `silence_s=None` ใน `interrupt_log_line`:
     ไม่รู้ค่า ≠ เข้าเงื่อนไข · เดาว่าใช่ = เสียเวลาไปหลายรอบเมื่อ 08-16)

    ต้องไม่ raise ไม่ว่า payload จะเพี้ยนแค่ไหน — ชั้นวัดพังห้ามล้ม session เสียง
    """
    try:
        p = payload if isinstance(payload, dict) else {}
        event = p.get("event")
        parts = [f"mic_probe {event if event is not None else '?'}"]
        for key, label in _MIC_PROBE_FIELDS:
            v = p.get(key)
            parts.append(f"{label}={'?' if v is None else v}")
        return " · ".join(parts)
    except Exception:                      # pragma: no cover — กันตายท่าเดียว
        return "mic_probe ? (payload อ่านไม่ได้)"
