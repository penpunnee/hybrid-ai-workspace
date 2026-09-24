"""ปุ่ม 🧹 (`cleanup_old_memories`) ต้องลบเฉพาะ episodic (`memory_*`) — audit 2026-09-24 ข้อ 9

เดิม denylist `{long_term_memory, preferences}` แล้วลบทุก collection ที่ `timestamp < cutoff`
วัดบน prod: กดวันนี้จะลบ `user_facts` 1/1 (ข้อเท็จจริงที่ user สอน) และ `lessons` 8/8 ทั้งหมด ·
`documents`/`obsidian_notes`/`skills_collection` รอดเพราะ *บังเอิญ* ไม่มี `timestamp`
→ allowlist ด้วย predicate เดียวกับ Dream prune (`memory_` และไม่ใช่เงา `__keys`) ที่ `memory/dualvec.py`
"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from memory.dualvec import is_episodic_collection
import utils.memory as um

OLD = (datetime.now() - timedelta(days=90)).isoformat()


@pytest.mark.parametrize("name,expected", [
    ("memory_kwan", True), ("memory_a", True),
    ("memory_kwan__keys", False), ("lessons", False), ("lessons__keys", False),
    ("user_facts", False), ("preferences", False), ("long_term_memory", False),
    ("documents", False), ("obsidian_notes", False), ("skills_collection", False),
    ("memorystuff", False), ("", False),
])
def test_is_episodic_collection(name, expected):
    assert is_episodic_collection(name) is expected


def _client(cols: dict[str, list[str]]):
    return SimpleNamespace(
        list_collections=lambda: [SimpleNamespace(name=n) for n in cols],
        get_collection=lambda name, **k: SimpleNamespace(
            get=lambda **k: {"ids": list(cols[name]), "metadatas": [{"timestamp": OLD} for _ in cols[name]]}),
    )


def test_cleanup_ลบเฉพาะ_episodic_แม้ทุก_collection_จะเก่าหมด(monkeypatch):
    cols = {"memory_kwan": ["m1", "m2"], "memory_kwan__keys": ["m1", "m2"],
            "user_facts": ["u1"], "lessons": ["l1"], "documents": ["d1"], "preferences": ["p1"]}
    monkeypatch.setattr(um, "_get_client", lambda: _client(cols))
    monkeypatch.setattr(um, "get_collection", lambda client, name, **k: client.get_collection(name))
    with patch("memory.dualvec.delete_with_keys") as dwk:
        out = um.cleanup_old_memories(days=30)
    called = sorted((c.args[1], c.args[2]) for c in dwk.call_args_list)
    assert called == [("memory_kwan", ["m1", "m2"])], f"ลบผิดชุด: {called}"
    assert out["ok"] and out["deleted"] == 2 and out["detail"] == {"memory_kwan": 2}


def test_cleanup_กลุ่มควบคุม_episodic_ที่ยังใหม่ต้องไม่ถูกลบ(monkeypatch):
    new = datetime.now().isoformat()
    client = SimpleNamespace(
        list_collections=lambda: [SimpleNamespace(name="memory_kwan")],
        get_collection=lambda name, **k: SimpleNamespace(
            get=lambda **k: {"ids": ["m1", "m2"], "metadatas": [{"timestamp": new}, {"timestamp": OLD}]}),
    )
    monkeypatch.setattr(um, "_get_client", lambda: client)
    monkeypatch.setattr(um, "get_collection", lambda c, name, **k: c.get_collection(name))
    with patch("memory.dualvec.delete_with_keys") as dwk:
        out = um.cleanup_old_memories(days=30)
    assert [c.args[2] for c in dwk.call_args_list] == [["m2"]]
    assert out["deleted"] == 1
