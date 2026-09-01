"""Ratchet: env ที่เอกสารโฆษณา ต้องมีโค้ดอ่านจริง

🔴 ทำไมต้องมี — เจอจริง 2026-09-01: `OLLAMA_EMBED_MODEL` /
`LMSTUDIO_EMBED_MODEL` อยู่ในเอกสารมาหลายเดือน **โดยไม่มีบรรทัดไหนในโค้ดอ่านเลย**
(ตัวจริงคือ `EMBEDDING_MODEL` ตัวเดียว ดู `utils/embed.py`) ⇒ คนตั้งค่าตามเอกสาร
แล้วค่าไม่มีผลอะไร **แต่ไม่มีอะไรแดง** — ต้องไปเจอเอาตอนไล่บั๊กอย่างอื่น

🔑 ผูกกับ **คุณสมบัติ** ไม่ใช่รายชื่อ (บทเรียน `508aa08`): ตัวกันที่ไล่เช็ค
"ห้ามมี 2 ชื่อนี้" กันได้แค่ผีสองตัวที่รู้จักแล้ว

⚠️ **ขอบเขตที่จับได้จริง — อย่าเชื่อว่าปิดหมด:** เฉพาะบรรทัดทรง `NAME=` ที่อยู่ใน
บล็อก ```env ของไฟล์ใน `_DOC_FILES` เท่านั้น · **จับ "การกล่าวถึงในเนื้อความ" ไม่ได้**
ซึ่งเป็นรูปแบบที่บั๊กครึ่งหนึ่งของ 2026-09-01 เป็น (`CLAUDE.md:165` อธิบายทิศ fallback
ผิดโดยอ้างชื่อ env ผีในประโยค)
- ลองขยายไปจับชื่อทรง env ใน backtick ทั้งไฟล์แล้ว: ได้ 20 ตัว **~18 เป็น false alarm**
  เพราะค่าคงที่ใน python ใช้ naming เดียวกัน (`AI_PALETTE`, `VOICE_MAP`, `WORKLET_SRC`)
  และมันไปจับ **บรรทัด backlog ที่อธิบายการลบผีเอง** ⇒ ทางนั้นปิดไม่ได้ด้วยตัวสแกน
- เกณฑ์ "มีโค้ดอ่าน = ไม่ใช่ผี" **ยังอ่อนไป** — env ที่ถูก pin ไว้ใน compose ก็มีโค้ดอ่าน
  แต่ตั้งใน `.env` ไม่มีผล ⇒ คุมด้วย `test_env_ที่_compose_ทับ_ต้องบอกไว้ในเอกสาร`
"""
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent

# เอกสารที่ "สัญญากับคนอ่านว่าตั้งค่านี้แล้วมีผล"
_DOC_FILES = [
    "CLAUDE.md",
    "skills/env-variables-reference.md",
    ".env.example",
]

# ดิรที่เป็นโค้ด **ที่รันบน prod** เท่านั้น
# ⛔ ห้ามใส่ `tests`/`scripts` — วัดจริง 2026-09-01: ใส่ `TTS_LIVE_TEST=1` ลงบล็อก env
# ของ `CLAUDE.md` แล้วเทสเขียว เพราะมี `tests/test_tts_model.py` เรียก `getenv` มัน
# ⇒ เอกสารสัญญาค่าที่ prod ไม่เคยอ่าน โดย ratchet ปล่อยผ่านแบบเงียบ
# (ตรวจแล้วตัดออกไม่เกิด false alarm: read set 127 → 123, ไม่มี env ในเอกสารตัวไหนหลุด)
_CODE_DIRS = ["core", "routers", "utils", "memory", "reasoning",
              "agents", "assistants"]

# ชื่อที่ "ไม่มีโค้ด python อ่าน" ได้อย่างถูกต้อง — ต้องมีเหตุผลกำกับเสมอ
_ALLOWED_UNREAD: dict[str, str] = {
    # ใส่ตัวใหม่ที่นี่พร้อมเหตุผล เช่น "compose อ่านเอง" / "ตั้งให้เครื่องมือภายนอก"
}

_ASSIGN = re.compile(r"^([A-Z][A-Z0-9_]{2,})=")
_READ = re.compile(r"""(?:getenv\(|environ\.get\(|environ\[)\s*["']([A-Z0-9_]+)""")
_COMPOSE_VAR = re.compile(r"\$\{([A-Z0-9_]+)")


def _env_names_in_docs() -> dict[str, list[str]]:
    """ชื่อ env ที่เอกสารโฆษณา → รายการที่มา (path:line)

    นับเฉพาะบรรทัดใน fenced block ```env เท่านั้น (`.env.example` ทั้งไฟล์
    ถือเป็น env block) — กัน false positive จากบรรทัด shell แบบ `FOO=bar cmd`
    """
    found: dict[str, list[str]] = {}
    for rel in _DOC_FILES:
        path = _ROOT / rel
        assert path.exists(), f"เอกสารที่ ratchet คุมหายไป: {rel}"
        in_block = path.name == ".env.example"
        for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = raw.lstrip(">").strip()
            if line.startswith("```"):
                in_block = line.startswith("```env")
                continue
            if not in_block:
                continue
            m = _ASSIGN.match(line)
            if m:
                found.setdefault(m.group(1), []).append(f"{rel}:{lineno}")
    return found


