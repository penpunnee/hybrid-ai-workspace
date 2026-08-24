"""Tests สำหรับ utils/embed.py — cosine, pack/unpack, two-tier cache, rerank

Mock Ollama client (`embed._ollama_client.embeddings`) = ตัวหลัก ทั้งหมด —
ไม่แตะ network จริง. LM Studio (`embed._client`) เป็น fallback ด้วยชื่อโมเดลเดิม
(สลับลำดับจากเดิม 2026-08-02 เพราะ nomic-embed-text บน LM Studio แมปประโยคไทย
ทุกประโยคเป็น vector เดียวกัน — ดู docstring ของ utils/embed.py).
sqlite cache ชี้ temp file ต่อ test, ล้าง lru_cache ก่อนทุกเทสต์.
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import utils.embed as embed


class FakeEmbeddings:
    """แทน _client.embeddings — บันทึก call + คืน vector ตาม mapping"""

    def __init__(self, mapping=None, fail=False, served_model=None):
        self.calls = []          # list ของ input ที่ถูกส่งเข้ามา (แต่ละครั้ง)
        self.mapping = mapping or {}
        self.fail = fail
        # ชื่อโมเดลที่ "เซิร์ฟเวอร์ตอบกลับ" — None = ตอบชื่อเดียวกับที่ขอ (พฤติกรรมปกติ)
        # ตั้งค่าเพื่อจำลอง LM Studio ที่สลับไปใช้โมเดลอื่นให้เงียบๆ
        self.served_model = served_model

    def create(self, model, input):
        self.calls.append(list(input))
        if self.fail:
            raise RuntimeError("embed provider down")
        data = [SimpleNamespace(embedding=self.mapping.get(t, [float(len(t)), 1.0, 0.0]))
                for t in input]
        # 🔴 ของจริงคืน `model` เสมอ (OpenAI SDK CreateEmbeddingResponse) — fake ต้องคืนด้วย
        # ไม่งั้นเทสจะไม่มีวันจับเคส "เซิร์ฟเวอร์สลับโมเดลให้เงียบๆ" ได้เลย
        return SimpleNamespace(data=data, model=self.served_model or model)


@pytest.fixture
def fake_client(monkeypatch, tmp_path):
    """ชี้ sqlite cache → temp, reset conn, ล้าง LRU, ติดตั้ง fake embeddings

    fake ถูกติดตั้งที่ **Ollama** = provider หลักตามสถาปัตยกรรมปัจจุบัน
    """
    monkeypatch.setattr(embed, "_CACHE_DB", str(tmp_path / "embed_cache.db"))
    monkeypatch.setattr(embed, "_CACHE_ENABLED", True)
    monkeypatch.setattr(embed, "_cache_conn", None)
    embed._embed_one_cached.cache_clear()
    fe = FakeEmbeddings()
    monkeypatch.setattr(embed._ollama_client, "embeddings", fe)
    yield fe
    embed._embed_one_cached.cache_clear()


# ── cosine_similarity (pure math) ─────────────────────────────────────────────
def test_cosine_identical_vectors_is_one():
    assert embed.cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_cosine_orthogonal_is_zero():
    assert embed.cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_opposite_is_negative_one():
    assert embed.cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


@pytest.mark.parametrize("a,b", [
    ([], [1.0]),
    ([1.0], []),
    ([1.0, 2.0], [1.0]),       # ความยาวไม่เท่ากัน
    ([0.0, 0.0], [1.0, 1.0]),  # zero vector
])
def test_cosine_bad_input_returns_zero(a, b):
    assert embed.cosine_similarity(a, b) == 0.0


# ── pack/unpack roundtrip ─────────────────────────────────────────────────────
def test_pack_unpack_roundtrip():
    vec = [0.5, -1.25, 3.0, 0.0]
    blob = embed._pack(vec)
    assert isinstance(blob, bytes)
    out = embed._unpack(blob, len(vec))
    assert out == pytest.approx(vec)


def test_cache_key_deterministic_and_differs():
    assert embed._cache_key("hello") == embed._cache_key("hello")
    assert embed._cache_key("hello") != embed._cache_key("world")


# ── embed_query: cold → client; warm → cache (no client) ──────────────────────
def test_embed_query_cold_calls_client(fake_client):
    vec = embed.embed_query("foo")
    assert vec == [3.0, 1.0, 0.0]      # len("foo")=3
    assert len(fake_client.calls) == 1


def test_embed_query_lru_warm_skips_client(fake_client):
    embed.embed_query("foo")
    embed.embed_query("foo")           # LRU hit
    assert len(fake_client.calls) == 1


def test_embed_query_sqlite_warm_skips_client(fake_client):
    embed.embed_query("bar")
    embed._embed_one_cached.cache_clear()   # ทิ้ง LRU แต่ sqlite ยังอยู่
    embed.embed_query("bar")                # sqlite hit
    assert len(fake_client.calls) == 1


def test_embed_query_failure_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(embed, "_CACHE_DB", str(tmp_path / "c.db"))
    monkeypatch.setattr(embed, "_cache_conn", None)
    embed._embed_one_cached.cache_clear()
    # ต้องล่มทั้งคู่ (หลัก+fallback) ถึงจะคืน [] — ล่มตัวเดียว fallback ยังทำงาน
    monkeypatch.setattr(embed._ollama_client, "embeddings", FakeEmbeddings(fail=True))
    monkeypatch.setattr(embed._client, "embeddings", FakeEmbeddings(fail=True))
    assert embed.embed_query("x") == []


# ── embed_texts: batch + partial cache ────────────────────────────────────────
def test_embed_texts_filters_empty(fake_client):
    out = embed.embed_texts(["", "  ", "ok"])
    assert len(out) == 1
    assert fake_client.calls == [["ok"]]      # ส่งเฉพาะ non-empty


def test_embed_texts_partial_cache_only_fetches_misses(fake_client):
    embed.embed_query("a")                    # warm "a" ลง sqlite
    fake_client.calls.clear()
    out = embed.embed_texts(["a", "bb"])       # "a" hit, "bb" miss
    assert len(out) == 2
    assert fake_client.calls == [["bb"]]


def test_embed_texts_batch_failure_returns_cached_only(fake_client):
    embed.embed_query("a")
    fake_client.calls.clear()
    fake_client.fail = True
    out = embed.embed_texts(["a", "new"])      # batch ล้ม → คืนเฉพาะ "a" ที่ cache ไว้
    assert out == [[1.0, 1.0, 0.0]]            # len("a")=1


# ── rerank_by_similarity ──────────────────────────────────────────────────────
def test_rerank_orders_by_similarity(fake_client):
    # query vec ใกล้ item "match" มากกว่า "other"
    fake_client.mapping = {
        "q": [1.0, 0.0],
        "match": [1.0, 0.0],
        "other": [0.0, 1.0],
    }
    items = [{"body": "other"}, {"body": "match"}]
    out = embed.rerank_by_similarity("q", items, text_keys=("body",), top_k=2)
    assert [it["body"] for it in out] == ["match", "other"]
    assert out[0]["_rerank_score"] >= out[1]["_rerank_score"]


def test_rerank_top_k_limits(fake_client):
    items = [{"body": f"i{i}"} for i in range(5)]
    out = embed.rerank_by_similarity("q", items, text_keys=("body",), top_k=2)
    assert len(out) == 2


def test_rerank_min_score_filters(fake_client):
    fake_client.mapping = {"q": [1.0, 0.0], "a": [1.0, 0.0], "b": [0.0, 1.0]}
    items = [{"body": "a"}, {"body": "b"}]
    out = embed.rerank_by_similarity("q", items, text_keys=("body",), top_k=5, min_score=0.5)
    assert [it["body"] for it in out] == ["a"]      # "b" score 0 ถูกตัด


def test_rerank_embed_fail_fallback_to_original(monkeypatch, tmp_path):
    monkeypatch.setattr(embed, "_CACHE_DB", str(tmp_path / "c.db"))
    monkeypatch.setattr(embed, "_cache_conn", None)
    embed._embed_one_cached.cache_clear()
    monkeypatch.setattr(embed._ollama_client, "embeddings", FakeEmbeddings(fail=True))
    monkeypatch.setattr(embed._client, "embeddings", FakeEmbeddings(fail=True))
    items = [{"body": "a"}, {"body": "b"}, {"body": "c"}]
    out = embed.rerank_by_similarity("q", items, text_keys=("body",), top_k=2)
    assert out == items[:2]                          # fallback ไม่ rerank


def test_rerank_empty_items_returns_empty(fake_client):
    assert embed.rerank_by_similarity("q", []) == []


# ── LM Studio fallback เมื่อ Ollama (ตัวหลัก) ล่ม ─────────────────────────────
def test_embed_falls_back_to_lmstudio(monkeypatch, tmp_path):
    monkeypatch.setattr(embed, "_CACHE_DB", str(tmp_path / "c.db"))
    monkeypatch.setattr(embed, "_cache_conn", None)
    embed.reset_metrics()
    # Ollama (หลัก) fail, LM Studio ตอบได้ด้วยชื่อโมเดลเดิม
    monkeypatch.setattr(embed._ollama_client, "embeddings", FakeEmbeddings(fail=True))
    monkeypatch.setattr(embed._client, "embeddings",
                        FakeEmbeddings(mapping={"x": [9.0, 9.0]}))
    vec = embed.embed_query("x")
    assert vec == [9.0, 9.0]
    assert embed.cache_stats()["ollama_fallback"] >= 1


def test_embed_fallback_uses_same_model_name_not_a_different_model(monkeypatch, tmp_path):
    """fallback ต้องขอโมเดล**ชื่อเดิม**จาก LM Studio — ห้ามสลับไปโมเดลอื่น
    (คนละโมเดล = คนละ vector space ปนใน collection เดียวกัน cosine เพี้ยนเงียบๆ)"""
    monkeypatch.setattr(embed, "_CACHE_DB", str(tmp_path / "c.db"))
    monkeypatch.setattr(embed, "_cache_conn", None)
    embed.reset_metrics()
    seen = {}

    class _CaptureModel(FakeEmbeddings):
        def create(self, model, input):
            seen["model"] = model
            return super().create(model, input)

    monkeypatch.setattr(embed._ollama_client, "embeddings", FakeEmbeddings(fail=True))
    monkeypatch.setattr(embed._client, "embeddings", _CaptureModel())
    embed.embed_query("x")
    assert seen["model"] == embed._EMBED_MODEL


def test_embed_both_down_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(embed, "_CACHE_DB", str(tmp_path / "c.db"))
    monkeypatch.setattr(embed, "_cache_conn", None)
    embed.reset_metrics()
    monkeypatch.setattr(embed._client, "embeddings", FakeEmbeddings(fail=True))
    monkeypatch.setattr(embed._ollama_client, "embeddings", FakeEmbeddings(fail=True))
    assert embed.embed_query("x") == []          # ทั้งคู่ล่ม → [] (pipeline ไม่พัง)


def test_embed_fallback_can_be_disabled(monkeypatch, tmp_path):
    """ปิด fallback ได้ด้วย EMBED_FALLBACK_LMSTUDIO=false — Ollama ล่ม = คืน [] ทันที"""
    monkeypatch.setattr(embed, "_CACHE_DB", str(tmp_path / "c.db"))
    monkeypatch.setattr(embed, "_cache_conn", None)
    monkeypatch.setattr(embed, "_EMBED_FALLBACK_ENABLED", False)
    embed.reset_metrics()
    lm = FakeEmbeddings(mapping={"x": [9.0, 9.0]})
    monkeypatch.setattr(embed._ollama_client, "embeddings", FakeEmbeddings(fail=True))
    monkeypatch.setattr(embed._client, "embeddings", lm)
    assert embed.embed_query("x") == []
    assert lm.calls == [], "ปิด fallback แล้วต้องไม่แตะ LM Studio เลย"


# ── 🔴 ด่านกัน "เซิร์ฟเวอร์สลับโมเดลให้เงียบๆ" (2026-08-24) ────────────────────
# วัดของจริงบน prod วันนี้: ขอ LM Studio ด้วย model="paraphrase-multilingual"
# แต่มันตอบ model="text-embedding-nomic-embed-text-v1.5" **โดยไม่ error**
# มิติ 768 เท่ากันเป๊ะ → ไม่มี assertion ไหนเดิมจับได้
# cosine ของข้อความเดียวกันจากสองฝั่ง = 0.0458 (ตั้งฉาก = คนละ vector space)
#
# ซ้ำร้าย ตัวที่มันสลับไปใช้คือ nomic-embed = ตัวที่ถูกถอดออกไปเมื่อ 2026-08-02
# เพราะแมปประโยคไทยทุกประโยคเป็น vector เดียวกัน (`42156dd`)
# ⇒ ประตูที่สร้างไว้กันมัน กลายเป็นประตูที่มันเดินกลับเข้ามา
#
# สมมติฐานเดิมในโค้ดที่พังคือ "ถ้า LM Studio ไม่มีโมเดลนี้จะ raise"
# — เป็นสมมติฐานเรื่องพฤติกรรมของ**เครื่องมือภายนอก** ที่ไม่เคยถูกทดสอบ
def test_lmstudio_fallback_serving_a_different_model_is_rejected(monkeypatch, tmp_path):
    """fallback ที่ได้ vector จากคนละโมเดล = ต้องทิ้ง ห้ามคืนและห้าม cache

    ยอมไม่มี embedding ดีกว่าได้ embedding ผิด space (เจตนาเดิมของ `42156dd`)
    """
    monkeypatch.setattr(embed, "_CACHE_DB", str(tmp_path / "c.db"))
    monkeypatch.setattr(embed, "_cache_conn", None)
    embed._embed_one_cached.cache_clear()
    embed.reset_metrics()
    monkeypatch.setattr(embed._ollama_client, "embeddings", FakeEmbeddings(fail=True))
    monkeypatch.setattr(embed._client, "embeddings",
                        FakeEmbeddings(mapping={"x": [9.0, 9.0]},
                                       served_model="text-embedding-nomic-embed-text-v1.5"))
    assert embed.embed_query("x") == [], "ได้ vector คนละโมเดลมาแล้วยังคืนออกไป = พิษเข้าคลัง"
    assert embed._cache_get("x") in (None, [], ()), "ห้าม cache vector ที่ปฏิเสธ"


def test_ollama_primary_serving_a_different_model_is_rejected(monkeypatch, tmp_path):
    """ด่านเดียวกันต้องคุมตัวหลักด้วย ไม่ใช่คุมแค่ fallback

    (ถ้าคุมแค่ fallback = ตัวหลักสลับโมเดลเมื่อไหร่ก็พิษเข้าเงียบๆ เหมือนเดิม)
    """
    monkeypatch.setattr(embed, "_CACHE_DB", str(tmp_path / "c.db"))
    monkeypatch.setattr(embed, "_cache_conn", None)
    embed._embed_one_cached.cache_clear()
    embed.reset_metrics()
    monkeypatch.setattr(embed._ollama_client, "embeddings",
                        FakeEmbeddings(mapping={"x": [1.0, 2.0]}, served_model="llama3"))
    monkeypatch.setattr(embed._client, "embeddings", FakeEmbeddings(fail=True))
    assert embed.embed_query("x") == []


def test_model_name_with_latest_tag_is_accepted(monkeypatch, tmp_path):
    """`X` กับ `X:latest` = ตัวเดียวกัน — Ollama ตั้งชื่อแบบมี tag

    🔴 ถ้าไม่ normalize ตรงนี้ ด่านใหม่จะปฏิเสธของถูกต้องบน prod ทั้งหมด
    (`/api/tags` ของ Ollama คืน `paraphrase-multilingual:latest`)
    """
    monkeypatch.setattr(embed, "_CACHE_DB", str(tmp_path / "c.db"))
    monkeypatch.setattr(embed, "_cache_conn", None)
    embed._embed_one_cached.cache_clear()
    embed.reset_metrics()
    monkeypatch.setattr(embed._ollama_client, "embeddings",
                        FakeEmbeddings(mapping={"x": [1.0, 2.0]},
                                       served_model=f"{embed._EMBED_MODEL}:latest"))
    assert embed.embed_query("x") == [1.0, 2.0]


def test_response_without_model_field_is_accepted(monkeypatch, tmp_path):
    """ไม่มี field `model` ในคำตอบ = ตรวจไม่ได้ → ปล่อยผ่าน (ไม่ใช่ปฏิเสธ)

    เจตนา: ด่านนี้จับ "สลับโมเดล" ที่พิสูจน์ได้เท่านั้น · การปฏิเสธเพราะ
    "ตรวจไม่ได้" จะทำให้ provider ที่ไม่ส่ง field นี้ใช้ไม่ได้ทั้งตัว
    ซึ่งแลกไม่คุ้ม (ของจริงทั้ง Ollama และ LM Studio ส่งครบอยู่แล้ว)
    """
    monkeypatch.setattr(embed, "_CACHE_DB", str(tmp_path / "c.db"))
    monkeypatch.setattr(embed, "_cache_conn", None)
    embed._embed_one_cached.cache_clear()
    embed.reset_metrics()

    class _NoModel(FakeEmbeddings):
        def create(self, model, input):
            r = super().create(model, input)
            return SimpleNamespace(data=r.data)          # ตัด field model ทิ้ง

    monkeypatch.setattr(embed._ollama_client, "embeddings", _NoModel(mapping={"x": [3.0, 4.0]}))
    assert embed.embed_query("x") == [3.0, 4.0]


def test_model_mismatch_counter_is_reported(monkeypatch, tmp_path):
    """ตัวนับ model_mismatch ต้องโผล่ใน cache_stats() ไม่ใช่แค่เพิ่มเงียบๆ

    🔴 `_metrics_block()` เลือกคีย์ทีละตัวด้วยมือ — เพิ่มตัวนับใหม่แล้วไม่เติมตรงนั้น
    = นับไปก็ไม่มีใครเห็น (เจอตอน verify บน prod 2026-08-24)
    """
    monkeypatch.setattr(embed, "_CACHE_DB", str(tmp_path / "c.db"))
    monkeypatch.setattr(embed, "_cache_conn", None)
    embed._embed_one_cached.cache_clear()
    embed.reset_metrics()
    assert "model_mismatch" in embed.cache_stats(), "ตัวนับไม่ถูกรายงานออกมา"
    assert embed.cache_stats()["model_mismatch"] == 0

    monkeypatch.setattr(embed._ollama_client, "embeddings",
                        FakeEmbeddings(mapping={"x": [1.0, 2.0]}, served_model="คนละตัว"))
    monkeypatch.setattr(embed._client, "embeddings", FakeEmbeddings(fail=True))
    embed.embed_query("x")
    assert embed.cache_stats()["model_mismatch"] >= 1
