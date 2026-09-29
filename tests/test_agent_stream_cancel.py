"""ก้อน 12 — agent (LM Studio) ต้องหยุดทันทีเมื่อผู้ใช้กด Stop เหมือนแชทปกติ (ก้อน 10)

เดิม `_LMStudioAdapter.step()` เรียก LM Studio แบบ non-stream → ตัดกลางทางไม่ได้ (ยังไม่มี response ให้ตัด socket)
⇒ handler ตัดสายมาช้าเท่าที่ step ใช้ (prod: 7–23 วิ · เพดาน LMSTUDIO_TIMEOUT 180) และ LM Studio คิดต่อทิ้งเปล่า
(วัด 2026-09-29: งานค้างทำให้งานใหม่ช้าลง 42.3 → 36.1 tok/s · ตัดแล้วกลับ 42.2 = LM Studio หยุดจริง)

probe LM Studio จริง (qwen3.5-9b · payload agent จริง 23 tools) ที่ออกแบบเทสนี้:
- stream: header มาใน 0.03–0.40 วิ ⇒ ตัดได้ตั้งแต่ช่วง prefill (ตัดที่ 0.5 วิ หยุดที่ 0.50 วิ · โยน RemoteProtocolError)
- tool call มาเป็นชิ้นตาม `index` · id+name มาชิ้นแรก · arguments แบ่งหลายชิ้น · 2 tools ในรอบเดียวตรงกับ non-stream 3/3
- finish_reason=length → content '' ทั้งสองแบบ ⇒ ต้องได้ "(agent ไม่มีคำตอบ)" เหมือนเดิม
  (⚠️ ห้ามใช้ openai ChatCompletionStreamState — `get_final_completion()` โยน LengthFinishReasonError เสมอ)
- timeout ของ httpx = ต่อการอ่านหนึ่งครั้ง: non-stream timeout=3 → APITimeoutError 3.45 วิ · stream วิ่งถึง 19.3 วิ
  ⇒ step ต้องมีเพดานรวมเองเพื่อรักษาพฤติกรรมเดิม
"""
import asyncio
import json
import os
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import openai
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agents.orchestrator as orch  # noqa: E402
import routers.chat as chatmod  # noqa: E402
from utils.history import load_history  # noqa: E402
from utils.llm import StreamCancel  # noqa: E402


# ── fake stream ในรูปที่ LM Studio ส่งจริง ─────────────────────────────────
def _ch(content=None, tool_calls=None, finish=None, reasoning=None):
    delta = SimpleNamespace(content=content, tool_calls=tool_calls, reasoning_content=reasoning)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason=finish)])


def _tc(index, id=None, name=None, args=None):
    return SimpleNamespace(index=index, id=id, function=SimpleNamespace(name=name, arguments=args))


class _Stream:
    """iterable + close() — `script` เป็น list ของ chunk หรือ callable (เรียกตอนถึงคิว: ตั้งธง/โยน exception)"""

    def __init__(self, script):
        self.script, self.closed = script, False

    def __iter__(self):
        for item in self.script:
            if callable(item):
                item = item()
                if item is None:
                    continue
            yield item

    def close(self):
        self.closed = True


class _Client:
    def __init__(self, *scripts):
        self.scripts, self.calls, self.streams = list(scripts), [], []

    def _create(self, **kw):
        self.calls.append(kw)
        s = self.scripts.pop(0)
        if isinstance(s, Exception):
            raise s
        st = _Stream(s)
        self.streams.append(st)
        return st

    @property
    def chat(self):
        return SimpleNamespace(completions=SimpleNamespace(create=self._create))


@pytest.fixture
def lms(monkeypatch):
    def install(client):
        monkeypatch.setattr(orch, "LMSTUDIO_BASE_URL", "http://fake:1/v1")
        monkeypatch.setattr(openai, "OpenAI", lambda **kw: client)
        return client
    return install


@pytest.fixture
def tools_ran(monkeypatch):
    ran = []
    monkeypatch.setattr(orch, "execute_tool", lambda name, args: ran.append((name, args)) or f"ผล {name}")
    return ran


