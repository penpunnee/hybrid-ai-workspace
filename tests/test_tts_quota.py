"""`generate_tts` ต้องไม่เผาโควตา 1 request ต่อ 1 ประโยค

ที่มา (2026-08-06): Gemini free tier ให้ **10 request/วัน/โมเดล** สำหรับสาย ``*-tts``
แต่ ``generate_tts()`` แบ่งข้อความด้วย ``_split_sentences()`` แล้วยิง **1 request ต่อ
1 ประโยค** (parallel 4 workers) เพื่อลด latency ⇒ คำตอบปกติ 5 ประโยค = 5 request
⇒ **ใช้ได้จริงราว 2 คำตอบต่อวัน** แล้วตายทั้งวัน

ตัวเลือกที่ user เคาะ (2026-08-06): **จัดกลุ่มประโยคเป็น chunk** —
รวมประโยคต่อกันจนใกล้เพดาน ``TTS_MAX_CHARS`` แล้วจำกัดจำนวน chunk ที่ ``TTS_MAX_CHUNKS``
⇒ คำตอบสั้น-กลางกิน 1 request (10 คำตอบ/วัน) · คำตอบยาวยังได้ parallel บางส่วน

เรื่องที่ต้องระวังคู่กัน — **เพดาน 2000 ตัวอักษรของ `_generate_one`**::

    contents=f"Say: {text[:2000]}"     ← ตัดทิ้งเงียบๆ ไม่มีคำเตือน

เดิมไม่มีใครเจอเพราะแบ่งเป็นประโยคย่อยหมดแล้ว · พอรวมเป็น chunk ต้องเคารพเพดานนี้เอง
ไม่งั้นแก้เรื่องโควตาแล้วไปสร้างบั๊ก "เสียงขาดหาย" แทน
"""

import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


@pytest.fixture
def tts():
    import utils.tts

    return importlib.reload(utils.tts)


# ---------------------------------------------------------------- การจัดกลุ่ม


def test_ประโยคสั้นหลายประโยครวมเป็น_chunk_เดียว(tts):
    """หัวใจของงานนี้ — 5 ประโยคสั้นต้องกลายเป็น 1 request ไม่ใช่ 5"""
    sentences = [
        "สวัสดีค่ะ.",
        "วันนี้อากาศดี.",
        "มีอะไรให้ช่วยไหม.",
        "ลองดูข้อมูลนี้.",
        "หวังว่าจะเป็นประโยชน์.",
    ]
    chunks = tts._group_sentences(sentences)
    assert len(chunks) == 1, f"ควรรวมเหลือ 1 chunk แต่ได้ {len(chunks)}: {chunks}"


def test_ไม่มีข้อความหายจากการจัดกลุ่ม(tts):
    """จัดกลุ่มแล้วต้องได้ข้อความครบเท่าเดิม — ห้ามหล่นประโยคไหนหาย"""
    sentences = ["ประโยคที่หนึ่ง.", "ประโยคที่สอง.", "ประโยคที่สาม."]
    joined = " ".join(tts._group_sentences(sentences))
    for s in sentences:
        assert s in joined, f"ประโยค {s!r} หายไปหลังจัดกลุ่ม"


def test_แต่ละ_chunk_ไม่เกินเพดานตัวอักษร(tts):
    """เพดานนี้คือขนาดที่ `_generate_one` ส่งได้จริง — เกินแล้วถูกตัดเงียบๆ"""
    sentences = [f"ประโยคทดสอบลำดับที่ {i} ที่มีความยาวพอสมควร." for i in range(200)]
    for chunk in tts._group_sentences(sentences):
        assert len(chunk) <= tts.TTS_MAX_CHARS, (
            f"chunk ยาว {len(chunk)} เกินเพดาน {tts.TTS_MAX_CHARS} "
            "— `_generate_one` จะตัดทิ้งเงียบๆ"
        )


def test_ข้อความยาวยังถูกแบ่งหลาย_chunk(tts):
    """กลุ่มควบคุม — ถ้าจับรวมเป็น chunk เดียวเสมอ เทสข้างบนก็เขียวฟรี"""
    long_text = "ประโยคยาวมากที่ใช้ทดสอบการแบ่ง chunk ให้ครบถ้วน." * 100
    sentences = tts._split_sentences(long_text)
    chunks = tts._group_sentences(sentences)
    assert len(chunks) > 1, "ข้อความยาวเกินเพดานต้องถูกแบ่งมากกว่า 1 chunk"


def test_จำนวน_chunk_ไม่เกินเพดานโควตา(tts):
    """เหตุผลทั้งหมดของงานนี้คือจำกัดจำนวน request ต่อคำตอบ"""
    sentences = [f"ประโยคที่ {i} ยาวพอประมาณสำหรับทดสอบเพดาน chunk." for i in range(500)]
    chunks = tts._group_sentences(sentences)
    assert len(chunks) <= tts.TTS_MAX_CHUNKS, (
        f"ได้ {len(chunks)} chunk เกินเพดาน {tts.TTS_MAX_CHUNKS} "
        "— 1 chunk = 1 request จากโควตา 10/วัน"
    )


