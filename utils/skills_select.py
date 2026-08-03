"""เลือก skill file ที่จะฉีดเข้า context — lexical ก่อน, semantic เป็นตัวสำรอง

**กติกาเดียว: เติมเฉพาะเทิร์นที่เดิมได้ศูนย์ไฟล์ ห้ามแตะเทิร์นที่ทำงานอยู่แล้ว**

ที่มา (วัดจริง 432 เทิร์นบน prod 2026-08-03 — ดู `scripts/skills_shadow_backfill.py`):

    วิธี                     ไทยล้วนได้ฉีด   มี Latin ปน
    .split() (ของเดิม)            29.7%        81.7%
    ngram                         92.8%        ~97%     ← ท่วม context
    semantic สัมบูรณ์ >= 0.40       5.9%        38.0%    ← แย่กว่าของเดิม

`.split()` ทำงานได้ดีอยู่แล้วกับคำถามที่มีคำอังกฤษ — ที่พังคือคำถามไทยล้วน (ไทยเขียน
ติดกัน `.split()` ได้ token เดียวที่ยาวเกินจะ match) จึงไม่มีเหตุผลจะทิ้งมัน

ส่วนการเลือกว่า "semantic แม่นกว่า lexical ไหม" — **ข้อมูลที่มีตอบไม่ได้** (ground truth
110 คู่ positives แค่ 11 → ความต่างระหว่างกฎอยู่ในระดับ noise, ดู `scripts/skills_rule_eval.py`)
ดีไซน์นี้จึงตั้งใจ**ไม่ถาม**คำถามนั้น: ให้ semantic ทำงานเฉพาะตอน lexical ยอมแพ้
เทิร์นที่ได้ผลกระทบคือเทิร์นที่วันนี้ได้ศูนย์อยู่แล้ว → **downside สูงสุดคือเท่าเดิม**

pattern เดียวกับ OR-gate ใน `memory/lexical.py` (ข้อ 16) ด้วยเหตุผลกลับด้าน: คราวนั้น
embedding มองไม่เห็นรหัส/รุ่น เลยเสริม lexical · คราวนี้ lexical มองไม่เห็นไทย เลยเสริม embedding

⚠️ **ทำไมใช้เกณฑ์สัมพัทธ์ ไม่ใช่คะแนนขั้นต่ำ**: คะแนน semantic ของ prompt ไทยต่ำทั้งแผง
(มัธยฐานอันดับ 1 = 0.253 ส่วน Latin = 0.371) เกณฑ์สัมบูรณ์ตัวเดียวจึงยุติธรรมกับสองภาษา
พร้อมกันไม่ได้ — `"deploy ยังไง"` ได้ `deploy-cheatsheet.md` เป็นอันดับ 1 ที่ 0.380
ซึ่งถูกที่สุดเท่าที่จะถูกได้ แต่ตกเกณฑ์ 0.40 → ไม่ฉีดอะไรเลย
ดู vault `wiki/concepts/threshold-vs-ranking-calibration.md`

เส้นสำรองต้องผ่าน **ทั้งสองด่าน**: นำอันดับถัดไป >= `SKILLS_FALLBACK_MARGIN` (0.05)
และคะแนน >= `SKILLS_FALLBACK_MIN_SCORE` (0.35) · ปิดทั้งฟีเจอร์ด้วย `SKILLS_FALLBACK_MARGIN=off`
วัดผลจริงบน 432 เทิร์น: ยิง 15 เทิร์น (3.5%) · ไทยล้วนได้ฉีดรวม 29.7% → 33.8% · เส้นเดิม 0 regression
"""
from __future__ import annotations

import logging
import os

from utils.rag import SkillPick, select_skill_files
from utils.skills_shadow import rule_margin, semantic_scores, skill_haystacks

logger = logging.getLogger(__name__)


def _parse_margin(raw: str | None) -> float | None:
    """คืน None = ปิดฟีเจอร์ · ค่าพิมพ์ผิดก็ปิด (ห้าม crash ตอน import — นี่คือเส้นแชทหลัก)"""
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    return v if v >= 0 else None