def _run(cancel=None, max_steps=4):
    return list(orch.run_agent([{"role": "system", "content": "base"}, {"role": "user", "content": "q"}],
                               provider="lmstudio", max_steps=max_steps, cancel=cancel))


def _chunks(out):
    return [p for k, p in out if k == "chunk"]


# ── step เป็น stream และประกอบผลได้เท่าแบบเดิม ─────────────────────────────
def test_step_ขอ_stream_และลงทะเบียนกับ_cancel(lms):
    client = lms(_Client([_ch("คำ"), _ch("ตอบ"), _ch(finish="stop")]))
    tok = StreamCancel()
    out = _run(cancel=tok)
    assert client.calls[0]["stream"] is True, "non-stream ตัดกลางทางไม่ได้"
    assert client.streams[0] in tok._streams, "ต้องลงทะเบียนเพื่อให้ cancel() ตัด socket ได้"
    assert _chunks(out) == ["คำตอบ"]
    assert tok.aborted is False


def test_tool_call_หลายตัว_arguments_แบ่งชิ้น_ประกอบถูก(lms, tools_ran):
    client = lms(_Client(
        [_ch(reasoning="คิด"),
         _ch(tool_calls=[_tc(0, id="c1", name="web_search", args="")]),
         _ch(tool_calls=[_tc(0, args='{"que')]), _ch(tool_calls=[_tc(0, args='ry": "ทอง"}')]),
         _ch(tool_calls=[_tc(1, id="c2", name="calculator", args='{"expression"')]),
         _ch(tool_calls=[_tc(1, args=': "1+1"}')]),
         _ch(finish="tool_calls")],
        [_ch("เสร็จ"), _ch(finish="stop")]))
    out = _run()
    assert tools_ran == [("web_search", {"query": "ทอง"}), ("calculator", {"expression": "1+1"})]
    sent = client.calls[1]["messages"]
    asst = next(m for m in sent if m["role"] == "assistant")
    assert [(t["id"], t["function"]["name"]) for t in asst["tool_calls"]] == [("c1", "web_search"), ("c2", "calculator")]
    assert [m["tool_call_id"] for m in sent if m["role"] == "tool"] == ["c1", "c2"]
    assert _chunks(out) == ["เสร็จ"]


def test_server_ส่ง_id_name_ซ้ำทุกชิ้น_ต้องไม่ต่อกันซ้ำ(lms, tools_ran):
    client = lms(_Client(
        [_ch(tool_calls=[_tc(0, id="c1", name="calculator", args='{"expression": ')]),
         _ch(tool_calls=[_tc(0, id="c1", name="calculator", args='"2+2"}')]),
         _ch(finish="tool_calls")],
        [_ch("4"), _ch(finish="stop")]))
    _run()
    asst = next(m for m in client.calls[1]["messages"] if m["role"] == "assistant")
    assert asst["tool_calls"][0]["id"] == "c1" and asst["tool_calls"][0]["function"]["name"] == "calculator"
    assert tools_ran == [("calculator", {"expression": "2+2"})]


def test_ถูกตัดเพราะยาว_content_ว่าง_ได้ข้อความเดิม(lms):
    lms(_Client([_ch(reasoning="คิดยาว"), _ch(finish="length")]))
    assert _chunks(_run()) == ["(agent ไม่มีคำตอบ)"]


# ── ยกเลิก ─────────────────────────────────────────────────────────────────
def test_ถูกยกเลิกกลาง_step_หยุดเงียบ_ไม่รัน_tool(lms, tools_ran):
    tok = StreamCancel()
    client = lms(_Client([_ch(reasoning="คิด"), tok.cancel,
                          _ch(tool_calls=[_tc(0, id="c1", name="fs_write", args="{}")]), _ch(finish="tool_calls")]))
    out = _run(cancel=tok)
    assert tools_ran == [], "ยกเลิกแล้วห้ามรัน tool"
    assert _chunks(out) == [], f"ห้ามมีข้อความ error/ไม่มีคำตอบ ไปปนในคำตอบที่บันทึก: {out}"
    assert tok.aborted is True
    assert len(client.calls) == 1
    assert client.streams[0].closed, "เห็นธงแล้วต้องปิด stream เอง (เผื่อ cancel() หา socket ไม่เจอ)"


