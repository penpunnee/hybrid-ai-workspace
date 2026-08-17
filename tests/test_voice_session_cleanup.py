"""ปิด Gemini Live session ที่ค้าง เมื่อ browser หลุดกลางช่วงที่โมเดลเงียบ

🔴 **อุบัติเหตุจริงบน prod 2026-08-17 13:10:56** — `[Voice WS] send_loop APIError: 1011
None. Resource has been exhausted (e.g. check quota).` **ครั้งแรกในทั้งไฟล์ log**
(1011 ตัวเดียวก่อนหน้าคือ `ConnectionClosedError keepalive ping timeout` คนละเรื่อง)

ไทม์ไลน์ที่ประกอบจาก log:
  13:08:25  โหลดหน้าเว็บ (config ยิง 3 ครั้งในวินาทีเดียว = mount)
  13:10:09  **โหลดหน้าใหม่ทับ** ⇒ สายเสียงของหน้าเก่ากลายเป็นผี
  13:10:19  สายใหม่เริ่ม (t₀ ของ `AudioLevelMeter` = 13:10:17–13:10:22)
  13:10:34  เริ่มค้นเว็บ — โมเดลเงียบ 37.5 วิ
  13:10:56  **ผีตายพร้อมโวย 1011** = มี 2 Live session พร้อมกันบน key เดียว
  13:11:38  สายของ user รอดต่อเนื่อง (`ตั้งแต่เริ่ม` เดินต่อไม่รีเซ็ต = ไม่ได้ reconnect)

ต้นเหตุ (โค้ด ไม่ใช่การเดา):
  · `send_loop` เห็นธง `stop` ได้เฉพาะ **เมื่อมีข้อความเข้ามาจาก Gemini** เพราะมันค้าง
    อยู่ใน `async for response in session.receive()` ที่ไม่มี timeout
  · `recv_loop` เจอ `WebSocketDisconnect` แล้วทำได้แค่ `stop.set()` — ปลุกใครไม่ได้
  · `asyncio.gather()` **ไม่ cancel พี่น้องเมื่อตัวหนึ่งจบปกติ** มันรอครบทุกตัว
  ⇒ `gather` ไม่คืน ⇒ `async with client.aio.live.connect(...)` ไม่ออก
  ⇒ **Gemini session ค้างเปิดกิน slot** จนกระทั่ง Gemini เอง reap ทิ้ง (คือ 1008 ที่ ~151 วิ)

🔑 กติกาของตัวแก้ — **ไม่สมมาตรโดยตั้งใจ** เพราะ 2 ลูปคุณสมบัติไม่เท่ากัน:
  · `recv_loop` มีจุดตื่นเอง (`wait_for(receive_json(), timeout=1.0)`) ⇒ จบเองได้ ≤1 วิ
  · `send_loop` ไม่มีจุดตื่น ⇒ ต้องมีคน cancel
  จึงใช้กฎ "ใครจบก่อน อีกตัวได้เวลา `grace` จบเอง ไม่จบแล้วค่อย cancel" ซึ่งทำให้
  **เส้น `go_away`/regen เดินทางเดิมบิตต่อบิต** (recv_loop จบเองใน ≤1 วิ < grace
  ⇒ ไม่มีการ cancel เกิดขึ้นเลย) — เส้นนั้นวิ่งทุก ~10 นาทีและตอนนี้ทำงานถูกอยู่แล้ว
"""
import ast
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.voice import LOOP_EXIT_GRACE_SEC, run_until_both_done


async def _จบทันที():
    """แทน `recv_loop` ตอน browser หลุด — ตั้งธงแล้วจบไปเลย"""
    return


async def _ค้างตลอดกาล():
    """แทน `send_loop` ที่ค้างใน `session.receive()` ตอน Gemini เงียบ (ค้นเว็บ 37.5 วิ)

    ⚠️ ห้ามใช้ `while True: pass` — ต้อง await เพื่อให้ event loop หมุนได้
    ไม่งั้นเทสจะบล็อกทั้ง loop แล้ววัดผิดสิ่ง
    """
    await asyncio.Event().wait()


