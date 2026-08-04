"""endpoint ของ memory tier

⚠️ handler ที่เป็น `async def` (เพราะต้องอ่าน body) **ห้าม**เรียกของ sync ตรงๆ —
`teach()` / `save_memory()` / `save_lesson()` / `cleanup_old_memories()` คุยกับ ChromaDB
ข้ามคอนเทนเนอร์ทั้งหมด ถ้าเรียกบน event loop = ทุกคำขอของทุกคนหยุดรอ (SSE ของแชทด้วย)
→ ต้องผ่าน `run_in_threadpool` · handler ที่เป็น `def` ธรรมดา FastAPI โยนเข้า threadpool
ให้เองอยู่แล้ว ไม่ต้องแตะ (ดู tests/test_memory_skills_router_concurrency.py)
"""
from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from utils.memory import (
    get_memory_stats, cleanup_old_memories, save_lesson, save_memory,
    list_lessons, list_preferences, delete_lesson, delete_preference,
)
from memory.operations import get_memory_summary, recall, teach

router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.get("/stats")
def memory_stats():
    return get_memory_stats()


@router.get("/summary/{assistant}")
def memory_summary(assistant: str):
    """สรุป memory ทุก tier ของ assistant"""
    return get_memory_summary(assistant)


@router.get("/recall/{assistant}")
def memory_recall(assistant: str, q: str, session_id: str = ""):
    """ทดสอบ recall memory — debug endpoint"""
    result = recall(assistant, q, session_id=session_id)
    return {"query": q, "context": result}


@router.post("/teach/{assistant}")
async def memory_teach(assistant: str, request: Request):
    """สอน AI โดยตรง — บันทึกเป็น verified memory"""
    data = await request.json()
    text = data.get("text", "").strip()
    if not text:
        return {"ok": False, "error": "ไม่มีข้อความ"}
    saved = await run_in_threadpool(teach, assistant, text)
    return {"ok": saved, "message": "บันทึกความรู้แล้ว" if saved else "ไม่พบ teaching pattern"}


@router.get("/lessons")
def api_list_lessons():
    return {"ok": True, "lessons": list_lessons(50)}


@router.get("/preferences")
def api_list_preferences():
    return {"ok": True, "preferences": list_preferences()}


@router.delete("/lessons/{doc_id}")
def api_delete_lesson(doc_id: str):
    return {"ok": delete_lesson(doc_id)}


@router.delete("/preferences/{doc_id}")
def api_delete_preference(doc_id: str):
    return {"ok": delete_preference(doc_id)}


@router.post("/cleanup")
async def memory_cleanup(request: Request):
    try:
        data = await request.json()
    except Exception:
        data = {}
    days = data.get("days", 30) if isinstance(data, dict) else 30
    # ไล่ `col.get()` ทุก collection แล้ว delete — หนักตามขนาดคลัง ไม่ใช่ตามพารามิเตอร์
    return await run_in_threadpool(cleanup_old_memories, days=days)


@router.post("/{assistant}")
async def save_mem(assistant: str, request: Request):
    data = await request.json()
    text = data.get("text", "")
    # ทั้งคู่คืน False (ไม่ raise) เมื่อ ChromaDB ไม่พร้อม — เดิมทิ้งค่าแล้วตอบ ok:True เสมอ
    # = ผู้ใช้เห็นว่า "บันทึกแล้ว" ทั้งที่ไม่มีอะไรถูกเก็บ และไม่มีใครรู้ว่าต้องทำซ้ำ
    mem_ok = await run_in_threadpool(save_memory, assistant, "remember", f"ข้อมูลที่บันทึก: {text}")
    lesson_ok = await run_in_threadpool(save_lesson, "ข้อมูลจากพี่ปอย", text)
    if not (mem_ok and lesson_ok):
        return {"ok": False, "saved": text,
                "error": "บันทึกไม่สำเร็จ (memory ok=%s, lesson ok=%s)" % (mem_ok, lesson_ok)}
    return {"ok": True, "saved": text}
