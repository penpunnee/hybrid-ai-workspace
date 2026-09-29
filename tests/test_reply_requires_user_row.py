"""คำตอบต้องไม่ถูกบันทึกเมื่อแถว user ของ turn นั้นถูกลบไปแล้ว — ความเสี่ยงที่เหลือจากตรวจทาน 09-29 [ต่อ 31]

FE ห้ามแก้ข้อความระหว่าง stream แล้ว (`bace965`) แต่ backend ยังบันทึกคำตอบของ stream ที่แถว user ถูก truncate
ไปแล้วได้: 2 แท็บ · bundle เก่า · Stop ตรงจังหวะที่ LLM ตอบครบ ⇒ ได้แถว assistant ต่อท้าย turn ใหม่ (ประวัติสลับคู่)
+ remember()/teach() เรียนจากคำถามที่ผู้ใช้ถอนไปแล้ว

แก้: `save_reply()` = INSERT แบบมีเงื่อนไขคำสั่งเดียว (อะตอม — ไม่มีช่องระหว่าง "เช็ค" กับ "เขียน" แบบ message_exists แล้ว save)
ครบทุกเส้นที่บันทึกคำตอบหลังมีช่วงรอ LLM: หลัก · agent · error (`_save_crash`) · regenerate (ปกติ + error)
"""
import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

import routers.chat as chatmod
import server
from utils.history import _get_conn, load_history, save_message, save_reply, truncate_from_db_id

client = TestClient(server.app)


def _user_id(sid):
    conn = _get_conn()
    try:
        return conn.execute("SELECT id FROM messages WHERE session_id = ? AND role = 'user' ORDER BY id DESC LIMIT 1",
                            (sid,)).fetchone()[0]
    finally:
        conn.close()


def _events(text):
    return [json.loads(ln[6:]) for ln in text.splitlines() if ln.startswith("data: ")]


# ── ระดับ history ─────────────────────────────────────────────────────────────
def test_save_reply_บันทึกเมื่อแถว_user_ยังอยู่():
    uid = save_message("kwan", "user", "q", "ollama", "sr_ok")
    mid = save_reply("kwan", "a", "ollama", "sr_ok", uid)
    assert mid > uid
    assert [m["content"] for m in load_history("kwan", "sr_ok")] == ["q", "a"]


def test_save_reply_ไม่บันทึกเมื่อแถว_user_ถูกลบแล้ว():
    uid = save_message("kwan", "user", "q", "ollama", "sr_gone")
    assert truncate_from_db_id(uid)
    assert save_reply("kwan", "a", "ollama", "sr_gone", uid) == 0
    assert load_history("kwan", "sr_gone") == []


def test_save_reply_ต้องเป็นแถว_user_ของ_session_เดียวกัน():
    """กลุ่มควบคุม: id ที่มีอยู่แต่เป็นของ session อื่น/เป็นแถว assistant ต้องไม่นับว่าเป็น anchor"""
    other = save_message("kwan", "user", "q", "ollama", "sr_other")
    assert save_reply("kwan", "a", "ollama", "sr_mine", other) == 0
    aid = save_message("kwan", "assistant", "a0", "ollama", "sr_mine")
    assert save_reply("kwan", "a", "ollama", "sr_mine", aid) == 0
    assert [m["content"] for m in load_history("kwan", "sr_mine")] == ["a0"]


# ── ระดับ router: ผู้ใช้แก้ข้อความ (truncate) ระหว่างที่ LLM กำลังตอบ ─────────────────
def _post(path, body):
    with patch.object(chatmod, "remember") as rem, patch.object(chatmod, "teach", return_value=False):
        r = client.post(path, json=body)
    assert r.status_code == 200
    return _events(r.text), rem


def _chat(sid, **extra):
    return {"assistant": "kwan", "session_id": sid, "prompt": "คำถามที่ถูกแก้ทีหลัง", "provider": "ollama",
            "active_learning": False, "response_cache": False, **extra}


def test_เส้นหลัก_user_ถูก_truncate_ระหว่างตอบ_ไม่บันทึก_ไม่_remember(monkeypatch):
    sid = "rr_main"

    def stream(messages, **k):
        yield "ท่อน0 "
        truncate_from_db_id(_user_id(sid))
        yield "ท่อน1 "

    monkeypatch.setattr(chatmod, "stream_response", stream)
    evs, rem = _post("/api/chat", _chat(sid))
    assert load_history("kwan", sid) == [], "ห้ามมีแถว assistant กำพร้าของคำถามที่ถูกแก้ไปแล้ว"
    rem.assert_not_called()
    done = [e for e in evs if e.get("done")]
    assert len(done) == 1 and not done[0].get("message_id"), f"ยังต้องส่ง done ให้ client จบ stream (ไม่มี id): {done}"


