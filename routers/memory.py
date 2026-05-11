from fastapi import APIRouter, Request

from utils.memory import (
    get_memory_stats, cleanup_old_memories, save_lesson,
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
    saved = teach(assistant, text)
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
    return cleanup_old_memories(days=days)


@router.post("/{assistant}")
async def save_mem(assistant: str, request: Request):
    data = await request.json()
    text = data.get("text", "")
    save_memory(assistant, "remember", f"ข้อมูลที่บันทึก: {text}")
    save_lesson("ข้อมูลจากพี่ปอย", text)
    return {"ok": True, "saved": text}
