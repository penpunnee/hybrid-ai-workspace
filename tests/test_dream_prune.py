"""Tests สำหรับ Step 1 — retention-score prune + capacity cap (Dream Phase 3.5)

หลักการ: episodic memory ใน ChromaDB ไม่เคยถูกลบจริง (decay แค่ลด confidence)
→ บวมเรื่อยๆ. prune ลบ memory ที่ "ตายจริง" + cap จำนวนต่อ assistant
โดยให้คะแนน retention = importance(confidence) + recency + frequency
verified/user_taught = ไม่ลบเด็ดขาด
"""
import os
import sys
from types import SimpleNamespace
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import utils.dream as dream


def _meta(conf, verified=False, access=0, days_old=0):
    ts = (datetime.now() - timedelta(days=days_old)).isoformat()
    return {
        "confidence": conf, "verified": verified, "access_count": access,
        "created_at": ts, "last_accessed": ts, "timestamp": ts,
    }


class _Col:
    def __init__(self, ids, metas):
        self._ids, self._metas = ids, metas
        self.deleted = []

    def get(self, **k):
        return {"ids": self._ids, "metadatas": self._metas}

    def delete(self, ids=None, **k):
        self.deleted.extend(ids or [])


def _client(col):
    return SimpleNamespace(
        list_collections=lambda: [SimpleNamespace(name="memory_logic")],
        get_collection=lambda name: col,
    )


# ── _retention_score ──
def test_retention_score_verified_is_one():
    assert dream._retention_score({"verified": True}) == 1.0


def test_retention_score_fresh_beats_stale():
    fresh = dream._retention_score(_meta(0.9, access=5, days_old=0))
    stale = dream._retention_score(_meta(0.2, access=0, days_old=60))
    assert fresh > stale


# ── memory_prune: floor-prune memory ที่ตายจริง ──
def test_prune_deletes_dead_keeps_verified_and_fresh(monkeypatch):
    col = _Col(
        ids=["verified1", "dead1", "fresh1"],
        metas=[
            _meta(0.95, verified=True),          # keep — verified
            _meta(0.1, access=0, days_old=40),   # dead → ลบ (conf≤0.2 + เก่า + ไม่เคยใช้)
            _meta(0.8, access=2, days_old=1),    # keep — สด+ มั่นใจ
        ],
    )
    monkeypatch.setattr(dream, "_get_client", lambda: _client(col))
    res = dream.memory_prune(cap=500, max_age_days=30)
    assert "dead1" in col.deleted
    assert "verified1" not in col.deleted
    assert "fresh1" not in col.deleted
    assert res["pruned"] == 1


# ── memory_prune: capacity cap → ลบ retention ต่ำสุด ──
def test_prune_capacity_cap_evicts_lowest(monkeypatch):
    col = _Col(
        ids=["low", "mid", "high"],
        metas=[
            _meta(0.3, access=0, days_old=20),   # retention ต่ำสุด
            _meta(0.6, access=1, days_old=5),    # กลาง
            _meta(0.9, access=4, days_old=0),    # สูงสุด
        ],
    )
    monkeypatch.setattr(dream, "_get_client", lambda: _client(col))
    res = dream.memory_prune(cap=1, max_age_days=30)  # ไม่มีตัว "ตาย" → cap ลบ 2 ต่ำสุด
    assert set(col.deleted) == {"low", "mid"}
    assert "high" not in col.deleted
    assert res["pruned"] == 2


def test_prune_no_client_safe(monkeypatch):
    monkeypatch.setattr(dream, "_get_client", lambda: None)
    assert dream.memory_prune()["pruned"] == 0
