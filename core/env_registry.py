"""ทะเบียน env — ให้โค้ด "ตอบได้" ว่าตัวเองอ่านตัวแปรอะไรบ้าง

**ปัญหาที่แก้** — `.env.example` / `CLAUDE.md` / `docker-compose.yml` เขียนด้วยมือ
ทั้งหมด แล้วดริฟต์จากโค้ดเงียบๆ (วัด 2026-09-23: โค้ดอ่าน env 122 ชื่อ · **38 ตัว
ไม่ได้ถูกจดไว้ที่ไหนเลย**) · ตัวกันเดิม `test_env_docs_ratchet.py` จับได้แค่ทิศ
*เอกสาร → โค้ด* ⇒ ของใหม่ที่ไม่มีใครจดผ่านฉลุย

helper พวกนี้อ่าน env **แล้วจดไว้** — ปลายทางคือ generate `.env.example` จากโค้ด
(ก้อนถัดไป) แทนที่จะให้คนจำเอาเอง

🔑 **สองเรื่องที่ตั้งใจ *ไม่* ทำ:**
- **ไม่แปลงค่าให้ฉลาดกว่าเดิม** — `env_bool` ใช้กติกาเดิมเป๊ะ (`lower() == "true"`)
  ไม่รับ `1`/`yes` เพิ่ม เพราะ `.env` ที่มีอยู่เขียนตามกติกาเดิม การ "ปรับปรุง"
  ตอนย้ายท่อ = เปลี่ยนพฤติกรรมพร้อมกับ refactor แล้วแยกไม่ออกว่าอะไรพังเพราะอะไร
- **ไม่กลืน error** — ค่าที่พิมพ์ผิด (`OLLAMA_TIMEOUT=ล้าน`) ต้องดังเหมือน
  `int(os.getenv(...))` ของเดิม ไม่ใช่ถอยไปใช้ default เงียบๆ แล้วรันด้วยค่าที่
  ไม่มีใครตั้งใจ (ต่างจาก `_positive_env` ใน `utils/tts.py` ที่จงใจไม่ raise
  เพราะที่นั่น raise = `backend-watchdog` พาระบบเข้า crashloop เพราะปุ่มลำโพงตัวเดียว)
"""

from __future__ import annotations

import os
from dataclasses import dataclass

__all__ = [
    "BEGIN_MARKER",
    "END_MARKER",
    "REGISTRY",
    "EnvSpec",
    "env_bool",
    "env_float",
    "env_int",
    "env_str",
    "render_env_example",
]


@dataclass(frozen=True)
class EnvSpec:
    """สิ่งที่รู้เกี่ยวกับ env หนึ่งตัว — พอสำหรับเขียนบรรทัดใน `.env.example`"""

    name: str
    default: object
    kind: str  # "str" | "int" | "float" | "bool"
    doc: str
    group: str = ""


REGISTRY: dict[str, EnvSpec] = {}


def _register(spec: EnvSpec) -> None:
    """จดลงทะเบียน — ลงซ้ำด้วย *ค่าเดิม* ได้ (importlib.reload ทำแบบนั้นเป็นปกติ)
    แต่ลงซ้ำด้วย **default คนละค่า** ต้องดัง เพราะนั่นคือบั๊กที่เพิ่งไล่ปิดไปทั้งชุด
    (`LMSTUDIO_BASE_URL` 2 ค่า · `GEMINI_MODEL` 3 ค่า — 2026-09-23)
    """
    old = REGISTRY.get(spec.name)
    if old is not None and (old.default, old.kind) != (spec.default, spec.kind):
        raise ValueError(
            f"{spec.name} ถูกลงทะเบียนซ้ำด้วยค่าที่ไม่ตรงกัน: "
            f"{old.default!r} ({old.kind}) vs {spec.default!r} ({spec.kind}) — "
            "env หนึ่งตัวต้องมี default เดียวทั้งระบบ"
        )
    REGISTRY[spec.name] = spec


def env_str(name: str, default: str, *, doc: str, group: str = "") -> str:
    _register(EnvSpec(name, default, "str", doc, group))
    value = os.environ.get(name)
    return default if value is None else value


def env_int(name: str, default: int, *, doc: str, group: str = "") -> int:
    _register(EnvSpec(name, default, "int", doc, group))
    value = os.environ.get(name)
    return default if value is None else int(value)


