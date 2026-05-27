#!/usr/bin/env python3
"""Stage 1 — export 👍 conversations → JSONL พร้อมเทรน (SFT)

Usage:
  python scripts/export_finetune.py [out.jsonl] [assistant_name]
  DB_PATH=... python scripts/export_finetune.py data/sft.jsonl ขวัญ
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.finetune_export import export_sft
from assistants.config import ASSISTANTS

DB = os.getenv("DB_PATH", "chat_history.db")
out = sys.argv[1] if len(sys.argv) > 1 else "data/finetune_sft.jsonl"
asst = sys.argv[2] if len(sys.argv) > 2 else None

sysmap = {name: cfg.get("system_prompt", "") for name, cfg in ASSISTANTS.items()}
res = export_sft(DB, out, system_prompts=sysmap, assistant=asst)

print(f"✅ exported {res['count']} examples → {res['path']} (skipped {res['skipped']})")
if res["count"] == 0:
    print("⚠️ 0 ตัวอย่าง — ยังไม่มี 👍 feedback ในระบบ กด 👍 ในแชตให้สะสมก่อนค่อยเทรน")
