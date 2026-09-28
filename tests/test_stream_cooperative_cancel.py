"""ก้อน 10 — client ตัดสายแล้ว LLM stream ต้องหยุด "ทันที" ไม่ใช่รอโมเดลคิดจบ (ค้างจากก้อน 6)

วัด prod 09-28 (qwen3.5-9b ผ่าน LM Studio): ช่วงคิดส่ง `reasoning_content` มาทุก ~24 ms แต่ `content` = 0 นาน
หลายสิบวินาที → ลูปใน `_stream_lmstudio` ไม่ yield → `next()` ของ worker thread ไม่คืน → anyio (abandon_on_cancel=False)
ส่ง CancelledError ให้ `_guard_disconnect` ไม่ได้จนกว่าจะมี content (log ก้อน 6: 8–110 วิ) · ช่วงก่อน chunk แรกเงียบสนิท 10.7 วิ
ทดลอง (macOS+Linux · openai 2.44 · httpx 0.28.1): `Stream.close()` จาก thread อื่น**ไม่ปลด**ตัวอ่าน · `socket.shutdown` ปลดใน 6–13 ms
แก้: task เฝ้าระดับ response (`_CancellableStreamingResponse`) → `StreamCancel.cancel()` = ตั้งธง + shutdown socket ที่ลงทะเบียน
· ทุก provider เช็คธงทุก raw chunk · ถูกยกเลิกแล้วห้าม cascade ไป Ollama และห้ามบันทึก/remember คำตอบครึ่งๆ
"""
import asyncio
import json
import os
import socket
import sys
import threading
import time
from unittest.mock import patch

import openai
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import app
import routers.chat as chatmod
import utils.llm as llm
from utils.history import load_history, save_message

HOLD = 20.0   # server ถือ connection นานเท่านี้ — ถ้าเทสรอเท่านี้ = ยังไม่ได้แก้


def _chunk(delta: dict) -> bytes:
    body = ("data: " + json.dumps({"id": "1", "object": "chat.completion.chunk", "created": 1, "model": "m",
                                   "choices": [{"index": 0, "delta": delta}]}) + "\n\n").encode()
    return hex(len(body))[2:].encode() + b"\r\n" + body + b"\r\n"


class _SSEServer:
    """SSE server จริงบน socket · mode: reasoning (ส่ง reasoning ทุก 20ms) | silent (เงียบ) | finish (ตอบจบปกติ)"""

    def __init__(self, mode: str):
        self.mode, self.closed_at = mode, None
        self.srv = socket.socket(); self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", 0)); self.srv.listen(4)
        self.port = self.srv.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            threading.Thread(target=self._one, args=(c,), daemon=True).start()

    def _one(self, c):
        try:
            c.recv(65536)
            c.sendall(b"HTTP/1.1 200 OK\r\ncontent-type: text/event-stream\r\ntransfer-encoding: chunked\r\n\r\n")
            c.sendall(_chunk({"content": "ท่อน0 "}))
            t0 = time.time()
            if self.mode == "finish":
                for i in range(1, 4):
                    c.sendall(_chunk({"content": f"ท่อน{i} "})); time.sleep(0.02)
                c.sendall(b"e\r\ndata: [DONE]\n\n\r\n0\r\n\r\n")
                return
            while time.time() - t0 < HOLD:
                if self.mode == "reasoning":
                    c.sendall(_chunk({"reasoning_content": "คิด"}))
                    time.sleep(0.02)
                else:
                    if c.recv(1) == b"":        # เงียบ แต่รู้ตัวเมื่อ client ตัด
                        break
        except OSError:
            pass
        finally:
            self.closed_at = time.time()
            c.close()


@pytest.fixture
def lm(monkeypatch):
    def make(mode):
        s = _SSEServer(mode)
        monkeypatch.setattr(llm, "lmstudio_client", openai.OpenAI(base_url=f"http://127.0.0.1:{s.port}/v1", api_key="x", timeout=60))
        return s
    return make


async def _post_then_drop(path: str, body: dict, drop_after_chunks: int):
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST", "scheme": "http",
             "path": path, "raw_path": path.encode(), "query_string": b"", "root_path": "",
             "headers": [(b"host", b"t"), (b"content-type", b"application/json")],
             "client": ("127.0.0.1", 1), "server": ("t", 80)}
    raw = json.dumps(body).encode()
    delivered, gone = False, asyncio.Event()
    meta = {"status": None, "gone_at": None}

    async def receive():
        nonlocal delivered
        if delivered:
            await gone.wait()
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": raw, "more_body": False}

    chunks = 0

    async def send(msg):
        nonlocal chunks
        if msg["type"] == "http.response.start":
            meta["status"] = msg["status"]
        if msg["type"] == "http.response.body" and b'"chunk"' in (msg.get("body") or b""):
            chunks += 1
            if chunks >= drop_after_chunks and not gone.is_set():
                meta["gone_at"] = time.perf_counter(); gone.set()

    await asyncio.wait_for(app(scope, receive, send), timeout=HOLD + 10)
    meta["returned_after_gone_s"] = (time.perf_counter() - meta["gone_at"]) if meta["gone_at"] else None
    await asyncio.sleep(0.3)
    return meta


