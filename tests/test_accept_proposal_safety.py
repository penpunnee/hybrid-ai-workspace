"""`accept_proposal()` — สองอาการที่โผล่มาตอนย้าย handler เข้า threadpool

**ทำไมสองข้อนี้ถึงมาด้วยกัน:** ก่อน PR นี้ `/api/skills/discover/accept` เป็น `async def`
ที่เรียก `accept_proposal()` แบบ sync ตรงๆ → ทั้งฟังก์ชันรันบน event loop = **atomic
โดยบังเอิญ** พอย้ายเข้า `run_in_threadpool` ตามที่ควรจะเป็น ของที่ปลอดภัยเพราะ
"มีคนใช้ทีละคน" ก็โผล่ออกมา

1. **double accept** — `_proposals_cache.get()` อยู่หัวฟังก์ชัน แต่ `.pop()` อยู่ท้าย
   สองคำขอที่ใช้ `proposal_id` เดียวกันจึงอ่านเจอ proposal ตัวเดียวกันได้ทั้งคู่ แล้ว
   เขียนไฟล์/db/ChromaDB ซ้ำแล้วตอบสำเร็จทั้งคู่ (ชื่อไฟล์ผูกกับ `int(time.time())`
   → ถ้าอยู่วินาทีเดียวกันคือไฟล์เดียวกัน = ทับกันเอง)

2. **index ถูกล้าง** — `sync_from_db()` นิยามว่า "upsert + **ลบของที่หายไปจาก db**"
   (เพิ่ม 2026-08-02 เพื่อแก้ index ค้างหลังลบ skill) แต่ผู้เรียกตรงนี้ส่ง mapping
   **แค่รายการเดียว** → ทุกครั้งที่มีคนกด accept, ChromaDB เหลือ skill เดียว
   ตัวที่เพิ่มการลบเข้าไปไม่ได้ไล่ดูว่าใครเรียกด้วย mapping บางส่วนบ้าง
"""
import json
import os
import sys
import threading
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import utils.skill_discovery as sd
import utils.skills as skills


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(sd, "_SKILLS_DIR", str(tmp_path / "skills"))
    monkeypatch.setattr(skills, "SKILLS_DB_PATH", str(tmp_path / "skills_db.json"))
    sd._proposals_cache.clear()
    yield tmp_path
    sd._proposals_cache.clear()


def _fake_search(monkeypatch, sink: list):
    """ดัก mapping ที่ถูกส่งเข้า `sync_skills_to_search()` — เทสว่าส่ง 'อะไร' ไม่ใช่ 'กี่ครั้ง'"""
    mod = types.ModuleType("utils.skills_search")
    mod.sync_skills_to_search = lambda db: sink.append(dict(db))
    monkeypatch.setitem(sys.modules, "utils.skills_search", mod)


def _proposal(pid: str = "p1"):
    return sd.SkillProposal(
        id=pid, topic="Docker Deploy", summary="ถามเรื่อง deploy บ่อยมากในช่วงนี้",
        examples=["deploy ยังไง", "docker คืออะไร"], cluster_size=4,
        detected_at="2026-08-04T00:00:00",
    )


def test_accept_พร้อมกันด้วย_id_เดียวต้องสำเร็จแค่ครั้งเดียว(isolated, monkeypatch):
    """เดิม `.get()` หัวฟังก์ชัน + `.pop()` ท้ายฟังก์ชัน = check-then-act ที่แยกกันได้"""
    _fake_search(monkeypatch, [])
    sd._proposals_cache["p1"] = _proposal()

    n = 8
    results: list[dict] = []
    lock = threading.Lock()
    start = threading.Barrier(n)

    def worker():
        start.wait()
        r = sd.accept_proposal("p1")
        with lock:
            results.append(r)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads: t.start()
    for t in threads: t.join(timeout=30)

    ok = [r for r in results if r.get("ok")]
    assert len(results) == n, f"worker ไม่ครบ: {len(results)}/{n}"
    assert len(ok) == 1, (
        f"สำเร็จ {len(ok)} ครั้งจาก {n} คำขอที่ใช้ proposal_id เดียวกัน — ต้องได้ครั้งเดียว")
    assert "p1" not in sd._proposals_cache


