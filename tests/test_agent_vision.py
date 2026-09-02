"""agent mode ต้องไม่ทิ้งรูปเงียบๆ (งานค้างข้อ 1, วินิจฉัย 2026-08-28)

`routers/chat.py` อ่าน `image_b64` จาก body และส่งให้ `stream_response` ปกติ
แต่เส้น `tool_agent` เรียก `run_agent(messages, provider=...)` **ไม่ส่งรูปไปด้วย**
⇒ "สรุปภาพ → export ไฟล์" ในเทิร์นเดียวทำไม่ได้ และผู้ใช้ไม่เห็นสัญญาณอะไรเลย

เทสชุดนี้ตรึง 3 ชั้น:
1. router ส่ง image_b64/image_mime ต่อให้ run_agent
2. run_agent ส่งต่อถึง adapter ของ provider ที่มองเห็นรูปจริง (gemini/lmstudio)
3. provider ที่ไม่รองรับ (ollama ReAct) ต้อง **บอก** ไม่ใช่ทิ้งเงียบ
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("UI_PASSWORD", "")

from unittest.mock import patch

# 1x1 PNG
PNG_1X1 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGMAAQAABQAB"
           "oIJXOQAAAABJRU5ErkJggg==")


def _collect(gen):
    return list(gen)


class TestRunAgentForwardsImage:
    """run_agent ต้องรับรูปแล้วส่งต่อให้ path ของ provider"""

    def test_gemini_path_receives_image(self):
        with patch("agents.orchestrator._run_agent_gemini") as mock_gemini:
            mock_gemini.return_value = iter([("chunk", "ok")])
            from agents.orchestrator import run_agent
            _collect(run_agent(
                [{"role": "user", "content": "ในรูปมีอะไร"}],
                provider="gemini", image_b64=PNG_1X1, image_mime="image/png",
            ))
        kw = mock_gemini.call_args.kwargs
        assert kw.get("image_b64") == PNG_1X1, "gemini path ไม่ได้รับรูป"
        assert kw.get("image_mime") == "image/png"

    def test_lmstudio_path_receives_image(self):
        with patch("agents.orchestrator._run_agent_lmstudio") as mock_lm:
            mock_lm.return_value = iter([("chunk", "ok")])
            from agents.orchestrator import run_agent
            _collect(run_agent(
                [{"role": "user", "content": "ในรูปมีอะไร"}],
                provider="lmstudio", image_b64=PNG_1X1, image_mime="image/png",
            ))
        kw = mock_lm.call_args.kwargs
        assert kw.get("image_b64") == PNG_1X1, "lmstudio path ไม่ได้รับรูป"


class TestGeminiAdapterCarriesImage:
    """รูปต้องไปอยู่ใน parts ของ user message ล่าสุดที่ส่งเข้า chat"""

    def _run(self, image_b64):
        captured = {}

        def fake_fc(adapter, max_steps):
            captured["adapter"] = adapter
            yield ("chunk", "ok")

        from agents import orchestrator as orch
        with patch.object(orch, "GEMINI_API_KEY", "fake-key"), \
             patch("google.genai.Client"), \
             patch.object(orch, "_run_agent_fc", fake_fc):
            _collect(orch._run_agent_gemini(
                [{"role": "user", "content": "ในรูปมีอะไร"}],
                model="gemini-3.5-flash-lite", max_steps=4,
                image_b64=image_b64, image_mime="image/png",
            ))
        return captured["adapter"]

    def test_image_becomes_inline_data_part(self):
        adapter = self._run(PNG_1X1)
        pending = adapter._pending
        assert isinstance(pending, list), f"มีรูปแล้ว pending ต้องเป็น list[Part] ได้ {type(pending).__name__}"
        assert any(getattr(p, "inline_data", None) for p in pending), "ไม่มี inline_data part = รูปหาย"
        assert any(getattr(p, "text", None) for p in pending), "ข้อความของ user หายไปพร้อมรูป"

    def test_empty_prompt_sends_image_only(self):
        """prompt ว่าง (เรียกตรงผ่าน API) — ห้ามแนบ Part(text="") เปล่าเข้า API"""
        from agents import orchestrator as orch
        parts = orch._gemini_pending_with_image("", PNG_1X1, "image/png")
        assert isinstance(parts, list) and len(parts) == 1
        assert getattr(parts[0], "inline_data", None), "เหลือแต่ part ที่ไม่ใช่รูป"

    def test_bad_base64_falls_back_to_text(self):
        from agents import orchestrator as orch
        assert orch._gemini_pending_with_image("ถาม", "ไม่ใช่ base64!!", "image/png") == "ถาม"

    def test_no_image_keeps_plain_text(self):
        """กลุ่มควบคุม — ไม่มีรูปต้องไม่เปลี่ยนพฤติกรรมเดิม (ส่ง str ตรงๆ)"""
        adapter = self._run("")
        assert adapter._pending == "ในรูปมีอะไร"


class TestLMStudioAdapterCarriesImage:
    def _run(self, image_b64):
        captured = {}

        def fake_fc(adapter, max_steps):
            captured["adapter"] = adapter
            yield ("chunk", "ok")

        from agents import orchestrator as orch
        with patch.object(orch, "LMSTUDIO_BASE_URL", "http://fake:1234/v1"), \
             patch("openai.OpenAI"), \
             patch.object(orch, "_run_agent_fc", fake_fc):
            _collect(orch._run_agent_lmstudio(
                [{"role": "user", "content": "ในรูปมีอะไร"}],
                model="qwen/qwen3.5-9b", max_steps=4,
                image_b64=image_b64, image_mime="image/png",
            ))
        return captured["adapter"]

    def test_image_becomes_image_url_content(self):
        adapter = self._run(PNG_1X1)
        last = adapter.messages[-1]
        assert last["role"] == "user"
        assert isinstance(last["content"], list), "มีรูปแล้ว content ต้องเป็น list ของ parts"
        kinds = [p.get("type") for p in last["content"]]
        assert "image_url" in kinds, "ไม่มี image_url = รูปหาย"
        assert "text" in kinds, "ข้อความของ user หายไปพร้อมรูป"
        url = next(p["image_url"]["url"] for p in last["content"] if p.get("type") == "image_url")
        assert url.startswith("data:image/png;base64,"), f"mime ไม่ตรง: {url[:40]}"

    def test_empty_prompt_sends_image_only(self):
        from agents import orchestrator as orch
        msgs = orch._attach_image_openai([{"role": "user", "content": ""}], PNG_1X1, "image/png")
        kinds = [p.get("type") for p in msgs[-1]["content"]]
        assert kinds == ["image_url"], f"มี text part เปล่าติดไปด้วย: {kinds}"

    def test_no_image_keeps_plain_string(self):
        adapter = self._run("")
        assert adapter.messages[-1]["content"] == "ในรูปมีอะไร"


class TestOllamaSaysItCannotSeeImages:
    """ReAct/llama3 ไม่มี vision — ต้องบอกผู้ใช้ ไม่ใช่ทิ้งเงียบแบบเดิม"""

    def test_warns_instead_of_dropping(self):
        from agents import orchestrator as orch

        def fake_react(*a, **k):
            yield ("chunk", "answer")

        # ⚠️ ต้อง patch ชื่อที่ **มีอยู่จริง** — `create=True` กับชื่อที่ไม่มี
        # = ไม่ได้ patch อะไรเลย แล้วเทสจะยิง HTTP ไป Ollama จริง (เจอตอน scrutinize)
        assert hasattr(orch, "_run_agent_ollama")
        with patch.object(orch, "_run_agent_ollama", fake_react):
            results = _collect(orch.run_agent(
                [{"role": "user", "content": "ในรูปมีอะไร"}],
                provider="ollama", image_b64=PNG_1X1, image_mime="image/png",
            ))
        events = [r[1] for r in results if r[0] == "event"]
        assert any("รูป" in str(e.get("message", "")) for e in events), \
            f"ไม่มี event เตือนว่ามองรูปไม่ได้: {events}"


class TestChatRouterPassesImageToAgent:
    def test_router_forwards_image_b64(self, monkeypatch):
        from fastapi.testclient import TestClient
        import server
        import agents.orchestrator as orch

        cap = {}

        def fake_run_agent(messages, **kw):
            cap.update(kw)
            yield ("chunk", "ok")

        monkeypatch.setattr(orch, "run_agent", fake_run_agent)
        client = TestClient(server.app)
        r = client.post("/api/chat", json={
            "session_id": "agent-vision",
            "prompt": "ในรูปมีอะไร",
            "tool_agent": True,
            "provider": "gemini",
            "image_b64": PNG_1X1,
            "image_mime": "image/png",
            "active_learning": False,
            "response_cache": False,
        })
        assert r.status_code == 200
        _ = r.text  # consume SSE
        assert cap.get("image_b64") == PNG_1X1, f"router ทิ้งรูป: {sorted(cap)}"
        assert cap.get("image_mime") == "image/png"
