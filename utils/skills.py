import os
import json
import logging
import re
import threading

from core.config import SKILLS_DB_PATH

logger = logging.getLogger(__name__)


# ── พื้นคะแนนสัมบูรณ์ของ skills injection (backlog ข้อ 9 — เคส "openclaw คืออะไร") ──
# จัดอันดับตอบได้แค่ "อันไหนดีกว่า" ตอบไม่ได้ว่า "ดีพอหรือยัง" — top-3 ของคลังที่
# ไม่มีอะไรเกี่ยวเลย ก็ยังคืน 3 อันอยู่ดี · เส้นพี่น้องมีพื้นกันหมดแล้ว
# (`SKILLS_FALLBACK_MIN_SCORE` 0.35 · `WEB_SEARCH_MIN_SCORE` 0.35) เหลือเส้นนี้เส้นเดียว
#
# **ที่มาของเลข 0.38** — sweep กับ ground truth 110 คู่ที่คนมาร์คเอง (ข้อ 21,
# `data/skills_pairs.json`) โดยใช้คะแนน semantic ที่วัดบน prod เส้นเดียวกันนี้:
#
#   เกณฑ์ | ฉีดถูก | ฉีดผิด | ตกหล่น | precision | recall
#   0.30  |   9    |   16   |   2    |   0.360   | 0.818
#   0.35  |   7    |    9   |   4    |   0.438   | 0.636
#   0.38  |   7    |    5   |   4    |   0.583   | 0.636   ← เลือกอันนี้
#   0.40  |   6    |    3   |   5    |   0.667   | 0.545
#   0.45  |   3    |    0   |   8    |   1.000   | 0.273
#
# 0.38 = จุดที่ precision ขึ้นฟรี (0.438→0.583) โดย recall ไม่ลดจาก 0.35 เลย
#
# ⚠️ **ไม่มี "ที่ราบ" ให้ตั้งเกณฑ์** — positive ต่ำสุด 0.142 · negative สูงสุด 0.430
# negative 59/99 ตัวคะแนนสูงกว่า positive อย่างน้อยหนึ่งตัว → เกณฑ์นี้ตัดหางล่างทิ้ง
# เฉยๆ ไม่ได้แยกของถูก/ผิดออกจากกัน · **ห้ามจูนละเอียดกว่านี้** positive มีแค่ 11 ตัว
# ขยับ label เดียว recall เปลี่ยน 9 จุด (บทเรียน "F1=1.00 คือ overfit" ของข้อ 17)
# ⚠️ ห้ามยืมเลข 0.35 ของ `SKILLS_FALLBACK_MIN_SCORE`/`WEB_SEARCH_MIN_SCORE` มาใช้ —
# คนละ scorer คนละสเกล ที่เลขใกล้กันเป็นเรื่องบังเอิญ
# `off` = ปิดพื้น (พฤติกรรมเดิมก่อน 2026-08-04)
_UNSET = object()


def _parse_min_score(raw: str):
    if raw.strip().lower() in ("off", "none", ""):
        return None
    try:
        return float(raw)
    except ValueError:
        logger.warning(f"[Skills] SKILLS_SEARCH_MIN_SCORE={raw!r} ไม่ใช่ตัวเลข — ปิดพื้นคะแนน")
        return None


SKILLS_SEARCH_MIN_SCORE = _parse_min_score(os.getenv("SKILLS_SEARCH_MIN_SCORE", "0.38"))


def _drop_below_min_score(rows: list, min_score=_UNSET) -> list:
    """ตัด skill ที่พิสูจน์ความเกี่ยวข้องไม่ได้ออกก่อนฉีดเข้า context

    `min_score=None` = ปิดพื้น · ไม่ส่ง = ใช้ `SKILLS_SEARCH_MIN_SCORE`
    แถวที่ `similarity is None` (ไม่มีคะแนน / space ไม่ใช่ cosine จึงแปลงไม่ได้)
    ถูกตัดด้วย — **ไม่มีหลักฐาน = ไม่ฉีด** ทิศเดียวกับ `_drop_below_min_score`
    ของ websearch ที่ตัดผลไม่มี `_rerank_score`
    """
    floor = SKILLS_SEARCH_MIN_SCORE if min_score is _UNSET else min_score
    if floor is None:
        return list(rows)
    return [r for r in rows if r.get("similarity") is not None and r["similarity"] >= floor]


def _handle_unscorable_results(query: str, results: list) -> None:
    """เรียกเมื่อ **ทุกแถว** แปลงเป็นคะแนนไม่ได้ (collection ไม่ได้อยู่บน cosine space)

    สถานการณ์: prod มี `skills_collection` ที่ถูกสร้างไว้ตั้งแต่ก่อนแก้ — space ของ
    collection เปลี่ยนตามโค้ดไม่ได้ ต้องสร้างใหม่เท่านั้น ระหว่างนั้น `similarity`
    เป็น `None` ทุกแถว → `_drop_below_min_score()` จะตัดทิ้งหมด = **skill injection
    หยุดสนิททั้งระบบ** จนกว่าจะมีคนเข้าไปสร้าง collection ใหม่

    **ทิศที่เลือก (user ตัดสินใจ 2026-08-04): fail-closed + ส่งเสียงดัง** — ไม่ฉีดอะไรเลย
    เพราะความรู้ยังเข้าได้ทาง `load_skills_relevant()` ซึ่งอ่าน .md จากดิสก์ตรงๆ
    ไม่ผ่าน ChromaDB (คนละเส้น ไม่ได้พังไปด้วย) → การปิดเส้นนี้ไม่ได้ทำให้ระบบ
    ไม่มีความรู้ใช้ แค่เสียเส้น semantic ไปชั่วคราว · ตรงข้ามกับ fail-open ที่จะ
    ฉีดของที่พิสูจน์ไม่ได้เข้าไปเงียบๆ ทุกเทิร์น (บทเรียนข้อ 19: เทเข้า context 45 ครั้ง)
    """
    logger.error(
        f"[Skills] skills_collection ไม่ได้อยู่บน cosine space — แปลง distance "
        f"เป็นคะแนนไม่ได้ทั้ง {len(results)} แถว จึงข้ามการฉีด skill "
        f"(query: {query[:40]!r}). space ของ collection เปลี่ยนตามโค้ดไม่ได้ "
        f"ต้องสร้างใหม่: docker exec ai-backend-1 sh -c \"cd /app && python -c "
        f"'from utils.skills_search import recreate_collection; print(recreate_collection())'\""
    )
    return None


