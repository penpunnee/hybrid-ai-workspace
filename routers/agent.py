"""Agent tools listing

GET /api/agent/tools — รายชื่อ tools ที่ agent ใช้ได้

⚠️ `POST /api/agent` ถูกถอดแล้ว (2026-09-29 · user เคาะ) — ใช้ `POST /api/chat` + `{"tool_agent": true}` แทน
ค้นก่อนถอด: ผู้เรียกในโค้ด 0 · access log prod 06-30→09-29 มี 13 ครั้งเป็น probe/verify ของเราเองทั้งหมด ·
เส้นนั้นไม่มี `_guard_disconnect`/cancel/`save_reply` (Stop หรือ exception ก่อน chunk = แถว user ค้างเดี่ยว)
ขณะที่ `/api/chat` tool_agent มีครบ ⇒ ไม่ดูแลโค้ดซ้ำสองชุด (บทเรียน websearch 2 pipeline)
"""
from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["agent"])


@router.get("/agent/tools")
def list_available_tools():
    """รายชื่อ tools ที่ agent ใช้ได้"""
    from agents.tools import TOOL_REGISTRY
    return {
        "count": len(TOOL_REGISTRY),
        "tools": [
            {
                "name": name,
                "description": spec["description"],
                "parameters": list(spec["parameters"].get("properties", {}).keys()),
            }
            for name, spec in TOOL_REGISTRY.items()
        ],
    }
