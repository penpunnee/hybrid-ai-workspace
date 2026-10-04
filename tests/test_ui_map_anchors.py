"""Ratchet: ตัวยึดใน `docs/ui-map.md` ฝั่ง overlay (`static/`) ต้องยังหาเจอในโค้ดจริง

🔴 ทำไมต้องมี — แผนที่ UI คือจุดเริ่มของ subagent `ui-investigator` · ถ้ามีคน rename
section ใน `enhanced.js` แล้วแผนที่ไม่ตาม subagent จะไล่ผิดที่โดยไม่มีอะไรเตือน

รูปแบบตัวยึด (ในแผนที่): `` `static/<ไฟล์> » <ข้อความที่ต้องเจอในไฟล์>` ``
ตัวยึดฝั่ง React (`a.ui/…`) อยู่คนละรีโป — เช็คด้วย vitest ใน `~/appscript.ui`
(`utils/uimap.test.ts` · รันใน pre-commit) ที่นี่เช็คแค่ `static/`

แก้เมื่อแดง: แก้แผนที่ให้ตรงโค้ด (อย่าลบแถวทิ้งเพื่อให้เขียว)
"""
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_MAP = _ROOT / "docs" / "ui-map.md"

_ANCHOR = re.compile(r"`(a\.ui|static)/([^`»]+?) » ([^`]+)`")


def _anchors(prefix: str) -> list[tuple[str, str]]:
    text = _MAP.read_text(encoding="utf-8")
    return [(f, needle) for p, f, needle in _ANCHOR.findall(text) if p == prefix]


def test_แผนที่มีตัวยึดทั้งสองฝั่ง():
    """regex พัง = เทสข้างล่างเขียวฟรี — ต้องเจอทั้ง static/ และ a.ui/ จริง"""
    assert len(_anchors("static")) >= 10, "ตัวยึด static/ น้อยผิดปกติ — regex หรือแผนที่พัง"
    assert len(_anchors("a.ui")) >= 10, "ตัวยึด a.ui/ น้อยผิดปกติ — regex หรือแผนที่พัง"


def test_ตัวยึด_static_ยังเจอในโค้ด():
    missing = []
    for f, needle in _anchors("static"):
        path = _ROOT / "static" / f
        if not path.is_file():
            missing.append(f"static/{f} (ไม่มีไฟล์)")
        elif needle not in path.read_text(encoding="utf-8"):
            missing.append(f"static/{f} » {needle}")
    assert not missing, "แผนที่ UI ไม่ตรงโค้ด — แก้ docs/ui-map.md:\n" + "\n".join(
        f"  {m}" for m in missing
    )
