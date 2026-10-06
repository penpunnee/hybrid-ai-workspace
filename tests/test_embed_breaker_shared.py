"""ตัวพัก "Ollama ต่อไม่ติด" ต้องใช้ร่วมกันระหว่าง utils/embed.py กับ OllamaEmbeddingFunction ของ chromadb (2026-10-06)

log prod 10-06 (PC .235 ปิด): ก่อนเรียก LLM ทุกแชทมี 5–6 ขั้นที่เรียก Ollama ผ่าน EF ของ chromadb
(get_lessons → search_entries → user_facts → long_term_memory → skills_search) ล้มทีละ ~3 วิต่อกัน
= ช้า 15–18 วิ · ตัวพัก 60 วิของ utils/embed.py (`_down_until`) ไม่ครอบ EF เพราะ EF เรียก ollama.Client ตรง

กติกา (ปอยเคาะ A1): ทางไหนล้มก่อนก็พักทั้งสองทาง · ระหว่างพักขั้นที่เหลือข้ามทันที (ไม่แตะเครือข่าย) ·
ครบเวลาพักแล้วกลับมาลองใหม่เองได้ (ไม่ค้างสถานะล่ม) · error ที่ไม่ใช่การเชื่อมต่อ (เครื่องยังอยู่) ห้ามปิดทาง
"""
import os
import sys

import httpx
import pytest
from openai import APIConnectionError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("UI_PASSWORD", "")

import utils.embed as embed
import utils.memory as memory_mod


class _BaseEF:
    """ตัวแทน chromadb OllamaEmbeddingFunction — นับครั้งที่ "แตะเครือข่าย" และโยนตามที่ตั้ง"""
    calls = 0
    raise_with: BaseException | None = None

    def __init__(self, url, model_name):
        self.url, self.model_name = url, model_name

    def __call__(self, input):
        # นับที่คลาสที่ประกาศตัวนับเอง (Base ของ fixture) — type(self) คือ subclass ตัวห่อ
        owner = next(c for c in type(self).__mro__ if "calls" in c.__dict__)
        owner.calls += 1
        if owner.raise_with is not None:
            raise owner.raise_with
        return [[0.1, 0.2] for _ in input]


@pytest.fixture
def ef(monkeypatch):
    """EF ของจริงจาก _get_embedding_function() โดยฐานเป็น _BaseEF (แทน chromadb)"""
    class Base(_BaseEF):
        calls = 0
        raise_with = None
    monkeypatch.setattr("chromadb.utils.embedding_functions.OllamaEmbeddingFunction", Base)
    monkeypatch.setattr(memory_mod, "EMBEDDING_MODEL", "paraphrase-multilingual")
    monkeypatch.setattr(memory_mod, "_embedding_function", None)
    monkeypatch.setattr(memory_mod, "_embedding_function_attempted", False)
    monkeypatch.setattr(embed, "_EMBED_DOWN_COOLDOWN", 60)
    clock = {"t": 1000.0}
    monkeypatch.setattr(embed, "_now", lambda: clock["t"])
    f = memory_mod._get_embedding_function()
    assert f is not None and isinstance(f, Base)
    return f, Base, clock


def test_EF_ล้มครั้งแรก_แล้วขั้นที่เหลือข้ามทันทีไม่แตะเครือข่าย(ef):
    f, Base, _ = ef
    Base.raise_with = ConnectionError("Failed to connect to Ollama")
    with pytest.raises(ConnectionError):
        f(["ก"])
    assert Base.calls == 1
    for _ in range(5):                       # 5 ขั้นที่เหลือของแชทเดียวกัน
        with pytest.raises(ConnectionError):
            f(["ข"])
    assert Base.calls == 1, "ระหว่างพักต้องไม่เรียก Ollama ซ้ำ (เดิมรอ ~3 วิทุกขั้น)"


def test_EF_ล้ม_ทำให้_utils_embed_ข้าม_Ollama_ด้วย(ef):
    f, Base, _ = ef
    Base.raise_with = ConnectionError("Failed to connect to Ollama")
    with pytest.raises(ConnectionError):
        f(["ก"])

    class _Client:
        base_url = "http://192.168.51.235:11434/v1"
        hit = 0

        class embeddings:  # noqa: N801
            @staticmethod
            def create(**kw):
                _Client.hit += 1
                raise AssertionError("ต้องไม่ถูกเรียกระหว่างพัก")

    with pytest.raises(APIConnectionError):
        embed._embed_via("Ollama", _Client, ["ก"])
    assert _Client.hit == 0


