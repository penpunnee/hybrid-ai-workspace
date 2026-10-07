"""skills_db.json ต้องอยู่ใน bind mount แบบ "โฟลเดอร์" ไม่ใช่ไฟล์เดี่ยว (ปอยเคาะ 2026-10-07 · devlog [ต่อ 146]–[148])

`_save_skills_db()` เขียนแบบ atomic = mkstemp ข้างไฟล์ แล้ว `os.replace` ทับ · ถ้า `/app/skills_db.json`
เป็น mount ไฟล์เดี่ยว rename ทับ mount point ไม่ได้ ⇒ `[Errno 16] Device or resource busy` ทุกครั้ง
(เจอจริงบน prod ตอน `clean_skills_db.py --resync --apply` · จำลองซ้ำด้วย Docker ใน
`tests/test_skills_db_mount_docker.py`) · `./data` mount ทั้งโฟลเดอร์ที่ `/app/data` อยู่แล้ว
⇒ ชี้ `SKILLS_DB_PATH` ไปใต้ `NAS_DATA_PATH` = ไฟล์เดิมบน host (inode เดียวกัน · ไม่ต้องย้ายข้อมูล)

`NAS_DATA_PATH` ต้อง pin ใน `environment:` ของ hybrid-ai — `environment:` ชนะ `env_file:` ·
ไม่ pin = วันไหนมีคนตั้ง `NAS_DATA_PATH` (path ฝั่ง host) ใน `.env` ค่านั้นไหลเข้าคอนเทนเนอร์
แล้ว path ของ cache DB/reader/skills_db ชี้ที่ที่ไม่มีอยู่ทั้งชุด
"""
import importlib.util
import os
import posixpath
import sys

import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ค่าจริงบน prod วัด 2026-10-07 ~21:20 (`docker exec ai-backend-1` · env NAS_DATA_PATH ไม่ได้ตั้ง)
# ⇒ pin แล้วต้องได้ path เดิมทุกตัว · ยกเว้น SKILLS_DB_PATH ที่ตั้งใจย้าย /app/skills_db.json → /app/data/
PROD_PATHS = {
    "NAS_DATA_PATH": "/app/data",
    "DB_PATH": "/app/data/chat_history.db",
    "SKILLS_DB_PATH": "/app/data/skills_db.json",
    "RESPONSE_CACHE_DB": "/app/data/response_cache.db",
    "EMBED_CACHE_DB": "/app/data/embed_cache.db",
    "READER_DB_DEFAULT": "/app/data/reader.db",
    "rc._DB_PATH": "/app/data/response_cache.db",
    "embed._CACHE_DB": "/app/data/embed_cache.db",
    "EXPORT_DIR": "/app/data/exports",
    "GEN_IMAGE_DIR": "/app/data/gen_images",
}


def _service():
    with open(os.path.join(ROOT, "docker-compose.yml"), encoding="utf-8") as f:
        return yaml.safe_load(f)["services"]["hybrid-ai"]


def _env(svc) -> dict:
    env = svc.get("environment") or {}
    if isinstance(env, list):
        return dict(e.split("=", 1) for e in env if "=" in e)
    return env


def _mounts(svc) -> list[tuple[str, str]]:
    out = []
    for v in svc.get("volumes") or []:
        host, container = v.rsplit(":", 1)
        if container in ("ro", "rw", "z", "Z"):
            host, container = host.rsplit(":", 1)
        out.append((host, container))
    return out


