"""TTS (`/api/tts`) ต้องใช้โมเดลที่รองรับ `generateContent` เท่านั้น

ที่มา (audit 2026-08-06 บน prod): ปุ่ม 🔊 ทั้งใน composer และบนข้อความ **ไม่เคยอ่านออกเสียงได้เลย**
`/api/tts` ตอบ HTTP 200 แต่ body เป็น::

    404 NOT_FOUND — models/gemini-2.5-flash-preview-native-audio-dialog is not found
    for API version v1beta, or is not supported for generateContent

ต้นเหตุคือ **สับสายกัน** ระหว่างสอง path ที่ต่างกันคนละ API:

===================  ==========================  =========================
path                 เรียกด้วย                    โมเดลที่ใช้ได้
===================  ==========================  =========================
``utils/tts.py``     ``generate_content()``      สาย ``*-tts``
``utils/voice.py``   Live API (bidi)             สาย ``*-live`` / ``native-audio``
===================  ==========================  =========================

โมเดลสาย ``native-audio`` รองรับ **เฉพาะ** ``bidiGenerateContent`` — ยัดเข้า
``generate_content()`` เมื่อไหร่ก็ 404 เมื่อนั้น (ยืนยันจาก ListModels ด้วย key ของ prod)

วัดจริงในคอนเทนเนอร์ prod 2026-08-06 (นับไบต์ PCM ที่ได้ ไม่ใช่แค่ "ไม่ throw")::

    gemini-2.5-flash-preview-native-audio-dialog  → 404, 404      ← ของเดิม
    gemini-2.5-flash-preview-tts                  → 159886, 150286
    gemini-3.1-flash-tts-preview                  → 180480, 176640
    gemini-2.5-pro-preview-tts                    → 429 (free tier)
"""

import importlib
import os

import pytest


def _tts_module(monkeypatch, env_value=None):
    """โหลด utils.tts ใหม่เพื่ออ่านค่า default ตอน import (module-level constant)"""
    if env_value is None:
        monkeypatch.delenv("GEMINI_TTS_MODEL", raising=False)
    else:
        monkeypatch.setenv("GEMINI_TTS_MODEL", env_value)
    import utils.tts

    return importlib.reload(utils.tts)


def test_default_ไม่ใช่โมเดลสาย_native_audio(monkeypatch):
    """สาย native-audio = bidi-only → ใช้กับ generate_content() ไม่ได้เด็ดขาด"""
    tts = _tts_module(monkeypatch)
    assert "native-audio" not in tts.GEMINI_TTS_MODEL, (
        f"{tts.GEMINI_TTS_MODEL} เป็นโมเดลสาย native-audio ซึ่งรองรับแค่ bidiGenerateContent "
        "— utils/tts.py เรียก generate_content() จะได้ 404 ทุกครั้ง"
    )


def test_default_เป็นโมเดลสาย_tts(monkeypatch):
    """ตรวจเชิงบวกคู่กัน — ไม่ใช่แค่ 'ไม่ใช่ native-audio' แต่ต้องเป็นสาย tts จริง"""
    tts = _tts_module(monkeypatch)
    assert tts.GEMINI_TTS_MODEL.endswith("-tts") or "-tts-" in tts.GEMINI_TTS_MODEL, (
        f"{tts.GEMINI_TTS_MODEL} ไม่ใช่โมเดลสาย *-tts "
        "(ตัวที่วัดแล้วใช้ได้: gemini-2.5-flash-preview-tts, gemini-3.1-flash-tts-preview)"
    )


def test_env_override_ยังใช้ได้(monkeypatch):
    """กลุ่มควบคุม: ถ้า hardcode ไว้ตายตัว เทสสองอันบนก็ผ่านฟรีเหมือนกัน"""
    tts = _tts_module(monkeypatch, "gemini-3.1-flash-tts-preview")
    assert tts.GEMINI_TTS_MODEL == "gemini-3.1-flash-tts-preview"


def test_tts_กับ_live_ต้องไม่ใช้โมเดลตัวเดียวกัน(monkeypatch):
    """สอง path นี้คนละ API — ถ้าวันหนึ่งชี้ไปตัวเดียวกันแปลว่ามีอันหนึ่งพังแน่นอน

    (CLAUDE.md บันทึกไว้ว่า default ของสองไฟล์นี้เคยไม่ตรงกันเงียบๆ มา 6 สัปดาห์)
    """
    tts = _tts_module(monkeypatch)
    from utils.voice import GEMINI_LIVE_MODEL_DEFAULT

    assert tts.GEMINI_TTS_MODEL != GEMINI_LIVE_MODEL_DEFAULT
    # ฝั่ง Live ต้องเป็นสาย bidi (live/native-audio) — ตรงข้ามกับฝั่ง TTS พอดี
    assert (
        "live" in GEMINI_LIVE_MODEL_DEFAULT or "native-audio" in GEMINI_LIVE_MODEL_DEFAULT
    ), f"{GEMINI_LIVE_MODEL_DEFAULT} ไม่ใช่โมเดลสาย Live/bidi"


@pytest.mark.skipif(
    os.getenv("TTS_LIVE_TEST") != "1",
    reason="ยิง Gemini จริง — เปิดด้วย TTS_LIVE_TEST=1 (รันในคอนเทนเนอร์ที่มีคีย์จริง)",
)
def test_ยิงจริงแล้วได้เสียงมาจริง(monkeypatch):
    """ด่านสุดท้าย: นับไบต์เสียง ไม่ใช่แค่ 'ไม่ throw'

    โมเดล 2.5-native-audio เคยคืน 0 ไบต์โดยไม่ error มาแล้ว (บันทึกใน CLAUDE.md)

    ⚠️ ต้อง opt-in ด้วย env แยก **ห้ามใช้แค่ `if GEMINI_API_KEY`** — เทสตัวอื่นในชุดเดียวกัน
    set คีย์ปลอมทิ้งไว้ใน env ทำให้ตัวนี้ "ตื่นขึ้นมายิงจริง" ด้วยคีย์ปลอมแล้วแดงมั่ว
    (เจอจริงตอนรันชุดเต็มครั้งแรก 2026-08-06)
    """
    tts = _tts_module(monkeypatch)
    wav = tts.generate_tts("สวัสดีค่ะ", assistant_slug="kwan")
    assert len(wav) > 10_000, f"ได้ WAV แค่ {len(wav)} ไบต์ — น่าจะเงียบ"
    assert wav[:4] == b"RIFF"
