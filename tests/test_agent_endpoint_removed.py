"""`POST /api/agent` ถูกถอด — ใช้ `/api/chat` + `tool_agent: true` แทน (user เคาะ 2026-09-29)

ค้นก่อนถอด: ผู้เรียกในโค้ด 0 (frontend/bundle/overlay/MCP/scripts) · access log prod 06-30→09-29 มี 13 ครั้ง ตรงกับ probe/verify
ของเราเองทั้งหมด · เส้นนี้ไม่มี `_guard_disconnect`/cancel/`save_reply` (Stop = user ค้างเดี่ยว · exception ก่อน chunk = ค้างเดี่ยว)
ขณะที่ `/api/chat` tool_agent มีครบ ⇒ ถอดดีกว่าดูแลโค้ดซ้ำสองชุด · `GET /api/agent/tools` เก็บไว้
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

import server

client = TestClient(server.app)


def test_post_api_agent_ไม่มีแล้ว():
    r = client.post("/api/agent", json={"assistant": "kwan", "session_id": "s_removed", "prompt": "hi"})
    assert r.status_code in (404, 405), f"POST /api/agent ต้องถูกถอดแล้ว (ได้ {r.status_code})"


def test_get_agent_tools_ยังอยู่():
    r = client.get("/api/agent/tools")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == len(body["tools"]) > 0


def test_ไม่มี_route_post_agent_ใน_app():
    """กันถอดแค่ครึ่ง · ⚠️ ใช้ OpenAPI ไม่ใช่ `app.routes` — FastAPI ที่ติดตั้งห่อ router ที่ include เป็น `_IncludedRouter`
    (path=None) จึงไม่เห็น route ข้างใน = เทสผ่านฟรี (เจอตอนเขียนเทสนี้)"""
    paths = server.app.openapi()["paths"]
    assert "/api/agent/tools" in paths, "กลุ่มควบคุม: ต้องเห็น route ของ router นี้ ไม่งั้นการตรวจข้างล่างไม่มีความหมาย"
    assert "post" not in paths.get("/api/agent", {})
