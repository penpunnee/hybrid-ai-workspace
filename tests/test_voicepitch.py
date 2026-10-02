"""ตัววัดความทุ้มของเสียงต่อท่อน (โหมดอ่าน) — จับ "เสียงผู้ชายแทรก" ให้เห็นใน log

ที่มา prod 2026-10-02 01:48:55 UTC: ท่อนแรกหลัง go_away ได้เสียงผู้ชายแทนเสียงขวัญ
(user ยืนยันท่อน) · ไม่มีไฟล์เสียง ⇒ พิสูจน์ไม่ได้ว่าเกิดบ่อยแค่ไหน/ผูกกับ go_away ไหม
⇒ วัดอย่างเดียว ห้ามแตะค่าเสียง (seed/temperature/voice/prompt 🔒)
"""
import ast
import math
from pathlib import Path

import numpy as np
import pytest

import utils.voicepitch as vp

RATE = 24000


def _pcm(f0: float, sec: float = 2.0, harmonics: int = 5, amp: int = 8000) -> bytes:
    """เสียงสังเคราะห์มีฮาร์มอนิก (ใกล้เสียงพูดกว่า sine เดี่ยว — autocorr มีโอกาสหลงครึ่งความถี่)"""
    t = np.arange(int(RATE * sec)) / RATE
    x = sum(np.sin(2 * math.pi * f0 * k * t) / k for k in range(1, harmonics + 1))
    x = x / np.max(np.abs(x)) * amp
    return x.astype("<i2").tobytes()


@pytest.mark.parametrize("f0", [110.0, 130.0, 190.0, 220.0, 260.0])
def test_ประเมินความถี่พื้นฐานใกล้ของจริง(f0):
    r = vp.estimate_f0(_pcm(f0), RATE)
    assert r["median_hz"] == pytest.approx(f0, rel=0.04)
    assert r["voiced"] >= 10


def test_ไม่หลงไปครึ่งความถี่_เสียงหญิงต้องไม่กลายเป็นชาย():
    """ฮาร์มอนิกที่ 2 แรง = autocorr ที่ lag 2 เท่าสูงเกือบเท่า lag จริง → อ่านได้ครึ่งความถี่
    = เสียงหญิง 220 กลายเป็น 110 (ชาย) ปลอม ⇒ ต้องเลือก lag สั้นสุดที่สูงพอ"""
    t = np.arange(RATE * 2) / RATE
    x = 0.6 * np.sin(2 * math.pi * 220 * t) + 1.0 * np.sin(2 * math.pi * 440 * t) \
        + 0.5 * np.sin(2 * math.pi * 660 * t)
    pcm = (x / np.max(np.abs(x)) * 8000).astype("<i2").tobytes()
    assert vp.estimate_f0(pcm, RATE)["median_hz"] == pytest.approx(220, rel=0.05)


def test_เงียบ_ไม่มีค่า():
    r = vp.estimate_f0(b"\x00\x00" * RATE, RATE)
    assert r["median_hz"] is None and r["voiced"] == 0


def test_เสียงหึ่งเบามาก_ไม่นับ():
    """ช่วงเว้นวรรคที่มีเสียงหึ่งเบาๆ แต่มีระดับเสียงชัด — ไม่มีด่านความดัง = ถูกนับเป็นเสียงพูดชาย"""
    t = np.arange(RATE) / RATE
    pcm = (np.sin(2 * math.pi * 120 * t) * 150).astype("<i2").tobytes()
    assert vp.estimate_f0(pcm, RATE)["voiced"] == 0


def test_เสียงรบกวน_ไม่นับเป็นเสียงพูด():
    rng = np.random.default_rng(0)
    pcm = (rng.standard_normal(RATE * 2) * 4000).astype("<i2").tobytes()
    r = vp.estimate_f0(pcm, RATE)
    assert r["voiced"] <= r["frames"] * 0.2


def test_ว่างเปล่า_ไม่พัง():
    assert vp.estimate_f0(b"", RATE)["median_hz"] is None
    assert vp.estimate_f0(b"\x01", RATE)["median_hz"] is None


