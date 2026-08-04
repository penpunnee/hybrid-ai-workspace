"""วัดระดับเสียงที่ Gemini ส่งมาจริง — เพื่อตัด "เสียงเบาลง" ออกเป็นสองฝั่งให้ขาด

**ปัญหาที่แก้:** user รายงานว่าคุยด้วยเสียงนานๆ แล้ว "เสียงเบาลง" · วินิจฉัยผิดมาแล้ว
2 รอบเพราะไปแปลง *ความรู้สึก* เป็น *กลไก* ทันที (ดู vault `symptom-vs-interpretation`)
ตัววัดนี้ตอบคำถามเดียวที่ตัดสินได้เด็ดขาด:

  · RMS ที่ log แบนราบ แต่ user ได้ยินว่าเบาลง → ปัญหาอยู่ปลายทาง (OS/AEC/Bluetooth HFP)
  · RMS ที่ log ลดลงตามเวลา          → Gemini ส่งเสียงเบาลงจริง ไม่เกี่ยวกับหูฟังเลย

**วัดที่จุดไหน:** `server.py:send_loop` ตรงที่ได้ `response.data` มา = **ก่อน**ส่งเข้า
เบราว์เซอร์ → ทุกอย่างที่เกิดหลังจากนี้ (worklet, OS mixer, Bluetooth) ไม่มีผลกับตัวเลขนี้
นั่นคือสิ่งที่ทำให้มันแยกสองฝั่งได้

⚠️ **ตัววัดนี้พิสูจน์ได้แค่ว่า "สิ่งที่เราได้รับ" ดังเท่าไหร่** — ไม่ได้พิสูจน์ว่าหูได้ยินอะไร
ถ้าตัวเลขแบนราบ **ห้ามสรุปว่า "ไม่มีปัญหา"** ให้สรุปแค่ว่า "ปัญหาไม่ได้อยู่ก่อนจุดนี้"
"""

import math
import struct

import pytest

from utils.voice import AudioLevelMeter

RATE = 24000


def _pcm(samples):
    return struct.pack(f"<{len(samples)}h", *samples)


def _tone(n, amp):
    """สลับ +amp/-amp = square wave → RMS = amp พอดี (คำนวณคาดหวังได้ตรงๆ)"""
    return _pcm([amp if i % 2 == 0 else -amp for i in range(n)])


