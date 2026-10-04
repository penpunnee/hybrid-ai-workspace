"""งานเบื้องหลังต้องพก request id + token จริงลง log (งานเปิด ▶️ ข้อ 2 · 10-04)

prod 10-04: `[rid=-] LM Studio stream OK (… in=?, out=?)` โผล่ 25–150 วิหลังแชท — ไล่ log
แล้วคือเธรด `_learn` (สรุปบทเรียน) ของ routers/chat.py · ระบุที่มาไม่ได้เพราะ
1) `threading.Thread` ไม่สืบ contextvars ⇒ rid หาย  2) ไม่ส่ง usage_sink ⇒ ไม่ขอ usage จาก LM Studio
"""
import ast
import logging
import os
import sys
import threading
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils.llm as llm
from core import observability as obs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_spawn_bg_carries_request_id():
    seen = {}
    done = threading.Event()

    def _work():
        seen["rid"] = obs.current_request_id()
        done.set()

    rid = obs.start_request("req")
    assert rid
    obs.spawn_bg(_work)
    assert done.wait(5)
    assert seen["rid"] == rid, "เธรดเบื้องหลังต้องเห็น request id เดียวกับ request ที่สปอนมัน"


def test_chat_router_has_no_bare_threads():
    """ทุกเธรดใน routers/chat.py ต้องผ่าน spawn_bg (ไม่งั้น log ขึ้น rid=- อีก)"""
    src = open(os.path.join(ROOT, "routers", "chat.py"), encoding="utf-8").read()
    bare = [n.lineno for n in ast.walk(ast.parse(src))
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "Thread"]
    assert bare == [], f"threading.Thread ดิบที่บรรทัด {bare} — ใช้ core.observability.spawn_bg"


def _oai_chunk(text):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text),
                                                    finish_reason=None)], usage=None)


def test_lmstudio_logs_real_usage_without_sink(monkeypatch, caplog):
    """คนเรียกที่ไม่ต้องการ usage (auto-learn) — log ยังต้องได้ตัวเลขจริง ไม่ใช่ `in=?`"""
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            tail = SimpleNamespace(choices=[], usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5))
            return iter([_oai_chunk("SKIP"), tail])

    monkeypatch.setattr(llm, "lmstudio_client",
                        SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions())))
    monkeypatch.setattr(llm, "_lmstudio_loaded_ctx", lambda m: None)
    with caplog.at_level(logging.INFO, logger="utils.llm"):
        got = "".join(llm._stream_lmstudio([{"role": "user", "content": "hi"}], model="m"))
    assert got == "SKIP"
    assert captured.get("stream_options") == {"include_usage": True}
    line = next(r.getMessage() for r in caplog.records if "LM Studio stream OK" in r.getMessage())
    assert "in=10" in line and "out=5" in line, line
