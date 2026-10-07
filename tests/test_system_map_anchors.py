"""Ratchet: ผังทั้งระบบ `docs/system-map.md` ต้องตรงกับโค้ดจริง

🔴 ทำไมต้องมี — ผังคือที่ตอบ "อะไรต่อกับอะไร · ถ้า X ล่มอะไรพัง" · ถ้ามีคน rename ฟังก์ชัน
หรือเพิ่ม router/งานตั้งเวลา/collection ใหม่แล้วผังไม่ตาม ผังจะชี้ผิดโดยไม่มีอะไรเตือน

ตรวจ 2 แบบ:
1. **ตัวยึดยังอยู่** — `` `<path> » <ข้อความ>` `` (path นับจากรากรีโป) ต้องมีไฟล์ + grep ข้อความเจอ
   · ตัวยึด `a.ui/…` อยู่คนละรีโป → เช็คด้วย vitest ใน `~/appscript.ui` (`utils/uimap.test.ts`)
2. **ผังครบ** — ของที่ดึงจากโค้ดเอง (router ใน server.py · `@app.websocket` · id ของ `add_job`
   · service ใน compose · ชื่อ collection ที่เป็นสตริงคงที่) ต้องมีในผังทุกตัว

แก้เมื่อแดง: แก้ผังให้ตรงโค้ด (อย่าลบแถวทิ้งเพื่อให้เขียว)
"""
import ast
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_MAP = _ROOT / "docs" / "system-map.md"

# path = ASCII ล้วน (ไม่ใช้ `\w` — Python จับอักษรไทยด้วย แต่ JS ไม่จับ ⇒ สองรีโปนับไม่เท่ากัน)
# · ไม่บังคับนามสกุล (`Dockerfile`) · ต้องตรงกับ `SYSTEM_ANCHOR` ใน `a.ui/utils/uimap.test.ts`
_ANCHOR = re.compile(r"`((?:a\.ui/)?[A-Za-z0-9_.][A-Za-z0-9_./-]*) » ([^`]+)`")
# backtick ก้อนไหนมี `»` = ตั้งใจเป็นตัวยึด
_GUILLEMET_SPAN = re.compile(r"`[^`\n]*»[^`\n]*`")

_COLLECTION_CALLS = {"get_or_create_collection", "get_collection", "get_collection_noembed"}


def _map_text() -> str:
    return _MAP.read_text(encoding="utf-8")


def _anchors(*, react: bool) -> list[tuple[str, str]]:
    return [(f, n) for f, n in _ANCHOR.findall(_map_text()) if f.startswith("a.ui/") == react]


def _parse(rel: str) -> ast.Module:
    return ast.parse((_ROOT / rel).read_text(encoding="utf-8"))


def _call_name(node: ast.Call) -> str:
    f = node.func
    return f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")


# ── ดึงของจากโค้ด ────────────────────────────────────────────────────────

def _routers_in_server() -> list[str]:
    """โมดูลใน `app.include_router(<mod>.router)`"""
    out = []
    for node in ast.walk(_parse("server.py")):
        if isinstance(node, ast.Call) and _call_name(node) == "include_router" and node.args:
            arg = node.args[0]
            if isinstance(arg, ast.Attribute) and isinstance(arg.value, ast.Name):
                out.append(arg.value.id)
    return out


def _websocket_paths() -> list[str]:
    out = []
    for node in ast.walk(_parse("server.py")):
        if isinstance(node, ast.Call) and _call_name(node) == "websocket" and node.args:
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                out.append(arg.value)
    return out


def _scheduler_job_ids() -> list[str]:
    out = []
    for node in ast.walk(_parse("core/scheduler.py")):
        if isinstance(node, ast.Call) and _call_name(node) == "add_job":
            for kw in node.keywords:
                if kw.arg == "id" and isinstance(kw.value, ast.Constant):
                    out.append(kw.value.value)
    return out


