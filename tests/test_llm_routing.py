"""Regression tests สำหรับ LLM provider routing

Bug ที่เจอ (session 2026-05-26):
  ผู้ใช้รัน Ollama เป็น local LLM (ไม่ได้รัน LM Studio) แต่โค้ด hardcode
  LMSTUDIO_BASE_URL default = http://192.168.51.235:1234/v1 ทำให้:
    1. provider="ollama" ถูก redirect ไป LM Studio ที่ไม่มีจริง → "เชื่อมต่อ LM Studio ไม่ได้"
    2. auto-route เลือก LM Studio (ตาย) ก่อน Ollama
    3. Gemini quota หมด → fallback ไป LM Studio (ตาย) แทน Ollama

  Fix: LM Studio ต้องเป็น opt-in (default ว่าง) — เปิดใช้เฉพาะเมื่อ set LMSTUDIO_BASE_URL
"""
import os
import sys
import importlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─────────────────────────────────────────────────────────────
# Config: LMSTUDIO_BASE_URL ต้องอ่านจาก env (ห้าม hardcode IP ใน source)
#   bug เดิม hardcode http://192.168.51.235:1234/v1 ไว้ใน core.config ทำให้
#   เปลี่ยน address ไม่ได้ผ่าน .env และเข้าใจผิดว่า "LM Studio พร้อมเสมอ"
# ─────────────────────────────────────────────────────────────
def test_lmstudio_base_url_is_env_driven(monkeypatch):
    """ค่า LMSTUDIO_BASE_URL ต้องมาจาก env/.env ไม่ใช่ค่า hardcode ตายตัว"""
    monkeypatch.setenv("LMSTUDIO_BASE_URL", "http://test-host:9999/v1")
    import core.config as cfg
    importlib.reload(cfg)
    try:
        assert cfg.LMSTUDIO_BASE_URL == "http://test-host:9999/v1", (
            f"config ไม่ได้อ่านจาก env — ได้ {cfg.LMSTUDIO_BASE_URL!r}"
        )
    finally:
        monkeypatch.undo()
        importlib.reload(cfg)


# ─────────────────────────────────────────────────────────────
# Behavior: provider="ollama" ต้องวิ่งไป Ollama จริง ไม่ใช่ LM Studio
# ─────────────────────────────────────────────────────────────
def test_ollama_provider_uses_ollama_even_when_lmstudio_set(monkeypatch):
    """ปุ่มแยกชัด: provider='ollama' ต้องเรียก _stream_ollama เสมอ
    แม้ตั้ง LMSTUDIO_BASE_URL ไว้ก็ห้าม redirect ไป LM Studio (bug เดิม)"""
    import utils.llm as llm

    # ตั้ง LM Studio ไว้ (เหมือน .env จริงของผู้ใช้) — ห้าม redirect
    monkeypatch.setattr(llm, "_LMSTUDIO_BASE_URL", "http://192.168.51.235:1234/v1")

    calls: list[str] = []
    monkeypatch.setattr(llm, "_stream_ollama",
                        lambda m: iter([(calls.append("ollama"), "hi")[1]]))
    monkeypatch.setattr(llm, "_stream_lmstudio",
                        lambda *a, **k: iter([(calls.append("lmstudio"), "x")[1]]))

    list(llm.stream_response([{"role": "user", "content": "hi"}], provider="ollama"))
    assert calls == ["ollama"], f"กด Ollama ต้องได้ Ollama แต่ได้ {calls}"


# ─────────────────────────────────────────────────────────────
# Router: auto + ไม่มี LM Studio → ต้องเลือก Ollama (ไม่ใช่ LM Studio)
# ─────────────────────────────────────────────────────────────
def test_auto_route_falls_back_to_ollama_when_no_lmstudio(monkeypatch):
    """auto-route สำหรับคำถามทั่วไป เมื่อไม่มี LM Studio → provider='ollama'"""
    import reasoning.router as router
    monkeypatch.setattr("core.config.LMSTUDIO_BASE_URL", "", raising=False)
    monkeypatch.setattr("core.config.GEMINI_API_KEY", "", raising=False)

    decision = router.route("สวัสดี วันนี้เป็นยังไงบ้าง", provider_hint="auto")
    assert decision.provider == "ollama", (
        f"คาดว่า auto-route → ollama แต่ได้ {decision.provider} ({decision.reason})"
    )


