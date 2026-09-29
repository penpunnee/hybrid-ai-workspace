"""/api/chat ต้องบอก id ของข้อความ user ที่เพิ่งบันทึก — backlog dbId (2026-09-29)

บั๊ก: ฟอง user ที่เพิ่งส่งในหน้าเดียวกันไม่มี `dbId` (FE รู้ id แค่ตอน loadHistory)
⇒ (1) แก้ข้อความที่เพิ่งส่ง = ไม่ยิง `/api/truncate` → DB มีคู่เก่า+ใหม่ซ้อน
   (2) ปุ่ม 📌/🗑️ ของฟอง user ไม่ขึ้นจนรีโหลด

ส่งเป็น event แยก `{"user_message_id": id}` **ทันทีหลัง save** ไม่ใช่ใน `done` —
กด Stop / stream ขาด = ไม่มี `done` แต่แถว user อยู่ใน DB แล้ว (แก้ข้อความทีหลังก็ต้อง truncate ได้)

ครบทุกเส้นที่ save user: หลัก · agent · image_gen · response cache · active-learning clarify
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch

from fastapi.testclient import TestClient

import routers.chat as chatmod
import server
from utils.history import _get_conn

client = TestClient(server.app)


def _events(text: str) -> list[dict]:
    return [json.loads(ln[6:]) for ln in text.splitlines() if ln.startswith("data: ")]


def _row(db_id: int):
    conn = _get_conn()
    try:
        return conn.execute("SELECT role, content, session_id FROM messages WHERE id = ?", (db_id,)).fetchone()
    finally:
        conn.close()


def _post(sid: str, prompt: str, **extra) -> list[dict]:
    body = {"assistant": "kwan", "session_id": sid, "prompt": prompt, "provider": "ollama",
            "active_learning": False, "response_cache": False, **extra}
    with patch.object(chatmod, "remember"), patch.object(chatmod, "teach", return_value=False):
        r = client.post("/api/chat", json=body)
    assert r.status_code == 200
    return _events(r.text)


def _assert_user_id(evs: list[dict], sid: str, prompt: str):
    got = [e["user_message_id"] for e in evs if "user_message_id" in e]
    assert len(got) == 1, f"ต้องมี event user_message_id หนึ่งครั้งพอดี (ได้ {got}) · events={evs}"
    uid = got[0]
    assert isinstance(uid, int) and uid > 0, uid
    # id ต้องชี้แถว user ของ turn นี้จริง — ไม่ใช่เลขมั่ว/แถว assistant
    assert _row(uid) == ("user", prompt, sid), f"id {uid} ไม่ได้ชี้แถว user ที่เพิ่ง save: {_row(uid)}"
    # ต้องมาก่อน chunk แรก — Stop กลางคำตอบก็ต้องได้ id แล้ว
    first_chunk = next((i for i, e in enumerate(evs) if "chunk" in e), len(evs))
    uid_at = next(i for i, e in enumerate(evs) if "user_message_id" in e)
    assert uid_at < first_chunk, f"user_message_id ต้องมาก่อน chunk แรก (อยู่ที่ {uid_at} · chunk ที่ {first_chunk})"


def test_เส้นหลัก_ส่ง_user_message_id(monkeypatch):
    monkeypatch.setattr(chatmod, "stream_response", lambda messages, **k: iter(["คำตอบ"]))
    sid = "uid-main"
    _assert_user_id(_post(sid, "คำถามเส้นหลัก"), sid, "คำถามเส้นหลัก")


def test_เส้น_agent_ส่ง_user_message_id(monkeypatch):
    import agents.orchestrator as orch

    def fake_run_agent(messages, **kw):
        yield ("chunk", "คำตอบ agent")

    monkeypatch.setattr(orch, "run_agent", fake_run_agent)
    sid = "uid-agent"
    _assert_user_id(_post(sid, "ค้นราคาทอง", tool_agent=True, provider="gemini"), sid, "ค้นราคาทอง")


def test_เส้น_image_gen_ส่ง_user_message_id(monkeypatch):
    import utils.image_gen as ig
    monkeypatch.setattr(ig, "detect_image_request", lambda p: True)
    monkeypatch.setattr(ig, "generate_image", lambda p, **k: {"ok": False, "error": "ปิดไว้ในเทส"})
    sid = "uid-image"
    _assert_user_id(_post(sid, "วาดรูปแมว"), sid, "วาดรูปแมว")


def test_เส้น_response_cache_ส่ง_user_message_id(monkeypatch):
    import utils.response_cache as rc
    monkeypatch.setattr(rc, "lookup", lambda a, p: {"response": "คำตอบจาก cache", "similarity": 0.99,
                                                    "source_prompt": p, "model": "cache"})
    sid = "uid-cache"
    _assert_user_id(_post(sid, "คำถามที่ cache ไว้", response_cache=True), sid, "คำถามที่ cache ไว้")


def test_เส้น_active_learning_clarify_ส่ง_user_message_id(monkeypatch):
    import reasoning.active_learning as al
    monkeypatch.setattr(chatmod, "stream_response", lambda messages, **k: iter(["ห้ามถึงตรงนี้"]))
    monkeypatch.setattr(al, "decide", lambda *a, **k: al.ActiveLearningDecision(
        should_ask=True, reason="test", clarify_directly=True, clarify_message="อยู่จังหวัดไหนคะ"))
    sid = "uid-clarify"
    evs = _post(sid, "ฝนจะตกไหม", active_learning=True)
    assert any(e.get("chunk") == "อยู่จังหวัดไหนคะ" for e in evs), f"ต้องเข้าเส้น clarify จริง: {evs}"
    _assert_user_id(evs, sid, "ฝนจะตกไหม")
