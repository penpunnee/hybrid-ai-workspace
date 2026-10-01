"""ค้นเว็บเมื่อเครื่อง embed (PC .235) ดับ — ต้องไม่เงียบเป็นนาที และต้องไม่บอกว่า "หาไม่เจอ"

ของจริง prod 2026-10-01 05:59–06:03 (devlog ต่อ 56–58): โหมดเสียงเงียบ 3 นาทีครึ่ง
- embed: Ollama timeout 30 วิ × (1 + retry 2 ของ openai) = 90 วิ → LM Studio อีก 92 วิ
- rerank ล้ม → ผลไม่มีคะแนน → `_drop_below_min_score` ตัดทิ้งหมด (fail-closed ตั้งใจ)
  → server ส่งโมเดลว่า "หาไม่เจอ" ทั้งที่จริงคือ "ระบบล่ม"
"""
import asyncio
import os
import time

os.environ.setdefault("UI_PASSWORD", "")

import httpx
import openai
import pytest

import utils.embed as embed
import utils.websearch as ws


def _conn_error():
    return openai.APIConnectionError(request=httpx.Request("POST", "http://192.168.51.235:11434/v1/embeddings"))


class _Counting:
    """แทน client.embeddings — นับครั้งที่ถูกเรียก แล้วโยน/คืนตามที่ตั้ง"""

    def __init__(self, exc=None):
        self.calls = 0
        self.exc = exc

    def create(self, model, input):
        self.calls += 1
        if self.exc:
            raise self.exc
        from types import SimpleNamespace
        return SimpleNamespace(model=model, data=[SimpleNamespace(embedding=[0.1, 0.2]) for _ in input])


@pytest.fixture()
def no_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(embed, "_CACHE_DB", str(tmp_path / "c.db"))
    monkeypatch.setattr(embed, "_cache_conn", None)
    monkeypatch.setattr(embed, "_down_until", {})
    embed._embed_one_cached.cache_clear()
    yield
    embed._embed_one_cached.cache_clear()


# ── ข้อ 1: ไม่ลองใหม่เอง + connect timeout สั้น ────────────────────────────────

@pytest.mark.parametrize("name", ["_client", "_ollama_client"])
def test_embed_client_ไม่ลองใหม่เอง(name):
    assert getattr(embed, name).max_retries == 0, "retry 2 ของ openai ทำ timeout จริงเป็น 3 เท่า"


@pytest.mark.parametrize("name", ["_client", "_ollama_client"])
def test_embed_client_connect_timeout_สั้น_read_timeout_เดิม(name):
    t = getattr(embed, name).timeout
    assert isinstance(t, httpx.Timeout)
    assert t.connect == embed._EMBED_CONNECT_TIMEOUT <= 5, "เครื่องดับใน LAN รู้ได้ในไม่กี่วิ"
    assert t.read == embed._EMBED_TIMEOUT, "read ต้องยาวเท่าเดิม — โหลดโมเดลครั้งแรกช้าได้"


# ── ข้อ 2: ข้ามเครื่องที่เพิ่งรู้ว่าดับ ──────────────────────────────────────────

def test_ต่อไม่ติด_แล้วข้าม_provider_นั้นช่วงพัก(monkeypatch, no_cache):
    oll, lms = _Counting(_conn_error()), _Counting(_conn_error())
    monkeypatch.setattr(embed._ollama_client, "embeddings", oll)
    monkeypatch.setattr(embed._client, "embeddings", lms)

    assert embed.embed_query("คำแรก") == []
    assert (oll.calls, lms.calls) == (1, 1)

    assert embed.embed_query("คำที่สอง") == []
    assert (oll.calls, lms.calls) == (1, 1), "เพิ่งต่อไม่ติด ยังยิงซ้ำ = รอ timeout ซ้ำทุกการค้น"


def test_พ้นช่วงพักแล้วลองใหม่(monkeypatch, no_cache):
    oll, lms = _Counting(_conn_error()), _Counting(_conn_error())
    monkeypatch.setattr(embed._ollama_client, "embeddings", oll)
    monkeypatch.setattr(embed._client, "embeddings", lms)
    now = [1000.0]
    monkeypatch.setattr(embed, "_now", lambda: now[0])

    embed.embed_query("ก")
    now[0] += embed._EMBED_DOWN_COOLDOWN + 1
    oll.exc = None
    assert embed.embed_query("ข") == [0.1, 0.2]
    assert oll.calls == 2


