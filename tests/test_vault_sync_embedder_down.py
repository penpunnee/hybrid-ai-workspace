"""vault sync ตอน embedder (Ollama บน PC .235) ต่อไม่ได้ ต้องจบเร็ว ไม่ใช่ 22 นาที (2026-09-23)

**หลักฐาน (log prod 09-23):** error ห่างกัน ~60 วิเป๊ะต่อไฟล์ · รอบ 3 errors = 180 วิ ·
รอบ 22 errors = **22 นาที** · ถูกสั่งซ้ำ 8 รอบ 02:17–04:59 ล้มทุกรอบ
**ต้นเหตุ (วัดในคอนเทนเนอร์):** `OllamaEmbeddingFunction` ของ chromadb 1.5.9 ตั้ง
`timeout=60` · PC ที่เพิ่งปิด ARP ยังค้าง ⇒ SYN หายเงียบ ⇒ `httpx.ConnectTimeout: timed out`
หลังรอครบ timeout (จำลองด้วย 10.255.255.1: timeout=8 → 8.01 วิ) · chromadb เติม " in upsert."
· ส่วน IP ที่ไม่เคยมีเครื่อง ล้มเร็ว 0.99 วิ (ไม่มี ARP) — จึงไม่ใช่ทุกกรณีที่ช้า

**ไม่ลด timeout 60 วิทั้งระบบ** — EF ตัวนี้ใช้ร่วมทุก collection · embed ปกติเร็ว (โน้ตใหญ่สุด
52K ตัวอักษร 0.17 วิ) แต่ไม่มีหลักฐานเรื่อง batch ใหญ่ของเส้นอื่น ⇒ แก้เฉพาะ vault sync:
1. preflight TCP ไป embedder ของ collection นั้นจริง ก่อน upsert ไฟล์แรก
2. ต่อไม่ได้ 2 ครั้งติด → หยุด upsert (ครั้งเดียวแล้วหาย = ไปต่อ · `test_partial_failure_still_ok_false`)
3. หยุดแล้ว**ยังตรวจไฟล์ที่เหลือแบบอ่านอย่างเดียว** ⇒ `errors` = ไฟล์ที่ต้อง sync แต่ไม่สำเร็จ
   (สัญญาเดิมของ `test_vault_sync_errors.py`) และ `seen` ครบ ⇒ prune ไม่ลบของที่ยังไม่ได้ตรวจ
"""
import time
from types import SimpleNamespace

import pytest

import utils.obsidian_sync as ov


class _Col:
    """collection ปลอมที่มี `_embedding_function.url` แบบของจริงบน prod"""

    def __init__(self, url="http://192.168.51.235:11434", upsert_exc=None, docs=None):
        self._embedding_function = SimpleNamespace(url=url)
        self.docs = dict(docs or {})
        self.upsert_calls = 0
        self._exc = upsert_exc
        self.deleted: list[str] = []

    def get(self, ids=None, **kw):
        keys = list(self.docs) if ids is None else [i for i in ids if i in self.docs]
        return {"ids": keys, "metadatas": [self.docs[k] for k in keys]}

    def upsert(self, ids, documents, metadatas):
        self.upsert_calls += 1
        if self._exc is not None:
            raise self._exc
        for i, m in zip(ids, metadatas):
            self.docs[i] = m

    def delete(self, ids):
        self.deleted += list(ids)
        for i in ids:
            self.docs.pop(i, None)


def _vault(tmp_path, n):
    for i in range(n):
        (tmp_path / f"n{i}.md").write_text(f"# N{i}\nเนื้อหา", encoding="utf-8")
    return str(tmp_path)


@pytest.fixture
def reach(monkeypatch):
    """ควบคุมผล preflight + จดว่าถูกถามกี่ครั้ง/ไปที่ไหน"""
    state = {"ok": True, "calls": []}

    def fake(host, port, timeout):
        state["calls"].append((host, port))
        return state["ok"]

    monkeypatch.setattr(ov, "_tcp_reachable", fake)
    return state


# ── 1) preflight ─────────────────────────────────────────────────────────────

def test_embedder_ต่อไม่ได้_ไม่เรียก_upsert_เลย(monkeypatch, tmp_path, reach):
    reach["ok"] = False
    col = _Col()
    monkeypatch.setattr(ov, "_get_collection", lambda: col)
    res = ov.sync_vault(_vault(tmp_path, 3))
    assert col.upsert_calls == 0, "ต่อ embedder ไม่ได้ ไม่ควรรอ timeout 60 วิทีละไฟล์"
    assert reach["calls"] == [("192.168.51.235", 11434)], "ต้องถาม embedder ของ collection นั้นจริง ครั้งเดียว"
    assert res["ok"] is False and res["errors"] == 3 and res["synced"] == 0
    assert "embedder" in res["error"] and "192.168.51.235" in res["error"]


def test_ไฟล์ไม่เปลี่ยนเลย_ไม่ต้องถาม_embedder(monkeypatch, tmp_path, reach):
    """กลุ่มควบคุม — sync ที่ไม่มีอะไรต้อง embed ต้องผ่านแม้ PC ปิด"""
    reach["ok"] = False
    vault = _vault(tmp_path, 2)
    docs = {ov._doc_id(f): {"mtime": str(f.stat().st_mtime)} for f in tmp_path.rglob("*.md")}
    col = _Col(docs=docs)
    monkeypatch.setattr(ov, "_get_collection", lambda: col)
    res = ov.sync_vault(vault)
    assert reach["calls"] == [] and res["ok"] is True and res["skipped"] == 2