CHAT = {"assistant": "kwan", "prompt": "อธิบาย TCP", "provider": "lmstudio", "active_learning": False, "response_cache": False}


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["reasoning", "silent"])
async def test_chat_ตัดสายระหว่างโมเดลคิด_ต้องหยุดทันที(lm, monkeypatch, mode):
    srv = lm(mode)
    cascaded = []
    monkeypatch.setattr(llm, "_stream_ollama", lambda *a, **k: cascaded.append(1) or iter(["จาก Ollama"]))
    sid = f"s_cancel_{mode}"
    with patch.object(chatmod, "remember") as rem, patch.object(chatmod, "teach", return_value=False):
        meta = await _post_then_drop("/api/chat", {**CHAT, "session_id": sid}, drop_after_chunks=1)
    assert meta["status"] == 200
    assert meta["returned_after_gone_s"] < 2.0, f"รอโมเดลคิดต่อ {meta['returned_after_gone_s']:.1f}s (server ถือ {HOLD}s)"
    assert srv.closed_at is not None, "connection ไป LM Studio ต้องถูกตัด (ให้ LM Studio หยุดคิด)"
    assert not cascaded, "ถูกยกเลิกแล้วห้าม cascade ไป Ollama"
    rem.assert_not_called()
    hist = load_history("kwan", sid)
    assert [m["role"] for m in hist] == ["user", "assistant"], hist
    assert "ท่อน0" in hist[1]["content"] and "หยุดกลางคัน" in hist[1]["content"]


@pytest.mark.asyncio
async def test_chat_กลุ่มควบคุม_จบปกติ_ไม่ถูกยกเลิก(lm):
    lm("finish")
    sid = "s_cancel_ctrl"
    with patch.object(chatmod, "remember"), patch.object(chatmod, "teach", return_value=False):
        await _post_then_drop("/api/chat", {**CHAT, "session_id": sid}, drop_after_chunks=10 ** 6)
    hist = load_history("kwan", sid)
    assert [m["role"] for m in hist] == ["user", "assistant"]
    assert "ท่อน3" in hist[1]["content"] and "หยุดกลางคัน" not in hist[1]["content"]


@pytest.mark.asyncio
async def test_regenerate_ตัดสายระหว่างโมเดลคิด_ต้องหยุดทันที(lm, monkeypatch):
    srv = lm("reasoning")
    monkeypatch.setattr(chatmod, "search_memory", lambda *a, **k: "")
    sid = "s_cancel_regen"
    for role, c in [("user", "U1"), ("assistant", "A1 เก่า")]:
        save_message("kwan", role, c, "lmstudio", sid)
    meta = await _post_then_drop("/api/regenerate", {"assistant": "kwan", "session_id": sid, "provider": "lmstudio"},
                                 drop_after_chunks=1)
    assert meta["returned_after_gone_s"] < 2.0, f"{meta['returned_after_gone_s']:.1f}s"
    assert srv.closed_at is not None
    hist = load_history("kwan", sid)
    assert [m["content"][:2] for m in hist][:1] == ["U1"] and "หยุดกลางคัน" in hist[-1]["content"]


# ── หน่วย ──────────────────────────────────────────────────────────────────
def test_StreamCancel_ตัด_socket_ที่ลงทะเบียน_และลงทะเบียนหลังยกเลิกก็ถูกตัดทันที():
    a, b = socket.socketpair()
    class _NS:
        def get_extra_info(self, k): return a if k == "socket" else None
    class _Resp:
        extensions = {"network_stream": _NS()}
    class _Stream:
        response = _Resp()
    tok = llm.StreamCancel()
    tok.register(_Stream())
    assert not tok.is_set()
    tok.cancel(); tok.cancel()                     # idempotent
    assert tok.is_set()
    assert b.recv(1) == b"", "socket ต้องถูก shutdown (ฝั่งตรงข้ามเห็น EOF)"
    c, d = socket.socketpair()
    class _NS2:
        def get_extra_info(self, k): return c
    class _S2:
        response = type("R", (), {"extensions": {"network_stream": _NS2()}})()
    tok.register(_S2())
    assert d.recv(1) == b"", "ลงทะเบียนหลังยกเลิกแล้วต้องถูกตัดทันที (race: create() คืนหลัง cancel)"


def test_gemini_และ_claude_หยุดเมื่อถูกยกเลิก(monkeypatch):
    tok = llm.StreamCancel()
    class _Ch:
        def __init__(self, t): self.text, self.candidates, self.usage_metadata = t, [], None
    def gen():
        yield _Ch("a"); tok.cancel(); yield _Ch("b"); yield _Ch("c")
    class _Models:
        def generate_content_stream(self, **kw): return gen()
    monkeypatch.setattr(llm, "gemini_client", type("C", (), {"models": _Models()})())
    out = list(llm._stream_gemini([{"role": "user", "content": "x"}], cancel=tok))
    assert out == ["a"], out