class TestWindowing:
    def test_no_report_before_window_is_full(self):
        m = AudioLevelMeter(rate=RATE, window_sec=1.0)
        assert m.add(_tone(RATE // 2, 1000)) is None, "รายงานก่อนครบหน้าต่าง"

    def test_reports_when_window_fills(self):
        m = AudioLevelMeter(rate=RATE, window_sec=1.0)
        m.add(_tone(RATE // 2, 1000))
        out = m.add(_tone(RATE // 2, 1000))
        assert out is not None
        assert out["samples"] == RATE

    def test_leftover_odd_byte_is_carried_not_dropped(self):
        """PCM 16-bit ถูกหั่นกลางตัวอย่างได้ — ห้ามทิ้งไบต์เศษ (จะเลื่อน phase ทั้งสตรีม)"""
        m = AudioLevelMeter(rate=RATE, window_sec=1.0)
        data = _tone(RATE, 1000)
        m.add(data[:1001])          # ตัดกลาง sample
        out = m.add(data[1001:])
        assert out is not None and out["samples"] == RATE, "ไบต์เศษหาย → นับ sample ขาด"


class TestLevels:
    def test_silence_is_reported_as_floor_not_crash(self):
        m = AudioLevelMeter(rate=RATE, window_sec=1.0)
        out = m.add(_pcm([0] * RATE))
        assert out["rms"] == 0
        assert out["dbfs"] <= -99, "เงียบสนิทต้องไม่เป็น -inf/NaN ที่ทำ log พัง"

    def test_full_scale_is_about_zero_dbfs(self):
        m = AudioLevelMeter(rate=RATE, window_sec=1.0)
        out = m.add(_tone(RATE, 32767))
        assert out["dbfs"] == pytest.approx(0.0, abs=0.01)

    def test_half_scale_is_about_minus_six_dbfs(self):
        m = AudioLevelMeter(rate=RATE, window_sec=1.0)
        out = m.add(_tone(RATE, 16384))
        assert out["dbfs"] == pytest.approx(-6.0, abs=0.1)

    def test_peak_is_tracked(self):
        m = AudioLevelMeter(rate=RATE, window_sec=1.0)
        loud = _pcm([30000] + [100] * (RATE - 1))
        assert m.add(loud)["peak"] == 30000


class TestDecayIsVisible:
    """นี่คือสิ่งเดียวที่ตัววัดนี้มีไว้เพื่อจับ — ถ้าจับไม่ได้ก็ไม่ต้องมี"""

    def test_a_decaying_stream_shows_falling_dbfs(self):
        m = AudioLevelMeter(rate=RATE, window_sec=1.0)
        reports = []
        for amp in (20000, 10000, 5000, 2500):
            reports.append(m.add(_tone(RATE, amp)))
        dbfs = [r["dbfs"] for r in reports]
        assert dbfs == sorted(dbfs, reverse=True), f"ไม่เห็นการลดลง: {dbfs}"
        # ครึ่งหนึ่งของ amplitude = -6 dB ต่อขั้น
        for a, b in zip(dbfs, dbfs[1:]):
            assert a - b == pytest.approx(6.0, abs=0.1)

    def test_a_flat_stream_shows_flat_dbfs(self):
        """ตัวควบคุม — ถ้าสตรีมนิ่ง ตัวเลขต้องนิ่ง ไม่งั้นเราจะไล่ผีของตัวเอง"""
        m = AudioLevelMeter(rate=RATE, window_sec=1.0)
        dbfs = [m.add(_tone(RATE, 12000))["dbfs"] for _ in range(4)]
        assert max(dbfs) - min(dbfs) < 0.01, f"สตรีมนิ่งแต่ตัวเลขแกว่ง: {dbfs}"


class TestElapsed:
    def test_audio_seconds_accumulate_across_windows(self):
        m = AudioLevelMeter(rate=RATE, window_sec=1.0)
        outs = [m.add(_tone(RATE, 1000)) for _ in range(3)]
        assert [round(o["audio_sec"]) for o in outs] == [1, 2, 3]

    def test_wall_clock_is_reported_too(self):
        """user เล่าอาการเป็น 'นาทีที่ 5' ตามนาฬิกา ไม่ใช่ตามวินาทีเสียงสะสม
        ช่องว่างระหว่าง turn ทำให้สองอย่างนี้ต่างกันมาก → ต้องมีทั้งคู่ถึงจับคู่กันได้
        """
        m = AudioLevelMeter(rate=RATE, window_sec=1.0)
        out = m.add(_tone(RATE, 1000))
        assert "wall_sec" in out and out["wall_sec"] >= 0


class TestFormatting:
    def test_line_contains_the_numbers_a_human_needs(self):
        m = AudioLevelMeter(rate=RATE, window_sec=1.0)
        line = AudioLevelMeter.format_line(m.add(_tone(RATE, 16384)))
        assert "dBFS" in line
        for token in ("-6.0", "peak", "นาที"):
            assert token in line, f"ขาด {token!r} ใน {line!r}"


class TestServerWiring:
    def test_send_loop_measures_the_bytes_it_forwards(self):
        from pathlib import Path

        src = (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")
        ws = src[src.index('@app.websocket("/ws/voice/'):]
        ws = ws[: ws.index("\n@app.")] if "\n@app." in ws else ws
        assert "AudioLevelMeter" in ws, "ไม่ได้ต่อตัววัดเข้าเส้นเสียงจริง"
        assert ws.index("meter.add(") < ws.index('"type": "audio"'), (
            "ต้องวัด **ก่อน** ส่งเข้าเบราว์เซอร์ ไม่งั้นวัดคนละอย่างกับที่ตั้งใจ"
        )

    def test_meter_survives_session_regeneration(self):
        """สร้างนอกลูป reconnect — ไม่งั้นนาฬิกาจะรีเซ็ตทุกนาทีที่ 10 พอดีกับจุดที่สงสัย"""
        from pathlib import Path

        src = (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")
        ws = src[src.index('@app.websocket("/ws/voice/'):]
        ws = ws[: ws.index("\n@app.")] if "\n@app." in ws else ws
        assert ws.index("AudioLevelMeter(") < ws.index("while not stop.is_set():"), (
            "meter ถูกสร้างในลูป reconnect → เวลาสะสมรีเซ็ตทุกครั้งที่ต่อ session ใหม่"
        )


class TestKillSwitch:
    def test_can_be_turned_off_without_a_deploy(self):
        import utils.voice as v

        assert hasattr(v, "VOICE_LEVEL_LOG"), "ไม่มีสวิตช์ปิด — ของชั่วคราวต้องปิดได้ด้วย env"

    def test_disabled_meter_reports_nothing(self):
        m = AudioLevelMeter(rate=RATE, window_sec=1.0, enabled=False)
        assert m.add(_tone(RATE * 2, 20000)) is None


def test_rms_matches_manual_calculation():
    """กันตัวเราเองคำนวณผิดแล้วเชื่อตัวเลขตัวเอง — เทียบกับสูตรตรงๆ"""
    samples = [100, -200, 300, -400, 500]
    m = AudioLevelMeter(rate=5, window_sec=1.0)
    out = m.add(_pcm(samples))
    expected = math.sqrt(sum(s * s for s in samples) / len(samples))
    assert out["rms"] == pytest.approx(expected, abs=0.01)
