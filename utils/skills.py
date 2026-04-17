import os
import json

SKILLS_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "skills_db.json")


def _load_skills_db() -> dict:
    if os.path.exists(SKILLS_DB_PATH):
        try:
            with open(SKILLS_DB_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_skills_db(db: dict):
    try:
        with open(SKILLS_DB_PATH, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def save_skill(topic: str, summary: str, source: str = "auto"):
    """บันทึก skill ใหม่ที่ AI เรียนรู้"""
    db = _load_skills_db()
    db[topic] = {
        "summary": summary,
        "source": source,
        "updated": __import__("datetime").datetime.now().isoformat(),
    }
    _save_skills_db(db)


def get_all_skills() -> str:
    """ดึง skills ทั้งหมดเป็น text สำหรับ inject ใน system prompt"""
    db = _load_skills_db()
    if not db:
        return ""
    lines = ["[ความรู้ที่สะสมไว้]"]
    for topic, data in db.items():
        lines.append(f"• {topic}: {data['summary']}")
    return "\n".join(lines)


def auto_extract_skills(text: str, assistant_name: str) -> list[str]:
    """
    สรุป skills จากไฟล์ที่ upload อัตโนมัติ
    คืนค่า list ของ topics ที่สกัดได้
    """
    if not text or len(text) < 50:
        return []

    extracted = []

    # สกัด JSON keys เป็น topics (สำหรับ identity.json)
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, str) and len(value) > 10:
                    save_skill(
                        topic=key,
                        summary=value[:300],
                        source=f"identity.json ({assistant_name})"
                    )
                    extracted.append(key)
            return extracted
    except Exception:
        pass

    # สกัดจาก Markdown headings
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("## ") or line.startswith("# "):
            topic = line.lstrip("#").strip()
            if 3 < len(topic) < 80:
                # ดึง content ถัดไป 3 บรรทัด
                idx = text.find(line)
                snippet = text[idx:idx+300].split("\n")
                summary = " ".join(snippet[1:4]).strip()[:200]
                if summary:
                    save_skill(topic=topic, summary=summary, source=assistant_name)
                    extracted.append(topic)

    return extracted


def get_skill_count() -> int:
    return len(_load_skills_db())
