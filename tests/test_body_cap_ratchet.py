"""Ratchet: ห้ามเพิ่ม endpoint ที่อ่าน body ดิบเข้ามาใหม่

`CLAUDE.md` เคยประกาศว่า "เพดาน body ครบทุกเส้นแล้ว" ทั้งที่ปิดไปแค่ 9 จาก 27 เส้น
(ดู PR #41) — ปัญหาไม่ใช่แค่เอกสารผิด แต่คือ**ไม่มีอะไรคอยนับให้** เลยไม่มีใครรู้ว่าเหลือเท่าไร

เทสนี้ตรึงรายชื่อเส้นที่ยังอ่านดิบไว้:
- **เพิ่มเส้นใหม่ที่อ่านดิบ → แดง** (นี่คือหน้าที่หลัก)
- **แก้เส้นในลิสต์ให้มีเพดานแล้ว → แดงเหมือนกัน** พร้อมบอกให้เอาออกจากลิสต์
  (บังคับให้ตัวเลขในเอกสารกับความจริงเดินไปพร้อมกัน ไม่ใช่ปล่อยให้ลิสต์เน่า)

⚠️ ตัวสแกนในไฟล์นี้ก็เป็นเครื่องมือวัด — มีเทสคุมมันเองอยู่ท้ายไฟล์
ถ้า regex พังแล้วคืนเซตว่าง `assert raw <= baseline` จะผ่านฟรีทันที
"""

import pathlib
import re

ROUTERS = pathlib.Path(__file__).resolve().parent.parent / "routers"

_ROUTE = re.compile(r'@router\.(post|put|patch|delete)\("([^"]*)"')
_PREFIX = re.compile(r'APIRouter\([^)]*prefix\s*=\s*"([^"]*)"', re.S)
_RAW = re.compile(r"await request\.json\(\)|await \w+\.read\(\)")
_CAPPED = re.compile(r"json_body_capped|read_capped")


def scan() -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    """คืน (เส้นที่อ่านดิบ, เส้นที่มีเพดาน) เป็นเซตของ (METHOD, path)

    วิธีดู: หลังเจอ decorator ของ route แล้วไล่บรรทัดถัดไปจนเจอการอ่าน body ครั้งแรก
    ว่าเป็นแบบดิบหรือแบบมีเพดาน — เจอ decorator ตัวใหม่ก่อน = route นั้นไม่อ่าน body
    """
    raw: set[tuple[str, str]] = set()
    capped: set[tuple[str, str]] = set()
    for path in sorted(ROUTERS.glob("*.py")):
        src = path.read_text(encoding="utf-8")
        m = _PREFIX.search(src)
        prefix = m.group(1) if m else ""
        current: tuple[str, str] | None = None
        for line in src.split("\n"):
            hit = _ROUTE.search(line)
            if hit:
                current = (hit.group(1).upper(), prefix + hit.group(2))
                continue
            if current is None:
                continue
            if _CAPPED.search(line):
                capped.add(current)
                current = None
            elif _RAW.search(line):
                raw.add(current)
                current = None
    return raw, capped


# ── baseline: เส้นที่ยังอ่าน body ดิบ ณ 2026-08-06 (ลดได้ เพิ่มไม่ได้) ────────────
# ปิดเส้นไหนได้แล้วให้ลบออกจากลิสต์นี้ + อัปเดตตัวเลขใน CLAUDE.md หัวข้อ "🟡 B. เพดาน body"
KNOWN_RAW: set[tuple[str, str]] = {
    ("POST", "/api/agent"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/chat"),            # ← เส้นที่โดนหนักสุด รับ image_b64 ด้วย
    ("POST", "/api/regenerate"),
    ("POST", "/api/dream"),
    ("POST", "/api/feedback"),
    ("POST", "/api/sandbox/python"),
    ("POST", "/api/fs/list"),
    ("POST", "/api/fs/read"),
    ("POST", "/api/fs/write"),
    ("POST", "/api/fs/search"),
    ("PATCH", "/api/sessions/{assistant}/{session_id}"),
    ("POST", "/api/pin/{db_id}"),
    ("POST", "/api/share"),
    ("POST", "/api/skills/extract"),
    ("POST", "/api/tts"),
    ("POST", "/api/tts/stream"),
    ("POST", "/api/admin/unlock"),
}


def test_ห้ามเพิ่ม_endpoint_ที่อ่าน_body_ดิบ():
    raw, _ = scan()
    added = raw - KNOWN_RAW
    assert not added, (
        f"เจอ endpoint ใหม่ที่อ่าน body ดิบ {len(added)} เส้น: {sorted(added)}\n"
        "→ ใช้ utils/http_limits.py (`json_body_capped()` / `read_capped()`) แทน\n"
        "   ถ้าจงใจปล่อยดิบจริงๆ ค่อยเพิ่มลง KNOWN_RAW พร้อมเหตุผล"
    )


def test_ลิสต์ต้องไม่ค้าง_ปิดเส้นไหนแล้วต้องเอาออก():
    raw, _ = scan()
    fixed = KNOWN_RAW - raw
    assert not fixed, (
        f"🎉 ปิดเพดานได้เพิ่ม {len(fixed)} เส้นแล้ว: {sorted(fixed)}\n"
        "→ ลบออกจาก KNOWN_RAW ในไฟล์นี้ และอัปเดตตัวเลขใน CLAUDE.md "
        'หัวข้อ "🟡 B. เพดาน body" ให้ตรง'
    )


# ── กลุ่มควบคุม: คุมตัวสแกนเอง ────────────────────────────────────────────────
# ถ้า regex พังแล้ว scan() คืนเซตว่าง เทสสองอันบนจะ "ผ่านฟรี" ทั้งคู่

def test_สแกนเจอ_route_จำนวนสมเหตุสมผล():
    raw, capped = scan()
    total = len(raw) + len(capped)
    assert total >= 20, f"สแกนเจอแค่ {total} เส้น — regex น่าจะพัง ไม่ใช่โค้ดเปลี่ยน"


def test_สแกนแยกเส้นที่มีเพดานออกได้จริง():
    """/api/documents/upload ใช้ read_capped() อยู่ — ต้องถูกจัดเป็น capped ไม่ใช่ raw"""
    raw, capped = scan()
    assert ("POST", "/api/documents/upload") in capped
    assert ("POST", "/api/documents/upload") not in raw


def test_สแกนแยกเส้นที่ยังดิบออกได้จริง():
    """/api/chat ยังใช้ await request.json() — ต้องถูกจัดเป็น raw"""
    raw, capped = scan()
    assert ("POST", "/api/chat") in raw
    assert ("POST", "/api/chat") not in capped


def test_เส้นที่มีเพดานกับเส้นที่ดิบต้องไม่ทับกัน():
    raw, capped = scan()
    assert not (raw & capped), f"เส้นที่ถูกนับสองฝั่ง: {sorted(raw & capped)}"
