"""เส้น {"error"} ต้องบอก id ของแถวที่บันทึกไว้ + ห้ามทิ้ง user เดี่ยว — ต่อจาก backlog dbId (2026-09-29)

เดิม: stream ล้ม → `_save_crash` บันทึกแถว "⚠️ การตอบหยุดกลางคัน" แล้ว**ทิ้ง id** · yield error **ก่อน** บันทึก
⇒ ฟอง AI ไม่มี dbId (🗑️ คู่นั้นไม่ขึ้นจนรีโหลด) · เส้น agent โยน exception **ไม่บันทึกเลย** ⇒ แถว user ค้างเดี่ยว
แก้: บันทึกก่อน แล้วส่ง {"error", "message_id"} — ทุกเส้น: หลัก · fallback ล้มซ้ำ · agent · regenerate
"""
import json
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

import routers.chat as chatmod
import server
from utils.history import _get_conn, load_history, save_message
from utils.llm import GeminiQuotaExhausted

client = TestClient(server.app)


def _events(text):
    return [json.loads(ln[6:]) for ln in text.splitlines() if ln.startswith("data: ")]


def _row(i):
    conn = _get_conn()
    try:
        return conn.execute("SELECT role, content, session_id FROM messages WHERE id = ?", (i,)).fetchone()
    finally:
        conn.close()


def _post(path, body):
    with patch.object(chatmod, "remember"), patch.object(chatmod, "teach", return_value=False):
        r = client.post(path, json=body)
    assert r.status_code == 200
    return _events(r.text)


def _assert_error_carries_saved_id(evs, sid, needle):
    err = [e for e in evs if "error" in e]
    assert len(err) == 1, evs
    mid = err[0].get("message_id")
    assert isinstance(mid, int) and mid > 0, f"error ต้องมี message_id ของแถวที่บันทึกไว้: {err[0]}"
    role, content, row_sid = _row(mid)
    assert (role, row_sid) == ("assistant", sid) and needle in content, (role, content, row_sid)


def _boom(*a, **k):
    raise RuntimeError("LLM ล่มในเทส")


def _chat(sid, **extra):
    return {"assistant": "kwan", "session_id": sid, "prompt": "ถามแล้วล่ม", "provider": "ollama",
            "active_learning": False, "response_cache": False, **extra}


def test_เส้นหลัก_error_มี_message_id(monkeypatch):
    monkeypatch.setattr(chatmod, "stream_response", _boom)
    sid = "err_mid_main"
    _assert_error_carries_saved_id(_post("/api/chat", _chat(sid)), sid, "LLM ล่มในเทส")


def test_fallback_ล้มซ้ำ_error_มี_message_id():
    calls = {"n": 0}

    def quota_then_boom(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise GeminiQuotaExhausted("429")
        raise RuntimeError("fallback ล่มในเทส")

    sid = "err_mid_fallback"
    with patch("routers.chat.stream_response", side_effect=quota_then_boom), \
         patch("reasoning.router.route", return_value=MagicMock(provider="ollama", model="", reason="t")), \
         patch("reasoning.classifier.needs_internet", return_value=False):
        evs = _post("/api/chat", _chat(sid, provider="gemini"))
    assert calls["n"] == 2, "ต้องเข้าเส้น fallback จริง"
    _assert_error_carries_saved_id(evs, sid, "fallback ล่มในเทส")


def test_agent_โยน_exception_ต้องบันทึกคู่_ไม่ทิ้ง_user_เดี่ยว(monkeypatch):
    import agents.orchestrator as orch

    def fake_run_agent(messages, **kw):
        yield ("chunk", "เริ่มตอบ ")
        raise RuntimeError("agent ล่มในเทส")

    monkeypatch.setattr(orch, "run_agent", fake_run_agent)
    sid = "err_mid_agent"
    evs = _post("/api/chat", _chat(sid, tool_agent=True, provider="gemini"))
    roles = [m["role"] for m in load_history("kwan", sid)]
    assert roles == ["user", "assistant"], f"agent ล้มแล้วต้องไม่เหลือ user เดี่ยว ({roles})"
    _assert_error_carries_saved_id(evs, sid, "agent ล่มในเทส")
    assert "เริ่มตอบ" in _row(next(e for e in evs if "error" in e)["message_id"])[1], "ต้องเก็บส่วนที่ตอบไปแล้วด้วย"


def test_regenerate_error_มี_message_id(monkeypatch):
    sid = "err_mid_regen"
    save_message("kwan", "user", "U1", "ollama", sid)
    save_message("kwan", "assistant", "A1", "ollama", sid)
    monkeypatch.setattr(chatmod, "stream_response", _boom)
    monkeypatch.setattr(chatmod, "search_memory", lambda *a, **k: "")
    evs = _post("/api/regenerate", {"assistant": "kwan", "session_id": sid, "provider": "ollama"})
    _assert_error_carries_saved_id(evs, sid, "LLM ล่มในเทส")
