"""Tests สำหรับ routers/vault.py — path ของ vault ต้องมาจาก config ไม่ใช่จาก body

ทำไมสำคัญ (security): `POST /api/vault/sync` เดิมรับ `vault_path` จาก body แล้วส่งต่อ
ให้ `sync_vault()` ตรงๆ → ผู้เรียก (หรือใครก็ตามใน LAN ซึ่ง bypass auth) ชี้ไปโฟลเดอร์ไหน
ก็ได้ในคอนเทนเนอร์ → `rglob("*.md")` ดูดเข้า ChromaDB แล้วอ่านกลับผ่าน `/api/vault/search`
= อ่านไฟล์นอก vault ได้ + ยัดขยะลง index ที่ระบบใช้ตอบคำถาม (index poisoning)

ผู้เรียกจริงมีที่เดียวและส่ง body ว่าง (`app.tsx:522` → `JSON.stringify({})`)
→ เลิกรับ path จาก body ไม่กระทบใคร
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from starlette.testclient import TestClient

import routers.vault as vault_router
import server

client = TestClient(server.app)


def test_sync_ignores_caller_supplied_path(monkeypatch):
    seen = {}

    def _fake_sync(*args, **kwargs):
        seen["args"] = args
        seen["kwargs"] = kwargs
        return {"ok": True, "total": 0}

    monkeypatch.setattr(vault_router, "sync_vault", _fake_sync)
    r = client.post("/api/vault/sync", json={"vault_path": "/etc"})

    assert r.status_code == 200
    passed = list(seen.get("args", ())) + list(seen.get("kwargs", {}).values())
    assert "/etc" not in passed, f"path จาก body หลุดเข้า sync_vault: {passed}"


def test_sync_still_works_with_empty_body(monkeypatch):
    """ผู้เรียกจริงส่ง {} — ต้องไม่พังและยังใช้ path จาก config"""
    monkeypatch.setattr(vault_router, "sync_vault", lambda *a, **k: {"ok": True, "total": 7})
    r = client.post("/api/vault/sync", json={})
    assert r.status_code == 200 and r.json()["total"] == 7


def test_sync_survives_non_json_body(monkeypatch):
    monkeypatch.setattr(vault_router, "sync_vault", lambda *a, **k: {"ok": True, "total": 0})
    r = client.post("/api/vault/sync", content=b"not json",
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 200
