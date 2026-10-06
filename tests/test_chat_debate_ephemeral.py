"""Debate = แบบชั่วคราว (ปอยเคาะ A · 10-06 · devlog [ต่อ 135–136])

DB prod 10-06: ฟ้อง Debate (3 ฟ้องขนานต่อรอบ) วิ่ง /api/chat เต็มรูป ⇒ session `debate_*` ขึ้นแถบข้าง · ซ้อน `debate_debate_` ·
คำถามเดียวกันบันทึก 3 ชุด · teach/remember/preference/auto-learn ×3 · ประวัติปนคำตอบโมเดลอื่น

กติกา: ตัดสินจากธง `debate: true` (boolean จริง — ไม่ใช่ชื่อ session) ⇒ ไม่บันทึก DB · ไม่อ่านประวัติ · ไม่ remember/teach/
preference/auto-learn · ไม่ push working memory · ไม่ shadow log · ไม่นับ access_count ของความจำที่ดึงมา ·
ปิดทางวาดรูป/cache/agent/plan/active learning ที่บันทึกเอง · แชทปกติ (ไม่มีธง) ต้องยังทำครบทุกเส้น
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("UI_PASSWORD", "")

from fastapi.testclient import TestClient

import routers.chat as chatmod
import server
from utils.history import _get_conn

client = TestClient(server.app)
LONG = "คำตอบยาวพอให้ผ่านเกณฑ์ auto-learn " * 8   # > 100 ตัวอักษร


def _events(text):
    return [json.loads(ln[6:]) for ln in text.splitlines() if ln.startswith("data: ")]


def _count_messages():
    conn = _get_conn()
    try:
        return conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    finally:
        conn.close()


@pytest.fixture
def rec(monkeypatch):
    """แทนทุกเส้นข้างเคียงด้วยตัวจด + เปิด gate ให้ผ่านหมด ⇒ แชทปกติต้องวิ่งครบทุกเส้น"""
    calls: dict[str, list] = {}

    def recorder(name, ret=None):
        def f(*a, **kw):
            calls.setdefault(name, []).append((a, kw))
            return ret
        return f

    ids = iter(range(10_000, 20_000))

    def save_message(*a, **kw):
        calls.setdefault("save_message", []).append((a, kw))
        return next(ids)

    def save_reply(*a, **kw):
        calls.setdefault("save_reply", []).append((a, kw))
        return next(ids)

    monkeypatch.setattr(chatmod, "save_message", save_message)
    monkeypatch.setattr(chatmod, "save_reply", save_reply)
    monkeypatch.setattr(chatmod, "load_history", recorder("load_history", []))
    monkeypatch.setattr(chatmod, "push_working", recorder("push_working"))
    monkeypatch.setattr(chatmod, "remember", recorder("remember"))
    monkeypatch.setattr(chatmod, "teach", recorder("teach", False))
    monkeypatch.setattr(chatmod, "save_preference", recorder("save_preference", True))
    monkeypatch.setattr(chatmod, "save_lesson", recorder("save_lesson", True))
    monkeypatch.setattr(chatmod, "recall", recorder("recall", ""))
    monkeypatch.setattr(chatmod, "_store_reply_meta", recorder("store_reply_meta"))
    monkeypatch.setattr(chatmod, "spawn_bg", lambda fn, *a, **kw: fn())          # เธรดเบื้องหลังรันทันที
    # gate ที่ตัดสินจากเนื้อหา → ผ่านหมด (เทสคุม "ธง" ไม่ใช่ตัวกรองเนื้อหา)
    monkeypatch.setattr(chatmod, "should_remember", lambda p, r: (True, ""))
    monkeypatch.setattr(chatmod, "detect_preferences", lambda p: [("ภาษา", "ไทย")])
    monkeypatch.setattr(chatmod, "should_auto_learn", lambda p: (True, ""))
    monkeypatch.setattr(chatmod, "clean_lesson", lambda raw: "บทเรียน")
    monkeypatch.setattr(chatmod, "_shadow_should_log", lambda p, is_test_request=False: True)
    import utils.skills_shadow as shadow
    monkeypatch.setattr(shadow, "observe", recorder("shadow"))
    import utils.response_cache as rc
    monkeypatch.setattr(rc, "lookup", recorder("cache_lookup", None))

    def stream(messages, **kw):
        calls.setdefault("llm", []).append((messages, kw))
        yield LONG

    monkeypatch.setattr(chatmod, "stream_response", stream)
    return calls


def _body(debate, **extra):
    b = {"assistant": "kwan", "prompt": "อธิบายเรื่องดาวอังคารหน่อย", "provider": "ollama"}
    if debate is not None:
        b["debate"] = debate
    else:
        b["session_id"] = "s_normal"
    b.update(extra)
    return b


def _post(body):
    r = client.post("/api/chat", json=body)
    assert r.status_code == 200
    return _events(r.text)


# เส้นที่ Debate ต้องไม่แตะ · แชทปกติต้องแตะ (ปอยสั่ง: คุมทีละเส้น)
PATHS = ["save_message", "save_reply", "load_history", "push_working", "remember", "teach",
         "save_preference", "save_lesson", "shadow", "store_reply_meta"]


@pytest.mark.parametrize("path", PATHS)
def test_debate_ไม่แตะเส้น(rec, path):
    evs = _post(_body(True))
    assert [e for e in evs if e.get("done")], "ยังต้องส่ง done ให้ client จบ stream"
    assert rec.get("llm"), "ต้องเรียก LLM จริง (Debate ยังตอบ)"
    assert path not in rec, f"Debate ต้องไม่แตะ {path}: {rec.get(path)}"


@pytest.mark.parametrize("path", PATHS)
def test_แชทปกติ_ยังแตะเส้นเดิม(rec, path):
    _post(_body(None))
    assert rec.get(path), f"แชทปกติต้องยังทำ {path} (กลุ่มควบคุม — ไม่งั้นเทสฝั่ง Debate ผ่านฟรี)"


def test_debate_done_มี_timings_ไม่มี_message_id(rec):
    done = [e for e in _post(_body(True)) if e.get("done")]
    assert len(done) == 1 and done[0].get("message_id") is None
    assert "timings" in done[0], "ทางแยกของ Debate ต้องส่ง done เต็ม (timings/usage) ไม่ใช่ทาง user-ถูกลบ"


def test_debate_ไม่นับ_access_count_และไม่ใช้_session_จริง(rec):
    _post(_body(True))
    (a, kw), = rec["recall"]
    assert kw.get("track_access") is False, f"Debate ดึงความจำต้องไม่นับ access_count: {kw}"
    assert kw.get("session_id") == "", "Debate ใช้ session ว่างภายใน (prod มี session 'default' จริง)"


def test_แชทปกติ_ยังนับ_access_count(rec):
    _post(_body(None))
    (a, kw), = rec["recall"]
    assert kw.get("track_access", True) is True and kw.get("session_id") == "s_normal"


def test_ธงต้องเป็น_boolean_จริง(rec):
    """"true" (string) ⇒ ไม่นับเป็น Debate — ตัดสินจากธง ไม่ใช่ค่าที่ดูเหมือน"""
    b = _body("true")
    b["session_id"] = "s_str"
    _post(b)
    assert rec.get("save_message") and rec.get("remember")


def test_debate_ไม่บันทึกลง_DB_จริง(rec, monkeypatch):
    """ไม่พึ่งตัวจด: คืน save_message/save_reply ของจริง แล้วนับแถวทั้งตาราง"""
    from utils import history
    monkeypatch.setattr(chatmod, "save_message", history.save_message)
    monkeypatch.setattr(chatmod, "save_reply", history.save_reply)
    before = _count_messages()
    _post(_body(True))
    assert _count_messages() == before


def test_debate_prompt_วาดรูป_ไม่สร้างรูป_ไม่บันทึก(rec, monkeypatch):
    import utils.image_gen as ig
    made = []
    monkeypatch.setattr(ig, "detect_image_request", lambda p: True)
    monkeypatch.setattr(ig, "generate_image", lambda *a, **k: made.append(a) or {"ok": False, "error": "x"})
    _post(_body(True, prompt="วาดรูปแมว"))
    assert made == [], "Debate 3 ฟ้อง = สร้างรูป 3 ครั้ง (กินโควตา)"
    assert "save_message" not in rec


def test_debate_กับ_tool_agent_ไม่เข้าเส้น_agent(rec, monkeypatch):
    import agents.orchestrator as orch
    ran = []
    monkeypatch.setattr(orch, "run_agent", lambda *a, **k: ran.append(1) or iter(()))
    _post(_body(True, tool_agent=True, plan_mode=True, agent_mode=True))
    assert ran == [], "Debate เทียบโมเดลตรงๆ — ห้ามเข้าเส้น agent (บันทึกเองผ่าน persist_agent_turn)"
    assert rec.get("llm") and "save_message" not in rec


def test_debate_ไม่ใช้_response_cache(rec):
    _post(_body(True))
    assert "cache_lookup" not in rec, "cache hit บันทึกข้อความเอง"


def test_debate_ตัดสายกลาง_stream_ไม่บันทึก(rec, monkeypatch):
    def boom(messages, **kw):
        yield "ท่อนแรก "
        raise RuntimeError("provider ล้ม")
    monkeypatch.setattr(chatmod, "stream_response", boom)
    _post(_body(True))
    assert "save_message" not in rec and "save_reply" not in rec, "_save_crash ต้องไม่บันทึกฟอง error ของ Debate"


# ── ระดับ store: track_access=False ต้องไม่ bump ────────────────────────────────────────

@pytest.mark.parametrize("track, bumped", [(True, True), (False, False)])
def test_search_entries_track_access(monkeypatch, track, bumped):
    import memory.store as store
    import utils.memory as um

    class _Col:
        def query(self, **kw):
            return {"ids": [["m1"]], "documents": [["ดาวอังคาร"]], "metadatas": [[{"confidence": 0.9}]],
                    "distances": [[0.05]]}

    monkeypatch.setattr(store, "_get_chroma_client", lambda: object())
    monkeypatch.setattr(um, "get_collection", lambda client, name: _Col())
    monkeypatch.setattr(store, "key_hits", lambda *a, **k: ([], []))
    monkeypatch.setattr(store, "_key_only_from_primary", lambda *a, **k: ([], []))
    monkeypatch.setattr(store, "merge_max", lambda cands, ks, **k: cands)
    hits = []
    monkeypatch.setattr(store, "bump_access_count", lambda a, ids: hits.append(ids))
    res = store.search_entries("kwan", "ดาวอังคาร", track_access=track)
    assert res and (bool(hits) is bumped)