def _compose_services() -> list[str]:
    import yaml
    data = yaml.safe_load((_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    return list(data["services"])


def _literal_collection_names() -> set[str]:
    """ชื่อ collection ที่เป็นสตริงคงที่ในโค้ด prod — รูปแบบที่ใช้จริง:
    `get_or_create_collection(client, "x")` · `collection_name="x"` · `COLLECTION_NAME = "x"` /
    `_COLLECTION = "x"` · `self.collection_name = "x"`"""
    names: set[str] = set()
    for pkg in ("utils", "memory", "routers", "reasoning", "agents", "core"):
        for py in (_ROOT / pkg).rglob("*.py"):
            for node in ast.walk(ast.parse(py.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Call):
                    if _call_name(node) in _COLLECTION_CALLS and len(node.args) >= 2:
                        a = node.args[1]
                        if isinstance(a, ast.Constant) and isinstance(a.value, str):
                            names.add(a.value)
                    for kw in node.keywords:
                        if kw.arg == "collection_name" and isinstance(kw.value, ast.Constant) \
                                and isinstance(kw.value.value, str):
                            names.add(kw.value.value)
                elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                        and isinstance(node.value.value, str):
                    for t in node.targets:
                        tname = t.attr if isinstance(t, ast.Attribute) else getattr(t, "id", "")
                        if tname.upper() in ("COLLECTION_NAME", "_COLLECTION"):
                            names.add(node.value.value)
    return names


# ── กลุ่มควบคุม (ตัวดึงพัง = เทสข้างล่างเขียวฟรี) ─────────────────────────

def test_กลุ่มควบคุม_ตัวยึดและของที่ดึงจากโค้ดไม่ว่าง():
    assert len(_anchors(react=False)) >= 60, "ตัวยึดฝั่งรีโปนี้น้อยผิดปกติ — regex หรือผังพัง"
    assert len(_anchors(react=True)) >= 5, "ตัวยึด a.ui/ น้อยผิดปกติ — regex หรือผังพัง"
    assert len(_routers_in_server()) >= 10
    assert _websocket_paths(), "ไม่เจอ @app.websocket ใน server.py — ตัวดึงพัง?"
    assert len(_scheduler_job_ids()) >= 3
    assert len(_compose_services()) >= 3
    assert {"obsidian_notes", "user_facts", "lessons"} <= _literal_collection_names(), \
        "ตัวดึงชื่อ collection หาชื่อที่รู้แน่ว่ามีไม่เจอ — รูปแบบในโค้ดเปลี่ยน?"


def test_backtick_ที่มี_guillemet_ต้องเป็นตัวยึดที่อ่านได้():
    """ตัวยึดเขียนผิดรูป (ไม่มีวรรครอบ `»` · path แปลก) จะไม่ถูก regex นับ ⇒ หลุดการตรวจเงียบๆ
    ทั้งที่กลุ่มควบคุมยังเขียว (ผู้ตรวจ 10-07 · ตอนเขียนเจอจริง `Dockerfile` ที่ regex เดิมบังคับนามสกุล)"""
    bad = [m.group(0) for m in _GUILLEMET_SPAN.finditer(_map_text()) if not _ANCHOR.fullmatch(m.group(0))]
    assert not bad, "backtick ที่มี » แต่ไม่ใช่ตัวยึดที่อ่านได้ — แก้รูปแบบใน docs/system-map.md:\n" + "\n".join(
        f"  {b}" for b in bad
    )


# ── 1. ตัวยึดยังอยู่ ──────────────────────────────────────────────────────

def test_ตัวยึดยังเจอในโค้ด():
    missing = []
    for f, needle in _anchors(react=False):
        path = _ROOT / f
        if not path.is_file():
            missing.append(f"{f} (ไม่มีไฟล์)")
        elif needle not in path.read_text(encoding="utf-8", errors="replace"):
            missing.append(f"{f} » {needle}")
    assert not missing, "ผังระบบไม่ตรงโค้ด — แก้ docs/system-map.md:\n" + "\n".join(
        f"  {m}" for m in missing
    )


# ── 2. ผังครบ ─────────────────────────────────────────────────────────────

def test_router_ทุกตัวใน_server_มีตัวยึดในผัง():
    text = _map_text()
    missing = [m for m in _routers_in_server() if f"`routers/{m}.py » " not in text]
    assert not missing, f"router ที่ server.py include แต่ผังไม่มีตัวยึด `routers/<ชื่อ>.py » …`: {missing}"


def test_websocket_ทุกเส้นอยู่ในผัง():
    text = _map_text()
    # เทียบส่วนคงที่ก่อน `{` — ผังเขียนพารามิเตอร์ย่อได้ (`{slug}` แทน `{assistant_slug}`)
    missing = [p for p in _websocket_paths() if p.split("{")[0] not in text]
    assert not missing, f"WebSocket ที่ไม่อยู่ในผัง: {missing}"


def test_งานตั้งเวลาทุก_id_อยู่ในผัง():
    text = _map_text()
    missing = [j for j in _scheduler_job_ids() if f"`{j}`" not in text and f'id="{j}"' not in text]
    assert not missing, f"id ของ add_job ที่ไม่อยู่ในผัง (ตารางงานตั้งเวลา): {missing}"


def test_service_ใน_compose_อยู่ในผัง():
    text = _map_text()
    missing = [s for s in _compose_services() if f"`{s}`" not in text]
    assert not missing, f"service ใน docker-compose.yml ที่ไม่อยู่ในผัง (ตารางคอนเทนเนอร์): {missing}"


def test_collection_ที่เป็นสตริงคงที่อยู่ในผัง():
    text = _map_text()
    missing = sorted(n for n in _literal_collection_names() if f"`{n}`" not in text)
    assert not missing, f"Chroma collection ที่ไม่อยู่ในผัง (ข้อ 6.1): {missing}"