# ── กลุ่มควบคุม: พิสูจน์ว่า `asyncio.gather` คือตัวปัญหาจริง ──────────────────
# ⚠️ เทสนี้ต้องผ่าน**ทั้งก่อนและหลัง**แก้ — มันตรึงพฤติกรรมของ stdlib ที่เป็นเหตุผล
# ของการมีฟังก์ชันใหม่ ถ้าวันหนึ่งมันแดง แปลว่า asyncio เปลี่ยนสัญญา ไม่ใช่โค้ดเราพัง
def test_gather_ค้างตลอดกาลเมื่อลูปตัวหนึ่งไม่มีจุดตื่น():
    async def _run():
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                asyncio.gather(_จบทันที(), _ค้างตลอดกาล()),
                timeout=0.5,
            )

    asyncio.run(_run())


# ── ตัวแก้: ต้อง cancel ตัวที่ค้าง เพื่อให้ `async with` ปิด session ได้จริง ──
def test_cancel_ลูปที่ค้างเกิน_grace_แล้วคืนภายในเวลา():
    """⚠️ ต้องครอบ `wait_for` — ไม่งั้นวันที่ตัวแก้หายไป เทสจะ **ค้าง** ไม่ใช่ **แดง**
    (CI จะ timeout ทั้ง job แทนที่จะรายงานว่าเทสไหนพัง = เครื่องมือวัดเสียเอง)
    """
    async def _run():
        return await asyncio.wait_for(
            run_until_both_done(_จบทันที(), _ค้างตลอดกาล(), grace=0.2),
            timeout=2.0,
        )

    # ตัวที่ค้างต้องถูก cancel 1 ตัว — ตัวเลขนี้คือสิ่งที่ caller เอาไป log ได้
    assert asyncio.run(_run()) == 1, "ต้อง cancel ลูปที่ค้าง 1 ตัว"


# ── 🔴 กันการถอยหลังของเส้น go_away/regen (ความเสี่ยงจริงข้อเดียวของงานนี้) ──
def test_ไม่_cancel_ถ้าอีกลูปจบเองทันใน_grace():
    """เส้น `go_away`: `send_loop` จบก่อน · `recv_loop` เห็นธง regen แล้วจบเองใน ≤1 วิ

    ถ้าเทสนี้แดง = เราไป cancel `recv_loop` กลาง `receive_json()` ทุกครั้งที่ go_away
    (เกิดทุก ~10 นาที) ⇒ เสี่ยงทิ้งเฟรมเสียงจาก client ทั้งที่เส้นเดิมทำงานถูกอยู่แล้ว
    """
    async def _ตื่นเองทัน():
        await asyncio.sleep(0.05)

    async def _run():
        return await run_until_both_done(_จบทันที(), _ตื่นเองทัน(), grace=1.0)

    assert asyncio.run(_run()) == 0, "ไม่ควร cancel ใครเลยเมื่อทุกตัวจบเองทัน"


def test_grace_ค่าเริ่มต้นยาวกว่าจังหวะตื่นของ_recv_loop():
    """`recv_loop` ใช้ `wait_for(..., timeout=1.0)` ⇒ grace ต้อง > 1.0 วิ

    ไม่งั้นเส้น go_away จะโดน cancel เพราะ recv_loop ยังไม่ถึงรอบเช็คธงถัดไป
    """
    assert LOOP_EXIT_GRACE_SEC > 1.0


# ── ตรึงว่า endpoint เสียงเลิกใช้ `asyncio.gather` กับคู่ลูปแล้วจริง ─────────
# ⚠️ เดินด้วย `ast` ไม่ใช่ `in src` — บทเรียน 2026-08-18: assertion ที่อ่าน "ตัวหนังสือ"
# เคยแดงเพราะไปโดน**คอมเมนต์ที่อธิบายบั๊กนั้นเอง** (ดู test_voice_logging)
def _หา_function(tree, ชื่อ):
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == ชื่อ:
            return node
    raise AssertionError(f"ไม่เจอฟังก์ชัน {ชื่อ} ใน server.py")


def _เรียกอะไรบ้าง(node):
    ชื่อที่เรียก = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Attribute):
                ชื่อที่เรียก.add(f.attr)
            elif isinstance(f, ast.Name):
                ชื่อที่เรียก.add(f.id)
    return ชื่อที่เรียก


def test_voice_websocket_ไม่เรียก_gather_กับคู่ลูปแล้ว():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "server.py"), encoding="utf-8").read()
    เรียก = _เรียกอะไรบ้าง(_หา_function(ast.parse(src), "voice_websocket"))
    assert "run_until_both_done" in เรียก, "voice_websocket ต้องใช้ run_until_both_done"
    assert "gather" not in เรียก, (
        "voice_websocket ยังเรียก asyncio.gather กับคู่ลูป — ตัวที่ค้างจะไม่ถูก cancel"
    )
