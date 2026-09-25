"""`utils/embed._embed_one_cached` ต้องไม่แคช "ความล้มเหลว" (audit 2026-09-24 MEDIUM)

`@lru_cache` แคชค่าที่คืน — เดิม except → `return tuple()` ⇒ Ollama สะดุดครั้งเดียว = ข้อความนั้น
embed ไม่ได้ **ตลอดอายุโปรเซส** (response cache / rerank / dedup เป็น no-op เงียบสำหรับข้อความนั้น)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils.embed as embed


def _flaky(calls, vec):
    def fake(texts):
        calls.append(1)
        if len(calls) == 1:
            raise ConnectionError("Ollama ดับชั่วคราว")
        return [vec for _ in texts], "fake-model"
    return fake


def test_ล้มครั้งแรก_ครั้งถัดไปต้องได้_vector(monkeypatch):
    calls = []
    monkeypatch.setattr(embed, "_create_embeddings", _flaky(calls, [1.0, 2.0]))
    monkeypatch.setattr(embed, "_cache_get", lambda t: None)
    monkeypatch.setattr(embed, "_cache_set", lambda *a, **k: None)
    embed._embed_one_cached.cache_clear()
    assert embed.embed_query("ข้อความเดิม") == []
    assert embed.embed_query("ข้อความเดิม") == [1.0, 2.0], "ความล้มเหลวถูกแคชไว้ใน LRU — ลองใหม่ไม่เคยถึง Ollama"
    assert len(calls) == 2


def test_สำเร็จแล้วยังแคชเหมือนเดิม(monkeypatch):
    calls = []
    def ok(texts):
        calls.append(1)
        return [[3.0] for _ in texts], "m"
    monkeypatch.setattr(embed, "_create_embeddings", ok)
    monkeypatch.setattr(embed, "_cache_get", lambda t: None)
    monkeypatch.setattr(embed, "_cache_set", lambda *a, **k: None)
    embed._embed_one_cached.cache_clear()
    assert embed.embed_query("x") == [3.0]
    assert embed.embed_query("x") == [3.0]
    assert len(calls) == 1, "สำเร็จแล้วต้อง hit LRU ไม่ยิงซ้ำ"
