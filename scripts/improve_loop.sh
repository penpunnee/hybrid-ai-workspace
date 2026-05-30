#!/usr/bin/env bash
# improve_loop.sh — เฟส 4: วงจร self-improvement ครบรอบ (รันบน PC ที่มี GPU + Ollama)
#
#   export 👍 + auto-score → รวม data → train → ollama create → ⚖️ EVAL GATE → deploy เฉพาะถ้าผ่าน
#
# 🔒 ปลอดภัยโดยดีไซน์: deploy ต่อเมื่อ eval gate บอก PASS เท่านั้น (กัน model collapse)
#   ถ้า FAIL → เก็บรุ่นเดิม ไม่สลับ (kwan-ft ที่สร้างยังอยู่ ลองปรับ data/config แล้วรันใหม่)
#
# Prereq (บน PC, WSL/Linux + CUDA): pip install -r requirements-train.txt ; ollama ; sqlite3
#   ANTHROPIC_API_KEY (กรรมการ eval + auto-score) ; เข้าถึง chat_history.db (DB_PATH)
#
# ปรับผ่าน env: DB_PATH BASELINE CANDIDATE THRESHOLD MIN_EXAMPLES SKIP_AUTOSCORE
#
# Usage:
#   ANTHROPIC_API_KEY=sk-ant-... DB_PATH=/path/chat_history.db bash scripts/improve_loop.sh
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

BASELINE="${BASELINE:-llama3}"          # รุ่นที่ใช้อยู่ตอนนี้ (เทียบกับของใหม่)
CANDIDATE="${CANDIDATE:-kwan-ft}"
THRESHOLD="${THRESHOLD:-0.55}"          # win rate ขั้นต่ำที่ eval gate ถือว่าผ่าน
MIN_EXAMPLES="${MIN_EXAMPLES:-50}"      # data ขั้นต่ำก่อนเทรน (น้อยกว่านี้ = overfit/ไม่คุ้ม)
SEED="data/finetune_seed.jsonl"
SFT="data/finetune_sft.jsonl"
AUTO="data/finetune_auto.jsonl"
ALL="data/finetune_all.jsonl"

echo "═══ เฟส 4: self-improvement loop ═══"
echo "baseline=$BASELINE  candidate=$CANDIDATE  threshold=$THRESHOLD"

# 1) seed (ตัวอย่างมาตรฐาน) + export 👍 ของจริง + auto-score (RLAIF)
echo "── 1) เตรียม data ──"
python3 scripts/gen_seed_sft.py "$SEED" || true
python3 scripts/export_finetune.py "$SFT" ขวัญ || echo "  (ยังไม่มี 👍 — ข้าม sft)"
if [ -z "${SKIP_AUTOSCORE:-}" ] && [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  python3 scripts/auto_score.py --threshold 7.5 || echo "  (auto-score ข้าม)"
fi

# 2) รวมทุกแหล่ง → all.jsonl (seed + 👍 + auto)
echo "── 2) รวม data ──"
: > "$ALL"
for f in "$SEED" "$SFT" "$AUTO"; do [ -f "$f" ] && cat "$f" >> "$ALL"; done
N=$(wc -l < "$ALL" 2>/dev/null || echo 0)
echo "  รวม $N ตัวอย่าง → $ALL"
if [ "$N" -lt "$MIN_EXAMPLES" ]; then
  echo "❌ data น้อยเกิน ($N < $MIN_EXAMPLES) — สะสม 👍 เพิ่ม/ลด MIN_EXAMPLES ก่อน. หยุด"
  exit 1
fi

# 3) train QLoRA → GGUF
echo "── 3) train (QLoRA, ใช้ GPU) ──"
python3 scripts/train_qlora.py "$ALL" || { echo "❌ train ล้ม — ดู error ด้านบน"; exit 1; }

# 4) สร้าง model ใน Ollama
echo "── 4) ollama create $CANDIDATE ──"
if [ ! -f Modelfile.kwan-ft ]; then
  cat > Modelfile.kwan-ft <<EOF
FROM ./kwan-ft/unsloth.Q4_K_M.gguf
PARAMETER temperature 0.7
PARAMETER num_ctx 8192
EOF
  # ใส่ SYSTEM persona จาก Modelfile.kwan ถ้ามี
  [ -f Modelfile.kwan ] && grep -A100 '^SYSTEM' Modelfile.kwan >> Modelfile.kwan-ft || true
fi
ollama create "$CANDIDATE" -f Modelfile.kwan-ft || { echo "❌ ollama create ล้ม"; exit 1; }

# 5) ⚖️ EVAL GATE — เทียบ candidate vs baseline ด้วย Claude
echo "── 5) ⚖️ EVAL GATE ──"
if python3 scripts/eval_kwan.py --candidate "$CANDIDATE" --baseline "$BASELINE" --threshold "$THRESHOLD"; then
  echo ""
  echo "✅ PASS — $CANDIDATE ดีกว่า $BASELINE → พร้อม deploy"
  echo "   ทำต่อ (บน NAS): แก้ .env → OLLAMA_MODEL=$CANDIDATE แล้ว"
  echo "     docker compose up -d hybrid-ai --force-recreate"
  echo "   (เก็บ $BASELINE ไว้ rollback ได้ตลอด)"
else
  echo ""
  echo "❌ FAIL/inconclusive — $CANDIDATE ไม่ดีกว่า $BASELINE → ไม่ deploy (กัน model collapse)"
  echo "   รุ่นเดิม ($BASELINE) ยังใช้อยู่. ลองเพิ่ม/ปรับ data แล้วรัน loop ใหม่"
  exit 1
fi
