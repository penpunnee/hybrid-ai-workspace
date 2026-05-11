"""Question Complexity Classifier

จัดประเภทคำถามเพื่อ route ไปยัง model ที่เหมาะสม
ไม่ใช้ AI — ใช้ pattern matching เพื่อความเร็ว
"""
import re
from enum import Enum


class Complexity(str, Enum):
    SIMPLE    = "simple"     # chat ทั่วไป greeting สั้นๆ
    NORMAL    = "normal"     # อธิบาย how-to คำถามกลางๆ
    REASONING = "reasoning"  # วิเคราะห์ เปรียบเทียบ debug ซับซ้อน


# ── Patterns ─────────────────────────────────────────────────────────────────

_SIMPLE_PATTERNS = [
    r"^(สวัสดี|หวัดดี|ดีครับ|ดีค่ะ|hello|hi)\b",
    r"^(ขอบคุณ|thanks|thank you)\b",
    r"^(โอเค|โอเค|ok|okay|ได้เลย|รับทราบ)\b",
    r"^(สบายดีไหม|เป็นยังไงบ้าง|how are you)\b",
    r"^(ใช่|ไม่ใช่|yes|no|yep|nope)\b",
    r"^[\w\s]{1,20}\?$",           # คำถามสั้นมาก < 20 ตัวอักษร
]

_REASONING_PATTERNS = [
    # การวิเคราะห์และเปรียบเทียบ
    r"(เปรียบเทียบ|ต่างกัน|ดีกว่า|ข้อดีข้อเสีย|pros.{0,5}cons)",
    r"(compare|difference|better|advantage|disadvantage)",
    r"(วิเคราะห์|analyze|analysis|evaluate|ประเมิน)",

    # การคิดเหตุผล
    r"(ทำไม|เพราะอะไร|สาเหตุ|why|reason|because)",
    r"(ควรจะ|น่าจะ|should|should i|คิดว่าดีไหม)",
    r"(แนะนำ|recommend|suggest|ช่วยแนะนำ)",

    # Technical reasoning
    r"(debug|error|bug|ปัญหา|ไม่ทำงาน|crash|fix)",
    r"(design|architecture|โครงสร้าง|ออกแบบระบบ)",
    r"(optimize|performance|ประสิทธิภาพ|ช้า|เร็วขึ้น)",

    # การวางแผนและออกแบบ
    r"(วางแผน|plan|roadmap|strategy|กลยุทธ์)",
    r"(step.{0,5}step|ขั้นตอน|วิธีการ|how to)",
    r"(ออกแบบ|design|schema|architecture|โครงสร้าง|สร้างระบบ)",

    # คำถามซับซ้อน
    r"(อธิบายละเอียด|explain in detail|อธิบายให้ครบ)",
    r"(ทั้งหมด|ครอบคลุม|comprehensive|overall)",
]

_REASONING_MIN_WORDS = 15  # ถ้าคำถามยาวกว่านี้ = complex

# Internet search patterns → ต้องใช้ Gemini Agent
_SEARCH_PATTERNS = [
    r"หาในเน็ต|หาข้อมูลในเน็ต|ค้นในเน็ต|search.*net|ค้นหาข้อมูล.*ออนไลน์",
    r"ไปหาข้อมูล|ช่วยหาข้อมูล|หาข้อมูลให้|google.*หน่อย",
    r"ข้อมูลล่าสุด|real.?time|ข่าวล่าสุด|ราคาตอนนี้|อัตราแลกเปลี่ยน",
    r"ราคาทอง|ราคาหุ้น|ราคาน้ำมัน|ราคา.*วันนี้|ค้นหาข้อมูล.*ราคา",
    r"อากาศ.*พรุ่งนี้|พยากรณ์อากาศ|weather.*tomorrow",
    r"เปิดเว็บ|browse|ค้น.*web|search.*web",
]


def needs_internet(text: str) -> bool:
    """ตรวจว่า query ต้องการ internet search จริงๆ"""
    text_lower = text.lower()
    for p in _SEARCH_PATTERNS:
        if re.search(p, text_lower, re.IGNORECASE):
            return True
    return False


def classify(text: str) -> Complexity:
    """จัดประเภทคำถาม → Complexity enum"""
    text_lower = text.lower().strip()
    word_count = len(text_lower.split())

    # ตรวจ reasoning pattern ก่อนเสมอ (priority สูงสุด)
    for p in _REASONING_PATTERNS:
        if re.search(p, text_lower, re.IGNORECASE):
            return Complexity.REASONING

    # คำถามยาวมาก → REASONING
    if word_count >= _REASONING_MIN_WORDS:
        return Complexity.REASONING

    # ตรวจ simple pattern
    if word_count <= 5:
        for p in _SIMPLE_PATTERNS:
            if re.search(p, text_lower, re.IGNORECASE):
                return Complexity.SIMPLE

    # ข้อความสั้นมาก (< 8 ตัวอักษร) และไม่มี space = คำเดี่ยว → SIMPLE
    if len(text.strip()) < 8 and word_count <= 1:
        return Complexity.SIMPLE

    return Complexity.NORMAL


def classify_label(text: str) -> str:
    c = classify(text)
    return {
        Complexity.SIMPLE:    "⚡ simple",
        Complexity.NORMAL:    "💬 normal",
        Complexity.REASONING: "🧠 reasoning",
    }[c]