def test_เส้น_agent_user_ถูก_truncate_ระหว่างตอบ_ไม่บันทึก_ไม่_remember(monkeypatch):
    import agents.orchestrator as orch
    sid = "rr_agent"

    def fake_run_agent(messages, **kw):
        yield ("chunk", "เริ่ม ")
        truncate_from_db_id(_user_id(sid))
        yield ("chunk", "จบ")

    monkeypatch.setattr(orch, "run_agent", fake_run_agent)
    evs, rem = _post("/api/chat", _chat(sid, tool_agent=True, provider="gemini"))
    assert load_history("kwan", sid) == []
    rem.assert_not_called()


def test_เส้น_error_user_ถูก_truncate_แล้ว_ไม่บันทึกฟองหยุดกลางคัน(monkeypatch):
    sid = "rr_error"

    def stream(messages, **k):
        yield "ท่อน0 "
        truncate_from_db_id(_user_id(sid))
        raise RuntimeError("ล่มหลังถูกแก้")

    monkeypatch.setattr(chatmod, "stream_response", stream)
    evs, _ = _post("/api/chat", _chat(sid))
    assert load_history("kwan", sid) == []
    err = [e for e in evs if "error" in e]
    assert len(err) == 1 and not err[0].get("message_id"), err


def test_regenerate_user_ถูก_truncate_ระหว่างตอบ_ไม่บันทึก(monkeypatch):
    sid = "rr_regen"
    save_message("kwan", "user", "U1", "ollama", sid)
    save_message("kwan", "assistant", "A1", "ollama", sid)
    u2 = save_message("kwan", "user", "U2", "ollama", sid)
    save_message("kwan", "assistant", "A2 เก่า", "ollama", sid)

    def stream(messages, **k):
        yield "ใหม่0 "
        truncate_from_db_id(u2)
        yield "ใหม่1 "

    monkeypatch.setattr(chatmod, "stream_response", stream)
    monkeypatch.setattr(chatmod, "search_memory", lambda *a, **k: "")
    _post("/api/regenerate", {"assistant": "kwan", "session_id": sid, "provider": "ollama"})
    assert [m["content"] for m in load_history("kwan", sid)] == ["U1", "A1"], "ห้ามต่อคำตอบใหม่ท้าย A1"


def test_กลุ่มควบคุม_ไม่ถูก_truncate_บันทึกและ_remember_ตามปกติ(monkeypatch):
    sid = "rr_ctrl"
    monkeypatch.setattr(chatmod, "stream_response", lambda m, **k: iter(["คำตอบปกติ"]))
    monkeypatch.setattr(chatmod, "should_remember", lambda p, r: (True, "ok"))
    evs, rem = _post("/api/chat", _chat(sid))
    assert [m["role"] for m in load_history("kwan", sid)] == ["user", "assistant"]
    rem.assert_called_once()
    assert next(e for e in evs if e.get("done"))["message_id"] > 0


def test_regenerate_error_หลัง_user_ถูก_truncate_ไม่บันทึกฟองหยุดกลางคัน(monkeypatch):
    """mutation จับได้ว่าเส้นนี้ไม่มีเทส (`_save_regen_crash`) — anchor เดียวกับเส้นปกติของ regenerate"""
    sid = "rr_regen_error"
    save_message("kwan", "user", "U1", "ollama", sid)
    save_message("kwan", "assistant", "A1", "ollama", sid)
    u2 = save_message("kwan", "user", "U2", "ollama", sid)

    def stream(messages, **k):
        yield "ใหม่0 "
        truncate_from_db_id(u2)
        raise RuntimeError("ล่มหลังถูกแก้")

    monkeypatch.setattr(chatmod, "stream_response", stream)
    monkeypatch.setattr(chatmod, "search_memory", lambda *a, **k: "")
    evs, _ = _post("/api/regenerate", {"assistant": "kwan", "session_id": sid, "provider": "ollama"})
    assert [m["content"] for m in load_history("kwan", sid)] == ["U1", "A1"]
    err = [e for e in evs if "error" in e]
    assert len(err) == 1 and not err[0].get("message_id"), err
