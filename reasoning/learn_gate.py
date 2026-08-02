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
