"""Router smoke tests — uncovered, dependency-light endpoints ผ่าน TestClient

ใช้ TestClient(app) แบบไม่ with (lifespan ไม่ fire → ไม่ค้างต่อ ChromaDB/scheduler)
เหมือน pattern ใน test_main.py. ครอบ feedback router + endpoint ที่ degrade ได้
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["UI_PASSWORD"] = ""

import pytest
from fastapi.testclient import TestClient

from server import app
import utils.feedback as feedback
from utils.history import _get_conn

client = TestClient(app)


@pytest.fixture
def clean_feedback(monkeypatch):
    # กัน propagate thread แตะ ChromaDB จริง
    monkeypatch.setattr(feedback, "_propagate_to_memory", lambda *a, **k: None)
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM feedback")
        conn.commit()
    finally:
        conn.close()
    yield


# ── POST /api/feedback ────────────────────────────────────────────────────────
def test_feedback_submit_ok(clean_feedback):
    r = client.post("/api/feedback", json={
        "assistant": "kwan", "session_id": "s1", "message_id": 101, "rating": "up",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["rating"] == "up"


def test_feedback_submit_missing_message_id(clean_feedback):
    r = client.post("/api/feedback", json={"assistant": "kwan", "rating": "up"})
    assert r.status_code == 400


def test_feedback_submit_invalid_rating(clean_feedback):
    r = client.post("/api/feedback", json={"message_id": 5, "rating": "meh"})
    assert r.status_code == 400


# ── GET /api/feedback/{id} ────────────────────────────────────────────────────
def test_feedback_get_one_404_when_missing(clean_feedback):
    r = client.get("/api/feedback/999999")
    assert r.status_code == 404


def test_feedback_get_one_after_submit(clean_feedback):
    client.post("/api/feedback", json={
        "assistant": "kwan", "session_id": "s1", "message_id": 202, "rating": "down",
        "comment": "ไม่ดี",
    })
    r = client.get("/api/feedback/202")
    assert r.status_code == 200
    assert r.json()["rating"] == "down"
    assert r.json()["comment"] == "ไม่ดี"


# ── GET /api/feedback/stats ───────────────────────────────────────────────────
def test_feedback_stats(clean_feedback):
    client.post("/api/feedback", json={"assistant": "kwan", "message_id": 1, "rating": "up"})
    client.post("/api/feedback", json={"assistant": "kwan", "message_id": 2, "rating": "down"})
    r = client.get("/api/feedback/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert body["ups"] == 1 and body["downs"] == 1


def test_feedback_low_rated_shape(clean_feedback):
    r = client.get("/api/feedback/low-rated")
    assert r.status_code == 200
    assert "items" in r.json()


# ── GET endpoints ที่ degrade ได้เมื่อ service ไม่พร้อม ───────────────────────
def test_documents_list_degrades_gracefully():
    # ChromaDB ไม่พร้อมใน test → ควรคืน list ว่าง ไม่ 500
    r = client.get("/api/documents")
    assert r.status_code == 200


def test_config_endpoint():
    r = client.get("/api/config")
    assert r.status_code == 200