def _fresh(modname: str):
    """ประเมินไฟล์โมดูลใหม่โดยไม่แตะ sys.modules (แบบเดียวกับ test_env_registry._fresh_module)"""
    spec = importlib.util.spec_from_file_location(modname, os.path.join(ROOT, modname.replace(".", "/") + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def isolated_registry(monkeypatch):
    """ประเมิน config ใหม่ด้วย NAS_DATA_PATH=/app/data → default ของ READER_DB_PATH ฯลฯ ต่างจากที่
    import ไว้แล้ว (path ของเครื่องนี้) · REGISTRY เป็น global ที่ห้ามลงซ้ำด้วยค่าต่าง ⇒ ใช้ dict แยก
    ชั่วคราว (monkeypatch คืนตัวเดิมหลังเทส)"""
    from core import env_registry
    # import ทุกโมดูลเข้าตัวจริงก่อน — ไม่งั้นโมดูลที่ถูก import ครั้งแรกระหว่างเทสนี้ไปลงทะเบียนใน dict
    # ชั่วคราวแล้วหายไปพร้อมมัน (ค้างใน sys.modules ⇒ load_all รอบหน้าไม่ import ซ้ำ · test_env_registry แดง 9)
    env_registry.load_all()
    monkeypatch.setattr(env_registry, "REGISTRY", {})


def test_ไม่มี_mount_ไฟล์เดี่ยวของ_skills_db():
    bad = [(h, c) for h, c in _mounts(_service()) if "skills_db.json" in (posixpath.basename(h), posixpath.basename(c))]
    assert bad == [], f"mount ไฟล์เดี่ยว = os.replace ทับไม่ได้ (EBUSY): {bad}"


def test_NAS_DATA_PATH_pin_ใน_environment_และเป็นโฟลเดอร์ที่_mount():
    svc = _service()
    pinned = _env(svc).get("NAS_DATA_PATH")
    assert pinned == "/app/data", f"ต้อง pin NAS_DATA_PATH=/app/data ใน environment: (ชนะ env_file) — ได้ {pinned!r}"
    targets = {c: h for h, c in _mounts(svc)}
    assert pinned in targets, f"{pinned} ต้องเป็นปลายทางของ bind mount — ไม่งั้นข้อมูลอยู่ใน writable layer"
    assert targets[pinned] in ("${NAS_DATA_PATH:-./data}", "./data"), (
        f"ต้นทางต้องเป็นโฟลเดอร์ data เดิม (ไฟล์เดิมบน host) — ได้ {targets[pinned]}")


def test_path_ทุกไฟล์ภายใต้_env_ของ_compose_ตรงกับ_prod(monkeypatch, isolated_registry):
    """ใช้ env ของ compose (`environment:`) ประเมิน config + โมดูลที่คำนวณ path ใหม่ทั้งชุด
    ตัวที่ prod ไม่ได้ตั้ง (override ราย DB) ลบออกให้เหมือน prod"""
    env = _env(_service())
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    for k in ("RESPONSE_CACHE_DB", "EMBED_CACHE_DB", "READER_DB_PATH"):
        monkeypatch.delenv(k, raising=False)
    cfg = _fresh("core.config")
    monkeypatch.setitem(sys.modules, "core.config", cfg)
    rc, em = _fresh("utils.response_cache"), _fresh("utils.embed")
    fe, ig = _fresh("utils.file_export"), _fresh("utils.image_gen")
    got = {
        "NAS_DATA_PATH": cfg.NAS_DATA_PATH, "DB_PATH": cfg.DB_PATH, "SKILLS_DB_PATH": cfg.SKILLS_DB_PATH,
        "RESPONSE_CACHE_DB": cfg.RESPONSE_CACHE_DB, "EMBED_CACHE_DB": cfg.EMBED_CACHE_DB,
        "READER_DB_DEFAULT": cfg.READER_DB_DEFAULT,
        "rc._DB_PATH": rc._DB_PATH, "embed._CACHE_DB": em._CACHE_DB,
        "EXPORT_DIR": fe.EXPORT_DIR, "GEN_IMAGE_DIR": ig.GEN_IMAGE_DIR,
    }
    assert got == PROD_PATHS


def test_โฟลเดอร์ของ_SKILLS_DB_PATH_เป็นปลายทางของ_mount_โฟลเดอร์(monkeypatch, isolated_registry):
    svc = _service()
    for k, v in _env(svc).items():
        monkeypatch.setenv(k, v)
    cfg = _fresh("core.config")
    folder = posixpath.dirname(cfg.SKILLS_DB_PATH)
    targets = {c: h for h, c in _mounts(svc)}
    assert folder in targets, f"{cfg.SKILLS_DB_PATH}: โฟลเดอร์ต้องเป็นปลายทางของ bind mount"
    assert not os.path.splitext(targets[folder])[1], f"ต้นทางต้องเป็นโฟลเดอร์ ไม่ใช่ไฟล์: {targets[folder]}"
