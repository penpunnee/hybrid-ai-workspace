import os
import json
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IDENTITY_PATH = os.path.join(ROOT_DIR, "identity.json")


def load_identity() -> str:
    """โหลด identity.json อัตโนมัติเป็น context พื้นฐานของทุก assistant"""
    if not os.path.isfile(IDENTITY_PATH):
        return ""
    try:
        with open(IDENTITY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return f"=== ข้อมูลเจ้าของระบบ (Identity) ===\n{json.dumps(data, ensure_ascii=False, indent=2)}"
    except Exception as e:
        return f"[โหลด identity.json ไม่ได้: {e}]"


def extract_text_from_file(uploaded_file) -> str:
    """อ่านข้อความจากไฟล์ที่ upload (txt, md, json, py)"""
    name = uploaded_file.name.lower()
    content = uploaded_file.read()

    try:
        if name.endswith(".json"):
            data = json.loads(content)
            return f"[ไฟล์ JSON: {uploaded_file.name}]\n{json.dumps(data, ensure_ascii=False, indent=2)}"
        else:
            return f"[ไฟล์: {uploaded_file.name}]\n{content.decode('utf-8', errors='ignore')}"
    except Exception as e:
        return f"[ไม่สามารถอ่านไฟล์ {uploaded_file.name}: {e}]"


def load_skills_folder(folder_path: str) -> str:
    """โหลดไฟล์ทั้งหมดจากโฟลเดอร์ skills/ เป็น context"""
    if not os.path.isdir(folder_path):
        return ""

    texts = []
    for filename in sorted(os.listdir(folder_path)):
        filepath = os.path.join(folder_path, filename)
        if os.path.isfile(filepath) and filename.endswith((".txt", ".md", ".json", ".py")):
            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    texts.append(f"[{filename}]\n{f.read()}")
            except Exception as e:
                logger.warning(f"load_skills_folder: failed to read '{filepath}': {e}")
                pass

    return "\n\n---\n\n".join(texts)


SKILL_HEAD_CHARS = 500      # ส่วนหัวของไฟล์ที่ใช้เทียบคะแนน (ทั้งไฟล์ถูกฉีดเมื่อชนะ)


@dataclass(frozen=True)
class SkillPick:
    """ไฟล์ที่ถูกเลือกฉีด 1 ไฟล์ — มีชื่อไฟล์ติดมาด้วยเพื่อให้ 'ของที่ฉีดจริง' สังเกตได้

    เดิม `load_skills_relevant()` คืน string ก้อนเดียว → ไม่มีใครรู้ว่ามันเลือกไฟล์ไหน
    ต้องไปคำนวณซ้ำเอาเองข้างนอก ซึ่งเป็นวิธีที่ทำให้ตัวเลขไม่ตรงกับ prod มาแล้ว
    (2026-08-03: จำลองโดยไม่ cap top-3 ได้ P=0.170 ทั้งที่ของจริง 0.109)
    """
    name: str
    score: float
    content: str


def select_skill_files(folder_path: str, query: str, max_files: int = 3) -> list[SkillPick]:
    """เลือก skill file ที่จะฉีด — **ตรรกะการเลือกตัวจริงของ prod อยู่ที่นี่ที่เดียว**

    scoring: นับคำจาก `query.lower().split()` ที่ไปโผล่ใน `filename + หัวไฟล์ 500 ตัว`
    ⚠️ วิธีนี้มองภาษาไทยแทบไม่เห็น (ไทยเขียนติดกัน `.split()` ได้ token เดียว) — วัดจริง
    บน prod: ไทยล้วนฉีด 32% vs มี Latin ปน 84%. **ยังไม่แก้** จนกว่าจะมีหลักฐานว่าของที่
    ฉีดเพิ่มมาเกี่ยวจริง (ดู backlog ข้อ 21 + `utils/skills_shadow.py`)
    """
    if not os.path.isdir(folder_path) or not query:
        return []

    query_words = set(query.lower().split())
    scored: list[SkillPick] = []

    # ไม่ sort ชื่อไฟล์: ลำดับ os.listdir คือลำดับที่ prod ใช้ตัดสินคะแนนเท่ากันมาตลอด
    # (sort จะเปลี่ยนว่าไฟล์ไหนหลุด top-3 ตอนคะแนนเสมอ = เปลี่ยนพฤติกรรมเงียบๆ)
    for filename in os.listdir(folder_path):
        filepath = os.path.join(folder_path, filename)
        if not (os.path.isfile(filepath) and filename.endswith((".txt", ".md", ".json", ".py"))):
            continue
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            haystack = (filename + " " + content[:SKILL_HEAD_CHARS]).lower()
            score = sum(1 for w in query_words if len(w) > 1 and w in haystack)
            if score > 0:
                scored.append(SkillPick(filename, float(score), content))
        except Exception as e:
            logger.warning(f"select_skill_files: failed to read '{filepath}': {e}")

    scored.sort(key=lambda p: p.score, reverse=True)     # stable → คะแนนเท่ากันคงลำดับเดิม
    return scored[:max_files]


def format_skill_files(picks: list[SkillPick]) -> str:
    """แปลงไฟล์ที่เลือกแล้วเป็นก้อน context — รูปแบบต้องคงเดิมเป๊ะ (เข้า prompt จริง)"""
    return "\n\n---\n\n".join(f"[{p.name}]\n{p.content}" for p in picks)


def load_skills_relevant(folder_path: str, query: str, max_files: int = 3) -> str:
    """โหลดเฉพาะ skill files ที่เกี่ยวข้องกับ query โดย keyword scoring — ไม่โหลดทั้งหมด

    เหลือไว้เป็น wrapper บางๆ: ตรรกะจริงอยู่ที่ `select_skill_files()` เพื่อให้ผู้เรียก
    ที่อยากรู้ *ชื่อไฟล์* (shadow logging) ใช้เส้นเดียวกันเป๊ะ ไม่ใช่คำนวณขนานกันไป
    """
    return format_skill_files(select_skill_files(folder_path, query, max_files))


def build_rag_context(uploaded_files: list, skills_folder: str = "") -> str:
    """รวม context จาก identity.json (auto), skills folder, และไฟล์ที่ upload"""
    parts = []

    # Auto-load identity.json เสมอ
    identity = load_identity()
    if identity:
        parts.append(identity)

    if skills_folder:
        skills_text = load_skills_folder(skills_folder)
        if skills_text:
            parts.append(f"=== ข้อมูลจาก Skills Folder ===\n{skills_text}")

    for f in uploaded_files:
        parts.append(extract_text_from_file(f))

    return "\n\n".join(parts)


def inject_context_to_system(system_prompt: str, context: str) -> str:
    """แทรก RAG context เข้าไปใน system prompt"""
    if not context.strip():
        return system_prompt
    return (
        f"{system_prompt}\n\n"
        f"--- ข้อมูล Context ที่ได้รับ (RAG) ---\n"
        f"{context}\n"
        f"--- จบ Context ---\n"
        f"กรุณาใช้ข้อมูล Context ด้านบนประกอบการตอบคำถามด้วย"
    )
