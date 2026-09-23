"""env ชื่อเดียวกัน ถูกอ่านหลายที่ → default ต้องตรงกันทุกที่

**ทำไมต้องมีเทสนี้** — `test_env_docs_ratchet.py` ตรวจแค่ทิศ *เอกสาร → โค้ด*
(ชื่อที่เอกสารโฆษณา ต้องมีโค้ดอ่านจริง) และจับแค่ **ชื่อ** ไม่เคยแตะ **ค่า**
⇒ env ตัวเดียวกันมี default คนละค่าในคนละไฟล์ได้โดยไม่มีอะไรร้อง

ของจริงที่เจอตอนเขียนเทสนี้ (2026-09-23) — 6 ชื่อ 27 จุด:
- `LMSTUDIO_BASE_URL` 10 จุด · 6 จุดเป็น `""` (= opt-in ปิดอยู่ ตามที่ `CLAUDE.md` โฆษณา)
  แต่ `embed` / `query_rewrite` / `reflection` / `skill_discovery` default เป็น
  **IP เครื่อง PC `192.168.51.235:1234` ตรงๆ** ⇒ วันไหน `.env` ไม่มีคีย์นี้
  สี่ไฟล์นั้นจะยิงออกไปหา PC เงียบๆ แทนที่จะปิดตัวเอง
- `GEMINI_MODEL` 5 จุด ได้ 3 ค่า — หนึ่งในนั้นคือ `gemini-2.5-flash` ที่
  **ถูกปลดจากโปรเจกต์ปัจจุบันแล้ว (404)** และอยู่ใน `GEMINI_MODEL_SUNSET` ของ `utils/llm.py` เอง
  ⇒ รอดอยู่ได้เพราะ prod เซ็ต `.env` ทับไว้เท่านั้น = กับระเบิดที่รอวัน `.env` หาย

🔑 **เกณฑ์นี้ผูกกับ *คุณสมบัติ* ไม่ใช่ *รายชื่อ*** — ชื่อใหม่ที่ยังไม่มีใครคิดถึง
ก็ถูกคุมทันทีโดยไม่ต้องมาเติมลิสต์ (บทเรียน 09-01: ratchet ที่จับตามชื่อตัวแปร
มองไม่เห็น `DB_PATH` ตัวเอง)

**ขอบเขตที่เทสนี้ทำไม่ได้ (เขียนไว้กันเข้าใจผิดว่าปิดหมดแล้ว):**
- เทียบได้เฉพาะ default ที่เป็น **ค่าคงที่** หรือชื่อที่ชี้ไปค่าคงที่ระดับโมดูลในไฟล์เดียวกัน
  · default ที่คำนวณ (เช่น `utils/history.py` ที่ประกอบ path จาก `__file__`) เทียบไม่ได้
  ⇒ `DB_PATH` relative-vs-absolute ยังหลุดอยู่โดยตั้งใจ
- จุดที่ **ไม่ใส่ default เลย** ไม่นับเป็นความขัดแย้ง — เพราะ "ไม่ตั้งค่า" เป็นเจตนาที่ต่าง
  จาก "ตั้งเป็นค่าว่าง" จริงๆ (เช่น `reasoning/router.py` แนบ Authorization เฉพาะเมื่อ
  ผู้ใช้ตั้งคีย์เอง) — ใครจะใช้ช่องนี้หนีเกณฑ์ก็ทำได้ แต่ต้องตั้งใจทำ
"""

from __future__ import annotations

import ast
import pathlib
from collections import defaultdict

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent

# โฟลเดอร์โค้ดที่ deploy จริง — ไม่รวม tests/ scripts/ legacy/ ด้วยเหตุผลเดียวกับ
# ratchet ตัวเดิม: ของในนั้นไม่ได้รันบน prod และ fixture จะทำให้ผลเพี้ยน
PROD_DIRS = ("core", "routers", "utils", "memory", "reasoning", "agents", "assistants")

# ข้อยกเว้น: ชื่อ env → เหตุผลที่ยอมให้ default ต่างกัน
# ว่างไว้ตั้งใจ — ถ้าจะเติม ต้องเขียนเหตุผลที่อ่านแล้วรู้ว่า "ต่างกันแล้วดีกว่า" ยังไง
_ALLOWED_MISMATCH: dict[str, str] = {}


def _prod_files() -> list[pathlib.Path]:
    files = [p for d in PROD_DIRS for p in (REPO / d).rglob("*.py")]
    files.append(REPO / "server.py")
    return [p for p in files if "__pycache__" not in p.parts]


def _module_constants(tree: ast.Module) -> dict[str, object]:
    """ค่าคงที่ระดับโมดูลในไฟล์เดียวกัน — ใช้คลี่ default ที่เขียนเป็นชื่อ

    เช่น `utils/llm.py`: `GEMINI_MODEL_DEFAULT = "gemini-3.5-flash"` แล้ว
    `os.getenv("GEMINI_MODEL", GEMINI_MODEL_DEFAULT)` — ถ้าไม่คลี่ จุดนี้จะถูกมองข้าม
    ทั้งที่เป็นจุดที่ค่า *ถูกต้องที่สุด* ในบรรดาทั้งหมด
    """
    out: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = node.value.value
    return out


def _is_env_read(call: ast.Call) -> bool:
    func = call.func
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr == "getenv" and isinstance(func.value, ast.Name) and func.value.id == "os":
        return True
    # os.environ.get("X", "default")
    return (
        func.attr == "get"
        and isinstance(func.value, ast.Attribute)
        and func.value.attr == "environ"
    )


