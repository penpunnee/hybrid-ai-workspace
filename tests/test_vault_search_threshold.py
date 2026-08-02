"""Test: search_vault() ต้องมีเกณฑ์ความเกี่ยวข้อง ไม่ใช่คืน top-N เสมอ

บั๊กจริง (เห็นกับตาบนหน้าเว็บ 2026-08-02): ถาม "ราคาน้ำมันเบนซินวันนี้เท่าไหร่"
แต่ระบบขึ้น citation อ้างโน้ตส่วนตัวใน Obsidian vault ที่ไม่เกี่ยวข้องเลย
(thai-embedding-chromadb / google-drive-icon-cr / frontend-payload-diet)

ต้นเหตุ: `search_vault()` ทิ้ง `distances` ที่ ChromaDB คืนมาทั้งดุ้น แล้วคืน
top-N ตรงๆ → ไม่ว่าคำถามจะเกี่ยวกับ vault หรือไม่ ก็ได้โน้ต 3 อันเสมอ
แล้วถูกยัดเข้า context + โชว์เป็นแหล่งอ้างอิง

ผลกระทบ: (1) คำตอบมีแหล่งอ้างอิงมั่วให้ผู้ใช้สับสน (2) **ชื่อโน้ตส่วนตัว
รั่วออกมาโชว์ในคำถามที่ไม่เกี่ยวข้อง** (3) เปลือง context window

วัดจริงบน prod (หลังแก้ embedding ไทยแล้ว):
  - คำถามไม่เกี่ยวกับ vault: 0.13, 0.14, 0.19, 0.20, 0.40
  - คำถามที่ตรงกับโน้ตจริง:  0.72, 0.74 (ตัวที่ 2-3 ร่วงไป 0.24-0.38)
"""
import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils.obsidian_sync as ov


def _fake_col(pairs):
    """pairs = [(title, score)] — score คือ 1-distance"""
    col = MagicMock()
    col.count.return_value = len(pairs)
    col.query.return_value = {
        "documents": [[f"เนื้อหาของ {t}" for t, _ in pairs]],
        "metadatas": [[{"title": t, "path": f"{t}.md"} for t, _ in pairs]],
        "distances": [[1 - s for _, s in pairs]],
    }
    return col


def test_irrelevant_notes_are_filtered_out(monkeypatch):
    """คำถามไม่เกี่ยวกับ vault → ต้องไม่คืนโน้ตอะไรเลย (ไม่ใช่คืน top-3 มั่วๆ)"""
    monkeypatch.setattr(ov, "_get_collection", lambda: _fake_col([
        ("thai-embedding-chromadb", 0.192),
        ("google-drive-icon-cr", 0.143),
        ("frontend-payload-diet", 0.133),
    ]))
    out = ov.search_vault("ราคาน้ำมันเบนซินวันนี้เท่าไหร่", n=3)
    assert out == [], f"โน้ตไม่เกี่ยวข้องต้องถูกกรองทิ้ง ได้ {[o['title'] for o in out]}"


def test_relevant_note_still_returned(monkeypatch):
    """โน้ตที่ตรงจริงต้องยังได้ — ไม่งั้นฟีเจอร์ vault ตายทั้งระบบ"""
    monkeypatch.setattr(ov, "_get_collection", lambda: _fake_col([
        ("thai-embedding-chromadb", 0.722),
        ("home", 0.381),
        ("bundle-splitting-lessons", 0.334),
    ]))
    out = ov.search_vault("บั๊ก embedding ภาษาไทย ChromaDB", n=3)
    titles = [o["title"] for o in out]
    assert "thai-embedding-chromadb" in titles, "โน้ตที่ตรงจริงต้องถูกคืน"
    assert "bundle-splitting-lessons" not in titles, "ตัวที่คะแนนต่ำต้องถูกตัด"


def test_score_is_exposed_for_callers(monkeypatch):
    """คืนคะแนนมาด้วย เพื่อให้ citation/ดีบักตรวจสอบได้"""
    monkeypatch.setattr(ov, "_get_collection", lambda: _fake_col([
        ("google-drive-icon-cr", 0.739),
    ]))
    out = ov.search_vault("Google Drive ทำให้เกิดไฟล์ Icon", n=3)
    assert out and "score" in out[0]
    assert out[0]["score"] == 0.739


def test_threshold_configurable_via_env(monkeypatch):
    """ปรับเกณฑ์ได้ทาง env โดยไม่ต้องแก้โค้ด"""
    monkeypatch.setattr(ov, "_VAULT_MIN_SCORE", 0.1)
    monkeypatch.setattr(ov, "_get_collection", lambda: _fake_col([
        ("อะไรก็ได้", 0.192),
    ]))
    out = ov.search_vault("คำถามอะไรก็ได้", n=3)
    assert len(out) == 1, "ลดเกณฑ์แล้วต้องคืนโน้ตที่เดิมถูกกรอง"


def test_no_collection_returns_empty(monkeypatch):
    monkeypatch.setattr(ov, "_get_collection", lambda: None)
    assert ov.search_vault("อะไรก็ได้") == []