def test_accept_ต้องไม่ล้าง_index_ที่เหลือ(isolated, monkeypatch):
    """`sync_from_db()` ลบ id ที่ไม่อยู่ใน mapping — ส่งรายการเดียว = ล้างที่เหลือทิ้ง"""
    sent: list[dict] = []
    _fake_search(monkeypatch, sent)

    # skill เดิมที่มีอยู่ก่อนแล้ว 2 ตัว
    skills.set_skill_entry("เรื่องเดิมที่หนึ่ง", {"summary": "เนื้อหาของ skill เดิมตัวที่หนึ่ง"})
    skills.set_skill_entry("เรื่องเดิมที่สอง", {"summary": "เนื้อหาของ skill เดิมตัวที่สอง"})

    sd._proposals_cache["p1"] = _proposal()
    res = sd.accept_proposal("p1")
    assert res["ok"] is True, res

    assert sent, "ไม่ได้เรียก sync_skills_to_search เลย"
    synced = sent[-1]
    on_disk = json.loads((isolated / "skills_db.json").read_text(encoding="utf-8"))
    missing = sorted(set(on_disk) - set(synced))
    assert not missing, (
        f"ส่งเข้า sync แค่ {sorted(synced)} — skill ที่หายจาก mapping จะถูกลบออกจาก "
        f"ChromaDB: {missing}")


def test_accept_ที่ถูกปฏิเสธต้องคืน_proposal_ให้ลองใหม่ได้(isolated, monkeypatch):
    """ถ้ายึด proposal ไว้ตั้งแต่ต้นแล้วล้มเหลว ต้องคืน ไม่งั้น retry ไม่ได้อีกเลย"""
    _fake_search(monkeypatch, [])
    sd._proposals_cache["p2"] = _proposal("p2")

    res = sd.accept_proposal("p2", custom_topic="ดู ")     # ติด gate (สั้น + junk pattern)
    assert res["ok"] is False

    assert "p2" in sd._proposals_cache, "proposal หายไปทั้งที่ยังไม่ได้ถูกใช้จริง"
    assert sd.accept_proposal("p2")["ok"] is True, "retry ด้วย topic ปกติต้องผ่าน"


def test_accept_ต้องบอกผู้เรียกเมื่อเขียน_db_ไม่สำเร็จ(isolated, monkeypatch):
    """.md เขียนแล้วแต่ skills_db ล้ม = skill ครึ่งใบ (ค้นไม่เจอเพราะไม่มีใน db)

    เดิมคืน `ok:True` เปล่าๆ ผู้เรียกแยกไม่ออกจากความสำเร็จเต็มใบ
    ใช้รูปแบบเดียวกับ `routers/skills.py:skills_extract` ที่มีอยู่แล้ว
    (`db_updated` + `warning`) — ไม่ใช่คิดสัญญาใหม่ขึ้นมาเอง
    """
    def _boom(*a, **k):
        raise RuntimeError("disk full")

    _fake_search(monkeypatch, [])
    monkeypatch.setattr("utils.skills.set_skill_entry", _boom)
    sd._proposals_cache["p1"] = _proposal()

    r = sd.accept_proposal("p1")

    assert r["ok"] is True, "ไฟล์ .md เขียนสำเร็จ จึงไม่ใช่ความล้มเหลวทั้งใบ"
    assert r["db_updated"] is False
    assert "disk full" in r["warning"]


def test_accept_ปกติต้องบอกว่า_db_updated_เป็นจริง(isolated, monkeypatch):
    """กลุ่มควบคุม — ถ้าไม่มีเคสนี้ การตั้ง db_updated=False ตายตัวก็ผ่านเทสข้างบน"""

    _fake_search(monkeypatch, [])
    sd._proposals_cache["p1"] = _proposal()
    r = sd.accept_proposal("p1")

    assert r["ok"] is True
    assert r["db_updated"] is True
    assert "warning" not in r
