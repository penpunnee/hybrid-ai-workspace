"""เพดาน body ของ 18 เส้นที่เหลือ (ปิดครบ 2026-08-06)

ต่อจาก `tests/test_upload_body_cap.py` ที่ปิดไป 9 เส้นแรก — คราวนี้เก็บที่เหลือทั้งหมด
รวม `/api/chat` ซึ่งเป็นเส้นที่โดนหนักที่สุดในระบบและรับ `image_b64` ได้ด้วย

⚠️ **10 MB ไม่ใช่ตัวเลขใหม่** — ประกาศไว้ใน CLAUDE.md และบังคับใช้ใน `documents.py`
อยู่ก่อนแล้ว งานนี้คือบังคับใช้ให้ครบ · ค่าอยู่ที่ `utils.http_limits.MAX_BODY_BYTES`
ที่เดียว (เดิมประกาศซ้ำ 3 ไฟล์)
"""

import json

import pytest
from fastapi.testclient import TestClient

import server
from utils.http_limits import MAX_BODY_BYTES

client = TestClient(server.app)


def _over_cap_json() -> bytes:
    """JSON ที่ valid แต่ใหญ่เกินเพดาน — ต้องโดนตัดก่อนถึง parser"""
    filler = "x" * (MAX_BODY_BYTES + 1024)
    return json.dumps({"prompt": filler, "content": "", "text": ""}).encode()


# (method, path, body เล็กที่ใช้เป็นกลุ่มควบคุม)
ROUTES = [
    ("POST",  "/api/agent",            {"prompt": "hi"}),
    ("POST",  "/api/auth/login",       {"password": "x"}),
    ("POST",  "/api/chat",             {"prompt": "hi"}),
    ("POST",  "/api/regenerate",       {"assistant": "x"}),
    ("POST",  "/api/dream",            {"hours": 1}),
    ("POST",  "/api/feedback",         {"message_id": 1, "rating": "up"}),
    ("POST",  "/api/sandbox/python",   {"code": "1"}),
    ("POST",  "/api/fs/list",          {"path": ""}),
    ("POST",  "/api/fs/read",          {"path": "x"}),
    ("POST",  "/api/fs/write",         {"path": "x", "content": "y"}),
    ("POST",  "/api/fs/search",        {"pattern": "x"}),
    ("PATCH", "/api/sessions/a/s",     {"name": "n"}),
    ("POST",  "/api/pin/1",            {"pinned": True}),
    ("POST",  "/api/share",            {"assistant": "a", "session_id": "s"}),
    ("POST",  "/api/skills/extract",   {"content": "", "topic": "t"}),
    ("POST",  "/api/tts",              {"text": ""}),
    ("POST",  "/api/tts/stream",       {"text": ""}),
    ("POST",  "/api/admin/unlock",     {"ip": "1.2.3.4"}),
]

IDS = [f"{m} {p}" for m, p, _ in ROUTES]


@pytest.mark.parametrize("method,path,_small", ROUTES, ids=IDS)
def test_body_เกินเพดานต้องได้_413(method, path, _small):
    r = client.request(
        method, path,
        content=_over_cap_json(),
        headers={"Content-Type": "application/json"},
    )
    # 403 = เส้นที่ปฏิเสธก่อนแตะ body เลย (LAN-only) ซึ่งยิ่งดีกว่า
    assert r.status_code in (413, 403), f"{method} {path} → {r.status_code}: {r.text[:160]}"


@pytest.mark.parametrize("method,path,small", ROUTES, ids=IDS)
def test_body_เล็กต้องไม่โดน_413(method, path, small):
    """กลุ่มควบคุม — ถ้าเพดานกินของที่ควรผ่าน เทสข้างบนก็ยังเขียว

    ไม่สนใจว่าจะได้ 200/400/401/403/500 — สนใจแค่ว่า **ไม่ใช่ 413**
    """
    r = client.request(
        method, path,
        content=json.dumps(small).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code != 413, f"{method} {path} → 413 ทั้งที่ body เล็ก: {r.text[:160]}"


def test_เพดานประกาศที่เดียว():
    """เดิม 10 MB ถูกประกาศซ้ำ 3 ไฟล์ — ถ้าแตกอีกจะกลายเป็น 12 ที่

    (บทเรียนเดียวกับ `skill_discovery._SKILLS_DB` ที่ชี้ไฟล์เดียวกัน 2 ที่
    แล้วทำให้เทส patch ได้ตัวเดียว "เขียวโดยวัดผิดไฟล์")
    """
    from routers.documents import _MAX_BYTES
    from routers.memory import _MAX_BODY_BYTES
    from routers.skills import _MAX_UPLOAD_BYTES

    assert _MAX_BYTES is MAX_BODY_BYTES
    assert _MAX_BODY_BYTES is MAX_BODY_BYTES
    assert _MAX_UPLOAD_BYTES is MAX_BODY_BYTES
    assert MAX_BODY_BYTES == 10 * 1024 * 1024


def test_เส้นที่body_ไม่บังคับ_ยังทนกับbody_ว่างได้():
    """`/api/dream` กับ `/api/admin/unlock` ตั้งใจให้ body ไม่บังคับ

    ⚠️ เคสนี้เคยพังมาแล้วตอนปิดเพดานรอบก่อน — `except HTTPException: raise`
    ส่งต่อ **400** (JSON เสีย) ไปด้วย ทำลายเจตนาเดิม · ต้องเช็ค 413 เท่านั้น
    """
    for path in ("/api/dream", "/api/admin/unlock"):
        r = client.post(path, content=b"", headers={"Content-Type": "application/json"})
        assert r.status_code != 413, f"{path} body ว่าง → 413"
        assert r.status_code != 500, f"{path} body ว่าง → 500: {r.text[:160]}"

        r2 = client.post(path, content="{ ไม่ใช่ json".encode(),
                         headers={"Content-Type": "application/json"})
        assert r2.status_code not in (413, 500), f"{path} JSON เสีย → {r2.status_code}"
