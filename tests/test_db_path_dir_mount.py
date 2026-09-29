"""chat_history.db ต้องอยู่ใน bind mount แบบ "โฟลเดอร์" ไม่ใช่ไฟล์เดี่ยว — ขั้น 2a (2026-09-29) ก่อนเปิด WAL

SQLite WAL สร้าง `<db>-wal` / `<db>-shm` ข้างไฟล์ DB (https://www.sqlite.org/wal.html) · ถ้า mount ไฟล์เดี่ยว
(`./data/chat_history.db:/app/chat_history.db`) ไฟล์พวกนั้นไปเกิดใน writable layer ของคอนเทนเนอร์ ⇒ recreate = `-wal`
ที่ยังไม่ checkpoint หาย · host เห็น DB แต่ไม่เห็น -wal (backup ด้วย cp จาก host = ได้ DB ไม่ครบ) · เปิดผ่าน 2 path =
"Swapping/Moving journal files" (https://www.sqlite.org/howtocorrupt.html)
`./data` mount ทั้งโฟลเดอร์ที่ `/app/data` อยู่แล้ว (reader.db ก็อยู่ที่นั่น) ⇒ ใช้ `DB_PATH=/app/data/chat_history.db` ไฟล์เดิมบน host
"""
import os
import posixpath

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _service():
    with open(os.path.join(ROOT, "docker-compose.yml"), encoding="utf-8") as f:
        return yaml.safe_load(f)["services"]["hybrid-ai"]


def _env(svc) -> dict:
    env = svc.get("environment") or {}
    if isinstance(env, list):
        return dict(e.split("=", 1) for e in env if "=" in e)
    return env


def _mounts(svc) -> list[tuple[str, str]]:
    """แยกจากขวา — ต้นทางมี `:` ได้ (`${NAS_DATA_PATH:-./data}`) · ตัด mode ท้าย (`:ro`) ถ้ามี"""
    out = []
    for v in svc.get("volumes") or []:
        host, container = v.rsplit(":", 1)
        if container in ("ro", "rw", "z", "Z"):
            host, container = host.rsplit(":", 1)
        out.append((host, container))
    return out


def test_ไม่มี_mount_ไฟล์เดี่ยวของ_chat_history_db():
    bad = [(h, c) for h, c in _mounts(_service()) if c.endswith("chat_history.db") or h.endswith("chat_history.db")]
    assert bad == [], f"mount ไฟล์เดี่ยว = -wal/-shm ไปเกิดใน writable layer ของคอนเทนเนอร์: {bad}"


def test_DB_PATH_อยู่ในโฟลเดอร์ที่_mount_ทั้งโฟลเดอร์():
    svc = _service()
    db_path = _env(svc).get("DB_PATH", "")
    assert db_path.endswith("/chat_history.db"), db_path
    folder = posixpath.dirname(db_path)
    targets = {c: h for h, c in _mounts(svc)}
    assert folder in targets, f"โฟลเดอร์ของ DB_PATH ({folder}) ต้องเป็นปลายทางของ bind mount — ไม่งั้นอยู่ใน writable layer"
    assert not os.path.splitext(targets[folder])[1], f"ต้นทางต้องเป็นโฟลเดอร์ ไม่ใช่ไฟล์: {targets[folder]}"


def test_กลุ่มควบคุม_ไฟล์บน_host_ยังเป็นตัวเดิม():
    """DB_PATH ใหม่ต้องชี้ไฟล์เดียวกับที่ mount ไฟล์เดี่ยวเดิมชี้ (./data/chat_history.db) — ไม่ใช่ DB เปล่าตัวใหม่"""
    svc = _service()
    db_path = _env(svc)["DB_PATH"]
    folder = posixpath.dirname(db_path)
    host_dir = {c: h for h, c in _mounts(svc)}[folder]
    assert host_dir in ("${NAS_DATA_PATH:-./data}", "./data"), host_dir
    assert posixpath.basename(db_path) == "chat_history.db"
