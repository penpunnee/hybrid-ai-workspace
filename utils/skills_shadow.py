"""Shadow logging ของ skills injection — backlog ข้อ 21 ขั้นที่ 2

**shadow = บันทึกว่าแต่ละวิธีให้คะแนน *จะ* เลือกไฟล์ไหน โดยไม่แตะสิ่งที่ฉีดจริง**
ไม่มีบรรทัดไหนในไฟล์นี้ที่เปลี่ยน context ที่โมเดลได้เห็น — ถ้ามีเมื่อไหร่ แปลว่ามันเลิก
เป็นเครื่องมือวัดแล้ว

ทำไมถึงต้องมี: `select_skill_files()` ตัดคำด้วย `.split()` ซึ่งมองไทยแทบไม่เห็น
(วัดจริงบน prod 376 prompt: ไทยล้วนฉีด 32% · มี Latin ปน 84%) แต่**ห้ามแก้ลอยๆ**
เพราะไฟล์ที่ฉีดมี median ~6,000 ตัวอักษร ดันให้ฉีดเยอะขึ้นโดยไม่รู้ว่าเกี่ยวจริงไหม
= เพิ่ม noise ให้ทุกบทสนทนา

⚠️ **สิ่งที่บันทึกเซสชัน 2026-08-03 เขียนไว้ผิด**: แผนเดิมคือ "log 1 สัปดาห์แล้วเทียบกับ
👍/👎 ที่มีอยู่แล้ว" — ตรวจ prod จริง 2026-08-03 พบตาราง `feedback` **ว่างเปล่า 0 แถว**
ตั้งแต่ 2026-04-21 (447 คำตอบ ~4 เทิร์น/วัน) การรอเก็บสด 1 สัปดาห์จะได้ ~30 เทิร์น
และไม่มี outcome ให้เทียบอยู่ดี → ตัวหลักจึงเป็น **backfill ย้อนหลัง** แทน
(`scripts/skills_shadow_backfill.py`) ซึ่งทำได้เพราะคะแนนเป็นฟังก์ชันบริสุทธิ์ของ
(prompt, ไฟล์ skill) ไม่ต้องรอเก็บสด — ส่วน logging สดคงไว้เผื่อทราฟฟิกโตขึ้น
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime

from memory.lexical import lexical_score
from utils.history import _get_conn
from utils.rag import SKILL_HEAD_CHARS

logger = logging.getLogger(__name__)

HEAD_CHARS = SKILL_HEAD_CHARS          # ต้องเท่ากับที่ prod ใช้เทียบ ไม่งั้นวัดคนละก้อน
CAP = 3                                # = max_files ของ select_skill_files()
# บันทึกลึกกว่าที่ฉีดจริง — shadow log ต้องประเมิน **กฎที่ยังไม่ได้คิดตอนเขียน log** ได้
# เจอจริง 2026-08-03: log ที่ตัดไว้แค่ 3 ทำให้กฎแบบ "นำอันดับถัดไปเท่าไร" มองไม่เห็น
# อันดับ 4 เลยคิดว่า top-3 นำที่เหลืออยู่อนันต์ → ผ่านเกณฑ์เกือบทุกเทิร์น = ตัวเลขพัง
RECORD_TOP = 8
_LATIN = re.compile(r"[A-Za-z]")

# เปิดไว้เป็น default: ปิดไว้แล้วลืมเปิด = "ตั้ง cron ไว้ไม่ได้แปลว่ามันรัน" เวอร์ชันนี้
SHADOW_ENABLED = os.getenv("SKILLS_SHADOW_LOG", "true").lower() == "true"


# ── scorer ที่เอามาเทียบกัน (ตัวเดียวกับที่ scripts/skills_groundtruth.py ใช้) ────
def score_split(query: str, haystack: str) -> float:
    """วิธีที่ prod ใช้อยู่วันนี้ — normalize เป็น 0..1 เพื่อ sweep ร่วมกับตัวอื่นได้

    หารด้วยจำนวนคำในคำถาม ซึ่งคงที่ภายในเทิร์นเดียว → **ลำดับไฟล์เหมือน prod เป๊ะ**
    (prod ใช้จำนวนดิบ) ต่างแค่สเกล ไม่ต่างที่การจัดอันดับ
    """
    words = {w for w in query.lower().split() if len(w) > 1}
    if not words:
        return 0.0
    return sum(1 for w in words if w in haystack) / len(words)


def score_ngram(query: str, haystack: str) -> float:
    """character n-gram containment — ตัวเดียวกับ `memory/lexical.py` (ข้อ 16)
    ไม่พึ่งช่องว่าง → ไทยล้วนก็ให้คะแนนได้"""
    return lexical_score(query, haystack)


SCORERS = {"split": score_split, "ngram": score_ngram}


def skill_haystacks(folder_path: str) -> dict[str, str]:
    """{ชื่อไฟล์: ก้อนที่ใช้เทียบ} — ต้องเป็นก้อนเดียวกับ `select_skill_files()` เป๊ะ

    ลำดับคีย์ = ลำดับ `os.listdir` เหมือน prod (ไม่ sort) เพื่อให้การตัดสินคะแนนเสมอ
    ของ shadow ตรงกับของจริง
    """
    docs: dict[str, str] = {}
    if not os.path.isdir(folder_path):
        return docs
    for fn in os.listdir(folder_path):
        path = os.path.join(folder_path, fn)
        if not (os.path.isfile(path) and fn.endswith((".txt", ".md", ".json", ".py"))):
            continue
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except OSError as e:
            logger.warning(f"skill_haystacks: อ่าน '{path}' ไม่ได้: {e}")
            continue
        docs[fn] = (fn + " " + content[:HEAD_CHARS]).lower()
    return docs


def select(query: str, haystacks: dict[str, str], scorer: str,
           cap: int = CAP, scores: dict[str, float] | None = None) -> list[tuple[str, float]]:
    """ไฟล์ที่ scorer นี้ *จะ* เลือก — จำลองการตัดของ prod ครบทุกขั้น

    ขั้นที่ห้ามลืม (เคยลืมมาแล้วจนตัวเลขผิด): คะแนน > 0 → เรียงลง → **ตัดที่ cap**
    """
    if scores is None:
        fn = SCORERS[scorer]
        scores = {f: fn(query, h) for f, h in haystacks.items()}
    ranked = [(f, round(float(s), 4)) for f, s in scores.items() if s > 0]
    ranked.sort(key=lambda kv: kv[1], reverse=True)      # stable → เสมอกันคงลำดับ listdir
    return ranked[:cap]


def rule_absolute(ranked: list[tuple[str, float]], min_score: float,
                  cap: int = CAP) -> list[tuple[str, float]]:
    """กฎที่ระบบใช้อยู่: คะแนน >= เกณฑ์ → เอา top-cap

    ใช้ได้ดีกับ lexical (0 = ไม่มีคำตรงเลย จึงตีความได้ตรงตัว) แต่กับ semantic เกณฑ์
    ตัวเดียวยุติธรรมกับไทย/อังกฤษพร้อมกันไม่ได้ — ดู `rule_margin()`
    """
    return [r for r in ranked if r[1] >= min_score][:cap]


def rule_margin(ranked: list[tuple[str, float]], min_margin: float,
                cap: int = CAP) -> list[tuple[str, float]]:
    """กฎสัมพัทธ์: เอา prefix ที่ **นำตัวถัดไปอยู่อย่างน้อย `min_margin`**

    ทำไมถึงต้องมี (วัดจริง 432 เทิร์นบน prod 2026-08-03): คะแนน semantic ของ prompt
    ไทยต่ำทั้งแผง (มัธยฐานอันดับ 1 = 0.253 · p90 = 0.347) ส่วน Latin ปน = 0.371
    เกณฑ์สัมบูรณ์ 0.40 จึงตัดไทยทิ้งเกือบหมด (ฉีดได้ 5.9% แย่กว่า `.split()` เดิมที่ 29.7%)
    ทั้งที่ **อันดับถูก** — `"deploy ยังไง"` ได้ `deploy-cheatsheet.md` ที่อันดับ 1 แต่ได้
    คะแนน 0.380 แล้วตกเกณฑ์

    ระยะห่างเป็นปริมาณภายในคำถามเดียวกัน จึงไม่ต้องเทียบสเกลข้ามภาษา
    ไล่ระดับเรียบ (ไม่มีใครนำใคร) → คืน [] โดยตั้งใจ: ไม่รู้ว่าอันไหนเกี่ยว ดีกว่าเดา
    ⚠️ **"ไม่มีอันดับถัดไป" ไม่ใช่ "นำอยู่อนันต์"** — ถ้ากลุ่มกินรายชื่อทั้งหมดแล้ว
    ก็ไม่มี "ที่เหลือ" ให้นำ ต้องคืน [] (ยกเว้นมีผู้สมัครอยู่คนเดียวจริงๆ) มิฉะนั้นคะแนน
    ที่ไล่ระดับเรียบจะผ่านเกณฑ์เสมอที่ k ตัวสุดท้าย = กฎไม่กรองอะไรเลย
    (พลาดตรงนี้มาแล้ว 2 ครั้งในวันเดียว: ครั้งแรกที่ตัว log เก็บแค่ top-3 ครั้งนี้ที่ตัวกฎ)
    """
    top = ranked[:cap]
    for k in range(1, len(top) + 1):
        if k >= len(ranked):
            return top[:k] if len(ranked) == 1 else []
        if top[k - 1][1] - ranked[k][1] >= min_margin:
            return top[:k]
    return []


def semantic_scores(prompt: str, n_results: int = 30) -> dict[str, float]:
    """similarity จาก ChromaDB (เส้นที่ `search_skills()` ใช้จริง) — {ชื่อไฟล์: 0..1}

    คืน `{}` เมื่อใช้ไม่ได้ — **ห้ามคืน 0.0 ทุกไฟล์** เพราะ "ไม่รู้" กับ "ไม่เกี่ยว"
    ต้องแยกกันให้ออกตอนวิเคราะห์ (ไม่งั้น semantic จะดูแย่ทุกครั้งที่ ChromaDB ล่ม)
    """
    try:
        from utils.skills_search import get_skills_search
        search = get_skills_search()
        if not search.available:
            return {}
        out: dict[str, float] = {}
        for r in search.search(prompt, n_results=n_results):
            key = r.get("source") or r.get("topic") or ""
            if not key.endswith(".md"):
                key = f"{key}.md"
            d = r.get("distance")
            if d is not None:
                out[key] = round(1.0 - float(d), 4)
        return out
    except Exception as e:
        logger.debug(f"semantic_scores ใช้ไม่ได้: {e}")
        return {}


def build_row(prompt: str, skills_dir: str, injected: list[str],
              cap: int = RECORD_TOP, source: str = "") -> dict:
    """สร้างแถว shadow ของ 1 เทิร์น — pure ไม่แตะ DB

    `injected` = ชื่อไฟล์ที่ **prod ฉีดจริง** (ส่งมาจากผู้เรียก ไม่ใช่คำนวณซ้ำที่นี่)
    `cap` = ความลึกที่ **บันทึก** (RECORD_TOP=8) ไม่ใช่ความลึกที่ฉีด (CAP=3) —
    ตอนวิเคราะห์ค่อยตัดเป็น 3 เอง ดู `apply_thresholds()`/`rule_*()`
    """
    hays = skill_haystacks(skills_dir)
    choices: dict[str, list[list]] = {}
    for name in SCORERS:
        choices[name] = [[f, s] for f, s in select(prompt, hays, name, cap=cap)]

    sem = semantic_scores(prompt)
    if sem:      # ไม่มีคีย์ = ChromaDB ใช้ไม่ได้ ≠ ทุกไฟล์ได้ 0
        sem_full = {f: sem.get(f, 0.0) for f in hays} or sem
        choices["semantic"] = [[f, s] for f, s in
                               select(prompt, hays, "semantic", cap=cap, scores=sem_full)]

    return {
        "prompt": prompt,
        "thai_only": not _LATIN.search(prompt or ""),
        "injected": list(injected),
        "source": source,          # เส้นที่ให้ผลจริงเทิร์นนี้: lexical | semantic_margin | none
        "choices": choices,
    }


def _ensure_table():
    conn = _get_conn()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS skill_shadow (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER NOT NULL UNIQUE,
                assistant TEXT NOT NULL,
                session_id TEXT NOT NULL,
                prompt TEXT NOT NULL,
                thai_only INTEGER NOT NULL,
                injected TEXT NOT NULL,
                choices TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.commit()
    finally:
        conn.close()


def record(row: dict, *, message_id: int, assistant: str, session_id: str) -> int | None:
    """เขียนแถว shadow — คีย์คือ `message_id` ของ **คำตอบ AI** เพื่อ join กับ `feedback`

    คืน `None` เมื่อเขียนไม่ได้ — shadow เป็นเครื่องมือวัด ห้ามทำให้แชทพังไม่ว่ากรณีใด
    """
    try:
        _ensure_table()
        conn = _get_conn()
        try:
            cur = conn.execute(
                """INSERT OR IGNORE INTO skill_shadow
                   (message_id, assistant, session_id, prompt, thai_only,
                    injected, choices, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (int(message_id), assistant, session_id, row["prompt"],
                 int(bool(row["thai_only"])),
                 json.dumps(row["injected"], ensure_ascii=False),
                 json.dumps(row["choices"], ensure_ascii=False),
                 datetime.now().isoformat()),
            )
            conn.commit()
            return cur.lastrowid or None
        finally:
            conn.close()
    except Exception as e:
        logger.debug(f"shadow record ข้าม: {e}")
        return None


