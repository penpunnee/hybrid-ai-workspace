"""`get_skills_search()` ปลุกสัญญาณเตือนผิด แล้วสั่งให้ลบ index ที่ยังดีอยู่ทิ้ง

**เคสจริง (prod, 2026-08-04 08:20:12):** log ขึ้น ERROR ว่า
*"skills_collection ไม่ได้อยู่บน cosine space ... ต้องสร้างใหม่: docker exec ... recreate_collection()"*
แล้วข้ามการฉีด skill ทั้ง 2 คำขอ

**ตรวจแล้วพบว่า collection ไม่ได้เป็นอะไรเลย** — `collection.id` วันนี้
(`56c1cde1-09e2-43eb-b8c4-08399db7d8f5`) ตรงกับ id ที่ upsert ตอน 08:18 ใน log เป๊ะ
= ไม่เคยถูกลบ/สร้างใหม่ · `metadata` = `{'hnsw:space': 'cosine'}` = เป็น cosine มาตลอด
→ **ข้อความนั้นเป็น false positive ที่สั่งให้ทำสิ่งที่ทำลายข้อมูล** (ลบ index 22 รายการ
ทิ้งเพื่อแก้ปัญหาที่ไม่มีอยู่จริง)

**สองข้อบกพร่องเชิงโครงสร้างที่ผลิต false positive นี้ได้ — วัดบน prod แล้วทั้งคู่:**
1. `get_skills_search()` เป็น lazy singleton **ไม่มี lock** — ยิง 12 เธรดพร้อมกัน
   ได้ `SkillsSearch` **12 ตัว** (ตั้งแต่ PR #23 เส้นนี้อยู่ใน threadpool 40 slot)
2. instance ที่ `__init__` ล้ม (ChromaDB สะดุดชั่วคราว) มี `collection=None` แล้ว
   **ถูก cache ค้างถาวร** → `_space()` คืน `'l2'` ตลอดกาลทั้งที่ collection เป็น cosine
   → ฉีด skill ไม่ได้อีกเลยจนกว่าจะ restart แอป

**หลักการที่ถูกละเมิด:** "อ่านค่าไม่ได้" ถูกกลืนรวมกับ "อ่านได้แล้วเป็น l2" — เป็น
รูปแบบที่ 4 ของ measuring-instruments-lie (ไม่มีข้อมูล ถูกนับเป็นค่าที่เจาะจง)
คนละเรื่องกับการ fail-closed: **ปิดเส้นเพราะพิสูจน์ไม่ได้ = ถูก · บอกว่ารู้สาเหตุแล้ว
ให้ไปลบข้อมูล = ผิด**
"""

import threading
import time

import pytest

import utils.skills_search as ss


@pytest.fixture(autouse=True)
def _reset_singleton():
    ss._skills_search = None
    yield
    ss._skills_search = None


class _FakeCollection:
    def __init__(self, metadata):
        self.metadata = metadata
        self.id = "fake-id"

    def count(self):
        return 0


def _instance(metadata=None, available=True, collection=True):
    s = ss.SkillsSearch.__new__(ss.SkillsSearch)
    s.collection_name = "skills_collection"
    s.available = available
    s.collection = _FakeCollection(metadata) if collection else None
    return s


class TestSingletonIsThreadSafe:
    def test_concurrent_callers_get_one_instance(self):
        """วัดบน prod ได้ 12/12 — แต่ละตัวเปิด client + embedding function ของตัวเอง

        ⚠️ barrier ต้องอยู่**ก่อน**เรียก `get_skills_search()` ไม่ใช่ใน `__init__`
        (เวอร์ชันแรกของเทสนี้วาง barrier ไว้ใน `__init__` — พอใส่ lock แล้วมีเธรดเดียว
        ที่เข้าไปถึง barrier ที่รออยู่ 12 ตัว = **เทส deadlock ตัวเอง** เทสที่ผ่านได้
        เฉพาะตอนโค้ดยังพังอยู่ ไม่ใช่เทส แต่เป็นกับดัก)
        """
        built = []
        lock = threading.Lock()
        barrier = threading.Barrier(12)

        def fake_init(self, *a, **kw):
            with lock:
                built.append(1)
            time.sleep(0.05)          # ถ่างช่องว่างให้ race เกิดได้จริงถ้าไม่มี lock
            self.collection_name = "skills_collection"
            self.available = True
            self.collection = _FakeCollection({"hnsw:space": "cosine"})

        original = ss.SkillsSearch.__init__
        ss.SkillsSearch.__init__ = fake_init
        out = []

        def worker():
            barrier.wait()            # ปล่อยพร้อมกันก่อนแตะ singleton
            out.append(ss.get_skills_search())

        try:
            ts = [threading.Thread(target=worker) for _ in range(12)]
            [t.start() for t in ts]
            [t.join() for t in ts]
        finally:
            ss.SkillsSearch.__init__ = original

        assert len(built) == 1, f"สร้าง SkillsSearch {len(built)} ตัว — singleton ไม่มี lock"
        assert len({id(o) for o in out}) == 1, "เธรดต่างกันได้คนละ instance"


