"""อุ่นโมเดล embed ของ Ollama ตอนผู้ใช้เปิด/กลับมาที่แอป (devlog 10-07 · คู่กับ warm_lmstudio)

prod 10-07 02:21 UTC: PC .235 เพิ่งตื่น (ดับตั้งแต่ 21:31) → แชทแรกเป็น cache hit แต่รอ embed 27 วิ
เพราะ Ollama ต้องโหลด paraphrase-multilingual ใหม่ (`keep_alive` 24h ไม่รอดตอน PC ดับ) ·
`/api/warmup` ยิงตอน 02:14 แต่อุ่นแค่ qwen ⇒ 7 นาทีระหว่างนั้นเสียเปล่า

ปอยเคาะ (10-07): อุ่นเบื้องหลังด้วย read timeout ยาว ~90 วิ (connect สั้นเท่าเดิม) ให้โหลดจนเสร็จจริง ·
อุ่นแล้ว timeout ตอนอ่าน **ห้าม**เปิดตัวพัก Ollama ล่ม (ไม่งั้นแชท/ความจำข้าม Ollama ไป 60 วิทั้งที่เครื่องอยู่)
"""
import os
import sys
from types import SimpleNamespace

import httpx
import pytest
from openai import APIConnectionError, APITimeoutError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils.embed as embed


class _FakeOllama:
    """แทน `_ollama_client` — จด timeout ที่ขอผ่าน with_options + input ที่ส่งไป embed"""

    def __init__(self, exc=None, model=None):
        self.calls = []
        self.timeouts = []
        self.exc = exc
        self.model = model or embed._EMBED_MODEL
        self.base_url = "http://192.0.2.1:11434/v1"
        self.embeddings = SimpleNamespace(create=self.create)

    def with_options(self, **kw):
        self.timeouts.append(kw.get("timeout"))
        return self

    def create(self, *, model, input):
        self.calls.append((model, list(input)))
        if self.exc is not None:
            raise self.exc
        return SimpleNamespace(model=self.model, data=[SimpleNamespace(embedding=[0.1, 0.2])])


def _sync(fn, *a):
    fn(*a)


@pytest.fixture()
def fake(monkeypatch):
    f = _FakeOllama()
    monkeypatch.setattr(embed, "_ollama_client", f)
    monkeypatch.setattr(embed, "_embed_warm_state", {"at": -1e9, "running": False})
    monkeypatch.setattr(embed, "_down_until", {})
    monkeypatch.setattr(embed, "_EMBED_DOWN_COOLDOWN", 60)
    monkeypatch.setattr(embed, "_ollama_embed_loaded", lambda: False)
    return f


def _read_timeout():
    req = httpx.Request("POST", "http://192.0.2.1:11434/api/embed")
    e = APITimeoutError(request=req)
    e.__cause__ = httpx.ReadTimeout("timed out", request=req)
    return e


def _connect_error():
    req = httpx.Request("POST", "http://192.0.2.1:11434/api/embed")
    e = APIConnectionError(request=req)
    e.__cause__ = httpx.ConnectError("refused", request=req)
    return e


def test_not_loaded_sends_one_embed_to_ollama(fake):
    assert embed.warm_ollama_embed(spawn=_sync) == "warming"
    assert len(fake.calls) == 1
    model, inputs = fake.calls[0]
    assert model == embed._EMBED_MODEL and len(inputs) == 1


def test_loaded_model_is_left_alone(fake, monkeypatch):
    monkeypatch.setattr(embed, "_ollama_embed_loaded", lambda: True)
    assert embed.warm_ollama_embed(spawn=_sync) == "loaded"
    assert fake.calls == []


def test_warm_bypasses_embed_cache(fake, monkeypatch):
    """ผ่าน cache = เจอใน cache แล้วไม่ถึง Ollama เลย ⇒ ไม่ได้อุ่นอะไร"""
    def _no_cache(*a, **k):
        raise AssertionError("การอุ่นห้ามผ่าน embed cache")
    monkeypatch.setattr(embed, "_cache_get", _no_cache)
    monkeypatch.setattr(embed, "_embed_one_cached", _no_cache)
    embed.warm_ollama_embed(spawn=_sync)
    assert len(fake.calls) == 1


def test_skipped_while_ollama_marked_down(fake):
    """PC ดับ (เพิ่งต่อไม่ติด) → ไม่ยิงซ้ำ ไม่เสียเวลา"""
    embed._down_until["Ollama"] = embed._now() + 30
    assert embed.warm_ollama_embed(spawn=_sync) == "down"
    assert fake.calls == []


def test_repeated_calls_are_throttled(fake):
    assert embed.warm_ollama_embed(spawn=_sync) == "warming"
    assert embed.warm_ollama_embed(spawn=_sync) == "skipped"
    assert len(fake.calls) == 1


def test_failure_does_not_raise_and_releases_flag(fake):
    fake.exc = RuntimeError("boom")
    assert embed.warm_ollama_embed(spawn=_sync) == "warming"
    assert embed._embed_warm_state["running"] is False, "ล้มแล้วต้องปลดธง ไม่งั้นอุ่นไม่ได้อีกเลย"