def test_socket_ถูกตัดแล้วโยน_exception_หยุดเงียบ(lms, tools_ran):
    tok = StreamCancel()

    def sever():
        tok.cancel()
        raise httpx.RemoteProtocolError("peer closed connection")   # ที่เห็นจริงบน prod probe
    lms(_Client([_ch(reasoning="คิด"), sever]))
    out = _run(cancel=tok)
    assert _chunks(out) == [] and not any(p.get("type") == "error" for k, p in out if k == "event"), out
    assert tok.aborted is True


def test_กลุ่มควบคุม_error_จริงที่ไม่ได้ยกเลิก_ยังแจ้ง_error(lms):
    tok = StreamCancel()

    def boom():
        raise httpx.RemoteProtocolError("LM Studio ล่ม")
    lms(_Client([_ch(reasoning="คิด"), boom]))
    out = _run(cancel=tok)
    assert _chunks(out)[0].startswith("❌ LM Studio agent error")
    assert tok.aborted is False


def test_ถูกยกเลิกระหว่างสรุปรอบสุดท้าย_หยุดเงียบ(lms, tools_ran):
    tok = StreamCancel()

    def sever():
        tok.cancel()
        raise httpx.RemoteProtocolError("peer closed connection")
    lms(_Client([_ch(tool_calls=[_tc(0, id="c1", name="calculator", args='{"expression": "1+1"}')]),
                 _ch(finish="tool_calls")],
                [_ch("สรุป"), sever]))
    out = _run(cancel=tok, max_steps=1)
    assert _chunks(out) == ["สรุป"], f"ห้ามมี '❌ Final synthesis failed' ต่อท้าย: {out}"
    assert tok.aborted is True


def test_ถูกยกเลิกระหว่างสรุป_เห็นธงในลูป_หยุดเงียบ(lms, tools_ran):
    tok = StreamCancel()
    client = lms(_Client([_ch(tool_calls=[_tc(0, id="c1", name="calculator", args='{"expression": "1+1"}')]),
                          _ch(finish="tool_calls")],
                         [_ch("สรุป"), tok.cancel, _ch("ต่อ"), _ch(finish="stop")]))
    out = _run(cancel=tok, max_steps=1)
    assert _chunks(out) == ["สรุป"] and tok.aborted is True
    assert client.streams[1].closed


def test_ถูกยกเลิกก่อนสรุปมีข้อความ_ห้ามได้_ไม่มีคำตอบ(lms, tools_ran):
    tok = StreamCancel()
    lms(_Client([_ch(tool_calls=[_tc(0, id="c1", name="calculator", args='{"expression": "1+1"}')]),
                 _ch(finish="tool_calls")],
                [_ch(reasoning="คิด"), tok.cancel, _ch("ต่อ"), _ch(finish="stop")]))
    out = _run(cancel=tok, max_steps=1)
    assert _chunks(out) == [], f"ห้ามมี '(ไม่มีคำตอบ)' ปนในคำตอบที่บันทึก: {out}"
    assert tok.aborted is True


def test_synthesize_ลงทะเบียน_stream(lms, tools_ran):
    tok = StreamCancel()
    client = lms(_Client([_ch(tool_calls=[_tc(0, id="c1", name="calculator", args="{}")]), _ch(finish="tool_calls")],
                         [_ch("สรุป"), _ch(finish="stop")]))
    _run(cancel=tok, max_steps=1)
    assert client.streams[1] in tok._streams


# ── เพดานเวลารวมของ step (เดิม non-stream timeout ของ httpx คุมให้) ────────
def test_step_เกินเพดานเวลารวม_หยุดและแจ้ง_error(lms, monkeypatch):
    monkeypatch.setattr(orch, "LMSTUDIO_TIMEOUT", 10)
    clock = iter([0.0, 1.0, 5.0] + [11.0] * 50)
    monkeypatch.setattr(orch, "_monotonic", lambda: next(clock))
    client = lms(_Client([_ch(reasoning="ก"), _ch(reasoning="ข"), _ch(reasoning="ค"), _ch("ไม่ควรถึง"), _ch(finish="stop")]))
    out = _run(cancel=StreamCancel())
    assert _chunks(out)[0].startswith("❌ LM Studio agent error") and "10" in _chunks(out)[0], out
    assert client.streams[0].closed, "เกินเวลาแล้วต้องปิด stream ให้ LM Studio หยุดคิด"


