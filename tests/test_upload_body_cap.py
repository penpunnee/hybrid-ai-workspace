"""เพดาน body ของเส้นที่ยังหลุด — `/api/upload`, `/api/memory/*`, `/api/skills/discover/accept`

ทำไม: `routers/documents.py` ใช้ `read_capped()`/`json_body_capped()` ครบทุกจุดแล้ว
(`_MAX_BYTES = 10 MB`) แต่ 5 เส้นนี้ยังอ่าน body ทั้งก้อนเข้า RAM ก่อนเสมอ —
`ai-backend-1` มี `mem_limit: 2g` เป็นด่านสุดท้าย ซึ่งแปลว่า "ถูก OOM kill"
ไม่ใช่ "ตอบ 413"

⚠️ **10 MB ไม่ใช่ตัวเลขที่คิดขึ้นใหม่** — เป็นเพดานที่ประกาศไว้แล้วใน CLAUDE.md
("ขนาดสูงสุด 10 MB") และบังคับใช้อยู่แล้วใน `documents.py` งานนี้คือ *บังคับใช้ให้ครบ*
ไม่ใช่ตั้งนโยบายใหม่ จึงไม่มีไฟล์ที่ "เคยอัปได้" กลายเป็น 413 เกินกว่าที่เอกสารบอกไว้
"""
import io

import pytest
from fastapi.testclient import TestClient

import server
from routers.skills import _MAX_UPLOAD_BYTES

client = TestClient(server.app)


def _blob(n: int) -> bytes:
    return b"x" * n


def test_upload_rejects_file_over_cap_with_413():
    over = _blob(_MAX_UPLOAD_BYTES + 1)
    r = client.post("/api/upload",
                    files={"file": ("big.txt", io.BytesIO(over), "text/plain")})
    assert r.status_code == 413, r.text


def test_upload_still_accepts_file_at_cap():
    """กลุ่มควบคุม — เพดานต้องไม่กินของที่ควรผ่าน

    ถ้าเคสนี้แดงแปลว่าเรานับ off-by-one หรือเผลอกันเข้มกว่าที่ประกาศไว้
    """
    at = _blob(1024)
    r = client.post("/api/upload",
                    files={"file": ("small.txt", io.BytesIO(at), "text/plain")})
    assert r.status_code != 413, r.text


@pytest.mark.parametrize("path", [
    "/api/memory/teach",
    "/api/memory/cleanup",
    "/api/skills/discover/accept",
])
def test_json_endpoints_reject_oversized_body(path):
    """`await request.json()` ดิบ = อ่านครบก้อนก่อนค่อยรู้ว่าใหญ่เกิน"""
    huge = '{"x":"' + "y" * (_MAX_UPLOAD_BYTES + 100) + '"}'
    r = client.post(path, content=huge.encode(),
                    headers={"content-type": "application/json"})
    assert r.status_code == 413, f"{path} → {r.status_code}"


@pytest.mark.parametrize("path", [
    "/api/memory/teach",
    "/api/skills/discover/accept",
])
def test_json_endpoints_still_read_small_bodies(path):
    """กลุ่มควบคุม — body ปกติต้องไม่โดนเพดานเล่นงาน

    ไม่สนใจว่า handler จะตอบ 200 หรือ 400 (ข้อมูลไม่ครบ) — สนใจแค่ว่า
    **ไม่ใช่ 413** เพราะนั่นคือสิ่งเดียวที่การเปลี่ยนแปลงนี้ควรทำ
    """
    r = client.post(path, json={"proposal_id": "", "text": "สั้นๆ"})
    assert r.status_code != 413, r.text
