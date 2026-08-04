"""routers/documents.py — งาน sync ที่ช้าต้องไม่บล็อก event loop

คลาสเดียวกับ `routers/sandbox.py` (ปิดไปแล้ว 2026-08-03) แต่หนักกว่ามาก:

| endpoint | งาน sync ที่เรียก | ช้าได้แค่ไหน |
|---|---|---|
| `/ocr` | `pdf2image` เรนเดอร์ทีละหน้า → Gemini/LMStudio Vision | หลายสิบวินาที |
| `/summarize` | `summarize_document()` map-reduce ผ่าน LLM | **เป็นนาที** |
| `/upload` | `_decode_bytes` (PDF/DOCX/XLSX) + `index_document` (embed+ChromaDB) | หลายวินาที |
| `/search` | `retrieve_chunks()` (embed + ChromaDB) | ~1 วินาที |

handler ทุกตัวถูกบังคับให้เป็น `async def` เพราะต้องอ่าน body → เรียกของ sync ตรงๆ
= event loop หยุดทั้งเส้น = **SSE ของแชททุกคนหยุดพร้อมกัน** ระหว่างที่มีคนสั่งสรุปเอกสาร

⚠️ วัดเวลาจาก **จุดอ้างอิงเดียวก่อนยิงทั้งคู่** — เวอร์ชันแรกของเทสฝั่ง sandbox
จับเวลาหลัง `await asyncio.sleep()` ซึ่งตัว sleep เองก็ถูกบล็อกไปด้วย → เขียวทั้งที่
ยังไม่ได้แก้ (บทเรียน "เครื่องมือวัดโกหก" ข้อ 1)

⚠️ เทสนี้วัด **พฤติกรรมพร้อมกันจริง** ไม่ได้ assert ว่าโค้ดเรียก `run_in_threadpool`
— assert ว่า "เรียกฟังก์ชันชื่อนี้" จะเขียวได้แม้ย้ายผิดที่
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
import pytest

import routers.documents as docs_router
import server

_BLOCK_SEC = 0.6


def _slow_retrieve(*args, **kwargs):
    """จำลอง embed+ChromaDB ที่ช้า — `time.sleep` บล็อกเธรดจริงเหมือนงาน CPU/IO sync"""
    time.sleep(_BLOCK_SEC)
    return []


def _slow_summarize(*args, **kwargs):
    time.sleep(_BLOCK_SEC)
    return {"ok": True, "summary": "สรุปแล้ว"}


async def _race(app, heavy_call):
    """ยิง heavy + light พร้อมกัน แล้วคืนเวลาที่ light ใช้ (นับจากก่อนยิงทั้งคู่)"""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        t0 = time.perf_counter()

        async def light():
            await asyncio.sleep(_BLOCK_SEC / 4)          # ให้ heavy เริ่มก่อน
            r = await c.get("/api/config")
            return time.perf_counter() - t0, r.status_code   # วัดจาก t0 ไม่ใช่หลัง sleep

        heavy, (elapsed, status) = await asyncio.gather(heavy_call(c), light())
        return heavy, elapsed, status


@pytest.mark.parametrize("name", ["search", "summarize"])
def test_งานหนักต้องไม่ทำให้คำขออื่นค้าง(monkeypatch, name):
    if name == "search":
        monkeypatch.setattr(docs_router, "retrieve_chunks", _slow_retrieve)
        async def heavy(c):
            return await c.post("/api/documents/search", json={"query": "อะไรก็ได้"})
    else:
        monkeypatch.setattr(docs_router, "summarize_document", _slow_summarize)
        async def heavy(c):
            return await c.post("/api/documents/summarize",
                                json={"source": "a.txt", "content": "เนื้อหาทดสอบ"})

    heavy_resp, light_elapsed, light_status = asyncio.run(_race(server.app, heavy))

    assert heavy_resp.status_code == 200, heavy_resp.text
    assert light_status == 200
    # ถ้า event loop ถูกบล็อก light จะตอบหลัง heavy จบ (~_BLOCK_SEC)
    assert light_elapsed < _BLOCK_SEC * 0.8, (
        f"/api/config ใช้ {light_elapsed:.3f}s ระหว่าง {name} ทำงาน "
        f"(งานหนักกิน {_BLOCK_SEC}s) — event loop ถูกบล็อก")
