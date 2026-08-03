import os
import json
import logging
import re

from core.config import SKILLS_DB_PATH

logger = logging.getLogger(__name__)


def _load_skills_db() -> dict:
    if os.path.exists(SKILLS_DB_PATH):
        try:
            with open(SKILLS_DB_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load skills_db.json: {e}")
            return {}
    return {}


def _save_skills_db(db: dict):
    try:
        with open(SKILLS_DB_PATH, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"Failed to save skills_db.json: {e}")
        pass


def save_skill(topic: str, summary: str, source: str = "auto", sync: bool = True) -> bool:
    """บันทึก skill ใหม่ที่ AI เรียนรู้ — คืน True ถ้าบันทึกจริง

    gate ด้วยเกณฑ์เดียวกับตอนลบ (`_is_meaningful_skill`) — ทางเข้าต้องเท่าทางออก
    ไม่งั้นระบบวนลูป "สร้าง → ล้าง → สร้างใหม่" (ต้นเหตุของขยะที่ล้างไปในข้อ 9)
    """
    if not _is_meaningful_skill(topic, summary):
        logger.info(f"[Skills] ปฏิเสธ skill ที่ไม่ผ่านเกณฑ์: {topic!r}")
        return False

    db = _load_skills_db()
    db[topic] = {
        "summary": summary,
        "source": source,
        "updated": __import__("datetime").datetime.now().isoformat(),
    }
    _save_skills_db(db)

    if not sync:
        return True

    # Sync to semantic search (sync=False เพื่อข้ามเมื่อบันทึกหลายรายการพร้อมกัน)
    try:
        from utils.skills_search import sync_skills_to_search
        sync_skills_to_search(db)
    except Exception as e:
        logger.warning(f"sync_skills_to_search failed: {e}")

    return True


def search_skills(query: str, n_results: int = 3) -> str:
    """ค้นหา skills ที่เกี่ยวข้องกับ query โดยใช้ semantic search

    ล้มเหลว = คืนว่าง ไม่ใช่คืนทั้งคลัง (fail-closed)
    เดิม fallback เป็น `get_all_skills()` → ChromaDB ไม่พร้อมเมื่อไหร่ก็ยัดทุกหัวข้อ
    เข้า context ทุกเทิร์น (วัดบน prod: 22 รายการ = 7,455 chars ≈ 1,863 tokens)
    ทั้งที่ไม่มีอะไรบอกว่ามันเกี่ยวกับคำถาม — และบนเส้น ollama ที่ตัด context ที่
    2,000 chars ยังไปเบียดข้อมูล real-time กับ citations ตกท้ายอีก
    ความรู้ยังเข้าได้ทาง `load_skills_relevant()` ซึ่งอ่าน .md ตรงและไม่พึ่ง ChromaDB
    """
    try:
        from utils.skills_search import get_skills_search
        search = get_skills_search()

        if not search.available:
            logger.warning("Skills search ใช้ไม่ได้ — ข้ามการฉีด skill เทิร์นนี้")
            return ""

        results = search.search(query, n_results=n_results)

        if not results:
            return ""

        lines = ["[ความรู้ที่เกี่ยวข้องกับคำถาม]"]
        for skill in results:
            lines.append(f"• {skill['topic']}: {skill['summary']}")
            if skill.get('category'):
                lines.append(f"  (หมวดหมู่: {skill['category']})")

        return "\n".join(lines)
    except Exception as e:
        logger.error(f"Skills search failed: {e} — ข้ามการฉีด skill เทิร์นนี้")
        return ""


def get_all_skills() -> str:
    """ดึง skills ทั้งหมดเป็น text สำหรับ inject ใน system prompt"""
    db = _load_skills_db()
    if not db:
        return ""
    lines = ["[ความรู้ที่สะสมไว้]"]
    for topic, data in db.items():
        lines.append(f"• {topic}: {data['summary']}")
    return "\n".join(lines)


def _is_meaningful_skill(topic: str, summary: str) -> bool:
    """กรอง skill ที่เป็น fragment / junk ออก"""
    import re
    # ตัด emoji และ symbols ออก เหลือแค่ตัวอักษรจริง
    clean = re.sub(r'[^\w\s฀-๿]', '', topic).strip()

    # หัวข้อต้องมีตัวอักษรมากกว่า 4 ตัว
    if len(clean) < 5:
        return False

    # summary ต้องมีเนื้อหาพอสมควร
    clean_summary = re.sub(r'[^\w\s฀-๿]', '', summary).strip()
    if len(clean_summary) < 20:
        return False

    # กรอง fragment/command ที่ไม่ใช่ความรู้จริง
    _JUNK_PATTERNS = [
        r'^ได้เลย', r'^ดู\s', r'^เปิด\s', r'^แล้ว\s',
        r'pull.*NAS', r'localhost', r'^http',
        r'ขั้นตอนข้างบน', r'ตามขั้นตอน',
    ]
    for p in _JUNK_PATTERNS:
        if re.search(p, topic, re.IGNORECASE):
            return False

    return True


def cleanup_junk_skills() -> dict:
    """ลบ skills ที่เป็น junk ออกจาก skills_db.json และ sync ChromaDB"""
    db = _load_skills_db()
    removed = []
    kept = {}
    for topic, data in db.items():
        summary = data.get("summary", "")
        if _is_meaningful_skill(topic, summary):
            kept[topic] = data
        else:
            removed.append(topic)

    if removed:
        _save_skills_db(kept)
        try:
            from utils.skills_search import sync_skills_to_search
            sync_skills_to_search(kept)
        except Exception as e:
            logger.warning(f"cleanup sync failed: {e}")
        logger.info(f"[Cleanup] ลบ {len(removed)} junk skills: {removed[:5]}...")

    return {"removed": removed, "remaining": len(kept)}


_FENCE_RE = re.compile(r"^(```|~~~)")


def _fence_flags(lines: list[str]) -> list[bool]:
    """คืน list ขนานกับ lines: True = บรรทัดนั้นอยู่ใน code fence (รวมตัว fence เอง)

    รองรับทั้ง ``` และ ~~~ ตาม CommonMark · fence ที่เปิดค้างไม่ปิด ให้ถือว่าครอบถึงท้ายไฟล์
    (ปลอดภัยกว่าเดาว่าปิดเอง — ความไม่แน่ใจเอียงไปทางไม่เก็บ ดีกว่าเก็บขยะ)
    """
    flags = []
    marker = None
    for line in lines:
        stripped = line.strip()
        m = _FENCE_RE.match(stripped)
        if marker is None and m:
            marker = m.group(1)
            flags.append(True)
        elif marker is not None and stripped.startswith(marker):
            marker = None
            flags.append(True)
        else:
            flags.append(marker is not None)
    return flags


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
                    if _is_meaningful_skill(key, value):
                        save_skill(
                            topic=key,
                            summary=value[:300],
                            source=f"identity.json ({assistant_name})"
                        )
                        extracted.append(key)
            return extracted
    except Exception as e:
        logger.debug(f"auto_extract_skills: text is not valid JSON, falling back to markdown: {e}")
        pass

    # สกัดจาก Markdown headings — ต้องมี content ข้างใต้ด้วย
    # ⚠️ ต้องรู้ว่าบรรทัดไหนอยู่ใน code fence: `.env`/shell ใช้ `#` เป็นคอมเมนต์
    # ถ้าไม่เช็ค คอมเมนต์ทุกบรรทัดจะกลายเป็น "หัวข้อความรู้" และหัวข้อจริงที่อยู่เหนือบล็อก
    # จะถูกทิ้งเพราะ loop เก็บเนื้อหาไปหยุดที่คอมเมนต์บรรทัดแรก (เจอจริงบน prod, backlog ข้อ 18)
    lines = text.split("\n")
    in_fence = _fence_flags(lines)

    for i, line in enumerate(lines):
        if in_fence[i]:
            continue
        line = line.strip()
        if line.startswith("## ") or line.startswith("# "):
            topic = line.lstrip("#").strip()
            if not (4 < len(topic) < 80):
                continue
            # ดึง content ข้างใต้ heading (ไม่รวม heading ถัดไป)
            content_lines = []
            for j in range(i + 1, min(i + 10, len(lines))):
                next_line = lines[j].strip()
                if next_line.startswith("#") and not in_fence[j]:
                    break
                if _FENCE_RE.match(next_line):
                    continue  # ตัว fence เองไม่ใช่เนื้อหา
                if next_line:
                    content_lines.append(next_line)
            summary = " ".join(content_lines[:3]).strip()[:200]

            if _is_meaningful_skill(topic, summary):
                save_skill(topic=topic, summary=summary, source=assistant_name)
                extracted.append(topic)

    return extracted


def get_skill_count() -> int:
    return len(_load_skills_db())