def test_error_ที่ไม่ใช่การเชื่อมต่อ_ไม่ทำให้ข้าม(monkeypatch, no_cache):
    """เช่น model mismatch / 400 — เครื่องยังอยู่ ห้ามปิดทางเพราะเรื่องนี้"""
    oll = _Counting(RuntimeError("อย่างอื่น"))
    lms = _Counting(RuntimeError("อย่างอื่น"))
    monkeypatch.setattr(embed._ollama_client, "embeddings", oll)
    monkeypatch.setattr(embed._client, "embeddings", lms)
    embed.embed_query("ก")
    embed.embed_query("ข")
    assert (oll.calls, lms.calls) == (2, 2)


def test_ollama_ดับ_lmstudio_ยังใช้ได้(monkeypatch, no_cache):
    oll, lms = _Counting(_conn_error()), _Counting()
    monkeypatch.setattr(embed._ollama_client, "embeddings", oll)
    monkeypatch.setattr(embed._client, "embeddings", lms)
    assert embed.embed_query("ก") == [0.1, 0.2]
    assert embed.embed_query("ข") == [0.1, 0.2]
    assert (oll.calls, lms.calls) == (1, 2), "ข้ามแค่ตัวที่ดับ"


# ── ข้อ 4: "ให้คะแนนไม่ได้" ≠ "หาไม่เจอ" ────────────────────────────────────────

_HITS = [{"title": f"t{i}", "href": f"https://ex{i}.com", "body": "b"} for i in range(4)]


@pytest.fixture()
def fake_pipeline(monkeypatch):
    monkeypatch.setattr(ws, "search_web", lambda q, max_results=5: [dict(h) for h in _HITS])
    monkeypatch.setattr(ws, "_enrich_with_fetch", lambda r, top_n=3: r)
    import utils.query_rewrite as qr
    monkeypatch.setattr(qr, "_REWRITE_ENABLED", False)

    def set_rerank(fn):
        monkeypatch.setattr(embed, "rerank_by_similarity", fn)
    return set_rerank


def test_status_rerank_ล้ม_คือ_unavailable(fake_pipeline):
    fake_pipeline(lambda q, items, text_keys=(), top_k=3: items[:top_k])  # ไม่มีคะแนน
    ctx, res, status = ws.web_search_with_status("ราคาทอง")
    assert (ctx, res, status) == ("", [], "unavailable")


def test_status_คะแนนต่ำหมด_คือ_empty(fake_pipeline):
    fake_pipeline(lambda q, items, text_keys=(), top_k=3:
                  [{**it, "_rerank_score": 0.05} for it in items[:top_k]])
    assert ws.web_search_with_status("ราคาทอง")[2] == "empty"


def test_status_ปกติ_คือ_ok(fake_pipeline):
    fake_pipeline(lambda q, items, text_keys=(), top_k=3:
                  [{**it, "_rerank_score": 0.9} for it in items[:top_k]])
    ctx, res, status = ws.web_search_with_status("ราคาทอง")
    assert status == "ok" and ctx and len(res) == 3


def test_status_ไม่มีผลค้นเลย_คือ_empty(monkeypatch, fake_pipeline):
    monkeypatch.setattr(ws, "search_web", lambda q, max_results=5: [])
    assert ws.web_search_with_status("ราคาทอง")[2] == "empty"


def test_web_search_with_results_สัญญาเดิม(fake_pipeline):
    fake_pipeline(lambda q, items, text_keys=(), top_k=3:
                  [{**it, "_rerank_score": 0.9} for it in items[:top_k]])
    out = ws.web_search_with_results("ราคาทอง")
    assert isinstance(out, tuple) and len(out) == 2


def test_agent_tool_rerank_ล้ม_ไม่บอกว่าหาไม่เจอ(fake_pipeline):
    """pipeline ที่ 2 (agents/tools.py) — แก้ต้องแก้คู่"""
    fake_pipeline(lambda q, items, text_keys=(), top_k=3: items[:top_k])
    from agents.tools import _t_web_search
    out = _t_web_search("ราคาทอง")
    assert "ขัดข้อง" in out
    assert "ไม่พบ" not in out