# ─────────────────────────────────────────────────────────────
# Fallback cascade: LM Studio ต่อไม่ได้ → ต้องไล่ต่อ Ollama อัตโนมัติ
#   bug (session 2026-05-27): _stream_lmstudio ดัก connection error แล้ว yield
#   string "เชื่อมต่อ LM Studio ไม่ได้" แทนการ raise → caller จับไม่ได้ →
#   fallback chain หยุดที่ LM Studio ตอบไม่ได้ ทั้งที่ Ollama ยังขึ้นอยู่
# ─────────────────────────────────────────────────────────────
def _mock_lmstudio_dead(monkeypatch, llm):
    """จำลอง LM Studio server ล่ม: create() โยน connection refused"""
    class _Boom:
        def create(self, *a, **k):
            raise Exception("Connection refused")
    fake_chat = type("Chat", (), {})()
    fake_chat.completions = _Boom()
    monkeypatch.setattr(llm.lmstudio_client, "chat", fake_chat)


def test_lmstudio_connection_failure_cascades_to_ollama(monkeypatch):
    """provider='lmstudio' แต่ server ต่อไม่ได้ → cascade ไป Ollama อัตโนมัติ"""
    import utils.llm as llm
    monkeypatch.setattr(llm, "_LMSTUDIO_BASE_URL", "http://192.168.51.235:1234/v1")
    _mock_lmstudio_dead(monkeypatch, llm)
    monkeypatch.setattr(llm, "_stream_ollama", lambda m: iter(["OLLAMA_ANSWER"]))

    out = "".join(llm.stream_response(
        [{"role": "user", "content": "hi"}], provider="lmstudio"))
    assert "OLLAMA_ANSWER" in out, f"ควร cascade ไป Ollama แต่ได้: {out!r}"


def test_lmstudio_failure_with_image_does_not_cascade_to_ollama(monkeypatch):
    """โหมดรูปภาพ: Ollama (llama3) ดูรูปไม่ได้ → ห้าม cascade เงียบๆ ต้องแจ้ง error"""
    import utils.llm as llm
    monkeypatch.setattr(llm, "_LMSTUDIO_BASE_URL", "http://192.168.51.235:1234/v1")
    _mock_lmstudio_dead(monkeypatch, llm)
    monkeypatch.setattr(llm, "_stream_ollama", lambda m: iter(["OLLAMA_ANSWER"]))

    out = "".join(llm.stream_response(
        [{"role": "user", "content": "นี่รูปอะไร"}],
        provider="lmstudio", image_b64="ZmFrZQ==", image_mime="image/png"))
    assert "OLLAMA_ANSWER" not in out, f"โหมดรูปไม่ควร cascade ไป Ollama: {out!r}"
    assert "LM Studio" in out, f"ควรแจ้ง error LM Studio แต่ได้: {out!r}"


# ─────────────────────────────────────────────────────────────
# Claude auto-routing (opt-in via CLAUDE_AUTO) — session 2026-05-29
#   off (default) → ไม่แตะ Claude; reasoning → เฉพาะคำถามยาก; all → ทุก text
#   ต้องมี ANTHROPIC_API_KEY; internet/vision ยังไปทางเดิม (Claude ไม่มี web tool)
# ─────────────────────────────────────────────────────────────
def _claude_env(monkeypatch, mode, key="sk-ant-x"):
    import reasoning.router as router
    from reasoning.classifier import Complexity
    if key is None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    else:
        monkeypatch.setenv("ANTHROPIC_API_KEY", key)
    if mode is None:
        monkeypatch.delenv("CLAUDE_AUTO", raising=False)
    else:
        monkeypatch.setenv("CLAUDE_AUTO", mode)
    monkeypatch.setattr("reasoning.classifier.needs_internet", lambda p: False)
    return router, Complexity


