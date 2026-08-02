"""Phase 3 (Deep Sleep) — resilience ต่อ theme เดียวที่ upsert พัง

บั๊กจริง (พบจาก audit 2026-08-01): deep_sleep() ครอบ loop upsert ของ
ทุก memory-type theme เข้า `long_term_memory` ด้วย try/except เดียว —
ถ้า theme หนึ่งพัง (เช่น metadata แปลก/embedding conflict) ทั้งฟังก์ชัน
throw ออกจาก loop ทันที ทำให้ theme อื่นที่ผ่านเกณฑ์คืนนั้นไม่ถูก
บันทึกไปด้วยแบบเงียบๆ — เหมือน bug light_sleep เดิม (2026-07-13) ที่แก้
เป็น per-collection try/except ไปแล้ว จุดนี้ต้องเป็น per-theme เหมือนกัน
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils.dream as dream


class _FlakyCol:
    """upsert พังเฉพาะ theme ชื่อ 'bad' — theme อื่นต้องรอด"""

    def __init__(self):
        self.saved_ids = []

    def upsert(self, ids, documents, metadatas):
        if "bad" in ids[0]:
            raise Exception("embedding function conflict")
        self.saved_ids.append(ids[0])


def test_deep_sleep_one_bad_theme_does_not_drop_the_rest(monkeypatch):
    col = _FlakyCol()
    client = SimpleNamespace()
    monkeypatch.setattr(dream, "_get_client", lambda: client)
    monkeypatch.setattr(dream, "get_or_create_collection", lambda c, name: col)
    monkeypatch.setattr(dream, "classify_theme", lambda name, summary: "memory")

    themes = [
        {"name": "bad", "summary": "สรุปธีมที่จะพัง", "count": 3},
        {"name": "good", "summary": "สรุปธีมที่ปกติ", "count": 2},
    ]

    result = dream.deep_sleep(memories=[], themes=themes)

    # ทั้งสอง theme ผ่านเกณฑ์ promote (นับใน report) แม้ "bad" upsert ล้ม
    assert set(result["promoted"]) == {"bad", "good"}
    # แต่ ChromaDB ต้องมีแค่ "good" จริง — "bad" ถูกข้ามแบบมี log ไม่ทำให้ "good" หายตาม
    assert len(col.saved_ids) == 1
    assert "good" in col.saved_ids[0]
    assert "bad" not in col.saved_ids[0]