def test_ไม่ส่ง_cancel_ทำงานได้เหมือนเดิม(lms, tools_ran):
    """/api/agent และผู้เรียกเก่าไม่ส่ง cancel"""
    lms(_Client([_ch(tool_calls=[_tc(0, id="c1", name="calculator", args='{"expression": "3"}')]), _ch(finish="tool_calls")],
                [_ch("สาม"), _ch(finish="stop")]))
    out = list(orch.run_agent([{"role": "user", "content": "q"}], provider="lmstudio"))
    assert tools_ran == [("calculator", {"expression": "3"})] and _chunks(out) == ["สาม"]


# ── ระดับ router (/api/chat tool_agent) ด้วย SSE server จริงบน socket (harness ก้อน 10) ──
from tests.test_stream_cooperative_cancel import HOLD, _SSEServer  # noqa: E402
from server import app  # noqa: E402


class _SSEServerSeen(_SSEServer):
    """จด "LM Studio ได้รับ request แล้ว" — ตัดสายตอนนั้น = step กำลังค้างรอในเธรดจริง
    (⚠️ ตัดตอนส่ง event `thinking` ไม่ได้วัดอะไร: การยกเลิกไปตกที่ `await send` ก่อน step เริ่ม — ทดลองแล้ว 09-29)"""

    def __init__(self, mode):
        self.accepted_at = None
        super().__init__(mode)

    def _one(self, c):
        self.accepted_at = time.perf_counter()
        super()._one(c)


async def _post_then_drop_on(body: dict, drop_when=None, hold_after: float = 0.3):
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST", "scheme": "http",
             "path": "/api/chat", "raw_path": b"/api/chat", "query_string": b"", "root_path": "",
             "headers": [(b"host", b"t"), (b"content-type", b"application/json")],
             "client": ("127.0.0.1", 1), "server": ("t", 80)}
    raw = json.dumps(body).encode()
    delivered = False
    meta = {"status": None, "gone_at": None}

    async def receive():
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": raw, "more_body": False}
        if drop_when is None:
            await asyncio.Event().wait()           # ไม่ตัดสาย — starlette ยกเลิกตัวรอนี้เองเมื่อ stream จบ
        while not drop_when():
            await asyncio.sleep(0.01)
        await asyncio.sleep(hold_after)            # ให้ step ค้างรอ LM Studio อยู่ในเธรดจริงก่อนตัด
        meta["gone_at"] = time.perf_counter()
        return {"type": "http.disconnect"}

    async def send(msg):
        if msg["type"] == "http.response.start":
            meta["status"] = msg["status"]

    await asyncio.wait_for(app(scope, receive, send), timeout=HOLD + 10)
    meta["returned_after_gone_s"] = (time.perf_counter() - meta["gone_at"]) if meta["gone_at"] else None
    await asyncio.sleep(0.3)
    return meta


AGENT = {"assistant": "kwan", "prompt": "ค้นราคาทอง", "provider": "lmstudio", "tool_agent": True,
         "active_learning": False, "response_cache": False}


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["reasoning", "silent"])
async def test_router_agent_ตัดสายระหว่างโมเดลคิด_หยุดทันที_บันทึกคู่(monkeypatch, mode):
    srv = _SSEServerSeen(mode)
    monkeypatch.setattr(orch, "LMSTUDIO_BASE_URL", f"http://127.0.0.1:{srv.port}/v1")
    # ถ้าการยกเลิกพัง เธรดจะค้างรอ LM Studio ปลอมจนหมดเวลานี้ — สั้นไว้ให้แดงเร็ว (180 ของจริง = CI แขวน 3 นาที)
    monkeypatch.setattr(orch, "LMSTUDIO_TIMEOUT", 5)
    sid = f"s_agent_cancel_{mode}"
    with patch.object(chatmod, "remember") as rem, patch.object(chatmod, "teach", return_value=False), \
         patch.object(chatmod, "persist_agent_turn") as persist:
        meta = await _post_then_drop_on({**AGENT, "session_id": sid}, drop_when=lambda: srv.accepted_at is not None)
    assert meta["status"] == 200
    assert meta["returned_after_gone_s"] < 2.0, f"รอ agent คิดต่อ {meta['returned_after_gone_s']:.1f}s (server ถือ {HOLD}s)"
    assert srv.closed_at is not None, "connection ไป LM Studio ต้องถูกตัด"
    persist.assert_not_called()
    rem.assert_not_called()
    hist = load_history("kwan", sid)
    assert [m["role"] for m in hist] == ["user", "assistant"], hist
    a = hist[1]["content"]
    assert "หยุดกลางคัน" in a and "❌" not in a and "ไม่มีคำตอบ" not in a, a


