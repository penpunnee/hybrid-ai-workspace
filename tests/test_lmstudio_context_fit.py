"""เส้น LM Studio ต้องตัดประวัติให้พอดี context + บอกผู้ใช้เมื่อคำตอบถูกตัด (2026-10-02 ต่อ 74)

prod 10-02 session `…5_d73044`: ประวัติ 10 ข้อความ = **7,114 token** (นับด้วย LM Studio เอง)
ขณะ qwen โหลดที่ context **8,192** · คำตอบสั้นลงทุกรอบ 8546 → 8304 → 328 ตัวอักษร (ตัดกลางประโยค)
→ ว่าง 2 ครั้ง · 08:24 `Context size has been exceeded`
ต้นเหตุ: `routers/chat.py` ตัดประวัติเฉพาะ provider `ollama` · เส้น LM Studio ส่งทั้งก้อนเสมอ
และไม่เช็ค `finish_reason` ⇒ ตัดเงียบ ("ไม่ต่อเนื่อง")
วัด qwen3.5-9b: คิดในใจ 844–1131 token ต่อคำตอบ · คำตอบยาวสุดในแชทจริง ~2.2k ⇒ รวม ~3.2k
"""
from types import SimpleNamespace

import pytest

from utils import llm
from utils.tokens import count_tokens_approx


def _chunk(text, finish=None):
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=text), finish_reason=finish)], usage=None)


class _Rec:
    def __init__(self, chunks):
        self.chunks, self.sent = chunks, None

    def create(self, **kw):
        self.sent = kw
        return iter(self.chunks)


@pytest.fixture()
def rec(monkeypatch):
    r = _Rec([_chunk("ตอบ"), _chunk("", "stop")])
    monkeypatch.setattr(llm.lmstudio_client, "chat", SimpleNamespace(completions=r))
    monkeypatch.setattr(llm, "_LMSTUDIO_CONTEXT_LENGTH", 8192)
    monkeypatch.setattr(llm, "_LMSTUDIO_REPLY_RESERVE", 3072)
    monkeypatch.setattr(llm, "_lmstudio_loaded_ctx", lambda model: None)
    return r


def _convo(n_pairs, reply_chars=6000):
    msgs = [{"role": "system", "content": "ระบบ " * 50}]
    for i in range(n_pairs):
        msgs.append({"role": "user", "content": f"คำถามที่ {i}"})
        msgs.append({"role": "assistant", "content": f"[{i}]" + "ก" * reply_chars})
    msgs.append({"role": "user", "content": "คำถามล่าสุด"})
    return msgs


def test_ประวัติเกินงบ_ตัดเก่าทิ้ง_เก็บ_system_กับคำถามล่าสุด(rec):
    msgs = _convo(5)                                   # ~10k token (approx) > 8192-3072
    "".join(llm._stream_lmstudio(msgs, model="m"))
    sent = rec.sent["messages"]
    assert sent[0] == msgs[0], "system prompt ต้องอยู่เสมอ"
    assert sent[-1] == msgs[-1], "คำถามล่าสุดต้องอยู่เสมอ"
    assert len(sent) < len(msgs)
    assert count_tokens_approx(sent) <= 8192 - 3072
    # ตัดจากเก่าสุด: ของที่เหลือเป็นท้ายบทสนทนาเดิมแบบต่อเนื่อง
    assert sent[1:] == msgs[len(msgs) - len(sent) + 1:]


def test_ไม่ทิ้งคำตอบโดยไม่ทิ้งคำถามคู่กัน(rec):
    """ห้ามเริ่มประวัติด้วย assistant ที่ไม่มีคำถามนำ — qwen งงว่าตอบอะไรอยู่"""
    "".join(llm._stream_lmstudio(_convo(5), model="m"))
    assert rec.sent["messages"][1]["role"] == "user"


def test_จุดตัดตกที่คำตอบ_ต้องทิ้งคำตอบนั้นด้วย(rec):
    """คำถามยาว (แปะเอกสาร) คำตอบสั้น — ตัดตามงบอย่างเดียวจะหยุดที่ assistant (กลุ่มควบคุมของเทสบน)"""
    msgs = [{"role": "system", "content": "ระบบ"}]
    for i in range(5):
        msgs.append({"role": "user", "content": f"[{i}]" + "ก" * 6000})
        msgs.append({"role": "assistant", "content": f"ตอบ {i}"})
    msgs.append({"role": "user", "content": "คำถามล่าสุด"})
    "".join(llm._stream_lmstudio(msgs, model="m"))
    sent = rec.sent["messages"]
    assert len(sent) < len(msgs)
    assert sent[1]["role"] == "user"


