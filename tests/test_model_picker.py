"""Tests: model picker (feature 2026-06-15)

กล่องแชทเพิ่ม dropdown เลือกโมเดล (ลิสต์เดียว provider วิ่งตามตัวที่เลือก) +
effort slider + thinking toggle. ครอบคลุม:
  1. GET /api/models — local (LM Studio dynamic) + cloud (curated) + available ตาม key
  2. provider="kimi" (Moonshot, OpenAI-compatible) → เรียก _stream_kimi
  3. model_override / thinking / effort ส่งทะลุไปถึง gemini/claude/ollama/kimi
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
import server

client = TestClient(server.app)


# ── GET /api/models ───────────────────────────────────────────────────────────
class TestModelsEndpoint:
    def test_returns_local_and_cloud(self):
        r = client.get("/api/models")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data.get("local"), list)
        assert isinstance(data.get("cloud"), list)

    def test_cloud_has_gemini_curated(self):
        ids = {m["model"] for m in client.get("/api/models").json()["cloud"]}
        for mid in ("gemini-3.5-flash", "gemini-3-flash-preview",
                    "gemini-3.1-flash-lite", "gemini-2.5-flash", "gemma-4-31b-it"):
            assert mid in ids, f"ขาด {mid} ใน cloud list"

    def test_cloud_has_kimi_and_claude(self):
        cloud = client.get("/api/models").json()["cloud"]
        ids = {m["model"] for m in cloud}
        assert "kimi-k2.6" in ids
        assert any(m["provider"] == "claude" for m in cloud)

    def test_each_item_shape(self):
        data = client.get("/api/models").json()
        for m in data["cloud"] + data["local"]:
            assert {"provider", "model", "label", "available"} <= set(m), m

    def test_gemini_items_use_gemini_provider(self):
        cloud = client.get("/api/models").json()["cloud"]
        for m in cloud:
            if m["model"].startswith(("gemini", "gemma")):
                assert m["provider"] == "gemini"

    def test_kimi_unavailable_without_key(self):
        # conftest ไม่ตั้ง MOONSHOT_API_KEY → kimi ต้อง available=False
        cloud = client.get("/api/models").json()["cloud"]
        kimi = next(m for m in cloud if m["model"] == "kimi-k2.6")
        assert kimi["available"] is False

    def test_local_returns_only_active_chat_model(self, monkeypatch):
        # LM Studio โหลด reason/vision/embedding ไว้ใช้ภายใน — picker ต้องโชว์
        # โมเดลแชท local ตัวที่ใช้งานจริง "ตัวเดียว" ไม่ใช่ทุกตัวที่ server โหลด
        import routers.system as sysmod
        monkeypatch.setattr(sysmod, "OLLAMA_MODEL", "qwen/qwen3.5-9b")
        local = client.get("/api/models").json()["local"]
        assert len(local) == 1, f"local ต้องเหลือตัวเดียว ได้ {local}"
        assert local[0]["model"] == "qwen/qwen3.5-9b"
        assert local[0]["provider"] == "ollama"
        # ไม่มี embedding/reason/aux model หลุดมา
        ids = " ".join(m["model"].lower() for m in local)
        assert "embed" not in ids and "deepseek" not in ids and "gemma" not in ids


# ── provider="kimi" routing ───────────────────────────────────────────────────
class TestKimiRouting:
    def test_kimi_provider_calls_stream_kimi(self, monkeypatch):
        import utils.llm as llm
        calls = []

        def fake_kimi(messages, **k):
            calls.append(k)
            yield "hi"

        monkeypatch.setattr(llm, "_stream_kimi", fake_kimi)
        out = "".join(llm.stream_response(
            [{"role": "user", "content": "hi"}],
            provider="kimi", model_override="kimi-k2.6", thinking=False))
        assert out == "hi"
        assert calls, "ไม่ได้เรียก _stream_kimi"
        assert calls[0].get("model") == "kimi-k2.6"
        assert calls[0].get("thinking") is False


# ── model / thinking / effort pass-through ────────────────────────────────────
class TestParamPassThrough:
    def test_gemini_receives_model_thinking_effort(self, monkeypatch):
        import utils.llm as llm
        cap = {}

        def fake(messages, image_b64="", image_mime="", agent_mode=False,
                 model="", thinking=None, effort=""):
            cap.update(model=model, thinking=thinking, effort=effort)
            yield "ok"

        monkeypatch.setattr(llm, "_stream_gemini", fake)
        list(llm.stream_response(
            [{"role": "user", "content": "hi"}],
            provider="gemini", model_override="gemini-3-flash-preview",
            thinking=True, effort="high"))
        assert cap == {"model": "gemini-3-flash-preview", "thinking": True, "effort": "high"}

    def test_claude_receives_model_thinking_effort(self, monkeypatch):
        import utils.llm as llm
        cap = {}

        def fake(messages, image_b64="", image_mime="",
                 model="", thinking=None, effort=""):
            cap.update(model=model, thinking=thinking, effort=effort)
            yield "ok"

        monkeypatch.setattr(llm, "_stream_claude", fake)
        list(llm.stream_response(
            [{"role": "user", "content": "hi"}],
            provider="claude", model_override="claude-opus-4-8",
            thinking=True, effort="max"))
        assert cap == {"model": "claude-opus-4-8", "thinking": True, "effort": "max"}

    def test_ollama_receives_model(self, monkeypatch):
        import utils.llm as llm
        cap = {}

        def fake(messages, model=""):
            cap.update(model=model)
            yield "ok"

        monkeypatch.setattr(llm, "_stream_ollama", fake)
        list(llm.stream_response(
            [{"role": "user", "content": "hi"}],
            provider="ollama", model_override="qwen/qwen3.5-9b"))
        assert cap["model"] == "qwen/qwen3.5-9b"

    def test_thinking_default_none_preserves_behavior(self, monkeypatch):
        """ไม่ส่ง thinking → ต้องเป็น None (ใช้ค่า env เดิมของแต่ละ provider, ไม่ regress)"""
        import utils.llm as llm
        cap = {}

        def fake(messages, image_b64="", image_mime="", agent_mode=False,
                 model="", thinking="SENTINEL", effort=""):
            cap.update(thinking=thinking)
            yield "ok"

        monkeypatch.setattr(llm, "_stream_gemini", fake)
        list(llm.stream_response([{"role": "user", "content": "hi"}], provider="gemini"))
        assert cap["thinking"] is None
