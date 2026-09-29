"""Test: REM ได้ 0 ธีม ต้องมีคำตอบดิบใน log + prompt สั่งข้ามเนื้อหาเกม

ที่มา (วัดบน prod 2026-09-30 · devlog [ต่อ 41]): memories 18 รายการชุดเดียว ส่ง Gemini ซ้ำ
ได้ธีม 1/4 รอบ ที่เหลือ `{"themes":[],...}` — แต่ log มีแค่ "Found 0 themes"
เพราะ `_try_parse` ผ่าน → คำตอบดิบถูกทิ้ง ⇒ แยกไม่ออกว่า "AI ตอบว่าง" หรือ "ตอบแปลก"
ต้องยิงซ้ำเองถึงจะรู้ · รอบที่ได้ธีม มี "ทริคเกม Onimusha" ติดมาทุกครั้ง (user: ไม่ต้องจำยาว)
เพิ่มกฎข้ามเกมแล้ววัด 5 รอบ: Onimusha ถูกข้ามทุกรอบ
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils.dream as dream

_MEMS = [{"timestamp": "2026-09-29T15:31:00", "doc": "Q: ต้องเล่นโหมดยากเท่านั้นหรอ A: ใช่ค่ะ"}]
_EMPTY = '{"themes":[],"insights":[],"connections":[]}'
_ONE = '{"themes":[{"name":"deploy","summary":"git reset แล้ว restart","count":2}],"insights":[],"connections":[]}'


def _run(monkeypatch, caplog, reply: str):
    sent = []

    def fake_stream(messages, **kw):
        sent.append(messages)
        yield reply

    monkeypatch.setattr(dream, "stream_response", fake_stream)
    with caplog.at_level(logging.INFO, logger="utils.dream"):
        result = dream.rem_sleep(_MEMS, provider="gemini")
    return result, sent, [r.getMessage() for r in caplog.records]


def test_ศูนย์ธีม_ต้องมีคำตอบดิบใน_log(monkeypatch, caplog):
    result, sent, logs = _run(monkeypatch, caplog, _EMPTY)
    assert result["themes"] == []
    assert len(sent) == 1, "parse ผ่านแล้ว ต้องไม่ยิงรอบ 2"
    assert any(_EMPTY in m for m in logs), f"ไม่เจอคำตอบดิบใน log: {logs}"


def test_รอบสองได้ศูนย์ธีม_ต้อง_log_คำตอบดิบของรอบสอง(monkeypatch, caplog):
    replies = iter(["ขอโทษค่ะ ไม่มีข้อมูล", '{"themes":[],"insights":["x2"],"connections":[]}'])

    def fake_stream(messages, **kw):
        yield next(replies)

    monkeypatch.setattr(dream, "stream_response", fake_stream)
    with caplog.at_level(logging.INFO, logger="utils.dream"):
        result = dream.rem_sleep(_MEMS, provider="gemini")
    logs = [r.getMessage() for r in caplog.records]
    assert result["insights"] == ["x2"], "ต้องได้ผลจากรอบ 2"
    assert any('"insights":["x2"]' in m and "0 themes" in m for m in logs), f"ไม่เจอคำตอบดิบรอบ 2: {logs}"


def test_มีธีม_ไม่ต้อง_log_คำตอบดิบ(monkeypatch, caplog):
    """กลุ่มควบคุม — log คำตอบดิบเฉพาะตอน 0 ธีม ไม่งั้น log บวมทุกคืน"""
    result, _, logs = _run(monkeypatch, caplog, _ONE)
    assert len(result["themes"]) == 1
    assert not any('"summary"' in m for m in logs), f"ไม่ควร log คำตอบดิบเมื่อมีธีม: {logs}"


def test_คำตอบดิบยาว_ต้องถูกตัด(monkeypatch, caplog):
    long_reply = '{"themes":[],"insights":[],"connections":[],"note":"' + "x" * 5000 + '"}'
    result, _, logs = _run(monkeypatch, caplog, long_reply)
    assert result["themes"] == []
    raw_logs = [m for m in logs if '"themes":[]' in m]
    assert raw_logs, f"ไม่เจอคำตอบดิบใน log: {logs}"
    assert all(len(m) < 1000 for m in raw_logs), "คำตอบดิบต้องถูกตัดก่อนลง log"


def test_prompt_ที่ส่งจริง_สั่งข้ามเนื้อหาเกม(monkeypatch, caplog):
    """ตรวจ system message ที่ส่งไปจริง ไม่ใช่ซอร์ส — กฎต้องอยู่ในหมวด SKIP"""
    _, sent, _ = _run(monkeypatch, caplog, _EMPTY)
    system = sent[0][0]["content"]
    skip_block = system[system.index("SKIP a theme entirely"):system.index("Returning an empty")]
    assert "game" in skip_block.lower(), f"หมวด SKIP ไม่มีกฎเรื่องเกม:\n{skip_block}"