class TestFailedInstanceIsNotCachedForever:
    def test_unavailable_instance_is_retried(self):
        """ChromaDB สะดุดตอน init ต้องไม่แปลว่า 'ฉีด skill ไม่ได้ไปตลอดชีวิตโปรเซส'"""
        ss._skills_search = _instance(available=False, collection=False)
        calls = []

        def fake_init(self, *a, **kw):
            calls.append(1)
            self.collection_name = "skills_collection"
            self.available = True
            self.collection = _FakeCollection({"hnsw:space": "cosine"})

        original = ss.SkillsSearch.__init__
        ss.SkillsSearch.__init__ = fake_init
        try:
            got = ss.get_skills_search()
        finally:
            ss.SkillsSearch.__init__ = original

        assert calls, "instance ที่พังถูก cache ค้าง — ไม่มีใครลองต่อ ChromaDB ใหม่เลย"
        assert got.available is True

    def test_healthy_instance_is_reused(self):
        """ต้องไม่กลายเป็น 'สร้างใหม่ทุกครั้ง' (เดิมตั้งใจให้เป็น singleton ก็เพราะแพง)"""
        healthy = _instance({"hnsw:space": "cosine"})
        ss._skills_search = healthy
        assert ss.get_skills_search() is healthy


class TestSpaceDistinguishesUnknown:
    """"อ่านไม่ได้" ต้องไม่ถูกรายงานว่า "อ่านได้แล้วเป็น l2"" """

    def test_cosine_is_reported(self):
        assert _instance({"hnsw:space": "cosine"})._space() == "cosine"

    def test_real_l2_is_reported(self):
        assert _instance({"hnsw:space": "l2"})._space() == "l2"

    def test_missing_metadata_is_unknown_not_l2(self):
        assert _instance(None)._space() is None, "metadata อ่านไม่ได้ ต้องเป็น unknown ไม่ใช่ l2"

    def test_no_collection_is_unknown(self):
        assert _instance(collection=False)._space() is None

    def test_unknown_space_still_refuses_to_score(self):
        """fail-closed ยังต้องเหมือนเดิม — เปลี่ยนแค่ 'เรารู้อะไร' ไม่ใช่ 'เราทำอะไร'"""
        assert _instance(None)._similarity(0.1) is None
        assert _instance({"hnsw:space": "l2"})._similarity(0.1) is None
        assert _instance({"hnsw:space": "cosine"})._similarity(0.1) == pytest.approx(0.9)


class TestAlarmDoesNotPrescribeDestructiveFix:
    """ข้อความเตือนห้ามยืนยันสาเหตุที่ยังไม่ได้ตรวจ และห้ามสั่งลบข้อมูลจากการเดา"""

    def _log(self, caplog, space):
        from utils.skills import _handle_unscorable_results

        caplog.clear()
        _handle_unscorable_results("openclaw คืออะไร", [{}, {}], space=space)
        return caplog.text

    def test_unknown_space_does_not_tell_operator_to_delete_the_index(self, caplog):
        import logging

        with caplog.at_level(logging.ERROR):
            text = self._log(caplog, None)
        assert "recreate_collection" not in text, (
            "อ่าน space ไม่ได้ แต่ไปสั่งให้ลบ collection ทิ้ง — วันที่ 08-04 collection "
            "แข็งแรงดี (id เดิม, cosine) การทำตามข้อความนี้ = ทำลาย index 22 รายการฟรีๆ"
        )
        assert "ไม่ได้อยู่บน cosine space" not in text, "ยืนยันสาเหตุที่ยังไม่ได้ตรวจ"

    def test_confirmed_l2_may_suggest_recreate(self, caplog):
        import logging

        with caplog.at_level(logging.ERROR):
            text = self._log(caplog, "l2")
        assert "recreate_collection" in text, "กรณีที่อ่านได้จริงว่าเป็น l2 ควรบอกวิธีแก้"
