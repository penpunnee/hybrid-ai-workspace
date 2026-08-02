"""learn_gate — quality gate ของ auto-learn (กัน memory/lessons ปนเปื้อน)

ใช้ก่อนตัดสินใจ save_lesson ใน routers/chat.py
2 ชั้น: `should_auto_learn(prompt)` กันที่ต้นทาง · `clean_lesson(raw)` กรอง
สิ่งที่โมเดลคายออกมาก่อนเก็บจริง
"""
import re

from utils.home_tools import detect_home_tools

# คำที่บ่งชี้ว่าพี่ปอยกำลัง 'ปฏิเสธ/แก้คำตอบเก่า' — exchange นี้ไม่ควรตกผลึกเป็นบทเรียน
# (เลือกคำที่ชัดเจน ไม่ชน 'ผิด' เดี่ยวๆ ที่อาจอยู่ในคำถามโค้ดปกติ)
_REJECTION_KW = (
    "ไม่ใช่", "ผิดแล้ว", "ไม่ถูก", "มั่ว", "ไม่ช่าย",
    "ตอบผิด", "ยังผิด", "ไม่เอา", "แก้ใหม่", "ไม่ใช่ละ",
)


def should_auto_learn(prompt: str) -> tuple[bool, str]:
    """ควรบันทึก exchange นี้เป็น 'บทเรียน' ไหม → (ok, reason)

    block เมื่อ:
      - empty                : prompt ว่าง
      - negative_feedback    : พี่ปอยปฏิเสธ/แก้คำตอบ (เก่าผิด อย่าตกผลึก)
      - realtime_home_tool   : งาน real-time/อุปกรณ์บ้าน (โมเดลเล่าไม่น่าเชื่อถือ → กุง่าย)
      - realtime_query       : คำถามข้อมูลสด (ราคา/อากาศ/ข่าว/ภัยพิบัติ) — คำตอบ
        ถูกต้องแค่ ณ วันนั้น ถ้าเก็บเป็น "ความรู้ถาวร" จะถูกป้อนให้ AI อ่านทุก
        prompt ไปตลอด (เจอจริงบน prod: ราคาทองวันที่ 11 มิ.ย. + พยากรณ์อากาศ
        คืนนั้น ยังอยู่ในคลัง lessons จนถึงวันนี้ — และเป็นเหตุที่คะแนน lessons
        กลับด้าน เพราะคลังมีแต่ข้อมูลสดเก่า)
    """
    p = (prompt or "").strip()
    if not p:
        return False, "empty"
    low = p.lower()
    if any(kw in low for kw in _REJECTION_KW):
        return False, "negative_feedback"
    if detect_home_tools(p):
        return False, "realtime_home_tool"
    try:
        from utils.response_cache import is_realtime_query
        if is_realtime_query(p):
            return False, "realtime_query"
    except Exception:
        pass  # ตัวตรวจพัง ไม่ควรทำให้ auto-learn ล่มทั้งระบบ
    return True, "ok"


# คำนำที่โมเดลชอบใส่ก่อนเนื้อหาจริง — ตัดทิ้งก่อนเก็บ (เจอจริงในคลัง prod)
_PREAMBLE_RE = re.compile(
    r"^\s*(here\s+is\s+[^:\n]{0,60}:|here's\s+[^:\n]{0,60}:|"
    r"นี่คือ[^:\n]{0,60}:|สรุป(?:ได้)?(?:ดังนี้)?\s*:|บทเรียน\s*:)\s*",
    re.IGNORECASE,
)

# ขึ้นต้นด้วยสัญลักษณ์ error = ข้อความระบบ ไม่ใช่บทเรียน
_ERROR_PREFIX = ("⚠️", "❌", "🚫", "error:", "exception:")

_MIN_LESSON_LEN = 10


# วลีที่บ่งบอก "ความชอบ" จริง — ต้องเจาะจงพอที่จะไม่ชนคำถามปกติ
# (เดิมใช้คำว่า "อธิบาย" เดี่ยวๆ ซึ่งโผล่ใน "ช่วยอธิบาย FastAPI หน่อย" = false positive)
# เรียงลำดับสำคัญ: ตัวหลังในประโยคชนะ (เจตนาล่าสุดของผู้พูด)
_PREF_PATTERNS: tuple[tuple[str, str, str], ...] = (
    # (key, regex, value)
    ("style",  r"ตอบสั้น|สั้นๆ|กระชับ|ย่อๆ|สรุปสั้น",              "ชอบคำตอบสั้น กระชับ"),
    ("style",  r"ละเอียดๆ|อธิบายละเอียด|แบบละเอียด|ลงลึก",        "ชอบคำตอบละเอียด ลงลึก"),
    ("format", r"เป็นข้อๆ|เป็นข้อ ๆ|bullet|เป็นบูลเล็ต",            "ชอบคำตอบเป็นข้อๆ"),
    ("format", r"เป็นตาราง|ขอตาราง|ทำเป็นตาราง",                  "ชอบคำตอบเป็นตาราง"),
    ("format", r"เป็นแผนภาพ|เป็นผัง|ไดอะแกรม|diagram|ผังงาน",      "ชอบให้มีแผนภาพประกอบ"),
)


