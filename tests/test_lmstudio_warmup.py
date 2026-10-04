"""อุ่น qwen ตอนผู้ใช้เปิด/กลับมาที่แอป (งานเปิด จ · ทางเลือก 3 จาก devlog ต่อ 73)

ว่าง >30 นาที LM Studio ปล่อยโมเดล (TTL JIT 1800 วิ) → แชทแรกรอโหลด 5.7–11.6 วิ ·
ไม่จอง VRAM ถาวร (ทางเลือก 2 ต้อง user เคาะ) — อุ่นเฉพาะเมื่อมีคนเปิดแอป ระหว่างที่เขากำลังพิมพ์
"""
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils.llm as llm


class _Fake:
    def __init__(self):
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(choices=[])


@pytest.fixture()
def fake(monkeypatch):
    f = _Fake()
    monkeypatch.setattr(llm, "lmstudio_client", f)
    monkeypatch.setattr(llm, "_warmup_state", {"at": -1e9, "running": False})
    return f


def _sync(fn, *a):
    fn(*a)


def test_not_loaded_triggers_tiny_load_request(fake, monkeypatch):
    monkeypatch.setattr(llm, "_lmstudio_loaded_ctx", lambda m: None)
    assert llm.warm_lmstudio("qwen/qwen3.5-9b", spawn=_sync) == "warming"
    assert len(fake.calls) == 1
    c = fake.calls[0]
    assert c["model"] == "qwen/qwen3.5-9b" and c["max_tokens"] == 1
    assert c.get("stream") in (None, False)


def test_loaded_model_is_left_alone(fake, monkeypatch):
    monkeypatch.setattr(llm, "_lmstudio_loaded_ctx", lambda m: 16384)
    assert llm.warm_lmstudio("qwen/qwen3.5-9b", spawn=_sync) == "loaded"
    assert fake.calls == []


def test_loaded_check_is_fresh_not_cached(fake, monkeypatch):
    """cache 5 นาทีของ _lmstudio_loaded_ctx จะบอก 'ยังโหลด' ทั้งที่ LM Studio ปล่อยไปแล้ว"""
    llm._lmstudio_ctx_cache["qwen/qwen3.5-9b"] = (llm.time.monotonic(), 16384)
    seen = []

    def _probe(m):
        seen.append(m in llm._lmstudio_ctx_cache)
        return None
    monkeypatch.setattr(llm, "_lmstudio_loaded_ctx", _probe)
    llm.warm_lmstudio("qwen/qwen3.5-9b", spawn=_sync)
    assert seen == [False], "ต้องล้าง cache ก่อนถาม"


def test_repeated_calls_are_throttled(fake, monkeypatch):
    monkeypatch.setattr(llm, "_lmstudio_loaded_ctx", lambda m: None)
    assert llm.warm_lmstudio("m", spawn=_sync) == "warming"
    assert llm.warm_lmstudio("m", spawn=_sync) == "skipped"
    assert len(fake.calls) == 1


def test_lmstudio_down_does_not_raise(fake, monkeypatch):
    monkeypatch.setattr(llm, "_lmstudio_loaded_ctx", lambda m: None)

    def boom(**kw):
        raise ConnectionError("down")
    fake.chat.completions.create = boom
    assert llm.warm_lmstudio("m", spawn=_sync) == "warming"
    assert llm._warmup_state["running"] is False, "ล้มแล้วต้องปลดธง ไม่งั้นอุ่นไม่ได้อีกเลย"


def test_endpoint(monkeypatch):
    from fastapi.testclient import TestClient
    import server
    import routers.system as sysmod
    monkeypatch.setattr(sysmod, "warm_lmstudio", lambda *a, **k: "warming")
    r = TestClient(server.app).post("/api/warmup")
    assert r.status_code == 200 and r.json() == {"status": "warming"}
