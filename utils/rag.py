import os
import json

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
            except Exception:
                pass

    return "\n\n---\n\n".join(texts)


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