# ── กันเขียนชนกันบน skills_db.json ───────────────────────────────────────────
# **race นี้เกิดได้แล้ววันนี้ ไม่ต้องรอย้ายไป threadpool** — `utils/dream.py:549`
# เขียนจาก APScheduler (dream cycle 02:00) ส่วน `auto_extract_skills()` เขียนจาก
# เส้นแชท = คนละ thread
#
# สองอาการที่วัดได้จริงในเทส (tests/test_skills_db_concurrency.py):
# 1. **lost update** — read-modify-write ไม่มี lock: A อ่าน {} · B อ่าน {} ·
#    A เขียน {a} · B เขียน {b} → เหลือแค่ {b} ไม่มี error ไม่มี log
# 2. **ไฟล์เปล่าระหว่างเขียน** — `open(..., "w")` truncate ทันทีก่อนเขียนเนื้อ
#    ใครอ่านจังหวะนั้นได้ไฟล์ว่าง → `_load_skills_db()` คืน `{}` → ถ้ามีคนเขียนต่อ
#    ก็ทับด้วยของว่าง = **คลังหายถาวร** (วัดได้ 79 ครั้งใน 150 การเขียน)
_db_lock = threading.RLock()


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
    """เขียนแบบ atomic — เขียนลงไฟล์ชั่วคราวข้างๆ แล้ว `os.replace()` ทับทีเดียว

    `os.replace()` เป็น atomic บน POSIX ในระบบไฟล์เดียวกัน → ผู้อ่านเห็นได้แค่
    "ของเก่าครบ" หรือ "ของใหม่ครบ" ไม่มีสถานะกลางที่ไฟล์ถูก truncate ไปแล้ว
    (ต้องอยู่ไดเรกทอรีเดียวกันถึงจะข้ามอุปกรณ์ไม่ได้ — `os.replace` ข้าม filesystem ไม่ได้)
    """
    import tempfile
    try:
        d = os.path.dirname(os.path.abspath(SKILLS_DB_PATH)) or "."
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".skills_db.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(db, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())        # กันไฟล์ว่างหลังไฟดับ (metadata ไปก่อนเนื้อ)
            os.replace(tmp, SKILLS_DB_PATH)
        except Exception:
            try: os.unlink(tmp)
            except OSError: pass
            raise
    except Exception as e:
        logger.warning(f"Failed to save skills_db.json: {e}")


def save_skill(topic: str, summary: str, source: str = "auto", sync: bool = True) -> bool:
    """บันทึก skill ใหม่ที่ AI เรียนรู้ — คืน True ถ้าบันทึกจริง

    gate ด้วยเกณฑ์เดียวกับตอนลบ (`_is_meaningful_skill`) — ทางเข้าต้องเท่าทางออก
    ไม่งั้นระบบวนลูป "สร้าง → ล้าง → สร้างใหม่" (ต้นเหตุของขยะที่ล้างไปในข้อ 9)
    """
    if not _is_meaningful_skill(topic, summary):
        logger.info(f"[Skills] ปฏิเสธ skill ที่ไม่ผ่านเกณฑ์: {topic!r}")
        return False

    with _db_lock:                      # read-modify-write ต้องแบ่งแยกไม่ได้
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

        raw_count = len(results)
        if SKILLS_SEARCH_MIN_SCORE is not None and all(
            r.get("similarity") is None for r in results
        ):
            # ทุกแถวแปลงคะแนนไม่ได้ = collection ไม่ได้อยู่บน cosine space
            # (เกิดกับ collection ที่ถูกสร้างไว้ก่อนแก้ `skills_search.py` — space
            # ของ collection เดิมไม่เปลี่ยนตามโค้ด ต้องสร้างใหม่ถึงจะเปลี่ยน)
            # เช็คเฉพาะตอนตั้งเกณฑ์ไว้ — `=off` คือการที่คนสั่งว่า "ยอมรับผลที่ไม่ได้ตรวจ"
            # จึงไม่ใช่สถานการณ์ผิดปกติที่ต้องรายงาน (กติกาเดียวกับ WEB_SEARCH_MIN_SCORE=off)
            _handle_unscorable_results(query, results)

        results = _drop_below_min_score(results)
        if not results:
            logger.info(
                f"[Skills] '{query[:40]}' — ไม่มี skill ไหนถึงเกณฑ์ "
                f"{SKILLS_SEARCH_MIN_SCORE} (จาก {raw_count} ผลลัพธ์) — ไม่ฉีด context"
            )
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
    # อ่าน→คัด→เขียน ต้องอยู่ใน lock เดียวกับ save_skill ไม่งั้น skill ที่ถูกบันทึก
    # ระหว่างที่กำลังคัดอยู่จะถูกเขียนทับหายไป (dream cycle เรียกทั้งสองเส้น)
    with _db_lock:
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
