"""วัดความทุ้มของเสียง (ความถี่พื้นฐาน F0) ต่อท่อนของโหมดอ่าน — **วัดอย่างเดียว ไม่แตะเสียง**

ที่มา prod 2026-10-02 01:48:55 UTC: ท่อนแรกหลัง go_away ได้เสียงผู้ชายแทนเสียงขวัญ (user ยืนยัน)
· Google ยังไม่มี fix (vault `gemini-live-voice-drift.md`) ⇒ ต้องรู้ก่อนว่าเกิดบ่อยแค่ไหน
และผูกกับ "ท่อนแรกของ session" ไหม ก่อนคิดวิธีแก้ · ⛔ ห้ามแก้ด้วย seed/temperature/voice/prompt (🔒)

วิธี: autocorrelation ต่อเฟรม (FFT) → lag ช่วง 70–400 Hz → เลือก **lag สั้นสุดที่สูงพอ**
(ไม่ใช่สูงสุด) กันอ่านได้ครึ่งความถี่ = เสียงหญิงกลายเป็นชายปลอม · ค่ากลางของเฟรมที่เป็นเสียงพูด
"""

from __future__ import annotations

import numpy as np

from core.env_registry import env_bool, env_float

_G = "Reader (นิยาย)"
READER_PITCH_LOG = env_bool("READER_PITCH_LOG", True, group=_G, doc=(
    "log ความทุ้ม (F0 ค่ากลาง) ต่อท่อนของโหมดอ่าน — จับเสียงผู้ชายแทรก · วัดอย่างเดียว ไม่เปลี่ยนเสียง"))
# วัด prod 2026-10-02 (config โหมดอ่านตัวจริง · ท่อน @98336 · ~18 วิ/รอบ):
# Aoede 179/167 · Kore 187 (หญิง) · Puck 146 · Charon 133 (ชาย) ⇒ กลางช่อง 146–167 ≈ 155
# ⚠️ ชั่วคราว — ตัวอย่าง Aoede แค่ 2 รอบ · ปรับจาก log การฟังจริง (ธงผิด = แค่ log ไม่กระทบเสียง)
READER_PITCH_LOW_HZ_DEFAULT = 155.0
READER_PITCH_LOW_HZ = env_float("READER_PITCH_LOW_HZ", READER_PITCH_LOW_HZ_DEFAULT, group=_G, doc=(
    "F0 ค่ากลางต่ำกว่านี้ = ติดธง ⚠️ ทุ้มผิดปกติ (เสียงผู้ชาย?) · ค่าตั้งจากวัด Aoede เทียบเสียงชายบน prod"))

_F_MIN, _F_MAX = 70.0, 400.0
_FRAME_SEC, _HOP_SEC = 0.04, 0.1
_SILENCE_RMS = 300.0          # int16 · ต่ำกว่านี้ = ช่วงเงียบ ไม่นับ
_VOICED_R = 0.5               # autocorr ปกติ ≥ นี้ = เสียงมีระดับเสียง (ไม่ใช่ลม/เสียงรบกวน)
_NEAR_BEST = 0.9              # lag สั้นสุดที่ได้ ≥ 90% ของยอดสูงสุด = กันหลงครึ่งความถี่


