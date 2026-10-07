"""Test: ผล REM ต้องบอกเหตุผลเสมอ — "ไม่พบความรู้" ต้องไม่หน้าตาเหมือน "พัง"

ที่มา (ปอยเคาะ 10-07 · ทดลอง 300 vs 600 ตัวอักษร 24 รอบ ได้ 0 ธีมทุกรอบ): ความจำ 7 คืนเป็นเกม/นิยาย/
ค้นเว็บ/ขอโค้ดตัวอย่าง/ทักทาย — ถูกตัดตามกติกา 09-30 (ไม่เก็บความรู้ทั่วไปจากเน็ต + เนื้อหาเกม) ทั้งหมด
⇒ 0 ธีม = ผลที่คาดไว้ แต่รายงานเดิมมีแค่ `"themes": []` ดูเหมือนพัง ·
และระหว่างทดลองเจอ Gemini 429 → รายงานออกมาเป็น `themes: []` + `raw` เหมือน "อ่านคำตอบไม่ได้"
⇒ แยก 3 สถานะ: `no_durable_knowledge` (ปกติ) · `parse_failed` · `llm_error` (+ `ok` เมื่อมีธีม)
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils.dream as dream

_MEMS = [{"timestamp": "2026-10-05T04:12:00", "doc": "Q: ขอโค้ด python สั้นๆ A: print('hi')"}]
_EMPTY = '{"themes":[],"insights":[],"connections":[]}'
_ONE = '{"themes":[{"name":"deploy","summary":"git reset แล้ว restart","count":2}],"insights":[],"connections":[]}'


def _run(monkeypatch, caplog, replies):
    """replies: แต่ละรอบเป็น str (ตอบ) หรือ Exception (โยน)"""
    it = iter(replies)

    def fake_stream(messages, **kw):
        r = next(it)
        if isinstance(r, Exception):
            raise r
        yield r

    monkeypatch.setattr(dream, "stream_response", fake_stream)
    with caplog.at_level(logging.INFO, logger="utils.dream"):
        result = dream.rem_sleep(_MEMS, provider="gemini")
    return result, [r.getMessage() for r in caplog.records]


def test_ศูนย์ธีม_สถานะปกติ_พร้อมเหตุผล(monkeypatch, caplog):
    r, logs = _run(monkeypatch, caplog, [_EMPTY])
    assert r["status"] == "no_durable_knowledge"
    assert "ไม่ใช่ error" in r["reason"] and "09-30" in r["reason"], r["reason"]
    assert "raw" not in r, "parse ผ่าน = ไม่ใช่ความล้มเหลว ห้ามมี raw (ตัวบอก parse ล้มของเดิม)"
    # บรรทัดที่อธิบายผล 0 ธีม (มีคำตอบดิบ) ต้องบอกว่าปกติ — "Found 0 themes" เป็นแค่ตัวนับ
    zero = [m for m in logs if "0 themes" in m and "raw=" in m]
    assert zero and all("ไม่ใช่ error" in m for m in zero), f"log 0 ธีมต้องบอกว่าปกติ: {logs}"


def test_มีธีม_สถานะ_ok(monkeypatch, caplog):
    r, _ = _run(monkeypatch, caplog, [_ONE])
    assert r["status"] == "ok" and len(r["themes"]) == 1


def test_LLM_ล้มทั้งสองรอบ_บอกว่าเป็น_error_ไม่ใช่ศูนย์ธีม(monkeypatch, caplog):
    r, logs = _run(monkeypatch, caplog, [RuntimeError("quota exhausted"), TimeoutError("read timeout")])
    assert r["status"] == "llm_error"
    assert "quota exhausted" in r["reason"] and "read timeout" in r["reason"], "ต้องเก็บ error ของทั้งสองรอบ"
    assert "ไม่ใช่ error" not in r["reason"]
    assert r["themes"] == []


def test_ตอบแต่อ่านไม่ได้ทั้งสองรอบ_parse_failed(monkeypatch, caplog):
    r, _ = _run(monkeypatch, caplog, ["ขอโทษค่ะ", "ไม่ใช่ JSON"])
    assert r["status"] == "parse_failed"
    assert "raw" in r and r["reason"]


def test_รอบแรกล้ม_รอบสองได้ศูนย์ธีม_เป็นสถานะปกติ(monkeypatch, caplog):
    r, _ = _run(monkeypatch, caplog, [RuntimeError("timeout"), _EMPTY])
    assert r["status"] == "no_durable_knowledge"


def test_รายงานใน_vault_บอกเหตุผลเมื่อศูนย์ธีม(monkeypatch, tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(dream, "_CFG_OBSIDIAN_VAULT_PATH", str(vault))
    monkeypatch.setattr(dream, "DREAM_REPORTS_DIR", tmp_path)
    reason = "ไม่พบความรู้ถาวร — ปกติ ไม่ใช่ error (ทดสอบ)"
    dream._save_report({"started_at": "x", "duration_sec": 1.0, "provider": "gemini", "hours_window": 24,
                        "phase1_light": {"raw_count": 3},
                        "phase2_rem": {"themes": [], "insights": [], "connections": [],
                                       "status": "no_durable_knowledge", "reason": reason},
                        "phase3_deep": {"count": 0, "promoted": []}})
    md = next(vault.glob("*-dream.md")).read_text(encoding="utf-8")
    assert f"**สถานะ:** {reason}" in md, md


def test_เอกสารบอกว่า_long_term_memory_ไม่โตเป็นผลที่คาดไว้():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for rel in ("docs/reference/architecture.md", "docs/system-map.md"):
        text = open(os.path.join(root, rel), encoding="utf-8").read()
        assert "long_term_memory ไม่โต" in text and "09-30" in text, f"{rel} ยังไม่ได้จด"