def env_float(name: str, default: float, *, doc: str, group: str = "") -> float:
    _register(EnvSpec(name, default, "float", doc, group))
    value = os.environ.get(name)
    return default if value is None else float(value)


def env_bool(name: str, default: bool, *, doc: str, group: str = "") -> bool:
    """กติกาเดิมของโปรเจกต์: `"true"` (ไม่สนตัวพิมพ์) = จริง · อย่างอื่นทั้งหมด = เท็จ"""
    _register(EnvSpec(name, default, "bool", doc, group))
    value = os.environ.get(name)
    return default if value is None else value.lower() == "true"


# ── สร้าง .env.example จาก registry ──────────────────────────────────────────
# ปิดทิศ *โค้ด → เอกสาร*: เพิ่ม env ใน core/config.py แล้วไม่ regenerate = CI แดง
# (ตัวกันเดิม test_env_docs_ratchet.py ตรวจได้แค่ทิศตรงข้าม)

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BEGIN_MARKER = "# ══ ⬇️ ส่วนนี้สร้างอัตโนมัติจาก core/env_registry.py — ห้ามแก้ด้วยมือ ══"
END_MARKER = "# ══ ⬆️ จบส่วนที่สร้างอัตโนมัติ · ข้างล่างนี้เขียนมือ (env ที่ยังไม่เข้า registry) ══"

_HEADER = f"""{BEGIN_MARKER}
# แก้คำอธิบาย/ค่าตั้งต้นที่ `core/config.py` แล้วรัน:
#     python scripts/gen_env_example.py --write
# มีเทสเทียบไฟล์นี้กับ registry ทุกครั้ง (tests/test_env_example_generated.py)
"""


def _format_value(spec: EnvSpec) -> str:
    """เขียนค่าให้ `python-dotenv` อ่านกลับได้ตรงกติกาเดิมของโปรเจกต์

    ⚠️ bool ต้องเป็น `true`/`false` ตัวเล็ก ไม่ใช่ `True`/`False` ของ Python —
    กติกาคือ `lower() == "true"` ⇒ `False` ของ Python จะอ่านเป็นเท็จ "โดยบังเอิญ"
    ซึ่งถูกด้วยเหตุผลผิด แล้ววันหนึ่งที่กติกาเปลี่ยนจะพังแบบหาไม่เจอ
    """
    if spec.kind == "bool":
        return "true" if spec.default else "false"
    value = str(spec.default)
    # default ที่คำนวณจากตำแหน่งรีโป (NAS_DATA_PATH, READER_DB_PATH) → เขียนเป็น
    # path สัมพัทธ์ ไม่งั้นได้ /Users/... บนเครื่อง dev และ /app/... บน CI
    # ⇒ ไฟล์ที่ generate ไม่มีทางตรงกัน และคนที่ก๊อปไปใช้ได้ path ของเครื่องเรา
    if value.startswith(_REPO_ROOT + os.sep):
        value = "./" + value[len(_REPO_ROOT) + 1:]
    return value


def _render_entry(spec: EnvSpec) -> str:
    lines = [f"# {line}" if line.strip() else "#" for line in spec.doc.splitlines()]
    lines.append(f"{spec.name}={_format_value(spec)}")
    return "\n".join(lines)


def render_env_example(current: str = "") -> str:
    """คืนเนื้อไฟล์ `.env.example` ฉบับเต็ม

    `current` = เนื้อไฟล์ปัจจุบัน — ใช้เก็บ**ส่วนที่เขียนมือ**ใต้ `END_MARKER` ไว้ดิบๆ
    (env ที่ยังไม่เข้า registry ~95 ชื่อ ยังต้องพึ่งคนเขียน — ลบทิ้งเพื่อให้
    "generate ได้ทั้งไฟล์" = ทำเอกสารแย่ลงเพื่อให้เทสสวย)
    """
    groups: dict[str, list[EnvSpec]] = {}
    for spec in REGISTRY.values():
        groups.setdefault(spec.group or "อื่นๆ", []).append(spec)

    parts = [_HEADER]
    for group, specs in groups.items():
        parts.append(f"\n# ── {group} " + "─" * max(0, 74 - len(group)))
        parts += [_render_entry(s) for s in specs]
    parts.append("\n" + END_MARKER)

    manual = current.split(END_MARKER, 1)[1] if END_MARKER in current else (
        "\n\n" + current.strip() + "\n" if current.strip() else "\n"
    )
    return "\n".join(parts) + manual