# 0.08 มาจากการวัด: ให้ไทย 14.5% (≈2.5 เท่าของเกณฑ์สัมบูรณ์ 0.40) ที่ precision พอกัน
# ⚠️ **ยังไม่มีหลักฐานระดับที่ยืนยัน 0.08 เป๊ะๆ ได้** — ที่ยืนยันได้คือ "ดีกว่าไม่ฉีดเลย"
# ซึ่งเป็นเกณฑ์ที่ดีไซน์นี้ต้องผ่านจริงๆ เพราะมันทำงานเฉพาะตอนทางเลือกอื่นคือศูนย์
FALLBACK_MARGIN = _parse_margin(os.getenv("SKILLS_FALLBACK_MARGIN", "0.05"))

# ⚠️ **พื้นสัมบูรณ์จำเป็น ห้ามถอด** — เกณฑ์สัมพัทธ์ล้วนพูดประโยคว่า "ไม่มีอะไรเกี่ยวเลย"
# ไม่ได้ เพราะมันเทียบผู้สมัครกันเองอย่างเดียว พอคำถามไม่เกี่ยวกับ skill ไหนเลยมันก็ยัง
# หยิบตัวที่ "แพ้น้อยที่สุด" ออกมา — เปิดดูผลจริงแล้วเจอ `"ราคาทองคำวันนี้เท่าไหร่"` →
# `env-variables-reference.md` ที่ 0.138 (2026-08-03) ทั้งที่ตัวเลขรวมดูดีขึ้นทุกช่อง
# 0.35 = จุดที่ยังเหลือ prompt ไทยผ่านได้จริง (p90 ของคะแนนอันดับ 1 ฝั่งไทย = 0.347)
# ต่างจาก 0.40 ที่ตัดไทยเหลือ 5.9% — แคบกว่านั้นนิดเดียวแต่คนละผลลัพธ์
FALLBACK_MIN_SCORE = float(os.getenv("SKILLS_FALLBACK_MIN_SCORE", "0.35"))


def select_skills(folder_path: str, query: str,
                  max_files: int = 3) -> tuple[list[SkillPick], str]:
    """คืน (ไฟล์ที่จะฉีด, มาจากเส้นไหน) — `lexical` | `semantic_margin` | `none`

    ชื่อเส้นถูกส่งต่อไปลง shadow log ด้วย เพื่อให้ตอบได้ทีหลังว่าเส้นสำรองยิงบ่อยแค่ไหน
    บนทราฟฟิกจริง (ไม่ใช่แค่บนข้อมูล backfill)
    """
    picks = select_skill_files(folder_path, query, max_files)
    if picks:
        return picks, "lexical"                    # เส้นเดิม — ไม่แตะ ไม่เรียก ChromaDB
    if FALLBACK_MARGIN is None or not query:
        return [], "none"

    try:
        hays = skill_haystacks(folder_path)         # ไฟล์ที่ *มีอยู่จริง* ณ ตอนนี้
        sem = semantic_scores(query)
        if not sem:
            return [], "none"                       # ChromaDB ล่ม → พฤติกรรมเดิมเป๊ะ
        ranked = sorted(((f, s) for f, s in sem.items()), key=lambda kv: -kv[1])
        # margin วัดบน "อันดับเต็ม" ก่อน แล้วค่อยกรองด้วยพื้น — สลับลำดับไม่ได้ เพราะ
        # กรองก่อนจะทำให้ระยะห่างถูกวัดเทียบกับรายชื่อที่ถูกตัดหัวท้ายไปแล้ว
        chosen = [x for x in rule_margin(ranked, FALLBACK_MARGIN, cap=max_files)
                  if x[1] >= FALLBACK_MIN_SCORE]

        out: list[SkillPick] = []
        for name, score in chosen:
            if name not in hays:
                # index ค้างหลังไฟล์ถูกลบ — เคยเกิดจริง (ไฟล์ 52 แต่ index 128, 2026-08-02)
                logger.debug(f"skills fallback: ข้าม '{name}' — ไม่มีไฟล์นี้แล้ว")
                continue
            path = os.path.join(folder_path, name)
            with open(path, encoding="utf-8", errors="ignore") as f:
                out.append(SkillPick(name, float(score), f.read()))
        if out:
            logger.info(f"skills fallback (semantic นำ >= {FALLBACK_MARGIN}): "
                        f"{[p.name for p in out]}")
            return out, "semantic_margin"
    except Exception as e:
        logger.warning(f"skills fallback ข้าม ({e}) — ใช้พฤติกรรมเดิม")
    return [], "none"
