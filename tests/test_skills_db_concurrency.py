"""`skills_db.json` ต้องทนการเขียนพร้อมกัน — เงื่อนไขก่อนย้าย handler ไป threadpool

**ทำไมไฟล์นี้ต้องมาก่อนการแก้ `async def` + งาน sync (backlog ข้อ 5 ท้ายหัวข้อ):**
`run_in_threadpool` ย้ายโค้ดที่เคยรัน*ทีละอัน*ไปรัน*พร้อมกัน* — ของที่ปลอดภัยเพราะ
"มีคนใช้ทีละคน" จะกลายเป็น race ทันที การแก้ blocking ก่อนแก้ของที่ถูกแชร์
= ย้ายบั๊กจาก "แอปค้าง" ไปเป็น "ข้อมูลหาย" ซึ่งเงียบกว่าและเจอยากกว่า

สิ่งที่ตรวจแล้ว **ไม่ต้องแก้** (พิสูจน์ด้วยการอ่านโค้ดจริง 2026-08-04):
- `utils/embed.py` · `utils/response_cache.py` — `check_same_thread=False` + `threading.Lock` แล้ว
- `utils/history.py` — `_get_conn()` เปิด connection ใหม่ทุกครั้ง = แต่ละ thread มีของตัวเอง
- ChromaDB — `HttpClient` คุยผ่าน HTTP ไม่ได้แชร์ handle ที่ผูกกับ thread

ที่เหลือคือตัวนี้: `save_skill()` ทำ read-modify-write บนไฟล์เดียวโดยไม่มี lock
และ `_save_skills_db()` เขียนทับไฟล์จริงตรงๆ (ไม่ atomic)
"""
import json
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import utils.skills as skills


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    p = tmp_path / "skills_db.json"
    monkeypatch.setattr(skills, "SKILLS_DB_PATH", str(p))
    return p


def _skill(i: int):
    return (f"หัวข้อทดสอบหมายเลข {i}",
            f"เนื้อหาของ skill ทดสอบหมายเลข {i} ที่ยาวพอจะผ่านเกณฑ์คุณภาพขั้นต่ำ")


class TestConcurrentWrites:
    def test_เขียนพร้อมกันแล้วต้องไม่มีรายการหาย(self, db_path):
        """read-modify-write ที่ไม่มี lock = lost update

        thread A อ่าน {} → thread B อ่าน {} → A เขียน {a} → B เขียน {b}
        ผลคือ {b} เท่านั้น — a หายไปเงียบๆ ไม่มี error ไม่มี log
        """
        n_threads, per_thread = 8, 25
        total = n_threads * per_thread
        errors: list[BaseException] = []
        start = threading.Barrier(n_threads)

        def worker(w: int):
            try:
                start.wait()
                for k in range(per_thread):
                    topic, summary = _skill(w * per_thread + k)
                    skills.save_skill(topic, summary, sync=False)
            except BaseException as e:      # noqa: BLE001 — เก็บไปรายงานท้ายเทส
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(w,)) for w in range(n_threads)]
        for t in threads: t.start()
        for t in threads: t.join(timeout=60)

        assert not errors, f"worker พัง: {errors[:3]}"
        saved = json.loads(db_path.read_text(encoding="utf-8"))
        missing = [i for i in range(total) if _skill(i)[0] not in saved]
        assert not missing, (
            f"หายไป {len(missing)}/{total} รายการ (lost update) — ตัวอย่าง {missing[:5]}")

    def test_ไฟล์ต้องอ่านได้ตลอดเวลาแม้ระหว่างเขียน(self, db_path):
        """เขียนทับไฟล์จริงตรงๆ = มีช่วงที่ไฟล์ถูก truncate อยู่

        ใครอ่านจังหวะนั้นได้ JSON พัง → `_load_skills_db()` จับ exception แล้วคืน `{}`
        = **คลังความรู้ว่างเปล่าชั่วคราวโดยไม่มีใครรู้** (แล้วถ้ามีคนเขียนต่อจากนั้น
        ก็เขียนทับด้วยของว่าง = ข้อมูลหายถาวร)
        """
        skills.save_skill(*_skill(0), sync=False)
        stop = threading.Event()
        bad: list[str] = []

        def reader():
            while not stop.is_set():
                try:
                    raw = db_path.read_text(encoding="utf-8")
                except FileNotFoundError:
                    bad.append("ไฟล์หายไประหว่างเขียน")
                    continue
                if not raw:
                    bad.append("อ่านได้ไฟล์เปล่า")
                    continue
                try:
                    json.loads(raw)
                except json.JSONDecodeError:
                    bad.append(f"JSON พัง ({len(raw)} ไบต์)")

        r = threading.Thread(target=reader, daemon=True)
        r.start()
        try:
            for i in range(1, 150):
                skills.save_skill(*_skill(i), sync=False)
        finally:
            stop.set()
            r.join(timeout=10)

        assert not bad, f"อ่านเจอสถานะพัง {len(bad)} ครั้ง — ตัวอย่าง {bad[:3]}"
