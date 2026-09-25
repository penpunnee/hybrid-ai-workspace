"""input ผิดชนิดต้องได้ 400/ok:false ไม่ใช่ 500 (audit 2026-09-24 MEDIUM กลุ่ม `int()` ดิบ · `.strip()` บน non-str)

500 = traceback ลง log + ดูเหมือน server พัง ทั้งที่แค่ client ส่งของผิด · `skills_delete` `.`/`..` +
`delete_file=true` → `os.remove(<dir>)` = 500 (macOS PermissionError · Linux IsADirectoryError)
"""
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server
import routers.documents as docs
import routers.sandbox as sb

client = TestClient(server.app)


@pytest.fixture
def seen(monkeypatch):
    box = {}
    monkeypatch.setattr(docs, "retrieve_chunks", lambda q, top_k=5, source_filter=None: box.update(top_k=top_k) or [])
    monkeypatch.setattr(sb, "search_files", lambda p, **k: box.update(k) or {"ok": True, "matches": []})
    return box


@pytest.mark.parametrize("raw,expected", [("abc", 5), (None, 5), (99999, 50), (0, 1), ("7", 7)])
def test_documents_search_top_k(seen, raw, expected):
    r = client.post("/api/documents/search", json={"query": "x", "top_k": raw})
    assert r.status_code == 200, r.text
    assert seen["top_k"] == expected


def test_fs_search_max_results_ขยะ_ไม่_500(seen):
    r = client.post("/api/fs/search", json={"pattern": "x", "max_results": "abc", "max_per_file": [1]})
    assert r.status_code == 200, r.text
    assert seen["max_results"] == 50 and seen["max_per_file"] == 5


@pytest.mark.parametrize("method,path,body", [
    ("POST", "/api/tts", {"text": 123}),
    ("POST", "/api/tts/stream", {"text": ["a"]}),
    ("POST", "/api/memory/teach/kwan", {"text": {"a": 1}}),
    ("PATCH", "/api/sessions/kwan/s_input400", {"name": 5}),
    ("POST", "/api/skills/extract", {"content": {"x": 1}, "topic": 3}),
])
def test_ฟิลด์ข้อความที่ไม่ใช่_str_ต้องไม่_500(method, path, body):
    r = client.request(method, path, json=body)
    assert r.status_code != 500, f"{method} {path} → {r.status_code} {r.text[:120]}"
    assert r.status_code in (200, 400)
    if r.status_code == 200:
        j = r.json()
        assert j.get("error") or j.get("ok") is False, j


@pytest.mark.parametrize("skill_id", ["%2E", "%2E%2E", "%252E"])   # httpx normalize `.`/`..` ใน path — ต้อง encode ถึงจะถึง handler (curl --path-as-is ก็ถึง)
def test_skills_delete_ไดเรกทอรี_ต้อง_400(skill_id):
    r = client.delete(f"/api/skills/{skill_id}?delete_file=true")
    assert r.status_code == 400, f"{r.status_code} {r.text[:120]}"
