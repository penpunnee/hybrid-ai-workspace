"""routers/memory.py + routers/skills.py — งาน sync ที่ช้าต้องไม่บล็อก event loop

คลาสเดียวกับ `sandbox.py` / `documents.py` / `chat.py` ที่ปิดไปแล้ว — สองไฟล์นี้เป็น
ที่เหลือสุดท้ายของ pattern เดิม: handler ถูกบังคับให้เป็น `async def` เพราะต้องอ่าน body
(`await request.json()` / `UploadFile`) แล้วเรียกของ sync ต่อตรงๆ

| endpoint | งาน sync ที่เรียก | ช้าได้แค่ไหน |
|---|---|---|
| `/api/memory/teach/{a}` | `teach()` → embed + เขียน ChromaDB | ~1 วินาที |
| `/api/memory/cleanup` | `cleanup_old_memories()` ไล่ `col.get()` ทุก collection | หลายวินาที |
| `/api/memory/{a}` | `save_memory()` + `save_lesson()` เขียน ChromaDB 2 รอบ | ~1-2 วินาที |
| `/api/skills/extract` | `stream_response()` เรียก Gemini **เต็มรอบ** + เขียนไฟล์ + db | **หลายสิบวินาที** |
| `/api/skills/discover/accept` | `accept_proposal()` เขียน .md + db | ~1 วินาที |
| `/api/upload` | pypdf/docx/openpyxl parse + `auto_extract_skills()` | หลายวินาที |

⚠️ `/api/skills/extract` เป็นตัวที่หลอกตาที่สุด: มันเรียก `stream_response()` ตัวเดียวกับ
`chat.py` — แต่ `chat.py` **ส่ง generator ต่อให้ `StreamingResponse`** ซึ่ง starlette ห่อด้วย
`iterate_in_threadpool()` ให้ ส่วนที่นี่ `"".join()` เอง → generator หมุนบน event loop ทั้งดุ้น
"sync generator ปลอดภัย" เป็นจริงเฉพาะตอนที่ starlette เป็นคนหมุนเท่านั้น

⚠️ วัดเวลาจาก **จุดอ้างอิงเดียวก่อนยิงทั้งคู่** — จับเวลาหลัง `await asyncio.sleep()`
จะเขียวทั้งที่ยังไม่ได้แก้ เพราะตัว sleep เองก็ถูกบล็อกไปด้วย
(บทเรียน "เครื่องมือวัดโกหก" ข้อ 1)

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

import routers.memory as mem_router
import routers.skills as skills_router
import utils.skill_discovery as skill_discovery
import server

_BLOCK_SEC = 0.6


def _slow(result):
    """จำลองงาน sync ที่ช้า — `time.sleep` บล็อกเธรดจริงเหมือน ChromaDB/LLM/parse"""
    def _fn(*args, **kwargs):
        time.sleep(_BLOCK_SEC)
        return result
    return _fn


def _slow_stream(*args, **kwargs):
    """`stream_response()` เป็น sync generator — ความช้าอยู่ตอนหมุน ไม่ใช่ตอนเรียก"""
    def _gen():
        time.sleep(_BLOCK_SEC)
        yield "# การทดสอบระบบ\n\nเนื้อหาตัวอย่างสำหรับเทส concurrency ที่ยาวพอผ่านเกณฑ์"
    return _gen()


async def _race(app, heavy_call):
    """ยิง heavy + light พร้อมกัน แล้วคืนเวลาที่ทั้งคู่ใช้ (นับจากก่อนยิงทั้งคู่)"""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        t0 = time.perf_counter()

        async def light():
            await asyncio.sleep(_BLOCK_SEC / 4)          # ให้ heavy เริ่มก่อน
            r = await c.get("/api/config")
            return time.perf_counter() - t0, r.status_code   # วัดจาก t0 ไม่ใช่หลัง sleep

        async def heavy():
            r = await heavy_call(c)
            return time.perf_counter() - t0, r

        (heavy_elapsed, heavy_resp), (elapsed, status) = await asyncio.gather(heavy(), light())
        return heavy_resp, heavy_elapsed, elapsed, status


@pytest.mark.parametrize("name", [
    "memory_teach",
    "memory_cleanup",
    "memory_save",
    "skills_extract",
    "skills_discover_accept",
    "upload",
])
def test_งานหนักต้องไม่ทำให้คำขออื่นค้าง(monkeypatch, tmp_path, name):
    if name == "memory_teach":
        monkeypatch.setattr(mem_router, "teach", _slow(True))

        async def heavy(c):
            return await c.post("/api/memory/teach/ขวัญ", json={"text": "จำไว้ว่าฟ้าสีฟ้า"})

    elif name == "memory_cleanup":
        monkeypatch.setattr(mem_router, "cleanup_old_memories", _slow({"ok": True, "deleted": 0}))

        async def heavy(c):
            return await c.post("/api/memory/cleanup", json={"days": 30})

    elif name == "memory_save":
        monkeypatch.setattr(mem_router, "save_memory", _slow(True))
        monkeypatch.setattr(mem_router, "save_lesson", _slow(True))

        async def heavy(c):
            return await c.post("/api/memory/ขวัญ", json={"text": "ข้อมูลทดสอบ"})

    elif name == "skills_extract":
        monkeypatch.setattr(skills_router, "stream_response", _slow_stream)
        monkeypatch.setattr(skills_router, "SKILLS_DIR", str(tmp_path))
        monkeypatch.setattr(skills_router, "set_skill_entry", lambda topic, entry: None)

        async def heavy(c):
            return await c.post("/api/skills/extract",
                                json={"content": "เนื้อหาต้นทางสำหรับสกัดเป็น skill",
                                      "topic": "การทดสอบระบบ"})

    elif name == "skills_discover_accept":
        # handler import ในตัวฟังก์ชัน → ต้อง patch ที่โมดูลต้นทาง
        monkeypatch.setattr(skill_discovery, "accept_proposal", _slow({"ok": True}))

        async def heavy(c):
            return await c.post("/api/skills/discover/accept", json={"proposal_id": "p1"})

    else:  # upload
        monkeypatch.setattr(skills_router, "auto_extract_skills", _slow([]))

        async def heavy(c):
            return await c.post("/api/upload",
                                files={"file": ("note.txt", b"x" * 200, "text/plain")})

    heavy_resp, heavy_elapsed, light_elapsed, light_status = asyncio.run(_race(server.app, heavy))

    assert heavy_resp.status_code == 200, heavy_resp.text
    assert heavy_resp.json().get("ok") is True, heavy_resp.text
    # กัน "เขียวฟรี": ถ้า monkeypatch ยิงผิดเป้า handler จะไปเรียกของจริงซึ่งเร็ว
    # → light ก็เร็วตาม → เทสเขียวทั้งที่ไม่ได้วัดการบล็อกเลย
    # ต้องพิสูจน์ก่อนว่า "งานหนักช้าจริงในเส้นนี้" แล้วค่อยเชื่อผลของ light
    assert heavy_elapsed >= _BLOCK_SEC, (
        f"{name} ใช้แค่ {heavy_elapsed:.3f}s (ควร >= {_BLOCK_SEC}s) "
        "— ของช้าที่ mock ไว้ไม่ได้ถูกเรียก เทสนี้ไม่ได้วัดอะไร")
    assert light_status == 200
    # ถ้า event loop ถูกบล็อก light จะตอบหลัง heavy จบ (~_BLOCK_SEC)
    assert light_elapsed < _BLOCK_SEC * 0.8, (
        f"/api/config ใช้ {light_elapsed:.3f}s ระหว่าง {name} ทำงาน "
        f"(งานหนักกิน {_BLOCK_SEC}s) — event loop ถูกบล็อก")
