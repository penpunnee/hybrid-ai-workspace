"""Phase 1 (Light Sleep) — resilience ต่อ collection ที่ get_collection() พัง

บั๊กจริง (เจอ 2026-07-13 ตรวจ Dream Cycle บน prod): เดิม light_sleep() ครอบ
loop สแกน collection ทั้งหมดด้วย try/except เดียว — พอ Thai-embedding
migration (2026-07-09) ทิ้ง collection backup ไว้ (`*__minilm_backup_*`,
ยังผูก default embedder เดิม) ก็ conflict กับ ollama embedding function
ปัจจุบันทันทีที่เจอ collection แรก → ทั้งฟังก์ชัน return [] แม้ collection อื่น
(memory_kwan/memory_logic ตัวจริง) จะมีข้อมูลอยู่ก็ตาม — Dream ประมวลผล
memory เป็น 0 ทุกคืนแบบเงียบๆ 4+ คืนติด ต้องกัน per-collection เหมือน
memory_decay/memory_prune ที่ทำถูกอยู่แล้ว
"""
import os
import sys
from types import SimpleNamespace
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils.dream as dream


def _doc(ts):
    return {"timestamp": ts, "assistant": "logic"}


class _BrokenCol:
    def get(self, **k):
        raise Exception(
            "An embedding function already exists in the collection configuration... "
            "Embedding function conflict: new: ollama vs persisted: default"
        )


class _HealthyCol:
    def __init__(self, ids, docs, metas):
        self._ids, self._docs, self._metas = ids, docs, metas

    def get(self, **k):
        return {"ids": self._ids, "documents": self._docs, "metadatas": self._metas}


def test_light_sleep_skips_broken_collection_keeps_healthy_ones(monkeypatch):
    now = datetime.now().isoformat()
    healthy = _HealthyCol(
        ids=["m1"], docs=["สวัสดีครับ"], metas=[_doc(now)],
    )
    cols = {
        "memory_kwan__minilm_backup_20260709": _BrokenCol(),
        "memory_logic": healthy,
    }
    client = SimpleNamespace(
        list_collections=lambda: [
            SimpleNamespace(name="memory_kwan__minilm_backup_20260709"),
            SimpleNamespace(name="memory_logic"),
        ],
        get_collection=lambda name: cols[name],
    )
    monkeypatch.setattr(dream, "_get_client", lambda: client)

    out = dream.light_sleep(hours=24)

    assert len(out) == 1, "collection ที่พังต้องไม่ทำให้ collection ที่ดีหายไปด้วย"
    assert out[0]["collection"] == "memory_logic"
    assert out[0]["doc"] == "สวัสดีครับ"


def test_light_sleep_broken_first_collection_does_not_abort_scan(monkeypatch):
    """เคสตรงกับ prod จริง: collection พังมาก่อน (ตามลำดับ list_collections) —
    เดิม exception จาก collection แรกทำทั้ง loop หยุดทันที"""
    now = datetime.now().isoformat()
    cols = {
        "memory_broken": _BrokenCol(),
        "memory_kwan": _HealthyCol(ids=["a"], docs=["real memory"], metas=[_doc(now)]),
    }
    client = SimpleNamespace(
        list_collections=lambda: [
            SimpleNamespace(name="memory_broken"),
            SimpleNamespace(name="memory_kwan"),
        ],
        get_collection=lambda name: cols[name],
    )
    monkeypatch.setattr(dream, "_get_client", lambda: client)

    out = dream.light_sleep(hours=24)
    assert len(out) == 1
    assert out[0]["doc"] == "real memory"


def test_light_sleep_filters_out_of_window_memories(monkeypatch):
    old_ts = (datetime.now() - timedelta(hours=48)).isoformat()
    recent_ts = datetime.now().isoformat()
    col = _HealthyCol(
        ids=["old", "recent"],
        docs=["เก่าเกิน", "ใหม่"],
        metas=[_doc(old_ts), _doc(recent_ts)],
    )
    client = SimpleNamespace(
        list_collections=lambda: [SimpleNamespace(name="memory_kwan")],
        get_collection=lambda name: col,
    )
    monkeypatch.setattr(dream, "_get_client", lambda: client)

    out = dream.light_sleep(hours=24)
    assert [m["doc"] for m in out] == ["ใหม่"]


def test_light_sleep_no_client_returns_empty(monkeypatch):
    monkeypatch.setattr(dream, "_get_client", lambda: None)
    assert dream.light_sleep() == []


def test_light_sleep_list_collections_failure_returns_empty(monkeypatch):
    client = SimpleNamespace(
        list_collections=lambda: (_ for _ in ()).throw(Exception("chroma down")),
    )
    monkeypatch.setattr(dream, "_get_client", lambda: client)
    assert dream.light_sleep() == []
