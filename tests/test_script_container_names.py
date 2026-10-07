"""Ratchet: ชื่อคอนเทนเนอร์/service ในสคริปต์ต้องมีจริงใน `docker-compose.yml`

🔴 ทำไมต้องมี — `start-ai.ps1` สั่ง `docker restart hybrid-ai` อยู่นานโดยไม่มีใครรู้ว่าพัง
(`hybrid-ai` คือชื่อ *service* · คอนเทนเนอร์จริงชื่อ `ai-backend-1`) — เจอตอนทำผังระบบ 10-07

กติกา:
- `docker compose <คำสั่ง> … <ชื่อ>` → ชื่อต้องเป็น **service** ใน compose
- `docker restart|exec|logs|stop|start|kill|inspect … <ชื่อ>` → ชื่อต้องเป็น **container_name**
สแกน `*.sh` / `*.ps1` ที่รากรีโป + `scripts/`

แก้เมื่อแดง: แก้สคริปต์ให้ใช้ชื่อจริง (อย่าเปลี่ยนชื่อใน compose ให้เทสเขียว)
"""
import re
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parent.parent

# `docker` ต้องเป็นคำเดี่ยว (นำหน้าด้วยต้นบรรทัด/วรรค/`/` ของ full path/เครื่องหมายคำพูด)
_COMPOSE = re.compile(r"(?:^|[\s/\"'])docker\s+compose\s+[a-z]+((?:\s+-[\w-]+)*)\s+([A-Za-z0-9_][\w.-]*)")
_CONTAINER = re.compile(
    r"(?:^|[\s/\"'])docker\s+(?:restart|exec|logs|stop|start|kill|inspect)((?:\s+-[\w-]+)*)\s+([A-Za-z0-9_][\w.-]*)"
)


def _compose():
    return yaml.safe_load((_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))["services"]


def _scripts() -> list[Path]:
    out = []
    for pat in ("*.sh", "*.ps1"):
        out += sorted(_ROOT.glob(pat)) + sorted((_ROOT / "scripts").glob(pat))
    return out


def _refs(pattern: re.Pattern) -> list[tuple[str, str]]:
    refs = []
    for f in _scripts():
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.lstrip().startswith("#"):
                continue
            for m in pattern.finditer(line):
                refs.append((f.relative_to(_ROOT).as_posix(), m.group(2)))
    return refs


def test_กลุ่มควบคุม_หาคำสั่ง_docker_ในสคริปต์เจอ():
    """regex พัง/ย้ายไฟล์ = เทสข้างล่างเขียวฟรี"""
    assert len(_refs(_COMPOSE)) >= 3, "หา `docker compose … <service>` ในสคริปต์ไม่เจอ — regex พัง?"
    assert _refs(_CONTAINER), "หา `docker restart|exec|… <container>` ในสคริปต์ไม่เจอ — regex พัง?"
    assert "ai-backend-1" in {s.get("container_name") for s in _compose().values()}


def test_docker_compose_ใช้ชื่อ_service_ที่มีจริง():
    services = set(_compose())
    bad = [f"{f}: {n}" for f, n in _refs(_COMPOSE) if n not in services]
    assert not bad, f"service ไม่มีใน docker-compose.yml (มี {sorted(services)}):\n" + "\n".join(bad)


def test_docker_restart_exec_ใช้ชื่อคอนเทนเนอร์ที่มีจริง():
    names = {s["container_name"] for s in _compose().values() if "container_name" in s}
    bad = [f"{f}: {n}" for f, n in _refs(_CONTAINER) if n not in names]
    assert not bad, (
        f"ชื่อคอนเทนเนอร์ไม่มีใน docker-compose.yml (มี {sorted(names)} · "
        "ชื่อ service ใช้กับ `docker compose` เท่านั้น):\n" + "\n".join(bad)
    )
