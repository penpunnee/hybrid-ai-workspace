"""โหมดเสียงนึกความจำได้ (ทางเลือก 1 · user เคาะ 2026-10-02)

เดิมโหมดเสียง "จด" ความจำ (remember_voice_turn · 51 turn ตั้งแต่ 09-29) แต่ "นึก" ไม่ได้เลย:
system prompt คงที่ · เครื่องมือมีแค่ค้นเว็บ ⇒ ข้ามสายแล้วลืมทุกอย่าง (ต้องไปถามในแชทพิมพ์)
ข้อควรระวังที่พบ: ความจำมีคำตอบที่ขวัญเคยเดา ("กดสามเหลี่ยมบน PS5" · ต่อ 60) ⇒ ผลนึกต้องแนบคำเตือน
และ turn ที่ใช้ความจำต้องไม่ถูกจดกลับ (ความจำวนซ้ำทับถม)
"""
import asyncio
import os
import time
from pathlib import Path

os.environ.setdefault("UI_PASSWORD", "")


import memory.voice_memory as vm
from utils.voice import (
    MEMORY_TOOL_NAME, WEB_SEARCH_TOOL_NAME, build_live_config, build_reader_config,
    live_tool_call_queries,
)


def _names(cfg):
    return [fd.name for t in (cfg.tools or []) for fd in (getattr(t, "function_declarations", None) or [])]


def test_โหมดคุยประกาศทั้งค้นเว็บและนึกความจำ_อย่างละหนึ่ง():
    names = _names(build_live_config("kwan", "SYS", None))
    assert names.count(WEB_SEARCH_TOOL_NAME) == 1 and names.count(MEMORY_TOOL_NAME) == 1


def test_โหมดอ่านยังไม่มีเครื่องมือ():
    assert build_reader_config(None).tools is None


def test_คำอธิบายเครื่องมือบอกว่าเมื่อไหร่ใช้_และเตือนว่าความจำอาจผิด():
    cfg = build_live_config("kwan", "SYS", None)
    fd = next(fd for t in cfg.tools for fd in (t.function_declarations or []) if fd.name == MEMORY_TOOL_NAME)
    assert "เคยคุย" in fd.description and "อาจผิด" in fd.description


def test_ดึง_call_นึกความจำออกมาพร้อมชื่อ():
    class FC:
        id, name, args = "m-1", MEMORY_TOOL_NAME, {"query": "เกม Onimusha"}

    class R:
        tool_call = type("T", (), {"function_calls": [FC()]})()

    assert live_tool_call_queries(R()) == [("m-1", MEMORY_TOOL_NAME, "เกม Onimusha")]


# ── payload ที่ส่งกลับให้โมเดล ─────────────────────────────────────────────────

def _run(coro):
    return asyncio.run(coro)


def test_นึกได้_แนบคำเตือนก่อนความจำ(monkeypatch):
    monkeypatch.setattr(vm, "_recall", lambda a, q, s: "Q: เล่นเกมอะไร A: Onimusha")
    r = _run(vm.voice_recall_payload("ขวัญ", "เกม", "s1"))["result"]
    assert r.startswith(vm.VOICE_MEMORY_GUIDE) and r.endswith("Onimusha")


def test_คำเตือนห้ามยืนยันข้อเท็จจริงจากความจำ():
    g = vm.VOICE_MEMORY_GUIDE
    assert "อาจผิด" in g and "ห้าม" in g and "ยืนยัน" in g


def test_ไม่เจอความจำ_บอกตรงๆ(monkeypatch):
    monkeypatch.setattr(vm, "_recall", lambda a, q, s: "")
    p = _run(vm.voice_recall_payload("ขวัญ", "เกม", "s1"))
    assert "ไม่พบ" in p["error"]


def test_นึกล้ม_ไม่หน้าตาเหมือนไม่เจอ(monkeypatch):
    def boom(a, q, s):
        raise RuntimeError("chroma down")
    monkeypatch.setattr(vm, "_recall", boom)
    p = _run(vm.voice_recall_payload("ขวัญ", "เกม", "s1"))
    assert "ขัดข้อง" in p["error"] and "ไม่พบ" not in p["error"]


def test_นึกช้าเกินเพดาน_ตอบทันที(monkeypatch):
    def slow(a, q, s):
        time.sleep(2)
        return "ช้า"
    monkeypatch.setattr(vm, "_recall", slow)
    monkeypatch.setattr(vm, "VOICE_MEMORY_TIMEOUT", 0.2)

    async def timed():
        t = time.monotonic()
        p = await vm.voice_recall_payload("ขวัญ", "เกม", "s1")
        return p, time.monotonic() - t
    p, took = _run(timed())
    assert took < 1.0 and "error" in p


def test_เพดานลงทะเบียน_env():
    from core.env_registry import REGISTRY, load_all
    load_all()
    assert REGISTRY["VOICE_MEMORY_TIMEOUT"].default == vm.VOICE_MEMORY_TIMEOUT_DEFAULT


# ── turn ที่ใช้ความจำ ห้ามจดกลับ ────────────────────────────────────────────────

def test_turn_ที่นึกความจำ_ไม่จดกลับ():
    assert vm.voice_memory_decision("จำได้ไหม", "จำได้ค่ะ", recalled=True) == (False, "recalled")


def test_turn_ปกติยังจดตามเดิม(monkeypatch):
    monkeypatch.setattr(vm, "should_remember", lambda u, a: (True, "ok"))
    assert vm.voice_memory_decision("ถาม", "ตอบ") == (True, "ok")


# ── wiring ใน server.py ─────────────────────────────────────────────────────────

def _voice_handler_src() -> str:
    src = (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")
    ws = src[src.index('@app.websocket("/ws/voice/'):]
    return ws[: ws.index("\n@app.")] if "\n@app." in ws else ws


def test_handler_ส่ง_call_นึกความจำไปที่_voice_recall_payload():
    h = _voice_handler_src()
    assert "voice_recall_payload(" in h and "MEMORY_TOOL_NAME" in h


def test_handler_ส่งธง_recalled_ให้ตัวจดความจำ_และรีเซ็ตทุก_turn():
    h = _voice_handler_src()
    i = h.index("remember_voice_turn(")
    assert "recalled=" in h[i:i + 300]
    assert h.count("turn_recalled = False") >= 2, "ต้องประกาศ + รีเซ็ตหลังจด"
    assert "turn_recalled = True" in h
