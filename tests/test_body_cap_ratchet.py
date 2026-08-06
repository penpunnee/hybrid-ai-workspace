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


def scan(root: pathlib.Path | None = None) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    """คืน (เส้นที่อ่านดิบ, เส้นที่มีเพดาน) เป็นเซตของ (METHOD, path)

    วิธีดู: หลังเจอ decorator ของ route แล้วไล่บรรทัดถัดไปจนเจอการอ่าน body ครั้งแรก
    ว่าเป็นแบบดิบหรือแบบมีเพดาน — เจอ decorator ตัวใหม่ก่อน = route นั้นไม่อ่าน body
    """
    raw: set[tuple[str, str]] = set()
    capped: set[tuple[str, str]] = set()
    for path in sorted((root or ROUTERS).glob("*.py")):
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


# ── baseline: เส้นที่ยังอ่าน body ดิบ (ลดได้ เพิ่มไม่ได้) ─────────────────────────
# 🎉 **ว่างแล้วตั้งแต่ 2026-08-06** — ปิดครบทั้ง 27 เส้น
# เพิ่มเข้ามาใหม่ได้เฉพาะเมื่อจงใจปล่อยดิบจริงๆ และต้องเขียนเหตุผลกำกับ
# (อย่าลืมอัปเดตตัวเลขใน CLAUDE.md หัวข้อ "B. เพดาน body" ให้ตรงด้วย)
KNOWN_RAW: set[tuple[str, str]] = set()


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


def test_สแกนแยก_raw_กับ_capped_ออกจากกันได้จริง(tmp_path):
    """ยิงตัวสแกนใส่ router สังเคราะห์ที่รู้คำตอบอยู่แล้ว

    ⚠️ **ห้ามผูกเทสนี้กับ endpoint จริงที่ 'ยังดิบ'** — พอปิดเพดานครบแล้วจะไม่เหลือ
    ตัวอย่างฝั่ง raw ให้ทดสอบเลย (เจอจริง 2026-08-06: เทสเดิมอิง /api/chat แล้วพังทันที
    ที่ปิดเพดานสำเร็จ = เทสที่ผ่านได้เฉพาะตอนโค้ดยังไม่ถูกแก้)
    """
    (tmp_path / "fake.py").write_text(
        'router = APIRouter(prefix="/x")\n'
        '@router.post("/raw")\n'
        "async def a(request: Request):\n"
        "    data = await request.json()\n"
        '@router.post("/capped")\n'
        "async def b(request: Request):\n"
        "    data = await json_body_capped(request, 1)\n"
        '@router.get("/nobody")\n'
        "def c():\n"
        "    return {}\n",
        encoding="utf-8",
    )
    raw, capped = scan(tmp_path)
    assert ("POST", "/x/raw") in raw and ("POST", "/x/raw") not in capped
    assert ("POST", "/x/capped") in capped and ("POST", "/x/capped") not in raw
    assert ("GET", "/x/nobody") not in raw | capped   # route ที่ไม่อ่าน body ต้องไม่ถูกนับ


def test_เส้นที่มีเพดานกับเส้นที่ดิบต้องไม่ทับกัน():
    raw, capped = scan()
    assert not (raw & capped), f"เส้นที่ถูกนับสองฝั่ง: {sorted(raw & capped)}"
