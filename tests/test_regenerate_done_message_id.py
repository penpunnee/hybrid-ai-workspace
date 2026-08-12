"""Test: done event ของ /api/regenerate ต้องมี message_id เหมือน /api/chat

บั๊กจริง (สืบ 2026-08-12 ตอนไล่หาสาเหตุ feedback 0 แถว): `gen_regen()` เรียก
`save_message(...)` แต่**ทิ้งค่า id ที่คืนมา** แล้ว yield done โดยไม่มี message_id
→ FE ตั้ง `dbId: obj.message_id` = undefined → **ปุ่ม 👍/👎/📌 หายทุกครั้งหลัง
regenerate** (ปุ่ม render เฉพาะ `msg.dbId` — app.tsx)

จังหวะ regenerate คือจังหวะที่คนอยากกด rate ที่สุด (คำตอบแรกไม่ดีเลยกดทำใหม่)
⇒ เส้นเก็บ feedback สำหรับ fine-tune เสียช่องทางหลักไปเงียบๆ
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

import routers.chat as chatmod
import server
from utils.history import load_history, save_message

client = TestClient(server.app)


def _sse_events(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        if line.startswith("data: "):
            out.append(json.loads(line[len("data: "):]))
    return out


def test_regenerate_done_event_carries_message_id(monkeypatch):
    def fake_stream(messages, **k):
        yield "คำตอบเวอร์ชันใหม่"

    monkeypatch.setattr(chatmod, "stream_response", fake_stream)
    session_id = "regen-done-mid-1"
    save_message("kwan", "user", "คำถามทดสอบ", "ollama", session_id)
    save_message("kwan", "assistant", "คำตอบเวอร์ชันแรก", "ollama", session_id)

    r = client.post("/api/regenerate", json={
        "session_id": session_id, "assistant": "kwan", "provider": "ollama",
    })
    assert r.status_code == 200
    done = next(e for e in _sse_events(r.text) if e.get("done"))

    mid = done.get("message_id")
    assert isinstance(mid, int) and mid > 0, (
        f"done ของ regenerate ต้องมี message_id (ได้ {done}) — "
        "ไม่มี = ปุ่ม 👍/👎/📌 หายหลัง regenerate"
    )

    # id ต้องชี้แถวคำตอบใหม่จริง — ไม่ใช่เลขมั่ว
    history = load_history("kwan", session_id)
    new_msg = next(m for m in history if m["role"] == "assistant")
    assert "เวอร์ชันใหม่" in new_msg["content"]
