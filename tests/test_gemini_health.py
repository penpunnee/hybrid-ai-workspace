"""สถานะ Gemini ที่บอกความจริง + default โมเดลที่ยังมีชีวิต (session 2026-08-26)

🐛 ของจริงวันนี้: เครดิต prepay ของโปรเจกต์หมด ⇒ **ทั้งแชทและสายเสียงยิงไม่ออกเลย**
(429 `Your prepayment credits are depleted` / Live 1011) แต่:
  · `/api/status` ยังรายงาน `gemini: true` เพราะมันเช็คแค่ว่า **มี API key ไหม**
  · หน้าโควตาใน AI Studio แถบยังไม่เต็ม (16.44K/65K) = อ่านแล้วเหมือนปกติ
  · `ListModels` **ผ่านฉลุย** ทั้งที่เครดิตหมด (ยืนยันด้วยการยิงจริง)
⇒ ไม่มีอะไรบอกเลยว่าระบบตาย เจอโดยบังเอิญตอนไปสำรวจโควตา

🔑 บทเรียน: **health check ที่ไม่ยิงงานจริง = ชั้นวัดที่โกหก**
`GET /models` ตอบ 200 ได้แม้ยิงงานจริงไม่ได้ ⇒ ต้อง `:generateContent` เท่านั้น
(ดู vault `wiki/concepts/measuring-instruments-lie.md`)

สัญญาใหม่:
1. `utils/llm.GEMINI_MODEL_DEFAULT` ต้องไม่ใช่รุ่นที่ Google ปิดไปแล้ว
   (ของเดิมคือ `gemini-2.0-flash` ซึ่งถูกปิด 1 มิ.ย. 2026 ⇒ `.env` หายเมื่อไร
    ระบบ 404 ทุกคำขอโดยหน้าตาเหมือน "แชทพัง")
2. `utils/llm.check_gemini_health()` → `(ok, msg)` แบบเดียวกับ ollama/lmstudio
   · ต้องยิง `:generateContent` จริง · แยก "เครดิตหมด" ออกจาก "โควตาเต็ม" และ "โมเดลตาย"
3. `/api/status` เพิ่ม `gemini_ok` + `gemini_message` (คง `gemini` เดิมไว้ = มี key ไหม)
"""
import json
import os
import sys
import urllib.error
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

os.environ["UI_PASSWORD"] = ""
import server  # noqa: E402
import utils.llm as llm  # noqa: E402

client = TestClient(server.app)


def _reset():
    llm._gemini_health_cache.update({"ok": None, "ts": 0.0, "msg": ""})


def _http_error(code, message):
    body = json.dumps({"error": {"code": code, "status": "RESOURCE_EXHAUSTED",
                                 "message": message}}).encode()
    return urllib.error.HTTPError("u", code, "err", {}, None) if False else \
        urllib.error.HTTPError("u", code, "err", {}, __import__("io").BytesIO(body))


class TestGeminiModelDefault:
    RETIRED = {"gemini-2.0-flash", "gemini-2.0-flash-001",
               "gemini-2.0-flash-lite", "gemini-2.0-flash-lite-001"}

    def test_default_ไม่ใช่รุ่นที่ถูกปิดไปแล้ว(self):
        assert llm.GEMINI_MODEL_DEFAULT not in self.RETIRED, (
            "default ชี้ไปรุ่นที่ Google ปิดแล้ว — `.env` หายเมื่อไรระบบ 404 ทุกคำขอ")

    def test_รายชื่อรุ่นที่ปิดแล้วถูกประกาศไว้ให้ตรวจได้(self):
        assert self.RETIRED <= set(llm.RETIRED_GEMINI_MODELS)

    def test_default_ถูกใช้จริงเมื่อไม่มี_env(self):
        # ตรงนี้กันไม่ให้มีใครประกาศค่าคงที่ไว้เฉย ๆ แล้ว hardcode ค่าอื่นในบรรทัดจริง
        import re
        src = open(os.path.join(os.path.dirname(__file__), "..", "utils", "llm.py")).read()
        m = re.search(r'GEMINI_MODEL\s*=\s*os\.getenv\("GEMINI_MODEL",\s*([A-Za-z_]+)\)', src)
        assert m, "ไม่เจอบรรทัดที่อ่าน env GEMINI_MODEL"
        assert m.group(1) == "GEMINI_MODEL_DEFAULT"