def test_ประวัติสั้น_ส่งครบ_และไม่ถาม_context_จาก_LM_Studio(rec, monkeypatch):
    def boom(model):
        raise AssertionError("ไม่ควรยิง /api/v1/models เมื่อข้อความพอดีงบอยู่แล้ว")
    monkeypatch.setattr(llm, "_lmstudio_loaded_ctx", boom)
    msgs = _convo(1, reply_chars=300)
    "".join(llm._stream_lmstudio(msgs, model="m"))
    assert rec.sent["messages"] == msgs


def test_ใช้_context_ที่โหลดจริงเมื่อใหญ่กว่า_default(rec, monkeypatch):
    msgs = _convo(5)
    "".join(llm._stream_lmstudio(msgs, model="m"))
    n_8k = len(rec.sent["messages"])
    monkeypatch.setattr(llm, "_lmstudio_loaded_ctx", lambda model: 32768)
    "".join(llm._stream_lmstudio(msgs, model="m"))
    assert len(rec.sent["messages"]) > n_8k
    assert count_tokens_approx(rec.sent["messages"]) <= 32768 - 3072


def test_system_กับคำถามล่าสุดเกินงบเอง_ยังส่ง(rec):
    msgs = [{"role": "system", "content": "ก" * 30000}, {"role": "user", "content": "ถาม"}]
    "".join(llm._stream_lmstudio(msgs, model="m"))
    assert rec.sent["messages"] == msgs


def test_finish_length_แจ้งผู้ใช้ว่าคำตอบถูกตัด(monkeypatch, rec):
    rec.chunks = [_chunk("ครึ่งประโยค"), _chunk("", "length")]
    out = "".join(llm._stream_lmstudio([{"role": "user", "content": "x"}], model="m"))
    assert out.startswith("ครึ่งประโยค")
    assert "⚠️" in out and "ถูกตัด" in out


def test_finish_stop_ไม่มีคำเตือน(rec):
    out = "".join(llm._stream_lmstudio([{"role": "user", "content": "x"}], model="m"))
    assert out == "ตอบ"


def test_อ่าน_context_ที่โหลดจาก_api_v1_models(monkeypatch):
    payload = {"models": [
        {"key": "other", "loaded_instances": [{"config": {"context_length": 4096}}]},
        {"key": "qwen/qwen3.5-9b", "loaded_instances": [{"config": {"context_length": 16384}}]},
        {"key": "idle", "loaded_instances": []},
    ]}
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        return SimpleNamespace(status_code=200, json=lambda: payload)
    monkeypatch.setattr(llm.httpx, "get", fake_get)
    llm._lmstudio_ctx_cache.clear()
    assert llm._lmstudio_loaded_ctx("qwen/qwen3.5-9b") == 16384
    assert calls and calls[0].endswith("/api/v1/models")
    assert llm._lmstudio_loaded_ctx("idle") is None, "ไม่ได้โหลด = ไม่รู้ → ใช้ default"


def test_อ่าน_context_ไม่ได้_คืน_None(monkeypatch):
    def fail(url, **kw):
        raise OSError("ต่อไม่ติด")
    monkeypatch.setattr(llm.httpx, "get", fail)
    llm._lmstudio_ctx_cache.clear()
    assert llm._lmstudio_loaded_ctx("qwen/qwen3.5-9b") is None


def _ctx_server(monkeypatch, state):
    """LM Studio จำลอง: state["ctx"] = None (ยังไม่โหลด) หรือ context ที่โหลด · นับจำนวนครั้งที่ถาม"""
    def fake_get(url, **kw):
        state["hits"] += 1
        inst = [{"config": {"context_length": state["ctx"]}}] if state["ctx"] else []
        return SimpleNamespace(status_code=200, json=lambda: {
            "models": [{"key": "qwen/qwen3.5-9b", "loaded_instances": inst}]})
    monkeypatch.setattr(llm.httpx, "get", fake_get)
    llm._lmstudio_ctx_cache.clear()


def test_ยังไม่โหลด_ไม่จำค่าว่างนาน_โหลดเสร็จแล้วต้องเห็นค่าจริง(monkeypatch):
    """prod 10-04: warmup ถามตอนโมเดลถูกปล่อย → จำ None 5 นาที → แชทหลังเปิดแอป
    ไม่มี context_limit + ตัดประวัติด้วย 8192 แทน 16384 ทั้งที่โหลดเสร็จใน 6.4 วิ"""
    state = {"ctx": None, "hits": 0}
    _ctx_server(monkeypatch, state)
    now = [1000.0]
    monkeypatch.setattr(llm.time, "monotonic", lambda: now[0])
    assert llm._lmstudio_loaded_ctx("qwen/qwen3.5-9b") is None
    state["ctx"] = 16384          # JIT โหลดเสร็จ (warmup ~6 วิ)
    now[0] += 15
    assert llm._lmstudio_loaded_ctx("qwen/qwen3.5-9b") == 16384


