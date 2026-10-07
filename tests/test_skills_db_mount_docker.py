"""จำลอง bind mount จริง (kernel) ด้วย Docker — ยืนยันว่า skills_db.json เขียนได้จริงหลังย้ายไป mount โฟลเดอร์

เทสโครงสร้าง (`test_skills_db_dir_mount.py`) ตรวจแค่ compose/config · ไฟล์นี้รัน `_save_skills_db()` ตัวจริง
ในอิมเมจที่ build จาก Dockerfile เดียวกับ prod (`hybrid-ai:ci`) กับ mount แบบเดียวกับ compose:
- กลุ่มควบคุม: mount ไฟล์เดี่ยว ⇒ ต้องได้ `[Errno 16] Device or resource busy` เหมือน prod 2026-10-07
  (พิสูจน์ว่าตัวจำลองนี้จับ bug ได้จริง)
- ตัวจริง: env ตาม `environment:` ของ compose + mount `data/` ทั้งโฟลเดอร์ · `SKILLS_DB_PATH` มาจาก config
  ไม่ override ⇒ ไฟล์บน host ต้องเปลี่ยน

⛔ ห้ามรันในคอนเทนเนอร์ prod · ข้ามเองเมื่อไม่มี docker หรือไม่มีอิมเมจ (CI รัน pytest ในอิมเมจ = ไม่มี docker ⇒ ข้าม)
build อิมเมจเอง: `docker buildx build -t hybrid-ai:ci --load .`
"""
import json
import os
import shutil
import subprocess

import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGE = os.environ.get("SKILLS_DB_DOCKER_IMAGE", "hybrid-ai:ci")

PROBE = """
import json, os, sys
sys.path.insert(0, "/app")
import utils.skills as s
if os.environ.get("FORCE_PATH"):
    s.SKILLS_DB_PATH = os.environ["FORCE_PATH"]
try:
    s._save_skills_db({"written": {"summary": "by-probe"}})
    print(json.dumps({"ok": True, "path": s.SKILLS_DB_PATH}))
except Exception as e:
    print(json.dumps({"ok": False, "path": s.SKILLS_DB_PATH, "err": str(e)}))
"""


def _docker_ready() -> str | None:
    if not shutil.which("docker"):
        return "ไม่มี docker CLI"
    try:
        r = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, timeout=20)
    except Exception as e:  # daemon ไม่ตอบ
        return f"docker ใช้ไม่ได้: {e}"
    return None if r.returncode == 0 else f"ไม่มีอิมเมจ {IMAGE}"


pytestmark = pytest.mark.skipif(_docker_ready() is not None, reason=str(_docker_ready()))


def _compose_env() -> dict:
    with open(os.path.join(ROOT, "docker-compose.yml"), encoding="utf-8") as f:
        env = yaml.safe_load(f)["services"]["hybrid-ai"].get("environment") or {}
    return dict(e.split("=", 1) for e in env) if isinstance(env, list) else dict(env)


def _run(tmp_path, mounts: list[str], env: dict) -> dict:
    probe = tmp_path / "probe.py"
    probe.write_text(PROBE, encoding="utf-8")
    cmd = ["docker", "run", "--rm", "--network", "none", "--entrypoint", "python",
           "-v", f"{ROOT}/utils:/app/utils:ro", "-v", f"{ROOT}/core:/app/core:ro",
           "-v", f"{probe}:/probe.py:ro"]
    for m in mounts:
        cmd += ["-v", m]
    for k, v in {**env, "LOG_FILE": "/tmp/probe.log"}.items():
        cmd += ["-e", f"{k}={v}"]
    r = subprocess.run(cmd + [IMAGE, "/probe.py"], capture_output=True, text=True, timeout=120)
    last = [ln for ln in r.stdout.splitlines() if ln.startswith("{")]
    assert last, f"probe ไม่พิมพ์ผล — stdout={r.stdout[-500:]!r} stderr={r.stderr[-800:]!r}"
    return json.loads(last[-1])


def _seed(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    db = data / "skills_db.json"
    db.write_text(json.dumps({"seed": {"summary": "เดิม"}}), encoding="utf-8")
    return data, db


def test_กลุ่มควบคุม_mount_ไฟล์เดี่ยว_ได้_EBUSY(tmp_path):
    data, db = _seed(tmp_path)
    res = _run(tmp_path, [f"{db}:/app/x/skills_db.json"], {"FORCE_PATH": "/app/x/skills_db.json"})
    assert res["ok"] is False and "Errno 16" in res["err"], res
    assert json.loads(db.read_text(encoding="utf-8")) == {"seed": {"summary": "เดิม"}}, "ไฟล์เดิมต้องไม่ถูกแตะ"


def test_env_ของ_compose_กับ_mount_โฟลเดอร์_เขียนลงไฟล์บน_host_ได้(tmp_path):
    data, db = _seed(tmp_path)
    res = _run(tmp_path, [f"{data}:/app/data"], _compose_env())
    assert res["ok"] is True, res
    assert res["path"] == "/app/data/skills_db.json", res
    assert json.loads(db.read_text(encoding="utf-8")) == {"written": {"summary": "by-probe"}}, "host ต้องเห็นของใหม่"
