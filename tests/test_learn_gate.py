"""Tests สำหรับ reasoning/learn_gate.py — quality gate ของ auto-learn

root cause: chat.py auto-save 'บทเรียน' จากทุก exchange >100 char โดยไม่เช็กคุณภาพ
→ คำตอบกุ (ping/network) + คำปฏิเสธของพี่ปอย ("ไม่ใช่ละ") กลายเป็นบทเรียน
→ recall กลับมา prime การกุซ้ำ (feedback loop ปนเปื้อน)
"""
from reasoning.learn_gate import should_auto_learn


def test_negative_feedback_blocked():
    """คำปฏิเสธ/แก้คำตอบ → ไม่เรียน (คำตอบเก่าผิด อย่าตกผลึก)"""
    for p in ["ไม่ใช่ละ", "ผิดแล้ว ds923+ ต่างหาก", "ไม่ถูกนะ", "มั่วแล้ว", "ตอบผิด"]:
        ok, reason = should_auto_learn(p)
        assert ok is False, f"ควร block: {p}"
        assert reason == "negative_feedback"


def test_realtime_home_tool_blocked():
    """งาน real-time/อุปกรณ์บ้าน → ไม่เรียน (โมเดลเล่าไม่น่าเชื่อถือ กุง่าย)"""
    for p in ["ช่วย ping เช็คอุปกรณ์ในเครือข่ายบ้าน", "NAS ออนไลน์ไหม",
              "disk เต็มยัง", "docker container รันอยู่ไหม", "เปิด PC ให้หน่อย"]:
        ok, reason = should_auto_learn(p)
        assert ok is False, f"ควร block: {p}"
        assert reason == "realtime_home_tool"


def test_empty_blocked():
    assert should_auto_learn("")[0] is False
    assert should_auto_learn("   ")[0] is False


def test_legit_knowledge_allowed():
    """คำถามความรู้/โค้ดทั่วไป → เรียนได้ปกติ"""
    for p in ["ช่วยเขียน function Python หา fibonacci",
              "อธิบาย closure ใน JavaScript",
              "โค้ดนี้มีจุดที่เขียนผิดตรงไหน",   # มี 'ผิด' แต่ไม่ใช่ rejection phrase
              "วางแผน roadmap โปรเจกต์ใหม่"]:
        ok, reason = should_auto_learn(p)
        assert ok is True, f"ควรเรียนได้: {p}"
        assert reason == "ok"
