"""Tests for utils.skills.auto_extract_skills — สกัด skill จากไฟล์ที่ upload (backlog ข้อ 18)

หลักฐานจาก prod 2026-08-03: `skills_db.json` มี 25 entry จาก `GUIDE.md` ที่อัปโหลดเมื่อ
2026-04-26 และในนั้นมี 3 รายการที่ **ไม่ใช่หัวข้อเอกสารเลย** แต่เป็นคอมเมนต์ `#` ที่อยู่
*ข้างใน* ```env code block:

    • ============ AI Models ============: GEMINI_API_KEY=your_key_here
    • ⚠️ ต้องเป็น gemini-2.0-flash ขึ้นไป (สำหรับ Agent Mode): GEMINI_MODEL=gemini-2.0-flash
    • ============ Ollama (Local) ============: OLLAMA_MODEL=llama3 OLLAMA_BASE_URL=... ```

ต้นเหตุ: ตัวสกัดเดินทีละบรรทัดหา `#`/`##` โดยไม่รู้ว่าอยู่ใน code fence หรือเปล่า —
`.env` ใช้ `#` เป็นคอมเมนต์ ทุกคอมเมนต์ในบล็อกจึงกลายเป็น "ความรู้"

ทำไมถึงสำคัญกว่าที่เห็น: entry พวกนี้เข้า `search_skills()` → ฉีดเข้า context จริง และ
เนื้อในเป็นค่า config ของ เม.ย. (`GEMINI_MODEL=gemini-2.0-flash`,
`OLLAMA_BASE_URL=http://host.docker.internal:11434`) ที่ **ขัดกับ `skills/*.md` ปัจจุบัน
ทุกค่า** = ป้อนค่าที่ผิดให้โมเดลโดยดูเหมือนเป็นความรู้ที่คนตั้งใจใส่
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import utils.skills as skills_mod


@pytest.fixture
def captured(monkeypatch):
    """ดัก save_skill ไม่ให้แตะ skills_db.json จริง"""
    saved = []
    monkeypatch.setattr(
        skills_mod, "save_skill",
        lambda topic, summary, source="auto", sync=True: saved.append((topic, summary)),
    )
    return saved


ENV_DOC = """# คู่มือใช้งาน Hybrid AI Workspace

## ตั้งค่า .env บน NAS

```env
# ============ AI Models ============
GEMINI_API_KEY=your_key_here
# ⚠️ ต้องเป็น gemini-2.0-flash ขึ้นไป (สำหรับ Agent Mode)
GEMINI_MODEL=gemini-2.0-flash

# ============ Ollama (Local) ============
OLLAMA_MODEL=llama3
OLLAMA_BASE_URL=http://host.docker.internal:11434
```

เมื่อแก้เสร็จให้ recreate container เพื่อให้ค่าใหม่มีผล
"""


class TestCodeFenceIsNotHeading:
    """บรรทัดใน code fence ไม่ใช่หัวข้อ แม้จะขึ้นต้นด้วย #"""

    def test_env_comments_do_not_become_skills(self, captured):
        skills_mod.auto_extract_skills(ENV_DOC, "GUIDE.md")
        topics = [t for t, _ in captured]
        leaked = [t for t in topics if "=" in t or t.startswith("=") or "⚠️" in t]
        assert not leaked, f"คอมเมนต์ใน code fence กลายเป็น skill: {leaked}"

    def test_real_heading_outside_fence_still_extracted(self, captured):
        """กันแก้เกิน — หัวข้อจริงนอก fence ต้องยังสกัดได้เหมือนเดิม"""
        skills_mod.auto_extract_skills(ENV_DOC, "GUIDE.md")
        topics = [t for t, _ in captured]
        assert "ตั้งค่า .env บน NAS" in topics, f"หัวข้อจริงหายไป: {topics}"

    def test_summary_never_contains_fence_marker(self, captured):
        """``` ที่ติดมาท้าย summary = สัญญาณว่าตัวสกัดอ่านข้าม fence"""
        skills_mod.auto_extract_skills(ENV_DOC, "GUIDE.md")
        bad = [(t, s) for t, s in captured if "```" in s]
        assert not bad, f"summary กิน fence marker เข้ามา: {bad}"

    def test_fence_with_tildes(self, captured):
        """markdown รองรับ ~~~ เป็น fence ด้วย"""
        doc = "## หัวข้อจริง\n\nเนื้อหาที่ยาวพอจะผ่านเกณฑ์ของตัวกรอง skill นะครับ\n\n~~~env\n# ไม่ใช่หัวข้อ แต่เป็นคอมเมนต์ในบล็อก\nKEY=value\n~~~\n"
        skills_mod.auto_extract_skills(doc, "x.md")
        topics = [t for t, _ in captured]
        assert "ไม่ใช่หัวข้อ แต่เป็นคอมเมนต์ในบล็อก" not in topics, topics


class TestUnchangedBehaviour:
    """กันแก้เกิน — พฤติกรรมเดิมที่ถูกอยู่แล้วต้องไม่เปลี่ยน"""

    def test_short_text_returns_empty(self, captured):
        assert skills_mod.auto_extract_skills("สั้นไป", "x.md") == []

    def test_plain_markdown_headings_extracted(self, captured):
        doc = (
            "## ระบบ Memory\n\nAI จำข้อมูลสำคัญของคุณข้ามเซสชัน เช่น ชื่อ งาน ความชอบ\n\n"
            "## Dream Cycle\n\nระบบปรับปรุง memory ให้มีคุณภาพขึ้นทุกคืนตอนตีสอง\n"
        )
        skills_mod.auto_extract_skills(doc, "x.md")
        topics = [t for t, _ in captured]
        assert "ระบบ Memory" in topics and "Dream Cycle" in topics, topics