def scan_env_defaults(files: list[pathlib.Path] | None = None,
                      sources: dict[str, str] | None = None) -> dict[str, set[tuple[str, str]]]:
    """คืน {ชื่อ env: {(repr(default), "file:line")}} เฉพาะจุดที่ระบุ default เป็นค่าคงที่

    รับ `sources` ได้ด้วยเพื่อให้เทส "เครื่องมือวัดมีตา" ป้อนโค้ดปลอมเข้ามาตรวจได้
    โดยไม่ต้องเขียนไฟล์จริง
    """
    pairs: list[tuple[str, str]] = []
    if sources is not None:
        pairs = list(sources.items())
    else:
        for path in files or _prod_files():
            pairs.append((str(path.relative_to(REPO)), path.read_text()))

    found: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for label, src in pairs:
        tree = ast.parse(src)
        consts = _module_constants(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not _is_env_read(node):
                continue
            if not node.args or not isinstance(node.args[0], ast.Constant):
                continue
            name = node.args[0].value
            if not isinstance(name, str) or len(node.args) < 2:
                continue  # ไม่ใส่ default = ไม่นำมาเทียบ (ดู docstring)
            default = node.args[1]
            if isinstance(default, ast.Constant):
                value = default.value
            elif isinstance(default, ast.Name) and default.id in consts:
                value = consts[default.id]
            else:
                continue  # default ที่คำนวณ — เทียบไม่ได้
            found[name].add((repr(value), f"{label}:{node.lineno}"))
    return found


def _conflicts(found: dict[str, set[tuple[str, str]]]) -> dict[str, set[tuple[str, str]]]:
    return {
        name: sites
        for name, sites in found.items()
        if len({default for default, _ in sites}) > 1 and name not in _ALLOWED_MISMATCH
    }


def test_env_เดียวกันต้องมี_default_เดียวกันทุกไฟล์():
    conflicts = _conflicts(scan_env_defaults())
    if conflicts:
        report = []
        for name, sites in sorted(conflicts.items()):
            report.append(f"  {name}:")
            report += [f"    {default:<40} {loc}" for default, loc in sorted(sites)]
        pytest.fail(
            "env ที่ default ไม่ตรงกัน (แก้ให้ทุกจุดอ่านค่าเดียวกัน "
            "เช่น import จาก core/config.py):\n" + "\n".join(report)
        )


def test_เครื่องมือวัดมีตาจริง():
    """กันเคสที่สแกนเนอร์พังแล้วเทสข้างบนเขียวฟรี

    เคยเจอมาแล้วทั้งโปรเจกต์: regex ที่ไม่ match รายงาน "ผ่าน" ครบ
    """
    found = scan_env_defaults()
    assert len(found) > 40, f"สแกนเนอร์อ่าน env ได้แค่ {len(found)} ชื่อ — น่าจะพัง"
    # ต้องเห็นไฟล์ที่รู้แน่ว่ายังอ่าน env ดิบอยู่
    # (ไม่ใช้ `core/config.py` เป็นตัวอ้าง — ตั้งแต่ 2026-09-23 มันอ่านผ่าน
    #  `core/env_registry.py` แล้ว จึงไม่มี `os.getenv` ให้สแกนเนอร์ตัวนี้เห็นอีก
    #  ซึ่งถูกต้องตามดีไซน์ ไม่ใช่อาการพัง)
    files_seen = {loc.split(":")[0] for sites in found.values() for _, loc in sites}
    assert "utils/llm.py" in files_seen
    assert "utils/embed.py" in files_seen


def test_สแกนเนอร์จับความขัดแย้งที่ปลูกไว้ได้():
    """กลุ่มควบคุม: ป้อนโค้ดที่ขัดกันจริง แล้วต้องจับได้ — ทั้งแบบค่าคงที่ตรงๆ
    และแบบที่ default เขียนเป็นชื่อค่าคงที่ระดับโมดูล (เคส `GEMINI_MODEL` ของจริง)"""
    sources = {
        "fake_a.py": 'import os\nX = os.getenv("FAKE_ENV", "หนึ่ง")\n',
        "fake_b.py": 'import os\nFAKE_DEFAULT = "สอง"\nY = os.getenv("FAKE_ENV", FAKE_DEFAULT)\n',
    }
    conflicts = _conflicts(scan_env_defaults(sources=sources))
    assert "FAKE_ENV" in conflicts, "สแกนเนอร์มองไม่เห็นความขัดแย้งที่ปลูกไว้"
    assert {d for d, _ in conflicts["FAKE_ENV"]} == {repr("หนึ่ง"), repr("สอง")}


def test_default_ที่ตรงกันอยู่แล้วต้องไม่ถูกรายงานว่าขัดกัน():
    """กลุ่มควบคุมด้านกลับ — กันเทสที่ 'แดงตลอด' ซึ่งก็ไร้ประโยชน์พอกัน"""
    sources = {
        "fake_a.py": 'import os\nX = os.getenv("FAKE_OK", "เท่ากัน")\n',
        "fake_b.py": 'import os\nY = os.getenv("FAKE_OK", "เท่ากัน")\n',
        # จุดที่ไม่ใส่ default เลย ต้องไม่ถูกนับเป็นความขัดแย้ง
        "fake_c.py": 'import os\nZ = os.getenv("FAKE_OK")\n',
    }
    assert _conflicts(scan_env_defaults(sources=sources)) == {}


@pytest.mark.parametrize("name", sorted(_ALLOWED_MISMATCH))
def test_ข้อยกเว้นต้องยังจำเป็นอยู่(name):
    """ถ้าความขัดแย้งถูกแก้ไปแล้ว ต้องถอดชื่อออกจากลิสต์ ไม่ใช่ปล่อยค้าง"""
    sites = scan_env_defaults().get(name, set())
    assert len({d for d, _ in sites}) > 1, (
        f"{name} ไม่ได้ขัดกันแล้ว — ถอดออกจาก _ALLOWED_MISMATCH ได้"
    )
