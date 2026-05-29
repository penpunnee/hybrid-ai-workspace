"""Test สำหรับ scripts/gen_seed_sft.py — seed dataset bootstrap ของ fine-tune ขวัญ

ยืนยันว่า generate ออกมาตรง schema ที่ train_qlora/export ใช้ ({"messages":[sys,user,asst]})
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import gen_seed_sft


def test_seed_has_examples():
    assert len(gen_seed_sft.SEED) >= 20      # bootstrap ต้องมีจำนวนพอควร


def test_generate_valid_jsonl(tmp_path):
    out = tmp_path / "seed.jsonl"
    n = gen_seed_sft.main(str(out))
    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == n == len(gen_seed_sft.SEED)
    for r in rows:
        roles = [m["role"] for m in r["messages"]]
        assert roles == ["system", "user", "assistant"]      # schema ตรงกับ export/train
        assert all(m["content"].strip() for m in r["messages"])


def test_system_prompt_from_config():
    # system ต้องมาจาก ASSISTANTS (single source) — มีคำว่า "ขวัญ"/"พี่ปอย"
    from assistants.config import ASSISTANTS
    sysp = ASSISTANTS["🧡 ขวัญ (Logic)"]["system_prompt"]
    assert "ขวัญ" in sysp and "พี่ปอย" in sysp


def test_answers_in_kwan_voice():
    # คำตอบควรเป็นสไตล์ขวัญ (เรียกพี่ปอย) อย่างน้อยส่วนใหญ่
    hits = sum(1 for _, a in gen_seed_sft.SEED if "พี่ปอย" in a)
    assert hits >= len(gen_seed_sft.SEED) * 0.6
