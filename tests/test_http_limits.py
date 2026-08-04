"""กันเพดานขนาด body **ก่อน** อ่านเข้า RAM — backlog ข้อ 5(ท้าย)

เดิมทุก endpoint ที่รับไฟล์ทำแบบเดียวกันหมด:

    raw = await file.read()          # ← อ่านทั้งก้อนเข้า RAM ก่อน
    if len(raw) > _MAX_BYTES:        # ← แล้วค่อยบอกว่าใหญ่เกิน
        raise HTTPException(413)

body 5 GB = กิน RAM 5 GB **ก่อน**จะถูกปฏิเสธ · `docker-compose` ไม่ได้ตั้ง mem limit
ให้ `ai-backend-1` → OOM ล้มทั้งคอนเทนเนอร์ ไม่ใช่แค่ request นั้น

รูเดียวกันถูกคัดลอกไป 5 จุด/4 endpoint (`upload` `search` `ocr` `summarize`)
— บทเรียนเดิมของโปรเจกต์: *pipeline ที่คัดลอกกันมาจะมีรูเหมือนกัน แก้เส้นเดียว
= ปิดรูครึ่งเดียว* (เจอมาแล้วกับ `websearch` / `agents/tools.py`)

⚠️ **`content-length` อย่างเดียวไม่พอ** — chunked transfer ไม่มี header นี้ และ client
โกหกได้ → ต้องมีเพดานตอนอ่านจริงด้วย เทสในไฟล์นี้จึงตรวจ **จำนวนไบต์ที่ถูกอ่านจริง**
ไม่ใช่แค่ว่าโยน 413 หรือเปล่า (โยน 413 หลังกิน RAM ไปแล้ว = ไม่ได้แก้อะไร)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi import HTTPException

from utils.http_limits import declared_too_large, read_capped

MAX = 1024  # เพดานเล็กๆ ให้เทสอ่านง่าย


class _FakeUpload:
    """เลียน `UploadFile` — จำว่าถูกขอไปแล้วกี่ไบต์ (นี่คือสิ่งที่เทสจริงๆ ตรวจ)"""

    def __init__(self, total: int, chunk_cap: int | None = None):
        self.total = total
        self.served = 0
        self.chunk_cap = chunk_cap

    async def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:            # อ่านทั้งก้อน — ท่าที่เราพยายามเลิกใช้
            size = self.total - self.served
        n = min(size, self.total - self.served)
        if self.chunk_cap is not None:
            n = min(n, self.chunk_cap)
        self.served += n
        return b"x" * n


class TestDeclaredTooLarge:
    def test_content_length_เกินเพดาน(self):
        assert declared_too_large({"content-length": str(5 * 1024**3)}, MAX) is True

    def test_content_length_พอดีเพดาน_ผ่าน(self):
        assert declared_too_large({"content-length": str(MAX)}, MAX) is False

    def test_ไม่มี_content_length_ต้องไม่ปฏิเสธ(self):
        """chunked transfer ไม่มี header นี้ — ปฏิเสธทิ้งเลยจะพังของที่ใช้งานได้จริง"""
        assert declared_too_large({}, MAX) is False

    def test_content_length_ขยะต้องไม่ระเบิด(self):
        for bad in ("", "abc", "-1", "9e99"):
            assert declared_too_large({"content-length": bad}, MAX) is False

    def test_header_ไม่สนตัวพิมพ์(self):
        assert declared_too_large({"Content-Length": str(MAX * 10)}, MAX) is True


class TestReadCapped:
    @pytest.mark.asyncio
    async def test_ไฟล์ใหญ่ต้องหยุดอ่านก่อนกิน_RAM(self):
        """หัวใจของข้อนี้ — ไม่ใช่แค่ 413 แต่ต้อง **ไม่เคยถือ** ไบต์ทั้งก้อนไว้

        ไฟล์ 100 MB เพดาน 1 KB → ต้องอ่านไปไม่เกินเพดาน + 1 chunk
        """
        up = _FakeUpload(total=100 * 1024 * 1024)
        with pytest.raises(HTTPException) as ei:
            await read_capped(up, MAX)
        assert ei.value.status_code == 413
        assert up.served <= MAX + 64 * 1024, (
            f"อ่านไปแล้ว {up.served} ไบต์ก่อนจะปฏิเสธ — ยังกิน RAM อยู่")

    @pytest.mark.asyncio
    async def test_ไฟล์เล็กได้ครบทุกไบต์(self):
        up = _FakeUpload(total=500)
        assert await read_capped(up, MAX) == b"x" * 500

    @pytest.mark.asyncio
    async def test_ขนาดพอดีเพดานต้องผ่าน(self):
        up = _FakeUpload(total=MAX)
        assert len(await read_capped(up, MAX)) == MAX

    @pytest.mark.asyncio
    async def test_เกินเพดานหนึ่งไบต์ต้องไม่ผ่าน(self):
        up = _FakeUpload(total=MAX + 1)
        with pytest.raises(HTTPException) as ei:
            await read_capped(up, MAX)
        assert ei.value.status_code == 413

    @pytest.mark.asyncio
    async def test_reader_ที่คืนทีละนิดต้องประกอบครบ(self):
        """`UploadFile.read(n)` ไม่รับประกันว่าจะคืนครบ n — ห้ามสรุปว่าคืนสั้น = จบไฟล์"""
        up = _FakeUpload(total=900, chunk_cap=7)
        assert len(await read_capped(up, MAX)) == 900
