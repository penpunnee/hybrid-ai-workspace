"""`get_memory_stats` ต้องไม่เปลี่ยน "อ่านไม่ได้" เป็น `0`

🔴 ของจริงบน prod 2026-09-02: `/api/health` รายงาน `documents: 0` ทั้งที่ collection
มี **1,740 chunk อยู่ครบ** และ `retrieve_chunks()` ทำงานปกติ

    WARNING utils.memory: failed to get count for collection 'documents':
      Embedding function conflict: new: ollama vs persisted: default
    → except: stats["collections"][name] = 0

เหตุ: wrapper `get_collection()` ฉีด embedding_function ของ ollama เข้าไป แต่
collection `documents` persist EF `default` ไว้ (มันฝัง vector เองด้วย `embed_texts()`
จึงไม่เคยต้องใช้ EF ของ collection) → Chroma ปฏิเสธตอน `get_collection`

🔑 **การนับไม่ต้องใช้ embedding function เลย** — นับผ่าน client ดิบคือตัวแก้ที่ต้นเหตุ
· และถ้ายังล้มด้วยเหตุอื่น ต้องแยก "ไม่รู้" ออกจาก "ศูนย์" ให้ขาด
คลาสเดียวกับบั๊ก `_google_search` ที่อ่าน 403 เป็น "0 ผลลัพธ์" (แก้ไปแล้ว `436f22b`)
และกับ vault `measuring-instruments-lie`
"""
import logging
from types import SimpleNamespace

import utils.memory as um


def _client(counts: dict, ef_hostile: set[str] = frozenset(), broken: dict = None):
    """client ปลอม · `ef_hostile` = collection ที่ **โยน error ถ้าถูกส่ง embedding_function**
    (จำลอง EF conflict ของ prod) · `broken` = collection ที่อ่านไม่ได้ไม่ว่าทางไหน"""
    broken = broken or {}

    def get_collection(name, **kwargs):
        if name in broken:
            raise RuntimeError(broken[name])
        if name in ef_hostile and "embedding_function" in kwargs:
            raise ValueError("Embedding function conflict: new: ollama vs persisted: default")
        return SimpleNamespace(count=lambda: counts[name])

    return SimpleNamespace(
        list_collections=lambda: [SimpleNamespace(name=n) for n in counts],
        get_collection=get_collection,
    )


def test_collection_ที่ชนกับ_EF_ต้องนับได้ตามปกติ(monkeypatch):
    """โหมดพังจริงของ prod — `documents` ต้องได้ 1740 ไม่ใช่ 0"""
    client = _client({"memory_kwan": 24, "documents": 1740}, ef_hostile={"documents"})
    monkeypatch.setattr(um, "_get_client", lambda: client)
    # บังคับให้ wrapper มี EF จริง (บน prod มี) เพื่อให้ conflict เกิดได้
    monkeypatch.setattr(um, "_get_embedding_function", lambda: object())

    s = um.get_memory_stats()
    assert s["collections"]["documents"] == 1740, s
    assert s["total"] == 1764


def test_อ่านไม่ได้จริง_ต้องไม่กลายเป็น_0(monkeypatch, caplog):
    """ถ้าอ่านไม่ได้ด้วยเหตุอื่น ห้ามรายงาน 0 — "ไม่รู้" ต้องไม่หน้าตาเหมือน "ว่าง" """
    client = _client({"memory_kwan": 24, "พัง": 0}, broken={"พัง": "chroma ล่ม"})
    monkeypatch.setattr(um, "_get_client", lambda: client)

    with caplog.at_level(logging.ERROR):
        s = um.get_memory_stats()
    assert "พัง" not in s["collections"], "อ่านไม่ได้แต่ยังโผล่ในรายการนับ"
    assert s["unreadable"]["พัง"], "ต้องบอกว่าอ่านไม่ได้ ไม่ใช่เงียบ"
    assert s["collections"]["memory_kwan"] == 24        # ตัวอื่นยังต้องนับได้
    assert s["total"] == 24
    assert any("พัง" in r.message for r in caplog.records if r.levelno >= logging.ERROR), \
        "ต้อง log ระดับ ERROR — WARNING ทำให้หายไปในกองบันทึก"


def test_ปกติแล้วไม่มี_unreadable(monkeypatch):
    """กลุ่มควบคุม — ไม่งั้นเทสข้างบนผ่านได้ด้วย dict ว่างตลอดเวลา"""
    client = _client({"memory_kwan": 24, "lessons": 8, "long_term_memory": 7})
    monkeypatch.setattr(um, "_get_client", lambda: client)

    s = um.get_memory_stats()
    assert s["unreadable"] == {}
    assert s["total"] == 39
    assert s["long_term"] == 7 and s["lessons"] == 8


def test_ไม่ฉีด_embedding_function_ตอนนับ(monkeypatch):
    """ตรึงตัวแก้ที่ต้นเหตุ: การนับไม่ต้องใช้ EF ⇒ ห้ามส่งไปเลย"""
    seen = []
    client = SimpleNamespace(
        list_collections=lambda: [SimpleNamespace(name="memory_kwan")],
        get_collection=lambda name, **kw: (seen.append(kw), SimpleNamespace(count=lambda: 1))[1],
    )
    monkeypatch.setattr(um, "_get_client", lambda: client)
    monkeypatch.setattr(um, "_get_embedding_function", lambda: object())
    um.get_memory_stats()
    assert seen and all("embedding_function" not in kw for kw in seen), seen
