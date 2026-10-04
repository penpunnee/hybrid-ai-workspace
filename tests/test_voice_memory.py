"""โหมดเสียงบันทึกลง episodic memory — user เคาะ 2026-09-29

สืบแล้ว: 88% ของบทสนทนา (224/254 turn ตั้งแต่ 08-18) มาจาก `/ws/voice` ซึ่งบันทึกแค่ประวัติแชท ไม่เคยเรียก `remember()`
⇒ memory แทบไม่โต (11 รายการใน 6 สัปดาห์) · Dream REM ไม่มีข้อมูล

เงื่อนไขที่ user เคาะ: ผ่าน `should_remember` · ไม่บันทึก turn ที่ถูกพูดแทรก (คำตอบไม่ครบ) · ไม่กรองข้อความสั้น
· ⚠️ เดิมข้าม turn ที่ใช้ web search ด้วย — ถอดแล้ว (user เคาะ 09-29 หลังทดสอบจริง: 4/9 turn ถูกข้ามทั้งที่เป็นคำถามภาษาทั่วไป
ที่โมเดลเลือกค้นเอง) · ข้อมูลสดให้ `should_remember` (`realtime_query` ดูจากคำถาม) กรองแทน · ห้ามบันทึกจากโหมดอ่านนิยาย (`/ws/reader`) · ห้ามแตะค่าเสียง (พิสูจน์ด้วย sha)
`remember()` embed ผ่าน Ollama 0.56–6.73 วิ ⇒ ห้าม await ในลูปเสียง ต้องยิง daemon thread
"""
import ast
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import memory.voice_memory as vm

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── การตัดสินใจ (pure) ────────────────────────────────────────────────────────
@pytest.mark.parametrize("user,ai,kw,expected", [
    ("เล่าเรื่องแมวให้ฟังหน่อย", "กาลครั้งหนึ่งมีแมว…", {}, (True, "ok")),
    ("ต่อ", "แล้วแมวก็เดินไป…", {}, (True, "ok")),                              # ไม่กรองข้อความสั้น (user เคาะ)
    ("   ", "คำตอบ", {}, (False, "no_user_text")),                               # auto-continue: AI พูดเอง
    ("ถาม", "  ", {}, (False, "no_ai_text")),
    ("เล่าเรื่องแมว", "กาลครั้ง…", {"interrupted": True}, (False, "interrupted")),
    ("คำว่า แม้ว่า เป็นภาษาราชการไหม", "เป็นคำเชื่อมที่ใช้ได้ทั้ง…", {}, (True, "ok")),   # เคสจริงที่เคยโดนข้ามเพราะโมเดลค้นเว็บ
    ("ราคาทองวันนี้เท่าไร", "ขายออก 41,000", {}, (False, "realtime_query")),   # ผ่าน should_remember จริง
    # ── ถอดเสียงเป็นภาษาอื่น (prod: 40+ turn ตั้งแต่ 06-18 · 10 รายการหลุดเข้า memory_kwan) ──
    # user พูดไทยเสมอ — ข้อความที่ไม่มีอักษรไทยเลย = ASR ฟังผิด/เสียงทีวี ไม่ใช่สิ่งที่ user พูด
    ("환 아 니 아이러닝 부가한 영화관에서 애니메이션 상영 중인", "ขวัญหาให้แล้ว…", {}, (False, "no_thai_text")),
    ("Quoi ? Bah quoi ? Allez, va chercher les détails", "ขวัญพยายามค้น…", {}, (False, "no_thai_text")),
    ("Juan", "ขวัญอยู่นี่ค่ะ", {}, (False, "no_thai_text")),                   # "ขวัญ" ถูกถอดเป็น Juan
    ("ໃນ ການ ຄວບຄຸມ ອຸປະກອນ", "…", {}, (False, "no_thai_text")),              # ลาว ≠ ช่วงอักษรไทย
    ("さ いしゃい", "…", {}, (False, "no_thai_text")),
    ("เปิด Raspberry Pi 5 ยังไง", "กดปุ่ม…", {}, (True, "ok")),                  # ไทยปนอังกฤษ = พูดจริง
])
def test_decision(user, ai, kw, expected):
    assert vm.voice_memory_decision(user, ai, **kw) == expected


# ── ยิงแบบ fire-and-forget ─────────────────────────────────────────────────────
class _SyncThread:
    """แทน threading.Thread — รัน target ทันทีตอน start() (ให้เทสเห็นผลแบบกำหนดได้)"""
    started = []

    def __init__(self, target, args=(), kwargs=None, daemon=None, name=None):
        self.target, self.args, self.kwargs, self.daemon = target, args, kwargs or {}, daemon
        _SyncThread.started.append(self)

    def start(self):
        self.target(*self.args, **self.kwargs)


@pytest.fixture
def sync_thread(monkeypatch):
    _SyncThread.started = []
    monkeypatch.setattr(vm.threading, "Thread", _SyncThread)
    return _SyncThread


