"""`sync_vault` ต้องลบเอกสารของไฟล์ที่หายไปจาก vault ด้วย

🔴 บั๊กจริง 2026-08-23: sync เป็น add/update อย่างเดียว ⇒ ลบหน้าใน vault แล้ว
เอกสารเก่ายังค้างใน ChromaDB และ **ชนะอันดับ 1 ในการค้น semantic** (หน้าที่ถูกลบ
ได้ระยะ 0.276 ส่วนหน้าจริง 0.372) = ตอบคำถามจากเนื้อหาที่เจ้าของตั้งใจลบทิ้งไปแล้ว

🔑 ตัวชี้วัดโกหกด้วย: sync คืน `ok:true errors:0` ทั้งที่ index มี 88 เอกสาร
ขณะที่ไฟล์จริงมี 87 ⇒ ผลลัพธ์ sync พิสูจน์ความถูกต้องของ index ไม่ได้เลย
ต้องมี invariant "จำนวนเอกสารใน index == จำนวนไฟล์ที่สแกนได้"
"""
import pytest


class FakeCollection:
    """คอลเลกชันจำลอง — พอสำหรับเส้นทางที่ sync_vault ใช้จริง"""

    def __init__(self):
        self.docs: dict[str, dict] = {}
        self.deleted_calls: list[list[str]] = []

    def get(self, ids=None, **kwargs):
        if ids is None:
            keys = list(self.docs)
        else:
            keys = [i for i in ids if i in self.docs]
        return {"ids": keys, "metadatas": [self.docs[k] for k in keys]}

    def upsert(self, ids, documents, metadatas):
        for i, m in zip(ids, metadatas):
            self.docs[i] = m

    def delete(self, ids):
        self.deleted_calls.append(list(ids))
        for i in ids:
            self.docs.pop(i, None)

    def count(self):
        return len(self.docs)