def should_shadow_log(prompt: str, *, is_test_request: bool) -> bool:
    """เทิร์นนี้ควรเก็บเข้า shadow ไหม

    เก็บทุกเทิร์นจริง เพราะทราฟฟิกน้อยอยู่แล้ว (~4/วัน) การสุ่มทิ้งไม่ได้ประหยัดอะไร
    แต่ตัดออก 2 กรณี:
      - `is_test_request` — บทเรียน 2026-06-11: smoke test ปนเข้า memory แล้วถูก
        recall กลับมาตอบซ้ำ · ที่นี่ผลคือตัวเลขจะเจือด้วย prompt ที่ไม่ใช่ของจริง
      - prompt ว่าง — `select_skill_files()` คืน [] ทันที ไม่มีอะไรให้เทียบ
    """
    if is_test_request or not (prompt or "").strip():
        return False
    return True


def observe(*, prompt: str, skills_dir: str, injected: list[str], message_id: int,
            assistant: str, session_id: str, is_test_request: bool,
            source: str = "") -> None:
    """จุดเดียวที่ `routers/chat.py` เรียก — กลืน exception ทุกชนิดโดยตั้งใจ"""
    try:
        if not SHADOW_ENABLED or not should_shadow_log(prompt, is_test_request=is_test_request):
            return
        row = build_row(prompt, skills_dir, injected, source=source)
        record(row, message_id=message_id, assistant=assistant, session_id=session_id)
    except Exception as e:
        logger.debug(f"shadow observe ข้าม: {e}")