def test_utils_embed_ล้มก่อน_EF_ข้ามทันที(ef):
    f, Base, _ = ef

    class _Client:
        base_url = "http://192.168.51.235:11434/v1"

        class embeddings:  # noqa: N801
            @staticmethod
            def create(**kw):
                raise APIConnectionError(request=httpx.Request("POST", "http://x"))

    with pytest.raises(APIConnectionError):
        embed._embed_via("Ollama", _Client, ["ก"])
    with pytest.raises(ConnectionError):
        f(["ข"])
    assert Base.calls == 0, "utils.embed เพิ่งเห็น Ollama ล่ม — EF ต้องข้ามโดยไม่แตะเครือข่าย"


def test_ครบเวลาพัก_กลับมาลองใหม่เอง_และใช้ได้ถ้าเครื่องกลับมา(ef):
    f, Base, clock = ef
    Base.raise_with = ConnectionError("Failed to connect to Ollama")
    with pytest.raises(ConnectionError):
        f(["ก"])
    clock["t"] += 59
    with pytest.raises(ConnectionError):
        f(["ข"])
    assert Base.calls == 1, "ยังไม่ครบ 60 วิ ต้องยังพัก"
    clock["t"] += 2                          # ครบ 61 วิ
    Base.raise_with = None                   # PC เปิดกลับมาแล้ว
    assert f(["ค"]) == [[0.1, 0.2]]
    assert Base.calls == 2, "ครบเวลาพักต้องลองใหม่เอง (ไม่ค้างสถานะล่ม)"
    assert f(["ง"]) == [[0.1, 0.2]]
    assert Base.calls == 3


def test_ConnectTimeout_ก็นับว่าต่อไม่ติด(ef):
    f, Base, _ = ef
    Base.raise_with = httpx.ConnectTimeout("timed out")
    with pytest.raises(httpx.ConnectTimeout):
        f(["ก"])
    with pytest.raises(ConnectionError):
        f(["ข"])
    assert Base.calls == 1


def test_error_ที่ไม่ใช่การเชื่อมต่อ_ห้ามปิดทาง(ef):
    """เช่น โมเดลไม่มี (ollama.ResponseError 404) = เครื่องยังอยู่ ⇒ ครั้งต่อไปต้องลองจริง"""
    f, Base, _ = ef
    Base.raise_with = ValueError("model not found")
    with pytest.raises(ValueError):
        f(["ก"])
    with pytest.raises(ValueError):
        f(["ข"])
    assert Base.calls == 2


def test_EF_ของจริงยังชื่อ_ollama_และ_config_เดิม(monkeypatch):
    """collection เก็บชื่อ/คอนฟิกของ EF ไว้ (chromadb 1.x) — ตัวห่อต้องไม่ทำให้ชนกับของที่บันทึกไว้"""
    from chromadb.utils.embedding_functions import OllamaEmbeddingFunction
    monkeypatch.setattr(memory_mod, "EMBEDDING_MODEL", "paraphrase-multilingual")
    monkeypatch.setattr(memory_mod, "_embedding_function", None)
    monkeypatch.setattr(memory_mod, "_embedding_function_attempted", False)
    f = memory_mod._get_embedding_function()
    assert isinstance(f, OllamaEmbeddingFunction)
    assert f.name() == "ollama"
    ref = OllamaEmbeddingFunction(url=f.url, model_name=f.model_name)
    assert f.get_config() == ref.get_config()


# ── ผู้ตรวจ diff 10-06: เส้นจริงของ chromadb + read timeout + vault catch-up ──────────────────────