def detect_preferences(prompt: str) -> list[tuple[str, str]]:
    """หา preference ของ user จาก prompt → [(key, value)] (ว่างถ้าไม่เจอ)

    แยกออกมาเป็นฟังก์ชัน pure เพราะเดิมโค้ดนี้ฝังอยู่ในเธรด `_learn()` ของ
    `routers/chat.py` ทำให้ทำงานเฉพาะเมื่อคำตอบยาว >100 ตัวอักษร **และ** ผ่าน
    gate ของ lesson ก่อน → collection `preferences` เลยว่างเปล่า 0 รายการ
    ตลอด 3 เดือน (audit 2026-08-02)

    key ต่างกันต่อหมวด (style/format) เพื่อไม่ให้ id ชนกันแบบบั๊กเดิมที่ทั้ง
    "ตอบสั้น" และ "อธิบาย" map ไป key `style` ตัวเดียว
    """
    if not prompt:
        return []
    found: dict[str, str] = {}
    for key, pattern, value in _PREF_PATTERNS:
        if re.search(pattern, prompt, re.IGNORECASE):
            found[key] = value          # ตัวหลังทับตัวหน้า = เจตนาล่าสุดชนะ
    return list(found.items())


def should_remember(prompt: str, response: str) -> tuple[bool, str]:
    """ควรเก็บ exchange นี้ลง episodic memory ไหม → (ok, reason)

    ต่างจาก `should_auto_learn()` ตรงที่ดู **คำตอบ** ด้วย ไม่ใช่แค่คำถาม

    ⚠️ episodic **ควร**เป็นบันทึกบทสนทนาตามหน้าที่ของมัน (ต่างจาก lessons/skills
    ที่ควรเป็นความรู้) จึงกันเฉพาะ 2 อย่างที่พิสูจน์แล้วว่าเป็นโทษ:
      - ข้อมูลสด — คำตอบถูกแค่ ณ วันนั้น เก็บไว้ = ป้อนของผิดให้ตัวเองในอนาคต
        (วัดจริง 2026-08-02: memory_kwan 57/92 · memory_logic 47/62 เป็นแบบนี้
         รวมถึง "ราคาทองวันนี้ ขายออก 72,100" ที่ผิดจากราคาจริงวันนี้ 7,900 บาท)
      - ข้อความ error/ระบบ — ไม่ใช่บทสนทนาจริง (27 + 21 รายการในคลัง)

    เดิมเส้น chat ปกติไม่ผ่าน gate เลย ขณะที่เส้น agent (`persist_agent_turn`)
    ผ่าน `should_auto_learn()` อยู่แล้ว — สองเส้นไม่ตรงกัน
    """
    ok, reason = should_auto_learn(prompt)
    if not ok:
        return False, reason
    text = (response or "").strip()
    if not text:
        return False, "empty_response"
    low = text.lower()
    if any(low.startswith(p.lower()) for p in _ERROR_PREFIX):
        return False, "error_response"
    if any(kw in text for kw in _REFUSAL_KW):
        return False, "error_response"
    return True, "ok"


# คำที่บ่งชี้ว่าคำตอบเป็นข้อความปฏิเสธ/ระบบขัดข้อง ไม่ใช่เนื้อหาจริง
# (เลือกวลีที่ยาวพอจะไม่ชนคำตอบปกติที่บังเอิญมีคำว่า "ขอโทษ")
_REFUSAL_KW = (
    "ไม่สามารถช่วยเหลือในกรณีนี้ได้",
    "การตอบหยุดกลางคัน",
    "ยังไม่ได้ตั้งค่า",
    "เชื่อมต่อ server ไม่ได้",
    "โมเดลไม่ได้ให้คำตอบ",
)


def clean_lesson(raw: str) -> str | None:
    """ทำความสะอาดสิ่งที่โมเดลคายออกมา → คืนบทเรียนที่ใช้ได้ หรือ None ถ้าไม่ควรเก็บ

    ทิ้งเมื่อ: มี SKIP (โมเดลบอกว่าไม่มีบทเรียน — เดิมเช็ค == "SKIP" เป๊ะๆ ทำให้
    "คืนนี้ฝนจะตกไหม? SKIP" รอดเข้าไปอยู่ใน prod จริง) · เป็นข้อความ error ·
    สั้นเกินไปหลังตัดคำนำ
    """
    if not raw:
        return None
    text = raw.strip()
    if not text:
        return None

    # SKIP ที่ไหนก็ได้ในข้อความ = โมเดลบอกว่าไม่มีบทเรียน
    if re.search(r"\bskip\b", text, re.IGNORECASE):
        return None

    low = text.lower()
    if any(low.startswith(p.lower()) for p in _ERROR_PREFIX):
        return None

    text = _PREAMBLE_RE.sub("", text, count=1).strip().strip('"').strip()
    if len(text) < _MIN_LESSON_LEN:
        return None
    return text
