"""สุขภาพของ embed (Ollama) สำหรับแถบ 🧠 บนจอ — งาน "จุดสถานะบอกความจริง" (devlog 2026-10-08 ต่อ 152–153)

ทำไม: `/api/status.memory` = ChromaDB heartbeat (อยู่บน NAS) ⇒ เป็น true ตอน PC ปิด
ทั้งที่ค้นความจำ/เอกสาร/Vault ใช้ไม่ได้ (embed ผ่าน Ollama บน PC) — จอไม่มีทางรู้

กติกา:
- probe `/api/tags` ทุกครั้งที่ cache หมด (ไม่ใช้ตัวพักตัดสิน — ตัวพักคือ "เพิ่งล้ม" ไม่ใช่สุขภาพ)
- ชื่อโมเดลเทียบแบบตัด `:latest` ทั้งสองฝั่ง (prod คืน `paraphrase-multilingual:latest`)
- ไม่มีผลข้างเคียง: ไม่ตั้งตัวพัก · ไม่ embed จริง
- `pc_off` เฉพาะเมื่อ LM Studio (เครื่องเดียวกัน) ก็ต่อไม่ได้ · ไม่งั้น `ollama_off`
"""
from unittest.mock import MagicMock, patch

import httpx
import pytest

import utils.embed as emb


@pytest.fixture(autouse=True)
def _clean_state():
    emb._embed_health_cache.update({"ts": -1e9, "res": None})
    with emb._down_lock:
        saved = dict(emb._down_until)
        emb._down_until.clear()
    yield
    emb._embed_health_cache.update({"ts": -1e9, "res": None})
    with emb._down_lock:
        emb._down_until.clear()
        emb._down_until.update(saved)


def _resp(status=200, models=()):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = {"models": [{"name": n} for n in models]}
    return r


def _probe(get):
    with patch.object(emb.httpx, "get", get), patch.object(emb, "_EMBED_MODEL", "paraphrase-multilingual"):
        return emb.check_embed_health(force=True)


def test_มีโมเดลแบบ_latest_นับว่าพร้อม():
    res = _probe(MagicMock(return_value=_resp(models=["qwen3:8b", "paraphrase-multilingual:latest"])))
    assert res["reason"] == "ok" and res["ok"] is True


def test_ไม่มีโมเดล_embed_ใน_tags():
    res = _probe(MagicMock(return_value=_resp(models=["qwen3:8b"])))
    assert res["reason"] == "model_missing" and res["ok"] is False


def test_ต่อไม่ได้_คือ_unreachable():
    res = _probe(MagicMock(side_effect=httpx.ConnectError("refused")))
    assert res["reason"] == "unreachable" and res["ok"] is False


def test_connect_timeout_ก็คือ_unreachable():
    res = _probe(MagicMock(side_effect=httpx.ConnectTimeout("timeout")))
    assert res["reason"] == "unreachable"


def test_http_ผิดปกติ_คือ_error_ไม่ใช่_pc_off():
    res = _probe(MagicMock(return_value=_resp(status=500)))
    assert res["reason"] == "error" and res["ok"] is False


def test_ไม่มีผลข้างเคียง_ไม่ตั้งตัวพัก_ไม่_embed_จริง():
    with patch.object(emb, "mark_provider_down") as mark, \
         patch.object(emb, "_embed_via") as via:
        _probe(MagicMock(side_effect=httpx.ConnectError("refused")))
    mark.assert_not_called()
    via.assert_not_called()
    assert emb.provider_down_for("Ollama") == 0


def test_ตัวพักไม่ใช่ตัวตัดสิน_probe_ได้ok_ก็ok():
    """ตัวพักค้างจาก ConnectTimeout ชั่วคราว ห้ามทำให้จอบอกว่า PC ปิดทั้งที่ Ollama ตอบอยู่"""
    with emb._down_lock:
        emb._down_until["Ollama"] = emb._now() + 60
    res = _probe(MagicMock(return_value=_resp(models=["paraphrase-multilingual"])))
    assert res["reason"] == "ok"


def test_cache_30_วิ_ไม่ยิงซ้ำ_แต่_force_ยิง():
    get = MagicMock(return_value=_resp(models=["paraphrase-multilingual"]))
    with patch.object(emb.httpx, "get", get), patch.object(emb, "_EMBED_MODEL", "paraphrase-multilingual"):
        emb.check_embed_health(force=True)
        emb.check_embed_health()
        assert get.call_count == 1
        emb.check_embed_health(force=True)
        assert get.call_count == 2


def test_ยิง_api_tags_ของ_ollama_root_ไม่ใช่_v1():
    get = MagicMock(return_value=_resp(models=["paraphrase-multilingual"]))
    _probe(get)
    url = get.call_args[0][0]
    assert url.endswith("/api/tags") and "/v1/" not in url


# ─── /api/status รวมกับผล LM Studio (เครื่องเดียวกัน) ───────────────────────────

def _status(embed_res, lm_ok, lm_configured=True):
    import routers.system as sysr
    from fastapi.testclient import TestClient
    from server import app
    with patch.object(sysr, "check_ollama_health", return_value=(True, "")), \
         patch.object(sysr, "is_memory_available", return_value=True), \
         patch.object(sysr, "check_lmstudio_health", return_value=(lm_ok, "")), \
         patch.object(sysr._llm, "check_gemini_health", return_value=(True, "")), \
         patch.object(sysr, "check_embed_health", **({"side_effect": embed_res} if isinstance(embed_res, Exception) else {"return_value": embed_res})), \
         patch.object(sysr, "LMSTUDIO_BASE_URL", "http://pc:1234/v1" if lm_configured else ""):
        return TestClient(app).get("/api/status").json()


@pytest.mark.parametrize("raw,lm_ok,configured,ok,reason", [
    ("ok", True, True, True, "ok"),
    ("unreachable", False, True, False, "pc_off"),
    ("unreachable", True, True, False, "ollama_off"),
    ("unreachable", False, False, False, "ollama_off"),   # ไม่มี LM Studio ให้เทียบ = บอกว่า PC ปิดไม่ได้
    ("model_missing", True, True, False, "model_missing"),
    ("error", True, True, False, "ollama_off"),
])
def test_status_ตัดสิน_reason(raw, lm_ok, configured, ok, reason):
    d = _status({"ok": raw == "ok", "reason": raw, "message": ""}, lm_ok, configured)
    assert d["embed_ok"] is ok
    assert d["embed_reason"] == reason


def test_status_probe_พัง_ไม่รู้_ไม่ใช่_ใช้ไม่ได้():
    d = _status(RuntimeError("boom"), True)
    assert d["embed_ok"] is None and d["embed_reason"] == "unknown"


def test_status_ฟิลด์เดิมยังครบ():
    d = _status({"ok": True, "reason": "ok", "message": ""}, True)
    for k in ("ollama", "lmstudio", "local_ok", "local_provider", "gemini", "gemini_ok", "memory", "skills"):
        assert k in d


def test_status_ใช้_worker_พอให้_probe_ทั้ง_5_วิ่งพร้อมกัน():
    """max_workers=4 + งานที่ 5 = ต่อคิวรอ — /api/status ช้าขึ้นตอน PC ดับ"""
    import ast
    import inspect
    import routers.system as sysr
    tree = ast.parse(inspect.getsource(sysr.status))
    workers = [kw.value.value for n in ast.walk(tree) if isinstance(n, ast.Call)
               for kw in n.keywords if kw.arg == "max_workers"]
    submits = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
               and getattr(n.func, "attr", None) == "submit"]
    assert workers and workers[0] >= len(submits) == 5