def test_ตัดทิ้งแล้วต้องมีร่องรอยใน_log(tts, caplog):
    """นโยบายที่เลือกคือ **ตัดทิ้ง** (2026-08-06) — ตัดได้ แต่ห้ามหายเงียบ

    บั๊ก TTS ที่แพงที่สุดของไฟล์นี้คือบั๊กที่ไม่ส่งเสียงบอก (``text[:2000]``
    ตัดทิ้งอยู่เป็นเดือนโดยไม่มีใครรู้) — เทสนี้กันไม่ให้ประวัติศาสตร์ซ้ำ
    """
    sentences = [f"ประโยคที่ {i} ยาวพอประมาณสำหรับทดสอบเพดาน chunk." for i in range(500)]
    with caplog.at_level("WARNING"):
        tts._group_sentences(sentences)
    assert any("ตัด" in r.getMessage() for r in caplog.records), (
        "ตัดข้อความทิ้งโดยไม่ log warning — ผู้ใช้จะไม่มีทางรู้ว่าเสียงขาด"
    )


def test_ไม่ตัดก็ต้องไม่เตือน(tts, caplog):
    """กลุ่มควบคุม — กัน log ที่ยิง warning ทุกครั้งจนเทสข้างบนเขียวฟรี"""
    with caplog.at_level("WARNING"):
        tts._group_sentences(["สั้นๆ.", "ไม่เกินเพดาน."])
    assert not caplog.records, f"ไม่ได้ตัดอะไรแต่ยัง warning: {caplog.records}"


# ------------------------------------------------- generate_tts ยิงตามจำนวน chunk


def test_generate_tts_ยิงตามจำนวน_chunk_ไม่ใช่จำนวนประโยค(tts, monkeypatch):
    """วัดที่ **จำนวน request จริง** ไม่ใช่แค่ว่า `_group_sentences` คืนอะไร

    เทสนี้คือตัวที่ต้องแดงถ้ามีใครถอดการจัดกลุ่มออกจาก `generate_tts`
    (เช่นเผลอกลับไปวน `sentences` ตรงๆ) — `_group_sentences` เขียวอย่างเดียวไม่พอ
    """
    calls: list[str] = []

    def _fake_generate_one(text: str, voice: str) -> bytes:
        calls.append(text)
        return tts._pcm_to_wav(b"\x00\x00" * 100)

    monkeypatch.setattr(tts, "GEMINI_API_KEY", "fake-key-for-test")
    monkeypatch.setattr(tts, "_generate_one", _fake_generate_one)

    text = "สวัสดีค่ะ. วันนี้อากาศดี. มีอะไรให้ช่วยไหม. ลองดูข้อมูลนี้. หวังว่าจะเป็นประโยชน์."
    tts.generate_tts(text)

    assert len(calls) == 1, f"ควรยิง 1 request แต่ยิง {len(calls)} ครั้ง: {calls}"
    # และต้องเป็นข้อความครบ ไม่ใช่ยิงครั้งเดียวเพราะหล่นประโยคอื่นทิ้ง
    assert "หวังว่าจะเป็นประโยชน์" in calls[0], "ยิงครั้งเดียวแต่ข้อความไม่ครบ"


def test_generate_tts_ข้อความยาวยังยิงมากกว่าหนึ่งครั้ง(tts, monkeypatch):
    """กลุ่มควบคุมของเทสข้างบน — กัน `generate_tts` ที่ยิงครั้งเดียวเสมอแล้วตัดทิ้ง"""
    calls: list[str] = []

    def _fake_generate_one(text: str, voice: str) -> bytes:
        calls.append(text)
        return tts._pcm_to_wav(b"\x00\x00" * 100)

    monkeypatch.setattr(tts, "GEMINI_API_KEY", "fake-key-for-test")
    monkeypatch.setattr(tts, "_generate_one", _fake_generate_one)

    tts.generate_tts("ประโยคยาวมากที่ใช้ทดสอบการแบ่ง chunk ให้ครบถ้วน." * 100)

    assert len(calls) > 1, "ข้อความยาวเกินเพดานต้องยิงมากกว่า 1 request"
    assert all(len(c) <= tts.TTS_MAX_CHARS for c in calls), (
        "มี request ที่ยาวเกินเพดาน — จะถูก `_generate_one` ตัดทิ้งเงียบๆ"
    )


# ------------------------------------------------------------ /api/tts/stream

def test_tts_stream_ก็ต้องจัดกลุ่มเหมือนกัน(monkeypatch):
    """เส้นที่สองที่กินโควตา — ``/api/tts/stream`` แบ่งประโยคเองอีกชั้น

    ตอน audit 2026-08-06 มองข้ามเส้นนี้ไป เพราะ bundle ของ frontend เรียกแค่
    ``/api/tts`` (นับแล้ว: ``api/tts`` 1 ครั้ง · ``api/tts/stream`` 0 ครั้ง)
    แต่ endpoint ยังเปิดอยู่ ⇒ ใครยิงตรงก็เผาโควตา 1 req/ประโยคเหมือนเดิม
    **แก้ที่ `utils/tts.py` อย่างเดียวไม่พอ — ต้องนับให้ครบทุกเส้น**
    """
    from fastapi.testclient import TestClient
    import server
    import routers.system as sysmod

    calls: list[str] = []
    monkeypatch.setattr(sysmod, "generate_tts", lambda t, s="": calls.append(t) or b"RIFF")

    client = TestClient(server.app)
    text = "สวัสดีค่ะ. วันนี้อากาศดี. มีอะไรให้ช่วยไหม. ลองดูข้อมูลนี้. หวังว่าจะเป็นประโยชน์."
    with client.stream("POST", "/api/tts/stream", json={"text": text}) as r:
        assert r.status_code == 200
        for _ in r.iter_lines():
            pass

    assert len(calls) == 1, f"ควรยิง 1 request แต่ยิง {len(calls)} ครั้ง"
    assert "หวังว่าจะเป็นประโยชน์" in calls[0], "ยิงครั้งเดียวแต่ข้อความไม่ครบ"