def test_ค่าที่โหลดแล้ว_ยัง_cache_5_นาที(monkeypatch):
    state = {"ctx": 16384, "hits": 0}
    _ctx_server(monkeypatch, state)
    now = [1000.0]
    monkeypatch.setattr(llm.time, "monotonic", lambda: now[0])
    assert llm._lmstudio_loaded_ctx("qwen/qwen3.5-9b") == 16384
    now[0] += 240
    assert llm._lmstudio_loaded_ctx("qwen/qwen3.5-9b") == 16384
    assert state["hits"] == 1, "ค่าจริงต้องไม่ถาม LM Studio ซ้ำทุกแชท"


def test_ค่าว่าง_cache_สั้นๆ_ไม่ถามรัวทุกคำขอ(monkeypatch):
    state = {"ctx": None, "hits": 0}
    _ctx_server(monkeypatch, state)
    now = [1000.0]
    monkeypatch.setattr(llm.time, "monotonic", lambda: now[0])
    llm._lmstudio_loaded_ctx("qwen/qwen3.5-9b")
    now[0] += 2
    llm._lmstudio_loaded_ctx("qwen/qwen3.5-9b")
    assert state["hits"] == 1


def test_ลงทะเบียน_env():
    from core.env_registry import REGISTRY
    assert REGISTRY["LMSTUDIO_CONTEXT_LENGTH"].default == 8192
    assert REGISTRY["LMSTUDIO_REPLY_RESERVE"].default == 3072


# ── เส้น agent (ต่อ 75) — prod 10-02 09:31: ปุ่ม agent เปิด → `_run_agent_lmstudio` ส่งประวัติทั้งก้อน
# ~8.5k + system + tools schema (วัดจริง 2,482 token / 24 tools) เข้า context 8,192
# → LM Studio ตัดเองเงียบๆ (prompt_tokens 7,142 → 3,826 เมื่อเพิ่มข้อความเดียว) = qwen ไม่เห็นบางส่วนโดยไม่มีใครรู้

def test_fit_หักงบ_extra_tokens(rec):
    msgs = _convo(3, reply_chars=4000)                 # ~4.1k token: พอดีงบ 5,120 ถ้าไม่หัก extra
    out, dropped = llm._fit_lmstudio_context(msgs, "m")
    assert dropped == 0
    out2, dropped2 = llm._fit_lmstudio_context(msgs, "m", extra_tokens=2000)
    assert dropped2 > dropped
    assert count_tokens_approx(out2) + 2000 <= 8192 - 3072


def test_agent_lmstudio_ตัดประวัติก่อนส่ง_และหักงบ_tools(monkeypatch):
    from agents import orchestrator as orch
    from tests.test_agents import FakeClient, _msg, _resp, _patch_lmstudio
    monkeypatch.setattr(llm, "_LMSTUDIO_CONTEXT_LENGTH", 8192)
    monkeypatch.setattr(llm, "_LMSTUDIO_REPLY_RESERVE", 3072)
    monkeypatch.setattr(llm, "_lmstudio_loaded_ctx", lambda model: None)
    fake = FakeClient([_resp(_msg(content="ตอบ"))])
    _patch_lmstudio(monkeypatch, fake)
    msgs = _convo(4, reply_chars=3000)
    list(orch.run_agent(msgs, provider="lmstudio", model="m"))
    sent = fake.calls[0]["messages"]
    tools_tok = len(__import__("json").dumps(fake.calls[0]["tools"], ensure_ascii=False)) // 3
    assert len(sent) < len(msgs)
    assert sent[0]["role"] == "system" and "[Agent Mode]" in sent[0]["content"]
    assert sent[-1]["content"] == "คำถามล่าสุด"
    assert sent[1]["role"] == "user"
    assert count_tokens_approx(sent) + tools_tok <= 8192 - 3072


def test_agent_lmstudio_ประวัติสั้น_ส่งครบ(monkeypatch):
    from agents import orchestrator as orch
    from tests.test_agents import FakeClient, _msg, _resp, _patch_lmstudio
    monkeypatch.setattr(llm, "_lmstudio_loaded_ctx", lambda model: None)
    fake = FakeClient([_resp(_msg(content="ตอบ"))])
    _patch_lmstudio(monkeypatch, fake)
    msgs = [{"role": "system", "content": "base"}, {"role": "user", "content": "สวัสดี"}]
    list(orch.run_agent(msgs, provider="lmstudio", model="m"))
    assert [m["content"] for m in fake.calls[0]["messages"]][1:] == ["สวัสดี"]
