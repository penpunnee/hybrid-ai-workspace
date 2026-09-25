"""`SlidingWindowLimiter._cap()` ต้องไล่ key เก่าสุด ไม่ใช่ key ที่เพิ่งใส่ (audit 2026-09-24 MEDIUM ข้อ 4)

`dict.popitem()` เป็น LIFO ตั้งแต่ Python 3.7 → key ที่เพิ่งถูกสร้างใน `hit()` คือตัวที่ถูกลบทันที
⇒ ตอน dict เต็ม (ถูก spoof IP จนถึง cap) **IP ใหม่ทุกตัวไม่เคยถูกนับ** = rate limit ปิดตัวเองพอดีตอนถูกโจมตี
"""
import os
import sys


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.ratelimit as rl


def _fill(lim, n):
    for i in range(n):
        lim.hit(f"ip{i}")


def test_dict_เต็มแล้ว_key_ใหม่ยังถูกนับจนโดน_limit():
    lim = rl.SlidingWindowLimiter(limit=3, window=60, max_keys=5)
    _fill(lim, 5)
    results = [lim.hit("attacker")[0] for _ in range(4)]
    assert results == [True, True, True, False], f"ครั้งที่ 4 ต้องถูก block ({results}) — เดิม key ใหม่ถูก popitem ทิ้งทุกครั้ง"
    assert len(lim._hits) <= 5


def test_cap_ไล่ตัวที่ไม่ได้ใช้นานสุด_ไม่ใช่ตัวล่าสุด():
    lim = rl.SlidingWindowLimiter(limit=10, window=60, max_keys=5)
    _fill(lim, 5)                 # ip0..ip4 · ip0 เก่าสุด
    lim.hit("ip0")                # ใช้ ip0 อีก → ไม่ควรเป็นเหยื่อรายต่อไป
    lim.hit("new")
    assert "new" in lim._hits and "ip0" in lim._hits, lim._hits.keys()
    assert "ip1" not in lim._hits, "ตัวที่ควรถูกไล่คือ ip1 (ไม่ได้ใช้นานสุด)"
    assert len(lim._hits) == 5


def test_record_ก็ต้องไม่ทิ้ง_key_ที่เพิ่งบันทึก():
    lim = rl.SlidingWindowLimiter(limit=2, window=60, max_keys=3)
    for i in range(3):
        lim.record(f"ip{i}")
    lim.record("attacker")
    lim.record("attacker")
    blocked, _ = lim.over_limit("attacker")
    assert blocked, "record 2 ครั้ง (limit=2) ต้องเกิน — เดิม popitem ทิ้ง attacker ทันทีหลัง record"


def test_record_ก็ต้อง_refresh_LRU_ของ_key_เดิม():
    """key ที่ถูก record ซ้ำ (IP ที่ยิง 401 ต่อเนื่อง) ต้องกลายเป็น "ใช้ล่าสุด" ไม่ใช่ถูกไล่เพราะเกิดก่อน"""
    lim = rl.SlidingWindowLimiter(limit=10, window=60, max_keys=3)
    for i in range(3):
        lim.record(f"ip{i}")
    lim.record("ip0")
    lim.record("new")
    assert "ip0" in lim._hits and "new" in lim._hits and "ip1" not in lim._hits, list(lim._hits)