class TestCheckGeminiHealth:
    def test_no_key_คืน_false(self, monkeypatch):
        _reset()
        monkeypatch.setattr(llm, "GEMINI_API_KEY", "")
        ok, msg = llm.check_gemini_health(force=True)
        assert ok is False
        assert "GEMINI_API_KEY" in msg

    def test_ยิงผ่าน_คืน_true(self, monkeypatch):
        _reset()
        monkeypatch.setattr(llm, "GEMINI_API_KEY", "k")
        with patch("urllib.request.urlopen", return_value=MagicMock()):
            ok, msg = llm.check_gemini_health(force=True)
        assert (ok, msg) == (True, "")

    def test_RED_เครดิตหมด_ต้องบอกว่าเครดิต_ไม่ใช่โควตา(self, monkeypatch):
        _reset()
        monkeypatch.setattr(llm, "GEMINI_API_KEY", "k")
        err = _http_error(429, "Your prepayment credits are depleted. Please go to AI Studio")
        with patch("urllib.request.urlopen", side_effect=err):
            ok, msg = llm.check_gemini_health(force=True)
        assert ok is False
        assert "เครดิต" in msg, "บอกแค่ 'โควตาหมด' = ไปนั่งรอโควตารีเซ็ตที่ไม่มีวันมา"

    def test_โควตาเต็มจริง_ต้องไม่ถูกเรียกว่าเครดิตหมด(self, monkeypatch):
        _reset()
        monkeypatch.setattr(llm, "GEMINI_API_KEY", "k")
        err = _http_error(429, "You exceeded your current quota, please check your plan")
        with patch("urllib.request.urlopen", side_effect=err):
            ok, msg = llm.check_gemini_health(force=True)
        assert ok is False
        assert "เครดิต" not in msg and "โควตา" in msg

    def test_โมเดลถูกปิด_404_ต้องบอกชื่อโมเดล(self, monkeypatch):
        _reset()
        monkeypatch.setattr(llm, "GEMINI_API_KEY", "k")
        monkeypatch.setattr(llm, "GEMINI_MODEL", "gemini-2.5-flash")
        err = _http_error(404, "This model is no longer available to new users")
        with patch("urllib.request.urlopen", side_effect=err):
            ok, msg = llm.check_gemini_health(force=True)
        assert ok is False
        assert "gemini-2.5-flash" in msg

    def test_RED_ต้องยิง_generateContent_ไม่ใช่แค่_ListModels(self, monkeypatch):
        """ListModels ผ่านฉลุยทั้งที่เครดิตหมด (ยืนยันด้วยการยิงจริง 2026-08-26)
        ⇒ health check ที่เช็คแค่ list = ชั้นวัดที่รายงานเขียวตอนระบบตาย"""
        _reset()
        monkeypatch.setattr(llm, "GEMINI_API_KEY", "k")
        seen = {}
        def fake_urlopen(req, *a, **kw):
            seen["url"] = req.full_url if hasattr(req, "full_url") else str(req)
            return MagicMock()
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            llm.check_gemini_health(force=True)
        assert ":generateContent" in seen["url"], (
            f"ยิงไปที่ {seen.get('url')} — ไม่ใช่การยิงงานจริง")

    def test_cache_กันยิงรัว(self, monkeypatch):
        _reset()
        monkeypatch.setattr(llm, "GEMINI_API_KEY", "k")
        calls = []
        def fake_urlopen(req, *a, **kw):
            calls.append(1); return MagicMock()
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            llm.check_gemini_health(force=True)
            llm.check_gemini_health()
            llm.check_gemini_health()
        assert len(calls) == 1, "ยิงทุกครั้งที่มีคนเปิด /api/status = เปลืองเงินจริง"

    def test_เน็ตล่ม_ไม่_throw(self, monkeypatch):
        _reset()
        monkeypatch.setattr(llm, "GEMINI_API_KEY", "k")
        with patch("urllib.request.urlopen", side_effect=OSError("no route")):
            ok, msg = llm.check_gemini_health(force=True)
        assert ok is False and msg


class TestStatusEndpoint:
    def test_RED_status_ต้องมี_gemini_ok_แยกจากการมี_key(self, monkeypatch):
        _reset()
        with patch.object(llm, "check_gemini_health", return_value=(False, "❌ เครดิต Gemini หมด")):
            r = client.get("/api/status")
        assert r.status_code == 200
        d = r.json()
        assert d["gemini_ok"] is False
        assert "เครดิต" in d["gemini_message"]
        assert "gemini" in d, "ห้ามถอดฟิลด์เดิม (UI ใช้อยู่)"

    def test_status_ยิงจริงผ่าน_gemini_ok_เป็น_true(self):
        _reset()
        with patch.object(llm, "check_gemini_health", return_value=(True, "")):
            d = client.get("/api/status").json()
        assert d["gemini_ok"] is True and d["gemini_message"] == ""