@pytest.mark.asyncio
async def test_router_agent_กลุ่มควบคุม_จบปกติ_บันทึกคำตอบเต็ม(monkeypatch):
    srv = _SSEServer("finish")
    monkeypatch.setattr(orch, "LMSTUDIO_BASE_URL", f"http://127.0.0.1:{srv.port}/v1")
    sid = "s_agent_cancel_ctrl"
    with patch.object(chatmod, "remember"), patch.object(chatmod, "teach", return_value=False):
        await _post_then_drop_on({**AGENT, "session_id": sid})
    hist = load_history("kwan", sid)
    assert [m["role"] for m in hist] == ["user", "assistant"], hist
    assert "ท่อน3" in hist[1]["content"] and "หยุดกลางคัน" not in hist[1]["content"], hist[1]["content"]


def test_router_agent_ตอบครบแล้วธงมาทีหลัง_บันทึกคำตอบเต็ม(monkeypatch):
    """บทเรียน CI 09-28: ตัดสินด้วย `aborted` ไม่ใช่ `is_set()`"""
    from fastapi.testclient import TestClient

    def fake_run_agent(messages, cancel=None, **kw):
        yield ("event", {"type": "answering"})
        yield ("chunk", "คำตอบเต็ม")
        if cancel is not None:
            cancel.cancel()
    monkeypatch.setattr(orch, "run_agent", fake_run_agent)
    sid = "s_agent_cancel_late"
    with patch.object(chatmod, "remember"), patch.object(chatmod, "teach", return_value=False):
        r = TestClient(app).post("/api/chat", json={**AGENT, "session_id": sid})
    assert r.status_code == 200
    hist = load_history("kwan", sid)
    assert [m["role"] for m in hist] == ["user", "assistant"], hist
    assert hist[1]["content"] == "คำตอบเต็ม", hist[1]["content"]


def test_router_ส่ง_cancel_ของ_request_ให้_run_agent(monkeypatch):
    from fastapi.testclient import TestClient
    got = {}

    def fake_run_agent(messages, cancel=None, **kw):
        got["cancel"] = cancel
        yield ("chunk", "ok")
    monkeypatch.setattr(orch, "run_agent", fake_run_agent)
    with patch.object(chatmod, "remember"), patch.object(chatmod, "teach", return_value=False):
        TestClient(app).post("/api/chat", json={**AGENT, "session_id": "s_agent_cancel_pass"})
    assert isinstance(got.get("cancel"), StreamCancel)


def test_router_agent_โยน_exception_หลังถูกยกเลิก_ไม่ส่ง_error_ไม่บันทึกเป็นคำตอบเต็ม(monkeypatch):
    from fastapi.testclient import TestClient

    def fake_run_agent(messages, cancel=None, **kw):
        yield ("chunk", "ครึ่ง")
        cancel.cancel()
        cancel.aborted = True
        raise RuntimeError("socket ถูกตัด")
    monkeypatch.setattr(orch, "run_agent", fake_run_agent)
    sid = "s_agent_cancel_raise"
    with patch.object(chatmod, "remember") as rem, patch.object(chatmod, "teach", return_value=False):
        r = TestClient(app).post("/api/chat", json={**AGENT, "session_id": sid})
    assert '"error"' not in r.text, r.text
    rem.assert_not_called()
    hist = load_history("kwan", sid)
    assert [m["role"] for m in hist] == ["user", "assistant"], hist
    assert hist[1]["content"].startswith("ครึ่ง") and "หยุดกลางคัน" in hist[1]["content"], hist[1]["content"]


