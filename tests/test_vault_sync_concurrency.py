"""vault sync สองรอบต้องไม่ทำงานซ้อนกัน (2026-09-23)

**หลักฐาน:** log prod 09-23 มี sync ซ้อนกันจริง — `req_adcddef0` เริ่ม ~04:30:45 (1,201 วิ) และ
`req_8ce23e37` เริ่ม ~04:37:52 (1,321 วิ) · ปุ่มบนหน้าเว็บ disable ระหว่าง sync อยู่แล้ว
(`app.tsx:1617`) ⇒ การซ้อนมาจากคนละแท็บ/คนละเครื่อง/curl · แอปมี uvicorn process เดียว
(ตรวจ `/proc` ในคอนเทนเนอร์: PID 1 ตัวเดียว) ⇒ `threading.Lock` พอ

**ความเสียหายที่เกิดได้:** รอบ A สแกนรายชื่อไฟล์ตอนเริ่ม → ระหว่างนั้นมีโน้ตใหม่ + รอบ B sync
โน้ตนั้นเข้า index → A จบแล้ว prune: เอกสารของโน้ตใหม่ไม่อยู่ใน `seen` ของ A ⇒ **ลบทิ้ง**

**เลือก "รอคิว" ไม่ใช่ "ปฏิเสธ"** — ผู้เรียกทาง curl หลัง push vault ต้องการให้การแก้ของตัวเอง
ถูก sync · ปฏิเสธ = การแก้ที่ A สแกนไม่ทันหายไปจนกว่าจะมีคนกดใหม่ · รอเกินเพดาน = ตอบ busy
"""
import threading
import time
from types import SimpleNamespace

import utils.obsidian_sync as ov


class _Col:
    """collection ปลอมแบบ thread-safe · upsert ของไฟล์ชื่อ `gate` จะรอ event ได้"""

    def __init__(self):
        self._embedding_function = SimpleNamespace()   # ไม่มี url = ข้าม preflight
        self.docs: dict[str, dict] = {}
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.gate_ids: set[str] = set()
        self.gate_entered = threading.Event()
        self.gate_release = threading.Event()

    def get(self, ids=None, **kw):
        with self.lock:
            keys = list(self.docs) if ids is None else [i for i in ids if i in self.docs]
            return {"ids": keys, "metadatas": [self.docs[k] for k in keys]}

    def upsert(self, ids, documents, metadatas):
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if ids[0] in self.gate_ids:
                self.gate_entered.set()
                assert self.gate_release.wait(5), "gate ไม่ถูกปล่อย"
            with self.lock:
                for i, m in zip(ids, metadatas):
                    self.docs[i] = m
        finally:
            with self.lock:
                self.active -= 1

    def delete(self, ids):
        with self.lock:
            for i in ids:
                self.docs.pop(i, None)


def test_prune_ของรอบแรกต้องไม่ลบโน้ตใหม่ที่รอบที่สอง_sync(monkeypatch, tmp_path):
    (tmp_path / "old.md").write_text("# เก่า\nx", encoding="utf-8")
    col = _Col()
    col.gate_ids = {ov._doc_id(tmp_path / "old.md")}
    monkeypatch.setattr(ov, "_get_collection", lambda: col)

    a = threading.Thread(target=ov.sync_vault, args=(str(tmp_path),))
    a.start()
    assert col.gate_entered.wait(5), "รอบ A ไม่ถึงจุด upsert"

    new = tmp_path / "new.md"                      # โน้ตใหม่ระหว่างที่ A ยังทำงาน
    new.write_text("# ใหม่\ny", encoding="utf-8")
    b = threading.Thread(target=ov.sync_vault, args=(str(tmp_path),))
    b.start()
    time.sleep(0.3)                                # ให้ B มีโอกาสทำงานซ้อน (ถ้าไม่มีตัวกัน)
    col.gate_release.set()
    a.join(5)
    b.join(5)

    assert ov._doc_id(new) in col.docs, "prune ของรอบแรกลบโน้ตใหม่ที่รอบที่สองเพิ่ง sync"
    assert col.max_active == 1, f"upsert ทำงานซ้อนกัน {col.max_active} ตัว"


def test_รอคิวเกินเพดาน_ตอบ_busy_ไม่แตะ_index(monkeypatch, tmp_path):
    (tmp_path / "a.md").write_text("# A\nx", encoding="utf-8")
    col = _Col()
    monkeypatch.setattr(ov, "_get_collection", lambda: col)
    monkeypatch.setattr(ov, "_SYNC_WAIT_TIMEOUT", 0.2)
    assert ov._sync_lock.acquire(timeout=1)       # จำลองรอบที่กำลังทำงานอยู่
    try:
        t = time.monotonic()
        res = ov.sync_vault(str(tmp_path))
        took = time.monotonic() - t
    finally:
        ov._sync_lock.release()
    assert res["ok"] is False and res.get("busy") is True
    assert "กำลัง sync" in res["error"]
    assert col.docs == {} and took < 1.0


def test_lock_ถูกปล่อยแม้_sync_โยน_exception(monkeypatch, tmp_path):
    """ไม่งั้น sync ล้มครั้งเดียว = ทุกรอบหลังจากนั้นตอบ busy ตลอดอายุโปรเซส"""
    (tmp_path / "a.md").write_text("# A\nx", encoding="utf-8")

    def boom():
        raise RuntimeError("chroma พัง")

    monkeypatch.setattr(ov, "_get_collection", boom)
    try:
        ov.sync_vault(str(tmp_path))
    except RuntimeError:
        pass
    assert ov._sync_lock.acquire(timeout=0.1), "lock ค้างหลัง exception"
    ov._sync_lock.release()


def test_รอบเดียว_ทำงานตามปกติ(monkeypatch, tmp_path):
    """กลุ่มควบคุม — ไม่มีใครถือ lock ต้องไม่ช้าลง/ไม่ busy"""
    (tmp_path / "a.md").write_text("# A\nx", encoding="utf-8")
    col = _Col()
    monkeypatch.setattr(ov, "_get_collection", lambda: col)
    res = ov.sync_vault(str(tmp_path))
    assert res["ok"] is True and res["synced"] == 1 and "busy" not in res
