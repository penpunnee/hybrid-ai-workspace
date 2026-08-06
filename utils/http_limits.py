"""เพดานขนาด request body — ปฏิเสธ **ก่อน** อ่านเข้า RAM

ที่มา: ทุก endpoint ที่รับไฟล์เขียนแบบเดียวกันหมด `raw = await file.read()` แล้วค่อย
`if len(raw) > _MAX_BYTES` → body 5 GB กิน RAM 5 GB ก่อนจะถูกปฏิเสธ และ compose
ไม่ได้ตั้ง mem limit ให้ `ai-backend-1` → OOM ล้มทั้งคอนเทนเนอร์ ไม่ใช่แค่ request นั้น

สองด่านที่ต้องมีคู่กัน:
1. `declared_too_large()` — เช็ค `content-length` ก่อนแตะ body เลย (ถูกที่สุด)
2. `read_capped()` — อ่านทีละ chunk แล้วหยุดเมื่อเกิน (ด่านจริง)

**ด่านที่ 1 อย่างเดียวไม่พอ** — chunked transfer ไม่มี `content-length` และ client
โกหกได้ · **ด่านที่ 2 อย่างเดียวก็ได้แต่เปลืองกว่า** เพราะต้องรับ byte มาก่อน
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException

# อ่านทีละ 64 KB — ใหญ่พอไม่ให้ loop ถี่จนช้า เล็กพอที่ "เกินเพดาน" จะรู้ตัวเร็ว
CHUNK = 64 * 1024

# เพดาน body มาตรฐานของทั้งระบบ — **ประกาศที่นี่ที่เดียว**
# 10 MB ไม่ใช่ตัวเลขใหม่: CLAUDE.md ประกาศไว้ ("ขนาดสูงสุด 10 MB") และ `documents.py`
# บังคับใช้อยู่ก่อนแล้ว · เดิมค่านี้ถูกก๊อปไว้ 3 ไฟล์ (documents/skills/memory) ซึ่งจะกลายเป็น
# 12 ที่เมื่อปิดเพดานครบทุกเส้น — รวมมาที่เดียวกันแบบเดียวกับที่เคยเก็บ `_SKILLS_DB` alias
MAX_BODY_BYTES = 10 * 1024 * 1024  # 10 MB


def declared_too_large(headers, max_bytes: int) -> bool:
    """`content-length` บอกว่าเกินเพดานไหม — ไม่มี/อ่านไม่ออก = `False`

    ⚠️ **ไม่มี header นี้ต้องแปลว่า "ไม่รู้" ไม่ใช่ "ใหญ่เกิน"** — chunked transfer
    ไม่ส่ง `content-length` มา ถ้าปฏิเสธทิ้งเลยจะพัง client ที่ใช้งานได้จริง
    (ทิศตรงข้ามกับ fail-closed ของ auth — ตรงนี้ยังมีด่านที่ 2 รับต่ออยู่)
    """
    try:
        raw = None
        # รองรับทั้ง dict ธรรมดาและ Starlette Headers (case-insensitive อยู่แล้ว)
        for k, v in dict(headers).items():
            if str(k).lower() == "content-length":
                raw = v
                break
        if raw is None:
            return False
        return int(str(raw).strip()) > max_bytes
    except (TypeError, ValueError):
        return False


async def read_capped(reader, max_bytes: int, detail: str | None = None) -> bytes:
    """อ่าน `reader` (มี `async read(n)`) ทีละ chunk แล้วโยน 413 ทันทีที่เกินเพดาน

    ไม่เคยถือไบต์เกิน `max_bytes + CHUNK` ไว้ใน RAM

    ⚠️ `UploadFile.read(n)` **ไม่รับประกันว่าจะคืนครบ n** — คืนสั้นไม่ได้แปลว่าจบไฟล์
    ต้องวนจนกว่าจะได้ `b""` (ถ้าเชื่อว่าคืนสั้น = จบ ไฟล์จะขาดกลางแบบเงียบๆ)
    """
    out = bytearray()
    while True:
        chunk = await reader.read(CHUNK)
        if not chunk:
            break
        out.extend(chunk)
        if len(out) > max_bytes:
            raise HTTPException(413, detail or f"file too large (>{max_bytes} bytes)")
    return bytes(out)


async def json_body_capped(request, max_bytes: int) -> Any:
    """`request.json()` ที่มีเพดาน — กันทั้ง `content-length` และตอนอ่านสตรีมจริง

    `await request.json()` ปกติดูดทั้ง body เข้า RAM แล้วค่อย parse (ซึ่งกิน RAM
    อีกชั้นตอนสร้าง object) — เส้นนี้หยุดตั้งแต่ยังเป็นไบต์
    """
    if declared_too_large(request.headers, max_bytes):
        raise HTTPException(413, f"body too large (>{max_bytes} bytes)")

    buf = bytearray()
    async for chunk in request.stream():
        buf.extend(chunk)
        if len(buf) > max_bytes:
            raise HTTPException(413, f"body too large (>{max_bytes} bytes)")
    try:
        return json.loads(buf or b"{}")
    except Exception:
        raise HTTPException(400, "expected JSON body")