def test_agent_tool_คะแนนต่ำ_ยังบอกว่าไม่พบ(fake_pipeline):
    fake_pipeline(lambda q, items, text_keys=(), top_k=3:
                  [{**it, "_rerank_score": 0.05} for it in items[:top_k]])
    from agents.tools import _t_web_search
    assert "ไม่พบ" in _t_web_search("ราคาทอง")


# ── ข้อ 3 + 4 ฝั่งโหมดเสียง: payload ที่ส่งกลับให้ Gemini Live ─────────────────

def _run(coro):
    return asyncio.run(coro)


def _patch_search(monkeypatch, fn):
    import utils.llm as llm
    monkeypatch.setattr(llm, "GEMINI_WEB_SEARCH_ENABLED", False)
    monkeypatch.setattr(ws, "web_search_with_status", fn)


def test_voice_ok_ส่งผล(monkeypatch):
    _patch_search(monkeypatch, lambda q: ("ผลค้น", [{"href": "x"}], "ok"))
    assert _run(ws.voice_search_payload("ราคาทอง")) == {"result": "ผลค้น"}


def test_voice_empty_บอกหาไม่เจอ(monkeypatch):
    _patch_search(monkeypatch, lambda q: ("", [], "empty"))
    p = _run(ws.voice_search_payload("ราคาทอง"))
    assert "หาไม่เจอ" in p["error"]


def test_voice_unavailable_ไม่หน้าตาเหมือนหาไม่เจอ(monkeypatch):
    _patch_search(monkeypatch, lambda q: ("", [], "unavailable"))
    p = _run(ws.voice_search_payload("ราคาทอง"))
    assert "ขัดข้อง" in p["error"] and "หาไม่เจอ" not in p["error"]


def test_voice_ค้นนานเกินเพดาน_ตอบทันทีไม่รอ(monkeypatch):
    def slow(q):
        time.sleep(2)
        return "ผลมาช้า", [], "ok"
    _patch_search(monkeypatch, slow)
    monkeypatch.setattr(ws, "VOICE_SEARCH_TIMEOUT", 0.2)

    async def timed():
        # จับเวลาใน loop — asyncio.run() ตอนปิดจะรอ thread ที่ยังหลับอยู่ (prod loop ไม่ปิด)
        t = time.monotonic()
        p = await ws.voice_search_payload("ราคาทอง")
        return p, time.monotonic() - t
    p, took = _run(timed())
    assert took < 1.0, f"ต้องตอบตอนชนเพดาน ไม่ใช่รอค้นเสร็จ (ใช้ {took:.2f}s)"
    assert "error" in p and "หาไม่เจอ" not in p["error"]


def test_voice_ใช้_gemini_ก่อนเมื่อเปิดสวิตช์(monkeypatch):
    import utils.llm as llm
    monkeypatch.setattr(llm, "GEMINI_WEB_SEARCH_ENABLED", True)
    monkeypatch.setattr(llm, "gemini_web_search", lambda q: ("จาก gemini", [{"href": "g"}]))
    monkeypatch.setattr(ws, "web_search_with_status", lambda q: pytest.fail("ไม่ควรถึง Brave"))
    assert _run(ws.voice_search_payload("ราคาทอง")) == {"result": "จาก gemini"}


def test_voice_เพดานลงทะเบียน_env():
    from core.env_registry import REGISTRY, load_all
    load_all()
    assert REGISTRY["VOICE_SEARCH_TIMEOUT"].default == ws.VOICE_SEARCH_TIMEOUT_DEFAULT
    assert 5 <= ws.VOICE_SEARCH_TIMEOUT_DEFAULT <= 30


def test_server_โหมดเสียงเรียกผ่าน_voice_search_payload():
    """ฟังก์ชันถูกแต่ handler ไม่เรียก = ไม่มีผลกับ prod"""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")
    h = src[src.index('@app.websocket("/ws/voice/'):]
    h = h[: h.index("\n@app.")] if "\n@app." in h else h
    assert "voice_search_payload(" in h
    assert "web_search_with_results" not in h, "เส้นเก่าที่ไม่มีเพดาน/สถานะยังค้างอยู่"