def test_auto_claude_off_by_default(monkeypatch):
    router, Complexity = _claude_env(monkeypatch, mode=None)
    monkeypatch.setattr(router, "classify", lambda p: Complexity.REASONING)
    monkeypatch.setattr("core.config.LMSTUDIO_BASE_URL", "", raising=False)
    monkeypatch.setattr("core.config.GEMINI_API_KEY", "", raising=False)
    d = router.route("ปัญหายากมาก คิดเยอะ", provider_hint="auto")
    assert d.provider != "claude"


def test_auto_claude_reasoning_picks_claude(monkeypatch):
    router, Complexity = _claude_env(monkeypatch, mode="reasoning")
    monkeypatch.setattr(router, "classify", lambda p: Complexity.REASONING)
    d = router.route("พิสูจน์ทฤษฎีบทนี้ทีละขั้น", provider_hint="auto")
    assert d.provider == "claude"
    assert d.model == "claude-sonnet-4-6"   # default คุ้ม (เปลี่ยนได้ผ่าน CLAUDE_MODEL)


def test_auto_claude_reasoning_skips_simple(monkeypatch):
    router, Complexity = _claude_env(monkeypatch, mode="reasoning")
    monkeypatch.setattr(router, "classify", lambda p: Complexity.NORMAL)
    monkeypatch.setattr("core.config.LMSTUDIO_BASE_URL", "", raising=False)
    monkeypatch.setattr("core.config.GEMINI_API_KEY", "", raising=False)
    d = router.route("สวัสดีครับ", provider_hint="auto")
    assert d.provider != "claude"      # NORMAL ไม่เข้าเกณฑ์ reasoning


def test_auto_claude_all_picks_claude_for_any_text(monkeypatch):
    router, Complexity = _claude_env(monkeypatch, mode="all")
    monkeypatch.setattr(router, "classify", lambda p: Complexity.NORMAL)
    d = router.route("เล่าเรื่องตลกให้ฟังหน่อย", provider_hint="auto")
    assert d.provider == "claude"


def test_auto_claude_requires_key(monkeypatch):
    router, Complexity = _claude_env(monkeypatch, mode="all", key=None)
    monkeypatch.setattr(router, "classify", lambda p: Complexity.NORMAL)
    monkeypatch.setattr("core.config.LMSTUDIO_BASE_URL", "", raising=False)
    monkeypatch.setattr("core.config.GEMINI_API_KEY", "", raising=False)
    d = router.route("อะไรก็ได้", provider_hint="auto")
    assert d.provider != "claude"      # ไม่มี key → ไม่ใช้ Claude


def test_auto_claude_does_not_steal_internet(monkeypatch):
    router, Complexity = _claude_env(monkeypatch, mode="all")
    monkeypatch.setattr("reasoning.classifier.needs_internet", lambda p: True)
    monkeypatch.setattr("core.config.GEMINI_API_KEY", "gkey", raising=False)
    d = router.route("ข่าวล่าสุดวันนี้", provider_hint="auto")
    assert d.provider == "gemini_agent"   # internet → Gemini ก่อนถึง Claude


# ── Fix #5: LM Studio probe ต้องส่ง LMSTUDIO_API_KEY (รุ่นใหม่บังคับ token) ──
def test_lmstudio_headers_includes_token(monkeypatch):
    import reasoning.router as router
    monkeypatch.setenv("LMSTUDIO_API_KEY", "sk-xyz")
    assert router._lmstudio_headers().get("Authorization") == "Bearer sk-xyz"


def test_lmstudio_headers_no_token(monkeypatch):
    import reasoning.router as router
    monkeypatch.delenv("LMSTUDIO_API_KEY", raising=False)
    assert "Authorization" not in router._lmstudio_headers()


def test_ping_model_sends_token(monkeypatch):
    """ไม่งั้น probe 401 → _is_model_available=False → auto-route หลบ lmstudio เสมอ"""
    import reasoning.router as router
    import urllib.request
    monkeypatch.setenv("LMSTUDIO_API_KEY", "sk-test")
    captured = {}
    def fake_urlopen(req, *a, **k):
        captured["auth"] = req.get_header("Authorization")
        raise OSError("stop after capture")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    router._ping_model("http://localhost:1234/v1", "m")
    assert captured["auth"] == "Bearer sk-test"
