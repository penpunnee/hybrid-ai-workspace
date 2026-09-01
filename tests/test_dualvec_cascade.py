"""เงา `__keys` ต้องเดินตามตัวหลักทุกเส้น — ไม่ใช่แค่ในสคริปต์

🔴 ที่มา (audit 2026-09-02): `memory/dualvec.py` เพิ่ม collection คู่ขนาน
`<name>__keys` เข้ามาทีหลัง แต่โค้ดที่เขียนไว้**ก่อน**หน้านั้นไม่รู้จักมัน ⇒ เกิดรอย
ต่อสองแบบพร้อมกัน

1. **ลบไม่ทั่ว** — `delete_entry()` (เบื้องหลัง `DELETE /api/admin/memory/...`
   ที่เอกสารเสนอให้ใช้ล้าง memory ปนเปื้อน) ลบแต่ตัวหลัก · ของจริงบน prod:
   `memory_kwan__keys` มี id ที่ไม่มีในตัวหลัก 1 ตัว ตั้งแต่รอบล้าง 2026-07-13
   และ `merge_max()` **ฉีด key-only hit กลับเข้า context ได้** (`dualvec.py:84`)
   ⇒ ของที่สั่งลบไปแล้ว โผล่กลับมา
2. **กวาดโดนตัวเอง** — `name.startswith("memory_")` จับ `memory_kwan__keys` ด้วย
   ⇒ `light_sleep`/`memory_decay`/`memory_prune` เดินเข้า collection เงา:
   นับแถวกุญแจเป็น memory (เนื้อหาซ้ำเข้า REM), decay confidence ของกุญแจ,
   prune กุญแจของ memory ที่ยังอยู่

🔑 **ทำไมต้องรวมศูนย์ ไม่ใช่ไล่เติมทีละจุด:** `tests/test_dualvec.py`
`TestDeletionStaysInSync` เขียนอาการนี้ไว้ถูกต้องตั้งแต่แรก แต่คุมแค่
`scripts/clean_episodic.py` · และ `TestUserFactsWiring` เขียนไว้เองว่า
"บทเรียนซ้ำของ audit นี้คือ 'แก้ 3 ใน 4 จุดแล้วคิดว่าจบ'" — แล้วก็เกิดซ้ำจริง

🔑 **ลำดับลบ: เงาก่อนเสมอ** (ChromaDB ไม่มี transaction ข้าม collection)
· ล้มหลังลบเงา → เหลือ "ตัวหลักไม่มีกุญแจ" = สถานะปกติที่ระบบรองรับอยู่แล้ว
  (`key_text()` คืน `None` ได้ · `key_hits()` คืน `{}` เมื่อไม่มี collection)
· ล้มหลังลบตัวหลัก → เหลือ "กุญแจกำพร้า" ที่ recall ขึ้นมาได้ = อาการที่กำลังแก้
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ── ตัวกลางเดียวที่ทุกเส้นต้องใช้ ────────────────────────────────────────────
class TestCascadeHelper:
    def test_ลบเงาก่อนตัวหลักเสมอ(self):
        """ลำดับคือการตัดสินใจเชิงออกแบบ ไม่ใช่รายละเอียด — ตรึงไว้"""
        from memory.dualvec import delete_with_keys

        order = []
        client, col = MagicMock(), MagicMock()
        col.delete.side_effect = lambda **kw: order.append("main")
        client.get_collection.return_value = col
        with patch("memory.dualvec.delete_keys",
                   side_effect=lambda *a, **k: order.append("keys") or True):
            delete_with_keys(client, "memory_kwan", ["x"])
        assert order == ["keys", "main"], f"ลำดับผิด: {order}"

    def test_เงาลบไม่สำเร็จ_ตัวหลักยังต้องถูกลบ_แต่ต้องเตือน(self, caplog):
        """เจตนาผู้ใช้คือ 'ลบข้อมูลนี้' — ห้ามบล็อกเพราะเงาล้ม แต่ต้องมีร่องรอย
        ให้ตัวกวาดกำพร้าตามเก็บ (แนวทาง reconciliation ของ Qdrant)"""
        import logging

        from memory.dualvec import delete_with_keys

        client, col = MagicMock(), MagicMock()
        client.get_collection.return_value = col
        with caplog.at_level(logging.ERROR), \
             patch("memory.dualvec.delete_keys", return_value=False):
            delete_with_keys(client, "memory_kwan", ["x"])
        col.delete.assert_called_once_with(ids=["x"])
        assert any("กุญแจ" in r.message or "keys" in r.message.lower()
                   for r in caplog.records), "ลบเงาล้มแล้วเงียบ = กำพร้าที่ไม่มีใครรู้"

    def test_delete_keys_คืน_False_เมื่อลบไม่สำเร็จจริง(self):
        """ต้องเทส **ไส้ใน** ของ delete_keys ด้วย — เทสที่ patch มันทิ้งไว้
        จะไม่มีวันจับได้ว่ามันรายงานผลผิด (mutation M6 รอดเพราะเหตุนี้)"""
        from memory.dualvec import delete_keys

        col = MagicMock()
        col.delete.side_effect = Exception("chroma ล่ม")
        client = MagicMock()
        with patch("utils.memory.get_collection", return_value=col):
            assert delete_keys(client, "memory_kwan", ["x"]) is False

    def test_delete_keys_คืน_True_เมื่อยังไม่มี_collection_เงา(self):
        """assistant ใหม่ / ยังไม่ backfill = ไม่มีอะไรกำพร้า ห้ามเตือนผิด"""
        from memory.dualvec import delete_keys

        client = MagicMock()
        with patch("utils.memory.get_collection", side_effect=Exception("ไม่มี collection")):
            assert delete_keys(client, "memory_new", ["x"]) is True

    def test_ไม่มี_id_ไม่แตะอะไรเลย(self):
        from memory.dualvec import delete_with_keys

        client = MagicMock()
        with patch("memory.dualvec.delete_keys") as dk:
            delete_with_keys(client, "memory_kwan", [])
        client.get_collection.assert_not_called()
        dk.assert_not_called()

    def test_สคริปต์เดิมต้องใช้ตัวกลางตัวเดียวกัน(self):
        """`scripts/clean_episodic.delete_with_keys` ห้ามเป็นสำเนาที่ดริฟต์ได้"""
        from memory.dualvec import delete_with_keys as canonical
        from scripts.clean_episodic import delete_with_keys as script_fn

        assert script_fn is canonical


class TestIsKeysCollection:
    @pytest.mark.parametrize("name,expected", [
        ("memory_kwan", False), ("memory_kwan__keys", True),
        ("lessons", False), ("lessons__keys", True),
        ("user_facts__keys", True), ("documents", False),
    ])
    def test_แยกเงาออกจากตัวหลักได้(self, name, expected):
        from memory.dualvec import is_keys_collection

        assert is_keys_collection(name) is expected


# ── เส้นลบใน production ต้อง cascade ────────────────────────────────────────
class TestProductionDeletePathsCascade:
    def test_delete_entry_ลบเงาด้วย(self):
        """เส้นเบื้องหลัง DELETE /api/admin/memory/{assistant}/{id}"""
        import memory.store as ms

        seen = {}
        with patch.object(ms, "_get_chroma_client", return_value=MagicMock()), \
             patch("memory.dualvec.delete_with_keys",
                   side_effect=lambda c, n, i: seen.update(col=n, ids=i)):
            ok = ms.delete_entry("kwan", "mem_1")
        assert ok is True
        assert seen == {"col": "memory_kwan", "ids": ["mem_1"]}

    def test_delete_lesson_ลบเงาด้วย(self):
        """`lessons` มีเงาเหมือนกัน (utils/memory.py:288 เขียน sync_key)"""
        import utils.memory as um

        seen = {}
        with patch.object(um, "_get_client", return_value=MagicMock()), \
             patch("memory.dualvec.delete_with_keys",
                   side_effect=lambda c, n, i: seen.update(col=n, ids=i)):
            ok = um.delete_lesson("les_1")
        assert ok is True
        assert seen == {"col": "lessons", "ids": ["les_1"]}


# ── ตัวกวาดต้องไม่เดินเข้า collection เงา ──────────────────────────────────
def _client_with_shadow(main_data, keys_data):
    """client ปลอมที่มีทั้ง memory_kwan และเงาของมัน"""
    main, keys = MagicMock(), MagicMock()
    main.get.return_value = main_data
    keys.get.return_value = keys_data
    cols = {"memory_kwan": main, "memory_kwan__keys": keys}
    client = SimpleNamespace(
        list_collections=lambda: [SimpleNamespace(name=n) for n in cols],
        get_collection=lambda name: cols[name],
    )
    return client, main, keys


class TestSweepsSkipShadow:
    def test_light_sleep_ไม่นับแถวของเงาเป็น_memory(self, monkeypatch):
        """เนื้อกุญแจถูกสกัดมาจาก doc เดิม ⇒ นับซ้ำ = ป้อนของซ้ำเข้า REM
        และ theme count อาจข้ามเกณฑ์ PROMOTE_MIN_HITS ทั้งที่เกิดครั้งเดียว"""
        import utils.dream as dream

        ts = "2999-01-01T00:00:00"       # อนาคต = ผ่านตัวกรอง 24 ชม.เสมอ
        client, _, _ = _client_with_shadow(
            {"ids": ["a"], "documents": ["Q: NAS รุ่นอะไร\nA: Synology"],
             "metadatas": [{"timestamp": ts}]},
            {"ids": ["a"], "documents": ["NAS รุ่นอะไร"],
             "metadatas": [{"timestamp": ts}]},
        )
        monkeypatch.setattr(dream, "_get_client", lambda: client)
        monkeypatch.setattr("utils.memory.get_collection",
                            lambda c, n: c.get_collection(n))
        out = dream.light_sleep()
        assert [m["collection"] for m in out] == ["memory_kwan"], \
            "แถวของ collection เงาหลุดเข้า REM"

    def test_memory_decay_ไม่แตะเงา(self, monkeypatch):
        """⚠️ meta ต้องมี `timestamp` เก่ากว่า 7 วัน ไม่งั้น decay ไม่เขียนอยู่แล้ว
        แล้วเทสจะผ่านฟรีทั้งที่ตัวกรองถูกถอดออก (mutation M2 จับได้ตอนแรก)"""
        import utils.dream as dream

        stale = {"confidence": 0.9, "timestamp": "2000-01-01T00:00:00"}
        client, main, keys = _client_with_shadow(
            {"ids": ["a"], "metadatas": [dict(stale)]},
            {"ids": ["a"], "metadatas": [dict(stale)]},
        )
        monkeypatch.setattr(dream, "_get_client", lambda: client)
        monkeypatch.setattr("utils.memory.get_collection",
                            lambda c, n: c.get_collection(n))
        out = dream.memory_decay()
        main.update.assert_called_once()          # กลุ่มควบคุม: ตัวหลักต้องถูก decay จริง
        keys.update.assert_not_called()
        assert out["decayed"] == 1, f"นับซ้ำจากเงา: {out}"

    def test_memory_prune_ไม่แตะเงา_และ_cascade_ตอนลบ(self, monkeypatch):
        import utils.dream as dream

        old = "2000-01-01T00:00:00"
        dead = {"confidence": 0.1, "access_count": 0, "created_at": old}
        client, main, keys = _client_with_shadow(
            {"ids": ["a"], "metadatas": [dead]},
            {"ids": ["a"], "metadatas": [dead]},
        )
        monkeypatch.setattr(dream, "_get_client", lambda: client)
        monkeypatch.setattr("utils.memory.get_collection",
                            lambda c, n: c.get_collection(n))
        seen = []
        with patch("memory.dualvec.delete_with_keys",
                   side_effect=lambda c, n, i: seen.append((n, i))):
            dream.memory_prune()
        keys.delete.assert_not_called()
        assert seen == [("memory_kwan", ["a"])], f"prune ไม่ cascade: {seen}"

    def test_cleanup_old_memories_ไม่กวาดเงาโดยตรง(self, monkeypatch):
        """เงาต้องหายเพราะตัวหลักถูกลบ ไม่ใช่เพราะถูกกวาดเองแยกกัน
        (กวาดแยก = สองชุดเดินคนละจังหวะ แล้วดริฟต์)"""
        import utils.memory as um

        client, main, keys = _client_with_shadow(
            {"ids": ["a"], "metadatas": [{"timestamp": "2000-01-01T00:00:00"}]},
            {"ids": ["a"], "metadatas": [{"timestamp": "2000-01-01T00:00:00"}]},
        )
        monkeypatch.setattr(um, "_get_client", lambda: client)
        monkeypatch.setattr(um, "get_collection", lambda c, n: c.get_collection(n))
        with patch("memory.dualvec.delete_with_keys") as dwk:
            um.cleanup_old_memories(days=30)
        keys.delete.assert_not_called()
        assert dwk.call_args_list, "cleanup ต้องลบผ่านตัวกลางที่ cascade"
        assert all(c[0][1] != "memory_kwan__keys" for c in dwk.call_args_list)


class TestReconcile:
    """ตัวกวาดกำพร้า — safety net ตามแนวทาง reconciliation ของ Qdrant"""

    def _client(self, cols):
        client = SimpleNamespace(
            list_collections=lambda: [SimpleNamespace(name=n) for n in cols],
            get_collection=lambda name: SimpleNamespace(
                get=lambda: {"ids": list(cols[name])}),
        )
        return client

    def test_เจอกุญแจที่ไม่มีเจ้าของ(self):
        from scripts.reconcile_keys import find_orphans

        out = find_orphans(self._client({
            "memory_kwan": ["a", "b"], "memory_kwan__keys": ["a", "zombie"]}))
        assert out == {"memory_kwan__keys": ["zombie"]}

    def test_main_ที่ไม่มีกุญแจ_ไม่ใช่ปัญหา(self):
        """ทิศกลับกันเป็นสถานะปกติ — `key_text()` คืน None ได้"""
        from scripts.reconcile_keys import find_orphans

        assert find_orphans(self._client({
            "memory_kwan": ["a", "b", "c"], "memory_kwan__keys": ["a"]})) == {}

    def test_เงาที่ตัวหลักหายทั้งใบ_กำพร้าทั้งหมด(self):
        from scripts.reconcile_keys import find_orphans

        out = find_orphans(self._client({"memory_logic__keys": ["x", "y"]}))
        assert out == {"memory_logic__keys": ["x", "y"]}