def test_meter_สะสมทีละ_chunk_ไบต์เศษไม่ทำให้เพี้ยน():
    pcm = _pcm(200.0)
    m = vp.PitchMeter(RATE)
    for i in range(0, len(pcm), 4801):          # ขนาดคี่ = ตัดกลาง sample
        m.add(pcm[i:i + 4801])
    assert m.result()["median_hz"] == pytest.approx(200, rel=0.04)


def test_meter_มีเพดานหน่วยความจำ():
    m = vp.PitchMeter(RATE, max_sec=1.0)
    m.add(_pcm(200.0, sec=3.0))
    assert len(m._buf) <= RATE * 2 * 1.0 + 2


def test_meter_ปิดได้_ไม่เก็บอะไร():
    m = vp.PitchMeter(RATE, enabled=False)
    m.add(_pcm(200.0))
    assert m.result() is None


# ── บรรทัด log ───────────────────────────────────────────────────────────────

def test_log_ปกติ_ไม่มีธง():
    line = vp.pitch_log_line("x.pdf#1", 100, {"median_hz": 210.4, "voiced": 300, "frames": 400},
                             first_on_session=False, low_hz=150.0)
    assert "@100" in line and "210Hz" in line and "⚠️" not in line and "แรกของ session" not in line


def test_log_ทุ้มผิดปกติ_ติดธง_และบอกว่าเป็นท่อนแรกของ_session():
    line = vp.pitch_log_line("x.pdf#1", 100, {"median_hz": 118.0, "voiced": 300, "frames": 400},
                             first_on_session=True, low_hz=150.0)
    assert "⚠️" in line and "118Hz" in line and "ท่อนแรกของ session" in line


def test_log_วัดไม่ได้_ต้องไม่หน้าตาเหมือนปกติ():
    line = vp.pitch_log_line("x.pdf#1", 100, {"median_hz": None, "voiced": 0, "frames": 400},
                             first_on_session=False, low_hz=150.0)
    assert "วัดไม่ได้" in line


def test_env_ลงทะเบียน():
    from core.env_registry import REGISTRY, load_all
    load_all()
    assert REGISTRY["READER_PITCH_LOG"].default is True
    assert REGISTRY["READER_PITCH_LOW_HZ"].default == vp.READER_PITCH_LOW_HZ_DEFAULT


# ── wiring ใน server.py (ฟังก์ชันถูกแต่ไม่มีใครเรียก = ไม่มีผลกับ prod) ───────────

def _reader_feed_loop_src() -> str:
    src = (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "reader_websocket":
            for sub in ast.walk(node):
                if isinstance(sub, ast.AsyncFunctionDef) and sub.name == "feed_loop":
                    return ast.get_source_segment(src, sub)
    pytest.fail("หา reader_websocket.feed_loop ไม่เจอ — โครงเปลี่ยน เทสนี้วัดผิดที่แล้ว")


def test_feed_loop_ป้อนเสียงที่ส่งออกจริงเข้าตัววัด():
    f = _reader_feed_loop_src()
    i_send = f.index('"type": "audio"')
    i_add = f.index("pitch.add(r.data)")
    assert i_add > i_send, "ต้องวัดเสียงที่ส่งออกสายจริง (หลัง send) เหมือน audio_bytes"


def test_feed_loop_log_ความทุ้มหลังท่อนจบ_นอก_event_loop():
    f = _reader_feed_loop_src()
    i_turn = f.index("reader_turn_log_line(")
    tail = f[i_turn:]
    assert "pitch_log_line" in tail, "ต้อง log ความทุ้มตอนท่อนจบจริง"
    assert "asyncio.to_thread(" in tail, "คำนวณ FFT ห้ามรันบน event loop"


def test_feed_loop_รู้ว่าท่อนแรกของ_session():
    """ตัวนับต้องเริ่ม 0 ใน feed_loop (เกิดใหม่ทุก session) และบวกหลังท่อนจบ — ไม่บวก = ทุกท่อนเป็น "ท่อนแรก" """
    f = _reader_feed_loop_src()
    assert f.count("blocks_done_on_session = 0") == 1
    i_turn = f.index("reader_turn_log_line(")
    assert "blocks_done_on_session += 1" in f[i_turn:]
    assert "first_on_session = blocks_done_on_session == 0" in f