def _env_names_read_by_code() -> set[str]:
    names: set[str] = set()
    for d in _CODE_DIRS:
        for py in (_ROOT / d).rglob("*.py"):
            names |= set(_READ.findall(py.read_text(encoding="utf-8", errors="ignore")))
    names |= set(_READ.findall((_ROOT / "server.py").read_text(encoding="utf-8")))
    for yml in _ROOT.glob("*.yml"):
        names |= set(_COMPOSE_VAR.findall(yml.read_text(encoding="utf-8", errors="ignore")))
    return names


def test_เอกสารต้องไม่โฆษณา_env_ที่ไม่มีโค้ดอ่าน():
    declared = _env_names_in_docs()
    read = _env_names_read_by_code()
    ghosts = {
        name: where for name, where in sorted(declared.items())
        if name not in read and name not in _ALLOWED_UNREAD
    }
    assert not ghosts, (
        "env ผี — เอกสารบอกให้ตั้ง แต่ไม่มีโค้ดไหนอ่านเลย:\n"
        + "\n".join(f"  {n}  ← {', '.join(w)}" for n, w in ghosts.items())
        + "\n\nแก้: ลบออกจากเอกสาร หรือถ้าถูกอ่านโดยเครื่องมือนอก python "
          "ให้ใส่ใน _ALLOWED_UNREAD พร้อมเหตุผล"
    )


def test_เครื่องมือวัดมีตาจริง():
    """กลุ่มควบคุม — ถ้าตัวสแกนอ่านอะไรไม่เจอ เทสข้างบนจะเขียวฟรี"""
    declared = _env_names_in_docs()
    read = _env_names_read_by_code()
    assert len(declared) > 40, f"อ่านชื่อจากเอกสารได้แค่ {len(declared)} — สแกนเนอร์พัง"
    assert len(read) > 40, f"อ่านชื่อจากโค้ดได้แค่ {len(read)} — สแกนเนอร์พัง"
    # ตัวจริงที่ต้องเห็นทั้งสองฝั่ง — ถ้าหายแปลว่า regex/รายการดิรพัง
    assert "EMBEDDING_MODEL" in read
    assert "GEMINI_MODEL" in declared


@pytest.mark.parametrize("name", sorted(_ALLOWED_UNREAD))
def test_ข้อยกเว้นต้องยังจำเป็นอยู่(name):
    """ถ้าวันหนึ่งมีโค้ดมาอ่านจริง = ข้อยกเว้นหมดอายุ ให้ถอดออก"""
    assert name not in _env_names_read_by_code(), (
        f"{name} มีโค้ดอ่านแล้ว — ถอดออกจาก _ALLOWED_UNREAD ได้"
    )


# ── compose ทับ env_file ────────────────────────────────────────────────────
_COMPOSE_MARKER = "docker-compose"


def _compose_pinned() -> set[str]:
    """ชื่อ env ที่ `docker-compose.yml` กำหนดใน `environment:` (ทับ `env_file:` เสมอ)"""
    names: set[str] = set()
    in_env = False
    for raw in (_ROOT / "docker-compose.yml").read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if stripped.startswith("environment:"):
            in_env = True
            continue
        if in_env:
            m = re.match(r"^-\s*([A-Z][A-Z0-9_]*)=", stripped)
            if m:
                names.add(m.group(1))
                continue
            if stripped and not stripped.startswith("#"):
                in_env = False
    return names


def test_env_ที่_compose_ทับ_ต้องบอกไว้ในเอกสาร():
    """🔴 วัดบน prod 2026-09-01: `.env` ไม่มี `LOG_FILE` เลย แต่คอนเทนเนอร์มี
    `/app/logs/server.log` — มาจาก `environment:` ของ compose ซึ่ง**ทับ `env_file:`**
    ส่วน `CLAUDE.md` เขียน `LOG_FILE=server.log` ชวนให้ตั้ง แล้วมันไม่มีผล

    ความสับสนนี้เกิดขึ้นแล้วจริง — `MEMORY.md` มีบรรทัดเตือนว่า prod อยู่ที่
    `/app/logs/server.log` "ไม่ใช่ `/app/server.log` ที่ว่างเปล่าและหลอกตา"

    เกณฑ์: ถ้าเอกสารจะประกาศชื่อพวกนี้ ต้องมีคำว่า `docker-compose` ในบรรทัดเดียวกัน
    """
    pinned = _compose_pinned()
    assert pinned, "อ่าน environment: จาก docker-compose.yml ไม่ได้เลย — ตัวสแกนพัง"

    bad: list[str] = []
    for rel in _DOC_FILES:
        path = _ROOT / rel
        in_block = path.name == ".env.example"
        for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = raw.lstrip(">").strip()
            if line.startswith("```"):
                in_block = line.startswith("```env")
                continue
            if not in_block:
                continue
            m = _ASSIGN.match(line)
            if m and m.group(1) in pinned and _COMPOSE_MARKER not in line:
                bad.append(f"  {m.group(1)}  ← {rel}:{lineno}")
    assert not bad, (
        "env พวกนี้ถูก pin ใน `environment:` ของ docker-compose ⇒ ตั้งใน `.env` **ไม่มีผล** "
        "แต่เอกสารประกาศไว้เฉยๆ เหมือนตั้งได้:\n" + "\n".join(bad)
        + f"\n\nแก้: เติมหมายเหตุที่มีคำว่า '{_COMPOSE_MARKER}' ในบรรทัดนั้น"
    )