def test_ผ่านแล้วเรียก_remember_ใน_daemon_thread(monkeypatch, sync_thread):
    seen = []
    monkeypatch.setattr(vm, "remember", lambda a, p, r: seen.append((a, p, r)))
    assert vm.remember_voice_turn("🧡 ขวัญ (Logic)", " เล่าเรื่องแมว ", " กาลครั้งหนึ่ง ") is True
    assert seen == [("🧡 ขวัญ (Logic)", "เล่าเรื่องแมว", "กาลครั้งหนึ่ง")]
    assert len(sync_thread.started) == 1 and sync_thread.started[0].daemon is True


def test_ไม่ผ่านแล้วไม่สร้าง_thread_เลย(monkeypatch, sync_thread):
    monkeypatch.setattr(vm, "remember", lambda *a: pytest.fail("ห้ามเรียก remember"))
    assert vm.remember_voice_turn("k", "เล่าเรื่องแมว", "กาลครั้ง", interrupted=True) is False
    assert sync_thread.started == []


def test_remember_ล้ม_ต้องไม่โยนกลับเข้าลูปเสียง(monkeypatch, sync_thread, caplog):
    def boom(*a):
        raise RuntimeError("chroma ล่ม")
    monkeypatch.setattr(vm, "remember", boom)
    vm.remember_voice_turn("k", "เล่าเรื่องแมว", "กาลครั้ง")       # ต้องไม่ raise
    assert any("chroma ล่ม" in r.getMessage() for r in caplog.records)


def test_log_ไม่มีเนื้อหาบทสนทนา(monkeypatch, sync_thread, caplog):
    import logging
    monkeypatch.setattr(vm, "remember", lambda *a: None)
    with caplog.at_level(logging.INFO, logger="memory.voice_memory"):
        vm.remember_voice_turn("k", "ความลับบ้านเลขที่ 99", "คำตอบลับ")
        vm.remember_voice_turn("k", "ความลับบ้านเลขที่ 99", "คำตอบลับ", interrupted=True)
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "[Voice/memory]" in text and "interrupted" in text
    assert "ความลับ" not in text and "คำตอบลับ" not in text


# ── wiring ใน server.py (ast) ────────────────────────────────────────────────
def _func(tree, name):
    return next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == name)


def _calls(node, fname):
    return [n for n in ast.walk(node) if isinstance(n, ast.Call)
            and getattr(n.func, "id", getattr(n.func, "attr", None)) == fname]


@pytest.fixture(scope="module")
def tree():
    with open(os.path.join(ROOT, "server.py"), encoding="utf-8") as f:
        return ast.parse(f.read())


def _turn_complete_block(voice):
    for n in ast.walk(voice):
        if isinstance(n, ast.If) and "turn_complete" in ast.unparse(n.test):
            return n
    raise AssertionError("ไม่เจอบล็อก turn_complete")


def test_ไม่มีเงื่อนไข_searched_แล้ว():
    import inspect
    assert "searched" not in inspect.signature(vm.voice_memory_decision).parameters
    assert "searched" not in inspect.signature(vm.remember_voice_turn).parameters


def test_voice_เรียกในบล็อก_turn_complete_ก่อนล้างบัฟเฟอร์(tree):
    block = _turn_complete_block(_func(tree, "voice_websocket"))
    calls = _calls(block, "remember_voice_turn")
    assert len(calls) == 1, "ต้องเรียกครั้งเดียวต่อ turn"
    call = calls[0]
    assert [ast.unparse(a) for a in call.args[1:]] == ["user_transcript", "ai_transcript"]
    kw = {k.arg: ast.unparse(k.value) for k in call.keywords}
    # ไม่ใช่ค่าคงที่ · ไม่มี searched แล้ว · recalled = turn ที่นึกความจำ ไม่จดกลับ (2026-10-02)
    assert kw == {"interrupted": "turn_interrupted", "recalled": "turn_recalled"}, kw
    clear_user = [i for i, s in enumerate(ast.unparse(block).splitlines()) if "user_transcript = ''" in s]
    assert clear_user, "ต้องยังล้างบัฟเฟอร์เหมือนเดิม"


def test_voice_ติดธง_interrupted_และรีเซ็ตทุก_turn(tree):
    voice = _func(tree, "voice_websocket")
    src = ast.unparse(voice)
    assert "turn_interrupted = True" in src, "ต้องจำว่า turn นี้ถูกพูดแทรก"
    block = _turn_complete_block(voice)
    assert "turn_interrupted = False" in ast.unparse(block), "ต้องรีเซ็ตธงทุกครั้งที่จบ turn"


def test_reader_ไม่บันทึก_memory(tree):
    reader = _func(tree, "reader_websocket")
    assert _calls(reader, "remember_voice_turn") == [] and _calls(reader, "remember") == []