@pytest.fixture()
def vault(tmp_path):
    (tmp_path / "a.md").write_text("# A\n\nเนื้อหา A\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("# B\n\nเนื้อหา B\n", encoding="utf-8")
    return tmp_path


@pytest.fixture()
def col(monkeypatch):
    import utils.obsidian_sync as mod

    c = FakeCollection()
    monkeypatch.setattr(mod, "_get_collection", lambda: c)
    return c


def test_control_first_sync_indexes_every_file(vault, col):
    from utils.obsidian_sync import sync_vault

    out = sync_vault(str(vault))
    assert out["ok"] and out["synced"] == 2
    assert col.count() == 2


def test_deleted_file_is_removed_from_the_index(vault, col):
    """🔴 หัวใจของบั๊ก — ลบไฟล์แล้ว sync ใหม่ เอกสารต้องหายตาม"""
    from utils.obsidian_sync import sync_vault

    sync_vault(str(vault))
    (vault / "b.md").unlink()
    out = sync_vault(str(vault))

    assert col.count() == 1, "เอกสารของไฟล์ที่ลบไปแล้วยังค้างใน index"
    assert out.get("removed") == 1, "ไม่รายงานว่าลบอะไรไป = เงียบหายแบบเดิม"
    paths = [m["path"] for m in col.docs.values()]
    assert all("b.md" not in p for p in paths)


def test_surviving_files_are_not_touched(vault, col):
    """กลุ่มควบคุม — prune ต้องไม่กวาดของที่ยังอยู่"""
    from utils.obsidian_sync import sync_vault

    sync_vault(str(vault))
    (vault / "b.md").unlink()
    sync_vault(str(vault))

    assert any("a.md" in m["path"] for m in col.docs.values())


def test_index_count_matches_scanned_files(vault, col):
    """invariant ที่จับบั๊กนี้ได้ตั้งแต่แรกถ้ามี — total ต้องเท่ากับจำนวนเอกสารใน index"""
    from utils.obsidian_sync import sync_vault

    sync_vault(str(vault))
    (vault / "b.md").unlink()
    (vault / "c.md").write_text("# C\n\nเนื้อหา C\n", encoding="utf-8")
    out = sync_vault(str(vault))

    assert col.count() == out["total"]


def test_empty_vault_must_not_wipe_the_index(vault, col):
    """🔴 กันหายนะ: mount หลุด / โฟลเดอร์ว่างชั่วคราว **ห้าม**ล้าง index ทั้งก้อน

    เคสนี้แยกจาก "ลบไฟล์จริง" ไม่ได้ด้วยข้อมูลที่มี ⇒ เลือกฝั่งที่กู้คืนได้
    (ปล่อยของเก่าค้างไว้ ยังลบทีหลังได้ · ล้างทิ้งแล้วต้อง re-embed ทั้ง vault)
    """
    from utils.obsidian_sync import sync_vault

    sync_vault(str(vault))
    for f in vault.glob("*.md"):
        f.unlink()
    out = sync_vault(str(vault))

    assert col.count() == 2, "vault ว่าง = สงสัยว่า mount หลุด ห้ามลบอะไรทั้งนั้น"
    assert out.get("removed", 0) == 0


def test_a_file_that_failed_to_embed_is_never_pruned(vault, col, monkeypatch):
    """🔴 กันหายนะข้อสอง: Ollama ดับ ⇒ upsert throw ทุกไฟล์

    ถ้า `seen` เก็บเฉพาะไฟล์ที่ upsert สำเร็จ → รอบที่ Ollama ดับจะมองว่าทุกไฟล์
    "หายไปจาก vault" แล้ว **ลบ index ทั้งก้อน** ทั้งที่ไฟล์อยู่ครบทุกไฟล์
    (เกิดจริงมาแล้ว 08-23: sync รอบแรกล้ม 5/5 เพราะ Ollama ต่อไม่ติด)
    """
    import utils.obsidian_sync as mod
    from utils.obsidian_sync import sync_vault

    sync_vault(str(vault))              # index ตั้งต้นครบ 2
    assert col.count() == 2

    def boom(*a, **k):
        raise RuntimeError("Failed to connect to Ollama")

    monkeypatch.setattr(col, "upsert", boom)
    for f in vault.glob("*.md"):        # แตะไฟล์ให้ mtime เปลี่ยน → บังคับ upsert
        f.write_text(f.read_text(encoding="utf-8") + "\nแก้\n", encoding="utf-8")

    out = sync_vault(str(vault))

    assert out["errors"] == 2 and not out["ok"]
    assert out["removed"] == 0, "embed ล้ม ≠ ไฟล์หาย — ห้าม prune"
    assert col.count() == 2, "ลบ index ทิ้งเพราะ Ollama ดับ = หายนะ"
    assert col.deleted_calls == []
    assert mod  # กัน import ไม่ถูกใช้


# ⚠️ เคยเขียนเทส "get() คืน id ไม่ครบ → ห้าม prune" แล้วลบทิ้ง (2026-08-23) —
# **มันผ่านแบบว่างเปล่า** เพราะทิศทางความเสี่ยงกลับด้านกับที่คิด:
#   stale = [i for i in col.get()["ids"] if i not in seen]
# get() ขาด ⇒ รายการ stale สั้นลง ⇒ **ลบน้อยลง** (ของเก่าค้าง = กู้ได้)
# ทิศที่อันตรายจริงคือ `seen` ขาด ซึ่งมีเทสคุมแล้วสองเคส (embed ล้ม · vault ว่าง)
# วัดบน prod 08-23: chromadb 1.5.9 · count()=87 · len(get()["ids"])=87 = ครบ


def test_prune_failure_must_not_pollute_the_error_count(vault, col, monkeypatch):
    """🔴 `errors` มีสัญญาว่า "จำนวนไฟล์ที่ upsert ล้ม" — ตรึงไว้ที่
    tests/test_vault_sync_errors.py (บั๊ก 2026-08-12 ที่ `skipped` โกหกว่าเขียว)

    รอบแรกของ prune บวก prune failure เข้า `errors` ⇒ **CI แดง 3 ตัว** เพราะ mock
    ในไฟล์นั้นคืน dict ที่ไม่มีคีย์ `ids` ⇒ ตัวเลขสองความหมายมารวมกัน = ตัวชี้วัด
    โกหกรอบใหม่ในโค้ดที่เขียนมาแก้ตัวชี้วัดโกหกพอดี
    """
    from utils.obsidian_sync import sync_vault

    sync_vault(str(vault))
    monkeypatch.setattr(col, "get", lambda ids=None, **k: {"metadatas": []})
    out = sync_vault(str(vault))

    assert out["errors"] == 0, "prune ล้มไม่ใช่ไฟล์ล้ม ห้ามปนกัน"
    assert out["removed"] == 0
