"""learn_gate — quality gate ของ auto-learn (กัน memory/lessons ปนเปื้อน)

ใช้ก่อนตัดสินใจ save_lesson ใน routers/chat.py
"""
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
    """
    p = (prompt or "").strip()
    if not p:
        return False, "empty"
    low = p.lower()
    if any(kw in low for kw in _REJECTION_KW):
        return False, "negative_feedback"
    if detect_home_tools(p):
        return False, "realtime_home_tool"
    return True, "ok"