def test_คลาสจริงผ่าน_embed_query_พอร์ตปิด_ครั้งที่สองไม่แตะเครือข่าย(monkeypatch):
    """เส้นจริงของ chromadb (embed_query → __call__ ที่ __init_subclass__ ห่อ validate) · 127.0.0.1:1 = ปฏิเสธทันที"""
    monkeypatch.setattr(memory_mod, "EMBEDDING_MODEL", "paraphrase-multilingual")
    monkeypatch.setattr(memory_mod, "OLLAMA_BASE_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setattr(memory_mod, "_embedding_function", None)
    monkeypatch.setattr(memory_mod, "_embedding_function_attempted", False)
    monkeypatch.setattr(embed, "_EMBED_DOWN_COOLDOWN", 60)
    f = memory_mod._get_embedding_function()
    hits = {"n": 0}
    real = f._client.embed

    def counting(*a, **kw):
        hits["n"] += 1
        return real(*a, **kw)
    monkeypatch.setattr(f._client, "embed", counting)
    with pytest.raises(ConnectionError):
        f.embed_query(input=["ก"])
    with pytest.raises(ConnectionError, match="ข้าม"):
        f.embed_query(input=["ข"])
    assert hits["n"] == 1, "ครั้งที่สองต้องโดนตัวพัก ไม่แตะ ollama.Client"


def _timeout_with_cause(cause):
    import openai
    try:
        try:
            raise cause
        except Exception as c:
            raise openai.APITimeoutError(request=httpx.Request("POST", "http://x")) from c
    except openai.APITimeoutError as e:
        return e


def _conn_error_with_cause(cause):
    """แบบที่ openai ทำจริง (`raise APIConnectionError(...) from err` · _base_client.py)"""
    try:
        try:
            raise cause
        except Exception as c:
            raise APIConnectionError(request=httpx.Request("POST", "http://x")) from c
    except APIConnectionError as e:
        return e


@pytest.mark.parametrize("make, cause, down", [
    (_timeout_with_cause, httpx.ReadTimeout("read"), False),        # เครื่องอยู่แต่ช้า (เช่นโหลดโมเดล) — ห้ามปิดทาง EF/ความจำ 60 วิ
    (_timeout_with_cause, httpx.ConnectTimeout("connect"), True),   # SYN หาย = ต่อไม่ติดจริง
    (_conn_error_with_cause, httpx.RemoteProtocolError("Server disconnected"), False),  # keep-alive เก่าถูกตัด เครื่องยังอยู่
    (_conn_error_with_cause, httpx.ReadError("reset"), False),
    (_conn_error_with_cause, httpx.ConnectError("refused"), True),
])
def test_utils_embed_timeout_ปิดทางเฉพาะตอนต่อไม่ติด(monkeypatch, make, cause, down):
    monkeypatch.setattr(embed, "_EMBED_DOWN_COOLDOWN", 60)
    err = make(cause)

    class _Client:
        base_url = "http://192.168.51.235:11434/v1"

        class embeddings:  # noqa: N801
            @staticmethod
            def create(**kw):
                raise err

    with pytest.raises(APIConnectionError):
        embed._embed_via("Ollama", _Client, ["ก"])
    assert (embed.provider_down_for("Ollama") > 0) is down


def test_vault_catchup_preflight_ผ่าน_ล้างตัวพัก_ไม่เลิกลองเงียบ(monkeypatch, tmp_path):
    """PC เพิ่งบูต: แชทเห็น Ollama ล่ม (พัก 60 วิ) → Ollama ขึ้นภายใน 60 วิ → catch-up tick: preflight TCP ผ่าน
    แต่ EF ยังโดนตัวพัก → ไฟล์เดียว = error ไม่ halted → เดิมตั้ง _catchup_pending=False เลิกลองเงียบ"""
    import utils.obsidian_sync as ov
    from types import SimpleNamespace
    monkeypatch.setattr(embed, "_EMBED_DOWN_COOLDOWN", 60)
    embed.mark_provider_down("Ollama")                                     # แชทก่อนหน้าเห็นล่ม

    class _Col:
        _embedding_function = SimpleNamespace(url="http://192.168.51.235:11434")
        upserts = 0

        def get(self, ids=None, **kw):
            return {"ids": [], "metadatas": []}

        def upsert(self, ids, documents, metadatas):
            if embed.provider_down_for("Ollama") > 0:                     # พฤติกรรมของ EF ที่ห่อแล้ว
                raise ConnectionError("Ollama ต่อไม่ติดเมื่อไม่นานนี้ — ข้าม")
            _Col.upserts += 1

        def delete(self, ids):
            pass

    (tmp_path / "n.md").write_text("# N\nเนื้อหา", encoding="utf-8")
    monkeypatch.setattr(ov, "VAULT_PATH", str(tmp_path))
    monkeypatch.setattr(ov, "_get_collection", lambda: _Col())
    monkeypatch.setattr(ov, "_tcp_reachable", lambda h, p, t: True)       # Ollama ขึ้นแล้ว
    monkeypatch.setattr(ov, "_catchup_pending", True)
    res = ov.catchup_sync_if_pending()
    assert res and res.get("synced") == 1, f"preflight ผ่าน = ต่อได้แล้ว ต้อง sync ได้ ({res})"
    assert _Col.upserts == 1
