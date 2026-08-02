"""Tests สำหรับ routers/sandbox.py — งาน sync ที่ช้าต้องไม่บล็อก event loop

ทำไมสำคัญ (availability): handler พวกนี้ต้องเป็น `async def` เพราะอ่าน body
(`await request.json()`) แต่ของที่เรียกต่อเป็น sync ล้วนและช้าได้ —
`run_python` ยิง subprocess ได้ถึง 62 วิ · `search_files` ไล่ `rglob` ทั้ง tree

เรียกตรงๆ ใน async def = บล็อก event loop ทั้งเส้น → SSE ของแชททุกคนหยุดพร้อมกัน
พิสูจน์แล้วบนเซิร์ฟเวอร์จริง 2026-08-03: `POST /api/fs/search {"pattern": "(a+)+$"}`
ทำให้ `/api/config` ไม่ตอบอีกเลยจนกว่าจะ restart (ดู tests/test_fs_tools.py สำหรับ
ฝั่ง ReDoS ซึ่งเป็นต้นเหตุอีกครึ่งหนึ่ง)

เทสนี้วัด "พฤติกรรมพร้อมกัน" จริง ไม่ได้ assert ว่าโค้ดเรียก run_in_threadpool

⚠️ ต้องวัดเวลาจาก **จุดอ้างอิงเดียวก่อนยิงทั้งคู่** — เวอร์ชันแรกของเทสนี้จับเวลา
*หลัง* `await asyncio.sleep()` ซึ่งตัว sleep เองก็ถูกบล็อกไปด้วย → เลยวัดได้แต่ช่วง
หลังบล็อกจบ = เขียวทั้งที่ยังไม่ได้แก้ (เจอตอนลองถอด fix ออกแล้วเทสไม่แดง)
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

import routers.sandbox as sandbox_router
import server

_BLOCK_SEC = 0.6


def _blocking_search(*args, **kwargs):
    """จำลองงาน sync ที่ช้า (regex/rglob ของจริง) — `time.sleep` บล็อกเธรดจริงเหมือนกัน"""
    time.sleep(_BLOCK_SEC)
    return {"ok": True, "matches": [], "count": 0}


def test_slow_fs_search_does_not_block_other_requests(monkeypatch):
    monkeypatch.setattr(sandbox_router, "search_files", _blocking_search)

    async def scenario():
        transport = httpx.ASGITransport(app=server.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            async def heavy():
                return await c.post("/api/fs/search", json={"pattern": "needle"})

            t0 = time.perf_counter()

            async def light():
                await asyncio.sleep(_BLOCK_SEC / 4)      # ให้ heavy เริ่มก่อน
                r = await c.get("/api/config")
                return time.perf_counter() - t0, r.status_code   # วัดจาก t0 ไม่ใช่หลัง sleep

            heavy_resp, (light_elapsed, light_status) = await asyncio.gather(heavy(), light())
            return heavy_resp.status_code, light_elapsed, light_status

    heavy_status, light_elapsed, light_status = asyncio.run(scenario())

    assert heavy_status == 200 and light_status == 200
    # ถ้า event loop ถูกบล็อก request เบาจะรอจน fs/search เสร็จ (~_BLOCK_SEC)
    assert light_elapsed < _BLOCK_SEC / 2, (
        f"/api/config เสร็จที่ {light_elapsed:.2f}s หลังยิง fs/search "
        f"(ควร ~{_BLOCK_SEC / 4:.2f}s) — event loop ถูกบล็อก งาน sync ไม่ได้ออก threadpool"
    )


def test_slow_sandbox_python_does_not_block_other_requests(monkeypatch):
    class _Result:
        def to_dict(self):
            return {"ok": True, "stdout": "", "mode": "docker"}

    def _blocking_run(*args, **kwargs):
        time.sleep(_BLOCK_SEC)
        return _Result()

    monkeypatch.setattr(sandbox_router, "run_python", _blocking_run)

    async def scenario():
        transport = httpx.ASGITransport(app=server.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            async def heavy():
                return await c.post("/api/sandbox/python", json={"code": "print(1)"})

            t0 = time.perf_counter()

            async def light():
                await asyncio.sleep(_BLOCK_SEC / 4)
                r = await c.get("/api/config")
                return time.perf_counter() - t0, r.status_code   # วัดจาก t0 ไม่ใช่หลัง sleep

            heavy_resp, (light_elapsed, _) = await asyncio.gather(heavy(), light())
            return heavy_resp.status_code, light_elapsed

    heavy_status, light_elapsed = asyncio.run(scenario())
    assert heavy_status == 200
    assert light_elapsed < _BLOCK_SEC / 2, (
        f"/api/config เสร็จที่ {light_elapsed:.2f}s หลังยิง sandbox/python "
        f"(ควร ~{_BLOCK_SEC / 4:.2f}s) — event loop ถูกบล็อก"
    )


def test_dream_trigger_does_not_block_other_requests(monkeypatch):
    """`/api/dream` ก็เป็นคลาสเดียวกัน — `ThreadPoolExecutor(...).result(timeout=600)`
    เป็น call แบบบล็อกที่เรียกอยู่ใน async def → แช่ event loop ได้ถึง 10 นาที
    (ปุ่ม '🌙 รัน Dream เลย' บน UI กดได้ตรงๆ)"""
    import routers.dream as dream_router

    def _blocking_dream(*args, **kwargs):
        time.sleep(_BLOCK_SEC)
        return {"ok": True, "themes": []}

    monkeypatch.setattr(dream_router, "run_dream_cycle", _blocking_dream)

    async def scenario():
        transport = httpx.ASGITransport(app=server.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            async def heavy():
                return await c.post("/api/dream", json={})

            t0 = time.perf_counter()

            async def light():
                await asyncio.sleep(_BLOCK_SEC / 4)
                r = await c.get("/api/config")
                return time.perf_counter() - t0, r.status_code

            heavy_resp, (light_elapsed, _) = await asyncio.gather(heavy(), light())
            return heavy_resp.status_code, light_elapsed

    heavy_status, light_elapsed = asyncio.run(scenario())
    assert heavy_status == 200
    assert light_elapsed < _BLOCK_SEC / 2, (
        f"/api/config เสร็จที่ {light_elapsed:.2f}s หลังยิง /api/dream "
        f"(ควร ~{_BLOCK_SEC / 4:.2f}s) — event loop ถูกบล็อก"
    )