def test_collection_ไม่มี_url_ข้าม_preflight(monkeypatch, tmp_path, reach):
    """EF แบบอื่น (ไม่มี url) — ไม่รู้ว่าจะไปถามที่ไหน ต้องไม่บล็อก"""
    col = _Col()
    col._embedding_function = SimpleNamespace()
    monkeypatch.setattr(ov, "_get_collection", lambda: col)
    res = ov.sync_vault(_vault(tmp_path, 2))
    assert reach["calls"] == [] and res["synced"] == 2 and res["ok"] is True


# ── 2) circuit breaker ───────────────────────────────────────────────────────

def test_ต่อไม่ได้สองครั้งติด_หยุด_upsert_แต่ยังนับไฟล์ที่เหลือเป็น_error(monkeypatch, tmp_path, reach):
    col = _Col(upsert_exc=Exception("timed out in upsert."))
    monkeypatch.setattr(ov, "_get_collection", lambda: col)
    res = ov.sync_vault(_vault(tmp_path, 5))
    assert col.upsert_calls == 2, f"ควรหยุดหลังล้ม 2 ครั้งติด ได้ {col.upsert_calls}"
    assert res["errors"] == 5 and res["ok"] is False
    assert "หยุด" in res["error"]


def test_error_ที่ไม่ใช่เรื่องต่อไม่ได้_ไม่หยุด(monkeypatch, tmp_path, reach):
    """กลุ่มควบคุม — ไฟล์เสียเป็นรายไฟล์ (เช่น ค่าผิด) ต้องลองไฟล์อื่นต่อ"""
    col = _Col(upsert_exc=ValueError("metadata ผิด"))
    monkeypatch.setattr(ov, "_get_collection", lambda: col)
    res = ov.sync_vault(_vault(tmp_path, 4))
    assert col.upsert_calls == 4 and res["errors"] == 4


# ── 3) หยุดกลางทางต้องไม่ทำ prune ลบของที่ยังไม่ได้ตรวจ ──────────────────────────

def test_หยุดกลางทางแล้ว_prune_ไม่ลบไฟล์ที่ยังมีอยู่(monkeypatch, tmp_path, reach):
    vault = _vault(tmp_path, 4)
    # index มีเวอร์ชันเก่าของทุกไฟล์ (mtime ไม่ตรง) + เอกสารของไฟล์ที่ถูกลบไปแล้ว 1 ตัว
    docs = {ov._doc_id(f): {"mtime": "เก่า"} for f in tmp_path.rglob("*.md")}
    docs["ลบแล้ว.md"] = {"mtime": "เก่า"}
    col = _Col(upsert_exc=Exception("timed out"), docs=docs)
    monkeypatch.setattr(ov, "_get_collection", lambda: col)
    ov.sync_vault(vault)
    assert col.deleted == ["ลบแล้ว.md"], f"prune ต้องลบแค่ของที่ไม่มีไฟล์แล้ว ได้ {col.deleted}"


# ── 4) ตัววัดเครือข่ายจริง ────────────────────────────────────────────────────

def test_tcp_reachable_คืน_False_เร็วเมื่อ_SYN_หายเงียบ():
    """10.255.255.1 = route ไปไม่ถึง/ไม่มีใครตอบ (จำลอง PC ที่เพิ่งปิด)"""
    t = time.monotonic()
    assert ov._tcp_reachable("10.255.255.1", 11434, timeout=0.5) is False
    assert time.monotonic() - t < 2.0


def test_ล้มสลับสำเร็จ_ไม่นับสะสมจนหยุด(monkeypatch, tmp_path, reach):
    """breaker นับ "ติดกัน" — สำเร็จคั่นกลางต้องเริ่มนับใหม่ (mutation V7 รอดมาก่อน)"""
    col = _Col()
    n = {"i": 0}

    def flaky(ids, documents, metadatas):
        n["i"] += 1
        col.upsert_calls += 1
        if n["i"] % 2 == 1:
            raise Exception("timed out in upsert.")

    col.upsert = flaky
    monkeypatch.setattr(ov, "_get_collection", lambda: col)
    res = ov.sync_vault(_vault(tmp_path, 5))
    assert col.upsert_calls == 5, f"ไม่ควรหยุด (ไม่เคยล้มติดกัน) ได้ {col.upsert_calls}"
    assert "halted" not in res and res["errors"] == 3 and res["synced"] == 2


def test_preflight_ถามครั้งเดียวต่อรอบ(monkeypatch, tmp_path, reach):
    """ไม่ใช่ทุกไฟล์ — ไม่งั้นเสีย TCP connect เพิ่มทุกไฟล์ที่ต้อง embed (mutation V8)"""
    col = _Col()
    monkeypatch.setattr(ov, "_get_collection", lambda: col)
    res = ov.sync_vault(_vault(tmp_path, 4))
    assert res["synced"] == 4 and len(reach["calls"]) == 1
