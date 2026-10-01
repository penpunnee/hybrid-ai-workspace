"""Ratchet: `CLAUDE.md` ต้องไม่โตจนกินโควตาทุกเซสชัน

🔴 ทำไมต้องมี — ไฟล์นี้ถูกฉีดเข้า context **ทันทีที่แตะไฟล์ใดก็ตามในรีโป**
(nested CLAUDE.md · เพดาน CLI 4 MB จึงไม่มีการตัดให้) · เคยโตถึง ~197 KB และ 103 KB
(2026-10-01) ทั้งที่กฎข้อ 4 ในไฟล์เองเตือนไว้แล้ว ⇒ คำเตือนอย่างเดียวไม่พอ ต้องมีอะไรแดง

แก้เมื่อแดง: ย้ายประวัติ/รายละเอียดลง `docs/reference/` หรือ `docs/session-log/devlog.md`
(ยกทั้งดุ้น ไม่แก้เนื้อ) แล้วเหลือบรรทัดชี้หนึ่งบรรทัด — **อย่าขยับเพดานขึ้น**
"""
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_CLAUDE_MD = _ROOT / "CLAUDE.md"

# ไบต์ (ไทย ~3 ไบต์/อักษร) · หลังย้ายรอบ 2026-10-01 เหลือ ~45 KB
_MAX_BYTES = 50_000

_LINK = re.compile(r"\]\(((?:docs|tests|scripts|skills)/[^)#\s]+|[A-Z][A-Za-z_]*\.md)\)")


def test_claude_md_ไม่เกินงบ():
    size = _CLAUDE_MD.stat().st_size
    assert size <= _MAX_BYTES, (
        f"CLAUDE.md {size:,} ไบต์ เกินงบ {_MAX_BYTES:,} — ย้ายรายละเอียดลง docs/ "
        "แล้วเหลือบรรทัดชี้ (ดู docstring)"
    )


def test_ลิงก์ใน_claude_md_ชี้ไฟล์ที่มีจริง():
    """ย้ายหัวข้อออกไปแล้ว ตัวชี้ที่เหลือต้องไม่เป็นลิงก์ตาย"""
    links = _LINK.findall(_CLAUDE_MD.read_text(encoding="utf-8"))
    assert len(links) >= 5, f"เจอลิงก์แค่ {len(links)} — regex พัง (เทสจะเขียวฟรี)"
    dead = sorted({l for l in links if not (_ROOT / l).exists()})
    assert not dead, "ลิงก์ตายใน CLAUDE.md:\n" + "\n".join(f"  {l}" for l in dead)
