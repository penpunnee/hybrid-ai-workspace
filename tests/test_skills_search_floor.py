"""พื้นคะแนนของ `search_skills()` — ห้ามฉีด skill ที่พิสูจน์ความเกี่ยวข้องไม่ได้

**เคสจริงที่ทำให้ต้องมีไฟล์นี้ (backlog ข้อ 9, ค้างมาตั้งแต่ 2026-08-03):**
ถาม *"openclaw คืออะไร"* → ได้ skill ที่ไม่เกี่ยวเลยฉีดเข้า context

เส้นนี้เป็น **เส้นสุดท้ายที่ยังไม่มีพื้นคะแนน** — พี่น้องของมันปิดไปหมดแล้ว:
- `load_skills_relevant()` → `utils/skills_select.py:64` มี `SKILLS_FALLBACK_MIN_SCORE` (0.35)
- `search_web()` → `utils/websearch.py:41` มี `WEB_SEARCH_MIN_SCORE` (0.35, ข้อ 24)
- `search_skills()` → **ไม่มีอะไรเลย** ทั้งที่ `utils/skills_search.py:168` คำนวณ
  `distance` ใส่ dict ไว้แล้ว — ค่าถูกคำนวณแต่ไม่มีใครตัดสินใจด้วยมัน

**บทเรียนที่คุมไฟล์นี้:** จัดอันดับตอบได้แค่ "อันไหนดีกว่า" ตอบไม่ได้ว่า "ดีพอหรือยัง"
— top-3 ของคลังที่ไม่มีอะไรเกี่ยวเลย ก็ยังคืน 3 อันอยู่ดี

⚠️ เทสในไฟล์นี้ **ส่งเกณฑ์เข้าไปตรงๆ** ไม่พึ่งค่า default — ค่า default ต้องมาจาก
การวัดจริงบน prod (`scripts/skills_floor_probe.py`) ไม่ใช่จากเทส
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils.skills as skills


def _row(similarity, topic="หัวข้อ", source="a.md"):
    """แถวผลลัพธ์แบบที่ `SkillsSearch.search()` คืน"""
    return {"topic": topic, "summary": "เนื้อหา", "category": "general",
            "source": source, "similarity": similarity}


class TestFloorMechanism:
    """กลไกพื้นคะแนน — ทดสอบด้วยเกณฑ์ที่ส่งเข้าไปเอง ไม่ผูกกับค่า default"""

    def test_drops_below_floor(self):
        kept = skills._drop_below_min_score(
            [_row(0.12, "หนัง"), _row(0.20, "อาหาร")], min_score=0.35)
        assert kept == [], f"ของที่ไม่เกี่ยวยังหลุดผ่าน: {[r['topic'] for r in kept]}"

    def test_keeps_above_floor(self):
        rows = [_row(0.82, "openclaw"), _row(0.61, "deploy")]
        assert skills._drop_below_min_score(rows, min_score=0.35) == rows

    def test_keeps_only_the_relevant_one(self):
        """เคส openclaw: ตัวที่เกี่ยวชนะอยู่แล้ว แต่ท้ายขบวนต้องถูกตัด"""
        kept = skills._drop_below_min_score(
            [_row(0.78, "openclaw"), _row(0.19, "ollama"), _row(0.17, "ui")],
            min_score=0.35)
        assert [r["topic"] for r in kept] == ["openclaw"]

    def test_missing_similarity_is_dropped(self):
        """ไม่มีคะแนน = พิสูจน์ไม่ได้ = ไม่ฉีด (ทิศเดียวกับ ข้อ 19 fail-closed
        และ `_drop_below_min_score` ของ websearch ที่ตัดผลไม่มี `_rerank_score`)"""
        kept = skills._drop_below_min_score(
            [_row(None, "ไม่รู้คะแนน"), _row(0.9, "ของดี")], min_score=0.35)
        assert [r["topic"] for r in kept] == ["ของดี"]

    def test_floor_can_be_disabled(self):
        """`min_score=None` = ปิดพื้น (เผื่อ embed ล่มยาวจนยอมรับผลที่ไม่ได้ตรวจ)"""
        rows = [_row(0.01), _row(None)]
        assert skills._drop_below_min_score(rows, min_score=None) == rows


class TestWiredIntoSearchSkills:
    """กลไกต้องถูกต่อเข้าเส้นที่ฉีดจริง ไม่ใช่มีฟังก์ชันลอยอยู่เฉยๆ"""

    def test_irrelevant_results_are_not_injected(self, monkeypatch):
        import utils.skills_search as ss

        class _Fake:
            available = True
            def search(self, query, n_results=3):
                return [_row(0.11, "หนังโป๊เก่าเก็บ"), _row(0.09, "สูตรต้มยำ")]

        monkeypatch.setattr(ss, "get_skills_search", lambda: _Fake())
        monkeypatch.setattr(skills, "SKILLS_SEARCH_MIN_SCORE", 0.35, raising=False)
        out = skills.search_skills("openclaw คืออะไร")
        assert out == "", f"ยังฉีด skill ที่ไม่เกี่ยว: {out!r}"


class TestUnscorableCollection:
    """collection ที่ไม่ได้อยู่บน cosine space — คะแนนแปลไม่ได้ทุกแถว

    ทิศที่เลือก (user, 2026-08-04): **fail-closed + ส่งเสียงดัง**
    เหตุผลที่ปิดเส้นนี้ได้โดยไม่ทำให้ระบบไร้ความรู้: `load_skills_relevant()`
    อ่าน .md จากดิสก์ตรงๆ ไม่ผ่าน ChromaDB — เป็นคนละเส้นและไม่ได้พังไปด้วย
    """

    def _fake(self, monkeypatch, rows):
        import utils.skills_search as ss

        class _Fake:
            available = True
            def search(self, query, n_results=3):
                return rows

        monkeypatch.setattr(ss, "get_skills_search", lambda: _Fake())

    def test_nothing_injected_when_no_row_can_be_scored(self, monkeypatch, caplog):
        self._fake(monkeypatch, [_row(None, "a"), _row(None, "b")])
        monkeypatch.setattr(skills, "SKILLS_SEARCH_MIN_SCORE", 0.35, raising=False)
        out = skills.search_skills("openclaw คืออะไร")
        assert out == "", f"ฉีดของที่พิสูจน์ไม่ได้: {out!r}"

    def test_error_log_names_a_command_that_exists(self, monkeypatch, caplog):
        """log ต้องบอกวิธีแก้ที่ **รันได้จริง** — log ที่ชี้ไปฟังก์ชันที่ไม่มีอยู่
        แย่กว่าไม่บอก เพราะคนจะเชื่อแล้วเสียเวลาไปกับคำสั่งที่พัง"""
        import logging
        self._fake(monkeypatch, [_row(None, "a")])
        monkeypatch.setattr(skills, "SKILLS_SEARCH_MIN_SCORE", 0.35, raising=False)
        with caplog.at_level(logging.ERROR):
            skills.search_skills("openclaw คืออะไร")

        assert any(r.levelname == "ERROR" for r in caplog.records), "ไม่ได้ส่งเสียงเลย"
        msg = " ".join(r.getMessage() for r in caplog.records)
        assert "recreate_collection" in msg, "log ไม่ได้บอกวิธีแก้"

        import utils.skills_search as ss
        assert callable(getattr(ss, "recreate_collection", None)), (
            "log ชี้ไป utils.skills_search.recreate_collection แต่ฟังก์ชันนั้นไม่มีอยู่จริง")

    def test_off_switch_stays_an_escape_hatch(self, monkeypatch, caplog):
        """`=off` คือคนสั่งว่า 'ยอมรับผลที่ไม่ได้ตรวจ' → ไม่ใช่สถานการณ์ผิดปกติ
        ต้องไม่ร้อง ERROR และต้องฉีดต่อได้ (เผื่อ embed ล่มยาว)"""
        import logging
        self._fake(monkeypatch, [_row(None, "a")])
        monkeypatch.setattr(skills, "SKILLS_SEARCH_MIN_SCORE", None, raising=False)
        with caplog.at_level(logging.ERROR):
            out = skills.search_skills("openclaw คืออะไร")
        assert out != "", "ปิดพื้นแล้วยังไม่ฉีด"
        assert not [r for r in caplog.records if r.levelname == "ERROR"]


class TestMeasuredValues:
    """ตรึงเลขที่ **วัดจริงบน prod 2026-08-04** ไม่ใช่เลขที่แต่งขึ้น

    ถ้าเทสพวกนี้แดงแปลว่ามีคนเปลี่ยน default หรือเปลี่ยน scorer — ต้องวัดใหม่
    ก่อนแก้เทส (`scripts/skills_floor_probe.py` + sweep กับ data/skills_pairs.json)
    """

    def test_default_floor_is_the_measured_value(self):
        assert skills.SKILLS_SEARCH_MIN_SCORE == 0.38, (
            "เปลี่ยน default โดยไม่ได้วัดใหม่? ที่มาของ 0.38 อยู่ในคอมเมนต์ utils/skills.py")

    def test_openclaw_case_is_actually_fixed(self):
        """คะแนนจริงจาก prod: openclaw.md 0.5461 · ขยะที่ตามมา 0.2956 / 0.2800
        (ยิง `openclaw คืออะไร` ในคอนเทนเนอร์ 2026-08-04)"""
        kept = skills._drop_below_min_score([
            _row(0.5461, "OpenClaw — AI Agent platform", "openclaw.md"),
            _row(0.2956, "MCP Server Export", "mcp-server-export.md"),
            _row(0.2800, "project-architecture", "project-architecture.md"),
        ])
        assert [r["source"] for r in kept] == ["openclaw.md"], (
            f"เคสที่เปิดบั๊กนี้ยังไม่ถูกปิด: {[r['source'] for r in kept]}")

    def test_out_of_domain_questions_inject_nothing(self):
        """คะแนนสูงสุดที่วัดได้จากคำถามนอกโดเมน 5 ข้อ — ต้องไม่ผ่านสักตัว
        (ปวดหัวข้างเดียว 0.3036 · ต้มยำกุ้ง 0.2345 · ราคาทอง 0.1379 ·
         แนะนำหนัง 0.1066 · อากาศวันนี้ 0.0855)"""
        kept = skills._drop_below_min_score(
            [_row(s) for s in (0.3036, 0.2345, 0.1379, 0.1066, 0.0855)])
        assert kept == [], f"คำถามนอกโดเมนยังฉีด skill: {len(kept)} รายการ"


class TestCollectionSpace:
    """`skills_collection` ต้องถูกสร้างด้วย cosine space เหมือน collection อื่นทั้งโปรเจกต์

    ทำไมถึงเป็นเทส ไม่ใช่คอมเมนต์: `utils/memory.py:96` เขียนไว้แล้วว่า "ทุกจุดที่
    สร้าง/ดึง collection ควรผ่านนี่" — แต่เจตนาที่ไม่มีกลไกบังคับคือข้อยกเว้นที่รอเวลาเกิด
    และมันเกิดจริงที่ `utils/skills_search.py:44` (เรียก `client.create_collection()` ตรงๆ)

    ผลถ้าไม่ใช่ cosine: chroma default = **l2** ซึ่ง distance ไม่มีขอบบน →
    `1.0 - distance` ที่ `utils/skills_shadow.py:159` ใช้แปลงเป็น similarity ให้ค่าติดลบ
    = เครื่องมือวัดของข้อ 21 อ่านสเกลผิด และเกณฑ์ 0.35 ของเส้นอื่นเอามาเทียบไม่ได้
    """

    def test_created_collection_uses_cosine_space(self, monkeypatch):
        import utils.skills_search as ss

        created = {}

        class _FakeClient:
            def __init__(self, *a, **kw): pass
            def get_collection(self, *a, **kw):
                raise RuntimeError("ยังไม่มี collection")
            def create_collection(self, **kwargs):
                created.update(kwargs)
                return object()
            def get_or_create_collection(self, name, **kwargs):
                created.update({"name": name, **kwargs})
                return object()

        monkeypatch.setattr(ss.chromadb, "HttpClient", _FakeClient)
        ss.SkillsSearch()

        space = (created.get("metadata") or {}).get("hnsw:space")
        assert space == "cosine", (
            f"skills_collection ถูกสร้างด้วย space={space!r} — "
            "l2/default ทำให้ distance ไม่มีขอบบนและเทียบเกณฑ์ข้ามเส้นไม่ได้"
        )
