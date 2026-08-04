"""routers/chat.py — งาน sync ที่อยู่ **ก่อน** StreamingResponse ต้องไม่บล็อก event loop

## สิ่งที่ตรวจแล้วพบว่าบันทึกเดิมล้าสมัย

backlog เขียนว่า *"`chat.py` (ช่วง context assembly ก่อนเริ่ม stream)"* เป็นตัวบล็อก
— **ไม่จริงแล้วตั้งแต่ 2026-07-13** ตอนย้ายงานทั้งหมดเข้าไปใน `def generate()`
เพื่อยิง SSE `{"phase": ...}` · starlette ห่อ **sync generator** ด้วย
`iterate_in_threadpool()` (ดู `StreamingResponse.__init__`) → context assembly,
retrieval, LLM stream ทั้งหมดรันนอก event loop อยู่แล้ว
การย้ายเข้า generator เพื่อ UX ปิดปัญหา blocking ไปด้วยโดยไม่ได้ตั้งใจ

**ที่ยังบล็อกจริงคือส่วนที่อยู่ก่อน `return StreamingResponse(...)`** ซึ่งไม่มีใครมองเพราะ
บันทึกชี้ไปที่ context assembly:

| จุด | งาน sync | ช้าเพราะ |
|---|---|---|
| `generate_image()` | เรียก Gemini Image API | หลายวินาที–หลายสิบวินาที |
| `_rc_lookup()` (response cache) | embed prompt → LMStudio/Ollama | round-trip ข้ามเครื่อง |
| `teach()` | เขียน ChromaDB | round-trip ข้ามคอนเทนเนอร์ |
| `search_memory()` ใน `/regenerate` | embed + ChromaDB | เหมือนกัน |

⚠️ วัดเวลาจาก **จุดอ้างอิงเดียวก่อนยิงทั้งคู่** — จับเวลาหลัง `await asyncio.sleep()`
จะเขียวทั้งที่ยังไม่ได้แก้ (บทเรียน "เครื่องมือวัดโกหก" ข้อ 1)

⚠️ เทสนี้เลือกเส้นที่ **short-circuit เร็ว** (image gen / cache hit) เพื่อแยกวัดเฉพาะ
งานก่อน generator — ไม่ต้อง mock LLM ทั้งกอง แล้วเผลอวัดอย่างอื่นไปด้วย
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

import routers.chat as chat_router
import server

_BLOCK_SEC = 0.6


async def _race(heavy_call):
    """ยิง heavy + light พร้อมกัน — คืนเวลาที่ light ใช้ นับจากก่อนยิงทั้งคู่"""
    transport = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        t0 = time.perf_counter()

        async def light():
            await asyncio.sleep(_BLOCK_SEC / 4)          # ให้ heavy เริ่มก่อน
            r = await c.get("/api/config")
            return time.perf_counter() - t0, r.status_code   # วัดจาก t0 ไม่ใช่หลัง sleep

        heavy, (elapsed, status) = await asyncio.gather(heavy_call(c), light())
        return heavy, elapsed, status


def _slow(result):
    def _fn(*a, **kw):
        time.sleep(_BLOCK_SEC)
        return result
    return _fn


def test_image_generation_ไม่บล็อกคำขออื่น(monkeypatch):
    """เส้นวาดรูป — `generate_image()` ยิง Gemini Image API แบบ sync ก่อน generator"""
    import utils.image_gen as image_gen
    monkeypatch.setattr(image_gen, "detect_image_request", lambda p: True)
    monkeypatch.setattr(image_gen, "generate_image",
                        _slow({"ok": True, "url": "/gen/x.png", "text": "วาดเสร็จ"}))
    monkeypatch.setattr(chat_router, "save_message", lambda *a, **kw: 1)

    async def heavy(c):
        return await c.post("/api/chat", json={"prompt": "วาดรูปแมว", "session_id": "t"})

    resp, light_elapsed, light_status = asyncio.run(_race(heavy))

    assert resp.status_code == 200, resp.text
    assert light_status == 200
    assert light_elapsed < _BLOCK_SEC * 0.8, (
        f"/api/config ใช้ {light_elapsed:.3f}s ระหว่างสร้างรูป (งานหนักกิน {_BLOCK_SEC}s) "
        "— event loop ถูกบล็อก")


def test_response_cache_lookup_ไม่บล็อกคำขออื่น(monkeypatch):
    """`_rc_lookup()` ต้อง embed prompt ก่อน = round-trip ไป LMStudio/Ollama"""
    import utils.response_cache as rc
    monkeypatch.setattr(rc, "lookup", _slow(
        {"response": "คำตอบจาก cache", "similarity": 0.95,
         "source_prompt": "เดิม", "model": "cache"}))
    monkeypatch.setattr(chat_router, "teach", lambda *a, **kw: None)
    monkeypatch.setattr(chat_router, "save_message", lambda *a, **kw: 1)

    async def heavy(c):
        return await c.post("/api/chat", json={"prompt": "ทดสอบแคช", "session_id": "t"})

    resp, light_elapsed, light_status = asyncio.run(_race(heavy))

    assert resp.status_code == 200, resp.text
    assert light_status == 200
    assert light_elapsed < _BLOCK_SEC * 0.8, (
        f"/api/config ใช้ {light_elapsed:.3f}s ระหว่าง cache lookup — event loop ถูกบล็อก")


def test_regenerate_search_memory_ไม่บล็อกคำขออื่น(monkeypatch):
    """`/api/regenerate` เรียก `search_memory()` (embed + ChromaDB) ก่อน generator"""
    monkeypatch.setattr(chat_router, "delete_last_assistant_message", lambda *a, **kw: None)
    monkeypatch.setattr(chat_router, "get_last_user_message", lambda *a, **kw: "คำถามเดิม")
    monkeypatch.setattr(chat_router, "load_history", lambda *a, **kw: [])
    monkeypatch.setattr(chat_router, "save_message", lambda *a, **kw: 1)
    monkeypatch.setattr(chat_router, "search_memory", _slow(""))
    monkeypatch.setattr(chat_router, "stream_response", lambda *a, **kw: iter(["ok"]))

    async def heavy(c):
        return await c.post("/api/regenerate", json={"assistant": "ขวัญ", "session_id": "t"})

    resp, light_elapsed, light_status = asyncio.run(_race(heavy))

    assert resp.status_code == 200, resp.text
    assert light_status == 200
    assert light_elapsed < _BLOCK_SEC * 0.8, (
        f"/api/config ใช้ {light_elapsed:.3f}s ระหว่าง regenerate — event loop ถูกบล็อก")
