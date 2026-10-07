"""Ratchet: เวลาสำรอง ChromaDB ที่เขียนไว้ในโค้ด/เอกสารต้องตรงของจริง (DSM task 00:00)

🔴 ทำไมต้องมี — DSM task `chroma-backup` รันจริง 00:00 (ปอยเปิด DSM ดู 10-07: รอบ 2026-10-07
00:00:01–00:00:30 สถานะ 0 · เก็บ 7 ไฟล์) แต่คอมเมนต์/เอกสารเขียนไว้ 3 แบบ (04:00 · 00:01)
ใครวางเวลางานใหม่ตามคอมเมนต์จะชนหรือเข้าใจลำดับผิด

ตรวจ: เวลา HH:MM ตัวแรกที่ตามหลังคำว่า chroma ภายใน 40 ตัวอักษร (บรรทัดเดียวกัน) ต้องเป็น 00:00
ขอบเขต: โค้ด/สคริปต์/`docs/reference`/`docs/system-map.md`/`CLAUDE.md` — **ไม่รวม** `docs/session-log/`
(ประวัติ เขียนตามที่รู้ตอนนั้น)

ถ้าย้ายเวลา DSM task จริง → แก้ `_ACTUAL` ที่นี่ + ทุกที่ที่เทสชี้
"""
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_ACTUAL = "00:00"
_CHROMA_TIME = re.compile(r"chroma[^\n]{0,40}?\b(\d{2}:\d{2})\b", re.IGNORECASE)


def _files() -> list[Path]:
    out = [_ROOT / "CLAUDE.md", _ROOT / "docs" / "system-map.md"]
    out += sorted((_ROOT / "docs" / "reference").glob("*.md"))
    for d in ("core", "utils", "scripts", "routers", "memory"):
        out += sorted(p for p in (_ROOT / d).rglob("*") if p.suffix in (".py", ".sh", ".ps1"))
    return [p for p in out if p.is_file()]


def _mentions() -> list[tuple[str, str, str]]:
    found = []
    for f in _files():
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            for m in _CHROMA_TIME.finditer(line):
                found.append((f.relative_to(_ROOT).as_posix(), m.group(1), line.strip()[:120]))
    return found


def test_กลุ่มควบคุม_เจอการเขียนเวลาสำรอง_chroma():
    """regex พัง/ข้อความถูกลบหมด = เทสข้างล่างเขียวฟรี"""
    assert len(_mentions()) >= 2, "หาเวลาสำรอง chroma ในโค้ด/เอกสารไม่เจอ — regex พัง?"


def test_เวลาสำรอง_chroma_ตรงของจริง():
    bad = [f"{f}: {t} ← {line}" for f, t, line in _mentions() if t != _ACTUAL]
    assert not bad, f"เวลาสำรอง ChromaDB ไม่ตรงของจริง ({_ACTUAL}):\n" + "\n".join(bad)