# ── ปอยเคาะข้อ 1: read timeout ยาว ~90 วิ · connect สั้นเท่าเดิม ─────────────────────────────
def test_warm_uses_long_read_short_connect_timeout(fake):
    embed.warm_ollama_embed(spawn=_sync)
    assert fake.timeouts, "การอุ่นต้องตั้ง timeout ของตัวเอง (with_options) ไม่ใช้ 30 วิของแชท"
    t = fake.timeouts[-1]
    assert isinstance(t, httpx.Timeout)
    assert t.read >= 90, f"read timeout ต้อง ~90 วิ ให้โหลดจนเสร็จจริง (ได้ {t.read})"
    assert t.connect == embed._EMBED_CONNECT_TIMEOUT, "connect ต้องสั้นเท่าเดิม — PC ดับต้องรู้เร็ว"


def test_warm_client_is_real_native_client_with_long_timeout():
    """ตรวจตัวจริง (ไม่ใช่ fake): client ที่ใช้อุ่นยังเป็นตัว native (ส่ง keep_alive) และ timeout ติดจริง"""
    c = embed._ollama_client.with_options(timeout=embed._WARM_TIMEOUT)
    assert isinstance(c, embed._OllamaNativeClient), "with_options ต้องคงคลาส native (ไม่งั้นเสีย keep_alive)"
    assert c.timeout.read >= 90 and c.timeout.connect == embed._EMBED_CONNECT_TIMEOUT
    assert embed._ollama_client.timeout.read == embed._EMBED_TIMEOUT, "ห้ามแก้ timeout ของ client แชท"


def test_chat_embed_timeout_unchanged():
    """กลุ่มควบคุม: เส้นแชท/ความจำยังใช้ read timeout เดิม (30 วิ) — ยาวขึ้นเฉพาะการอุ่นเบื้องหลัง"""
    assert embed._HTTP_TIMEOUT.read == embed._EMBED_TIMEOUT
    assert embed._EMBED_TIMEOUT < 90


# ── ปอยเคาะข้อ 2: timeout ตอนอ่านระหว่างอุ่น ห้ามเปิดตัวพัก Ollama ล่ม ──────────────────────
def test_read_timeout_during_warm_does_not_mark_ollama_down(fake):
    fake.exc = _read_timeout()
    assert embed.warm_ollama_embed(spawn=_sync) == "warming"
    assert len(fake.calls) == 1
    assert embed.provider_down_for("Ollama") == 0, "อ่านช้า = เครื่องยังอยู่ ห้ามพัก Ollama 60 วิ"


def test_connect_error_during_warm_still_marks_down(fake):
    """กลุ่มควบคุม: ต่อไม่ติดจริง (PC ดับ) ยังพักตามเดิม — เทสข้างบนจึงแยกได้จริง ไม่ใช่ไม่เคยพักเลย"""
    fake.exc = _connect_error()
    embed.warm_ollama_embed(spawn=_sync)
    assert embed.provider_down_for("Ollama") > 0


# ── endpoint ──────────────────────────────────────────────────────────────────
def test_endpoint_warms_both(monkeypatch):
    from fastapi.testclient import TestClient
    import server
    import routers.system as sysmod
    called = []
    monkeypatch.setattr(sysmod, "warm_lmstudio", lambda *a, **k: called.append("lm") or "warming")
    monkeypatch.setattr(sysmod, "warm_ollama_embed", lambda *a, **k: called.append("embed") or "loaded")
    r = TestClient(server.app).post("/api/warmup")
    assert r.status_code == 200
    assert r.json() == {"status": "warming", "embed": "loaded"}
    assert sorted(called) == ["embed", "lm"]


def test_real_read_timeout_from_silent_server_does_not_mark_down(monkeypatch):
    """ของจริงทั้งสาย (ไม่ fake exception): เซิร์ฟเวอร์รับ TCP แล้วเงียบ = Ollama กำลังโหลดโมเดล ·
    client native ตัวจริง + read timeout สั้นลงเฉพาะเทส ⇒ ต้องจบด้วย ReadTimeout และไม่พัก Ollama"""
    import socket
    import threading
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    held = []
    threading.Thread(target=lambda: held.append(srv.accept()), daemon=True).start()
    port = srv.getsockname()[1]
    try:
        client = embed._OllamaNativeClient(base_url=f"http://127.0.0.1:{port}/v1", api_key="ollama",
                                           timeout=embed._HTTP_TIMEOUT, max_retries=0)
        monkeypatch.setattr(embed, "_ollama_client", client)
        monkeypatch.setattr(embed, "_embed_warm_state", {"at": -1e9, "running": False})
        monkeypatch.setattr(embed, "_down_until", {})
        monkeypatch.setattr(embed, "_EMBED_DOWN_COOLDOWN", 60)
        monkeypatch.setattr(embed, "_ollama_embed_loaded", lambda: False)
        monkeypatch.setattr(embed, "_WARM_TIMEOUT", httpx.Timeout(0.5, connect=embed._EMBED_CONNECT_TIMEOUT))
        seen = []
        real_via = embed._embed_via

        def _spy(provider, c, inputs):
            try:
                return real_via(provider, c, inputs)
            except Exception as e:
                seen.append(e)
                raise
        monkeypatch.setattr(embed, "_embed_via", _spy)
        assert embed.warm_ollama_embed(spawn=_sync) == "warming"
        assert len(seen) == 1 and isinstance(seen[0].__cause__, httpx.ReadTimeout), \
            f"ต้องเป็น ReadTimeout จริง (ได้ {seen!r} cause={getattr(seen[0], '__cause__', None)!r})"
        assert embed.provider_down_for("Ollama") == 0
    finally:
        srv.close()
        for conn, _ in held:
            conn.close()