def estimate_f0(pcm: bytes, rate: int = 24000) -> dict:
    """PCM 16-bit LE mono → ``{"median_hz", "voiced", "frames"}`` · วัดไม่ได้ = median_hz None"""
    n = len(pcm) - (len(pcm) % 2)
    x = np.frombuffer(pcm[:n], dtype="<i2").astype(np.float64) if n else np.zeros(0)
    frame, hop = int(rate * _FRAME_SEC), int(rate * _HOP_SEC)
    lo, hi = int(rate / _F_MAX), int(rate / _F_MIN)
    if len(x) < frame or hi >= frame:
        return {"median_hz": None, "voiced": 0, "frames": 0}
    nfft = 1 << (2 * frame - 1).bit_length()
    window = np.hanning(frame)
    f0s, frames = [], 0
    for start in range(0, len(x) - frame + 1, hop):
        frames += 1
        seg = x[start:start + frame]
        if np.sqrt(np.mean(seg * seg)) < _SILENCE_RMS:
            continue
        seg = (seg - seg.mean()) * window
        spec = np.fft.rfft(seg, nfft)
        ac = np.fft.irfft(spec * np.conj(spec), nfft)[:frame]
        if ac[0] <= 0:
            continue
        r = ac / ac[0]
        band = r[lo:hi + 1]
        best = float(band.max())
        if best < _VOICED_R:
            continue
        # lag สั้นสุดที่เป็นยอดเฉพาะที่และสูงใกล้ยอดสูงสุด — ⚠️ mutation 2026-10-02: เทียบ argmax แล้ว
        # ผลเท่ากันทุกสัญญาณสังเคราะห์ (window ทำให้ lag สั้นชนะเอง) = พิสูจน์ผลไม่ได้ · คงไว้เพราะ
        # ค่าเกณฑ์ปรับเทียบจากเสียงจริงด้วยเส้นนี้ · จะถอดต้องวัด Aoede/Charon/Puck ใหม่
        cand = np.nonzero(band >= _NEAR_BEST * best)[0]
        k = int(cand[0])
        while k + 1 < len(band) and band[k + 1] > band[k]:
            k += 1
        lag = lo + k
        # parabolic interpolation ให้ได้ทศนิยม
        if 0 < lag < frame - 1:
            a, b, c = r[lag - 1], r[lag], r[lag + 1]
            den = a - 2 * b + c
            lag = lag + (0.5 * (a - c) / den if den else 0.0)
        f0s.append(rate / lag)
    med = float(np.median(f0s)) if len(f0s) >= 3 else None
    return {"median_hz": med, "voiced": len(f0s), "frames": frames}


class PitchMeter:
    """สะสม PCM ของหนึ่งท่อน (มีเพดาน) แล้วประเมินตอนจบท่อน — `result()` ใช้ CPU ⇒ เรียกนอก event loop"""

    def __init__(self, rate: int = 24000, max_sec: float = 120.0, enabled: bool | None = None):
        self.rate = rate
        self.enabled = READER_PITCH_LOG if enabled is None else enabled
        self._cap = int(rate * 2 * max_sec)
        self._buf = bytearray()

    def add(self, pcm: bytes) -> None:
        if not self.enabled or not pcm:
            return
        room = self._cap - len(self._buf)
        if room > 0:
            self._buf += pcm[:room]

    def result(self) -> dict | None:
        if not self.enabled:
            return None
        return estimate_f0(bytes(self._buf), self.rate)


def pitch_log_line(tag: str, pos: int, res: dict | None, *, first_on_session: bool,
                   low_hz: float | None = None) -> str:
    """บรรทัดคู่กับ "ท่อนจบ" · ⚠️ เมื่อทุ้มผิดปกติ · "วัดไม่ได้" ต้องไม่หน้าตาเหมือนปกติ"""
    low = READER_PITCH_LOW_HZ if low_hz is None else low_hz
    first = " · ท่อนแรกของ session" if first_on_session else ""
    if not res or res.get("median_hz") is None:
        v, f = (res or {}).get("voiced", 0), (res or {}).get("frames", 0)
        return f"[Reader WS] ความทุ้ม {tag} @{pos} · วัดไม่ได้ (เสียงพูด {v}/{f} เฟรม){first}"
    hz = res["median_hz"]
    flag = f" ⚠️ ทุ้มผิดปกติ < {low:.0f}Hz (เสียงผู้ชาย?)" if hz < low else ""
    return (f"[Reader WS] ความทุ้ม {tag} @{pos} · F0 กลาง {hz:.0f}Hz "
            f"(เสียงพูด {res['voiced']}/{res['frames']} เฟรม){first}{flag}")
