"""Guard: skills/*.md ต้องไม่อ้างของที่เลิกใช้แล้ว (backlog ข้อ 9)

ทำไมต้องมีเทสนี้ — `skills/*.md` ถูกฉีดเข้า **stable block ทุกเทิร์น** ผ่าน
`load_skills_relevant()` โดย **ไม่มี threshold กรอง** (ต่างจาก episodic/lessons ที่ผ่าน
semantic 0.55): match keyword ตรง 1 คำ = ฉีดทั้งไฟล์ วัดจริงบน prod 2026-08-02
ได้ 233/460 prompt (51%) median ~1,500 tokens → เนื้อหาผิด 1 บรรทัดในไฟล์เดียว
ป้อนข้อมูลล้าสมัยให้โมเดลได้ครึ่งหนึ่งของทุกบทสนทนา

ไฟล์พวกนี้เป็น "เอกสารที่คนเขียน" จึงไม่มีทางเข้าให้ตั้ง gate แบบ `should_remember()`
— guard เดียวที่เป็นไปได้คือตรวจเนื้อหาย้อนหลัง ซึ่งก็คือเทสนี้

⚠️ บทเรียนตอนสร้างเทสนี้: การ grep หาชื่อโมเดลตายตรงๆ ให้ **false positive 9 จาก 16 จุด**
— ชื่อที่เลิกใช้ปรากฏโดยชอบธรรมได้ 2 แบบ (1) เป็นตัวอย่างของ "สิ่งที่โมเดลกุ" ใน
เอกสารกัน hallucination (2) อยู่ในโน้ต "เปลี่ยนจาก X → Y แล้ว" ซึ่งเป็นข้อมูลที่ *ถูก*
เทสจึงต้องมีทางยกเว้นที่ชัดเจน ไม่งั้นจะถูกปิดทิ้งภายในเดือนเดียว
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core.config import SKILLS_DIR

# ── สิ่งที่เลิกใช้แล้ว → เหตุผล (ต้องมีหลักฐานวันที่เสมอ ไม่ใส่ของที่ยังไม่ยืนยัน) ──
# ⚠️ ห้ามใส่ `llama3` — Ollama เป็น dormant fallback แต่โมเดลมันยังเป็น llama3 จริง
# ⚠️ ห้ามใส่ `192.168.51.49:8000` — นั่นคือ ChromaDB ที่ถูกต้อง (แอปคือ :8080)
BANNED = {
    r"deepseek[-/]deepseek-r1|deepseek-r1-0528": (
        "โมเดล local เปลี่ยนเป็น qwen/qwen3.5-9b แล้ว 2026-07-05"
    ),
    r"gemini-2\.0-flash-exp|gemini-live-2\.0-flash-001": (
        "ถูกถอดจาก Live API แล้ว — bidiGenerateContent คืน 1008 not found (2026-06-16)"
    ),
    r"google/gemma-4-e4b|llama-3\.2-11b-vision-instruct": (
        "LMSTUDIO_* ทั้ง 3 ตัวชี้ qwen/qwen3.5-9b แล้ว 2026-07-05"
    ),
    r"gemini-2\.5-pro": (
        "free tier quota limit=0 → 429 ทุก request (2026-06-11) ห้ามแนะนำให้ตั้งค่านี้"
    ),
    # เจอ 4 จุดใน 4 ไฟล์ (2026-08-03) — พลาดในรอบแรกเพราะไม่ได้เข้ารหัสเป็นกฎไว้
    # 1234 = LM Studio · 11434 = Ollama · สลับกันแล้วคำสั่ง troubleshoot จะพาไปผิดเครื่อง
    r"[Oo]llama[^\n]{0,60}:1234|:1234[^\n]{0,30}[Oo]llama": (
        "1234 คือพอร์ต LM Studio — Ollama คือ 11434"
    ),
    r"host\.docker\.internal": (
        "ค่าเก่าสมัยรันบนเครื่องเดียว — prod ชี้ PC 192.168.51.235"
    ),
}

# ไฟล์ที่ auto-discovery สร้าง — ชื่อลงท้ายด้วย timestamp 10 หลัก
AUTO_DISCOVERED = re.compile(r"-\d{10}\.md$")

# ── ข้อยกเว้น: (ไฟล์, regex ใน BANNED) → เหตุผลที่การอ้างถึงนั้น *ถูกต้อง* ──
# เก็บไว้ที่นี่ ไม่ใช่ marker ใน .md เพราะไฟล์พวกนี้ถูกฉีดเข้า context ของโมเดลทุกเทิร์น
# — annotation ในไฟล์ = ต้นทุนโทเคนที่จ่ายทุกครั้ง + โมเดลเห็นข้อความที่ไม่ได้ตั้งใจสื่อ
# จุดอ่อนของวิธีนี้คือข้อยกเว้นเน่าเงียบเมื่อ .md ถูกแก้ → กันด้วย
# `test_every_exemption_is_still_needed` ข้างล่าง
EXEMPTIONS = {
    ("gemini-api-quota-sdk-gotchas.md", r"gemini-2\.5-pro"):
        "ไฟล์นี้มีหน้าที่เตือนว่าห้ามใช้รุ่นนี้ (limit=0) — การเอ่ยชื่อคือเนื้อหาของมัน",
}


def _skill_files():
    if not os.path.isdir(SKILLS_DIR):
        pytest.skip(f"ไม่มี {SKILLS_DIR}")
    return sorted(f for f in os.listdir(SKILLS_DIR) if f.endswith(".md"))


# บรรทัดที่ "เอ่ยชื่อของตายเพื่อบอกว่าห้ามใช้" = เนื้อหาที่ถูกต้อง และเป็นเนื้อหาที่มีค่าที่สุด
# ในเอกสารพวกนี้ด้วย — กันไว้ด้วยบริบทในบรรทัด ไม่ใช่ยกเว้นทั้งไฟล์ (ซึ่งจะทำให้
# `GEMINI_MODEL=gemini-2.5-pro` ที่โผล่กลับมาในไฟล์เดียวกันหลุดไปเงียบๆ)
WARNING_CONTEXT = re.compile(
    r"⚠️|❌|ห้าม|เลิกใช้|ถูกถอด|อย่าใช้|ไม่รองรับ|limit=0|deprecated", re.I
)


def is_exempt(filename: str, pattern: str) -> bool:
    """การอ้างถึง `pattern` ในไฟล์นี้ได้รับยกเว้นทั้งไฟล์หรือไม่"""
    return (filename, pattern) in EXEMPTIONS


class TestNoStaleReferences:
    """ไม่มี skill ไหนอ้างโมเดล/ค่า config ที่เลิกใช้แล้ว"""

    def test_no_banned_references(self):
        offences = []
        for fn in _skill_files():
            path = os.path.join(SKILLS_DIR, fn)
            with open(path, encoding="utf-8", errors="ignore") as f:
                for i, line in enumerate(f, 1):
                    if WARNING_CONTEXT.search(line):
                        continue  # บรรทัดเตือน "ห้ามใช้ X" — ต้องเอ่ยชื่อ X ถึงจะสื่อได้
                    for pat, why in BANNED.items():
                        if is_exempt(fn, pat):
                            continue
                        m = re.search(pat, line, re.I)
                        if m:
                            offences.append(f"{fn}:{i} '{m.group(0)}' — {why}")
        assert not offences, "skills/*.md อ้างของที่เลิกใช้แล้ว:\n  " + "\n  ".join(offences)

    def test_every_exemption_is_still_needed(self):
        """ข้อยกเว้นที่ไม่ match อะไรแล้ว = เน่า ต้องถอดออก

        นี่คือราคาที่ต้องจ่ายของการเก็บ allow-list ไว้นอกไฟล์: ถ้าไม่มีเทสตัวนี้
        EXEMPTIONS จะค่อยๆ กลายเป็นรูโหว่ที่ไม่มีใครรู้ว่ายังเปิดค้างอยู่
        """
        dead = []
        for (fn, pat), why in EXEMPTIONS.items():
            path = os.path.join(SKILLS_DIR, fn)
            if not os.path.exists(path):
                dead.append(f"{fn} — ไฟล์ถูกลบไปแล้ว ({why})")
                continue
            text = open(path, encoding="utf-8", errors="ignore").read()
            if not re.search(pat, text, re.I):
                dead.append(f"{fn} :: {pat} — ไม่มีในไฟล์แล้ว ({why})")
        assert not dead, "EXEMPTIONS ที่เน่าแล้ว ถอดออกได้:\n  " + "\n  ".join(dead)


class TestNoJunkSkills:
    """ไฟล์ที่ auto-discovery สร้างต้องไม่หลุดเข้ามาโดยไม่มีคนตรวจ

    หลักฐาน 2026-08-02: prod มี 5 ไฟล์แบบนี้ที่ไม่เคยอยู่ใน git เลย — หนึ่งในนั้น
    (`ได-เลย.md`) มีเนื้อหาเดียวคือข้อความ error "❌ Gemini quota หมด..." และอีกตัว
    (`openclaw-*.md`) เป็นนิยามที่โมเดลกุขึ้นเองจากคำถามซ้ำ 2 ครั้ง ถูกฉีดกลับเข้า
    context 24 ครั้ง = feedback loop ปนเปื้อนแบบเดียวกับ episodic (backlog ข้อ 1)
    """

    def test_no_auto_discovered_files(self):
        junk = [f for f in _skill_files() if AUTO_DISCOVERED.search(f)]
        assert not junk, (
            "ไฟล์ auto-discovered หลุดเข้า skills/ — ต้องมีคนอ่านและเขียนใหม่ก่อน commit:\n  "
            + "\n  ".join(junk)
        )

    def test_no_error_message_only_files(self):
        """ไฟล์ที่เนื้อหาเป็นข้อความ error ล้วน = ของที่ pipeline เก็บผิด ไม่ใช่ skill"""
        bad = []
        for fn in _skill_files():
            with open(os.path.join(SKILLS_DIR, fn), encoding="utf-8", errors="ignore") as f:
                text = f.read().strip()
            if len(text) < 200 and re.search(r"^[❌⚠️]|quota หมด|เกิดข้อผิดพลาด|error:", text, re.I | re.M):
                bad.append(f"{fn} ({len(text)} chars)")
        assert not bad, "skill ที่เป็นข้อความ error ล้วน:\n  " + "\n  ".join(bad)
