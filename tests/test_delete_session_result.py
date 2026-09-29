"""DELETE /api/sessions/{assistant}/{sid} ต้องบอกผลจริง — เจอ 2026-09-29 ตอนเก็บกวาด probe บน prod

ใส่ชื่อผู้ช่วยผิด (ขาด emoji `🧡`) → ตอบ **200 `{"ok": true}` ทั้งที่ลบ 0 แถว** — "ไม่มีอะไรให้ลบ" หน้าตาเหมือน "ลบแล้ว"
(session ทดสอบค้างใน prod จนเช็ค DB เอง)

สัญญาที่เลือก (RFC 9110 §9.2.2: idempotent = ผลที่ตั้งใจเหมือนเดิม response ต่างได้ · §9.3.5 ไม่บังคับ 404):
- session ในระบบนี้ **ไม่มีแถวของตัวเอง** (`POST /api/sessions/{a}` แค่สุ่ม id) ⇒ "ว่าง" กับ "ไม่มี" แยกไม่ได้
  ⇒ ลบ 0 แถว = สำเร็จ แต่ต้องบอก `deleted` (เริ่มแชทใหม่ → 🗑️ ต้องไม่ขึ้น error)
- **ชื่อผู้ช่วยที่ไม่รู้จัก** (ไม่อยู่ใน config และไม่เคยมีข้อความใน DB) ตรวจได้แน่นอน ⇒ 404
  (ชื่อรุ่นเก่าที่ยังมีข้อความใน DB เช่น `kwan` ต้องลบได้ — prod มี 49 แถว)
"""
from fastapi.testclient import TestClient

import server
from assistants.config import ASSISTANTS
from utils.history import load_history, save_message

client = TestClient(server.app)
ASST = next(iter(ASSISTANTS))


def _delete(assistant: str, sid: str):
    return client.delete(f"/api/sessions/{assistant}/{sid}")


def test_ลบจริง_ต้องบอกจำนวนข้อความที่ลบ():
    sid = "del_count"
    save_message(ASST, "user", "q", "ollama", sid)
    save_message(ASST, "assistant", "a", "ollama", sid)
    r = _delete(ASST, sid)
    assert r.status_code == 200
    assert r.json() == {"ok": True, "deleted": 2}
    assert load_history(ASST, sid) == []


def test_ชื่อผู้ช่วยผิด_ต้อง_404_และไม่แตะของจริง():
    sid = "del_wrong_name"
    save_message(ASST, "user", "ของจริง", "ollama", sid)
    wrong = ASST.replace("🧡 ", "")            # เคสจริง 09-29: ลืม emoji
    assert wrong != ASST
    r = _delete(wrong, sid)
    assert r.status_code == 404, f"ชื่อผู้ช่วยที่ไม่รู้จักต้องไม่ตอบว่าสำเร็จ ({r.status_code} {r.text})"
    assert wrong in r.json()["detail"]
    assert len(load_history(ASST, sid)) == 1, "ต้องไม่ลบของผู้ช่วยตัวจริง"


def test_แชทใหม่ที่ยังว่าง_ลบได้_deleted_0():
    """กลุ่มควบคุม: เริ่มแชทใหม่ → 🗑️ ล้างแชท ต้องไม่เป็น error (session ยังไม่มีแถวใน DB เลย)"""
    sid = client.post(f"/api/sessions/{ASST}").json()["session_id"]
    r = _delete(ASST, sid)
    assert r.status_code == 200
    assert r.json() == {"ok": True, "deleted": 0}


def test_ชื่อผู้ช่วยรุ่นเก่าที่ยังมีข้อความใน_DB_ต้องลบได้():
    """กลุ่มควบคุม: ถ้าตรวจแค่ config จะลบ session ของ `kwan`/`ฟ้า` บน prod ไม่ได้อีกเลย"""
    legacy = "ผู้ช่วยรุ่นเก่า"
    assert legacy not in ASSISTANTS
    sid = "del_legacy"
    save_message(legacy, "user", "เก่า", "ollama", sid)
    r = _delete(legacy, sid)
    assert r.status_code == 200
    assert r.json() == {"ok": True, "deleted": 1}
    assert load_history(legacy, sid) == []


def test_ผู้ช่วยใน_config_ที่ยังไม่มีข้อความเลย_ลบแชทใหม่ได้(monkeypatch):
    """กลุ่มควบคุม: ผู้ช่วยที่เพิ่งเพิ่มใน config (หรือ DB ใหม่เอี่ยม) ยังไม่มีแถวใดๆ —
    ถ้าตัดสิน "รู้จัก" จาก DB อย่างเดียว เริ่มแชทใหม่ → 🗑️ จะได้ 404 (mutation จับได้)"""
    import routers.sessions as rs
    fresh = "ผู้ช่วยใหม่เอี่ยม"
    monkeypatch.setitem(rs.ASSISTANTS, fresh, {})
    sid = client.post(f"/api/sessions/{fresh}").json()["session_id"]
    r = _delete(fresh, sid)
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "deleted": 0}