# ── หลังผล tool: content ว่าง (คำตอบไปอยู่ใน reasoning_content) → สรุปใหม่ (09-29) ──────────
# probe LM Studio จริง (qwen3.5-9b · payload agent จริง): หลังผล tool ได้ content ว่าง **11/12** (ข่าวทอง 5/6 ·
# เช็คเครือข่าย 6/6) เพราะ template เปิด `<think>` ให้แล้วโมเดลตอบโดยไม่ปิด → LM Studio นับเป็น reasoning ทั้งก้อน
# (LM Studio #1602: ปิด think ไม่ทันก่อน EOT) · `enable_thinking=False` ใช้ไม่ได้กับรุ่นนี้ (#1990 · วัด 3/6) ·
# reasoning_content ไม่ใช่คำตอบสะอาด ("โอเค พี่ปอย … ผมได้ผลจาก tool") ห้ามโชว์แทน ·
# เส้น synthesize() เดิม (ต่อ user=_FORCE_SYNTH_PROMPT · ไม่ส่ง tools) ได้คำตอบ **15/15**
def test_หลังผล_tool_content_ว่าง_สรุปใหม่แทนไม่มีคำตอบ(lms, tools_ran):
    client = lms(_Client([_ch(tool_calls=[_tc(0, id="c1", name="ping_network", args="{}")]), _ch(finish="tool_calls")],
                         [_ch(reasoning="โอเค พี่ปอย เครือข่ายดี"), _ch(finish="stop")],
                         [_ch("🟢 ออนไลน์"), _ch("ครบ"), _ch(finish="stop")]))
    out = _run()
    assert _chunks(out) == ["🟢 ออนไลน์", "ครบ"], out
    assert len(client.calls) == 3
    synth = client.calls[2]
    assert synth["messages"][-1] == {"role": "user", "content": orch._FORCE_SYNTH_PROMPT}
    assert "tools" not in synth, "รอบสรุปห้ามเปิด tool (probe 15/15 ทำแบบนี้)"


def test_รอบแรก_content_ว่าง_ยังไม่มีผล_tool_ไม่สรุปใหม่(lms):
    client = lms(_Client([_ch(reasoning="คิด"), _ch(finish="stop")]))
    assert _chunks(_run()) == ["(agent ไม่มีคำตอบ)"]
    assert len(client.calls) == 1, "ยังไม่มีข้อมูลจาก tool ให้สรุป — สรุปใหม่ = ชวนแต่งเอง"


def test_หลังผล_tool_มีคำตอบอยู่แล้ว_ไม่เรียกซ้ำ(lms, tools_ran):
    client = lms(_Client([_ch(tool_calls=[_tc(0, id="c1", name="calculator", args='{"expression": "2"}')]), _ch(finish="tool_calls")],
                         [_ch("สอง"), _ch(finish="stop")]))
    assert _chunks(_run()) == ["สอง"]
    assert len(client.calls) == 2


def test_สรุปใหม่แล้วยังว่าง_ได้ไม่มีคำตอบ(lms, tools_ran):
    lms(_Client([_ch(tool_calls=[_tc(0, id="c1", name="calculator", args="{}")]), _ch(finish="tool_calls")],
                [_ch(reasoning="ก"), _ch(finish="stop")],
                [_ch(reasoning="ข"), _ch(finish="stop")]))
    assert _chunks(_run()) == ["(agent ไม่มีคำตอบ)"]


def test_ถูกยกเลิกระหว่างสรุปใหม่_หยุดเงียบ(lms, tools_ran):
    tok = StreamCancel()
    lms(_Client([_ch(tool_calls=[_tc(0, id="c1", name="calculator", args="{}")]), _ch(finish="tool_calls")],
                [_ch(reasoning="ก"), _ch(finish="stop")],
                [_ch("ครึ่ง"), tok.cancel, _ch("ต่อ"), _ch(finish="stop")]))
    out = _run(cancel=tok)
    assert _chunks(out) == ["ครึ่ง"] and tok.aborted is True, out