# ── ชั้นป้องกันซ้อน (mutation L3/L4/L5 รอดจากเทส end-to-end เพราะอีกชั้นรับแทน) ──
@pytest.mark.asyncio
async def test_หา_socket_ไม่เจอ_ธงในลูปต้องหยุดเองได้(lm, monkeypatch):
    """ตัด socket ไม่ได้ (เช่นโครง httpx เปลี่ยน) → ช่วง reasoning ไหลต่อเนื่อง ธงที่เช็คทุก raw chunk ต้องหยุดเอง"""
    lm("reasoning")
    monkeypatch.setattr(llm, "_sever_stream", lambda s: None)
    sid = "s_cancel_nosever"
    with patch.object(chatmod, "remember"), patch.object(chatmod, "teach", return_value=False):
        meta = await _post_then_drop("/api/chat", {**CHAT, "session_id": sid}, drop_after_chunks=1)
    assert meta["returned_after_gone_s"] < 2.0, f"{meta['returned_after_gone_s']:.1f}s"
    assert "หยุดกลางคัน" in load_history("kwan", sid)[-1]["content"]


def test_ReadError_หลังยกเลิก_ห้ามกลายเป็นข้อความ_error(monkeypatch):
    """ReadError ที่ไม่มีข้อความ (Linux) จัดเป็น 'other' → เดิม yield "❌ LM Studio error:" ปนเข้าคำตอบที่บันทึก"""
    import httpx
    tok = llm.StreamCancel()

    class _S:
        response = type("R", (), {"extensions": {}})()
        def __iter__(self):
            tok.cancel()
            raise httpx.ReadError("")

    class _C:
        def create(self, **kw): return _S()
    monkeypatch.setattr(llm, "lmstudio_client", type("L", (), {"chat": type("X", (), {"completions": _C()})()})())
    assert list(llm._stream_lmstudio([{"role": "user", "content": "x"}], model="m", cancel=tok)) == []


def test_LMStudioUnavailable_หลังยกเลิก_ห้าม_cascade(monkeypatch):
    tok = llm.StreamCancel()

    def boom(*a, **k):
        tok.cancel()
        raise llm.LMStudioUnavailable("gone")
        yield  # pragma: no cover
    called = []
    monkeypatch.setattr(llm, "_stream_lmstudio", boom)
    monkeypatch.setattr(llm, "_stream_ollama", lambda *a, **k: called.append(1) or iter(["x"]))
    assert list(llm._stream_lmstudio_or_ollama([{"role": "user", "content": "x"}], cancel=tok)) == []
    assert not called


# ── stream จบเองครบแล้ว แต่ผู้ใช้ตัดสายพอดี (CI Linux จับได้ 09-28: test_ตัดสายหลังคำตอบ_save_แล้ว...) ──
def _complete_then_cancel(messages, cancel=None, **k):
    """ส่งครบทุกท่อน (LLM จบเอง) แล้วธงยกเลิกถูกตั้งหลังท่อนสุดท้าย — จำลองกด Stop ตรงจังหวะนั้นพอดี"""
    for i in range(3):
        yield f"ท่อน{i} "
    if cancel is not None:
        cancel.cancel()


def test_stream_จบครบแล้วถูกยกเลิกทีหลัง_ต้องบันทึกคำตอบเต็ม_ไม่ใช่หยุดกลางคัน(monkeypatch):
    from fastapi.testclient import TestClient
    import server
    monkeypatch.setattr(chatmod, "stream_response", _complete_then_cancel)
    sid = "s_cancel_after_complete"
    with patch.object(chatmod, "remember"), patch.object(chatmod, "teach", return_value=False):
        r = TestClient(server.app).post("/api/chat", json={**CHAT, "session_id": sid, "provider": "ollama"})
    assert r.status_code == 200
    hist = load_history("kwan", sid)
    assert [m["role"] for m in hist] == ["user", "assistant"], hist
    assert "ท่อน2" in hist[1]["content"] and "หยุดกลางคัน" not in hist[1]["content"], hist[1]["content"]


def test_regenerate_stream_จบครบแล้วถูกยกเลิกทีหลัง_ต้องบันทึกคำตอบเต็ม(monkeypatch):
    from fastapi.testclient import TestClient
    import server
    monkeypatch.setattr(chatmod, "stream_response", _complete_then_cancel)
    monkeypatch.setattr(chatmod, "search_memory", lambda *a, **k: "")
    sid = "s_regen_cancel_after_complete"
    save_message("kwan", "user", "U1", "ollama", sid)
    r = TestClient(server.app).post("/api/regenerate", json={"assistant": "kwan", "session_id": sid, "provider": "ollama"})
    assert r.status_code == 200
    hist = load_history("kwan", sid)
    assert "ท่อน2" in hist[-1]["content"] and "หยุดกลางคัน" not in hist[-1]["content"], hist


def test_provider_ที่หยุดเพราะธง_ต้องบอกว่า_aborted():
    tok = llm.StreamCancel()
    assert tok.aborted is False
    tok.cancel()
    assert tok.aborted is False, "ตั้งธงเฉยๆ ≠ stream ถูกตัด — ต้องให้ provider เป็นคนบอก"
    assert llm._stop_if_cancelled(tok) is True and tok.aborted is True
    assert llm._stop_if_cancelled(None) is False
