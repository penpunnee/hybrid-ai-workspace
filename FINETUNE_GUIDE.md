# Fine-tune Pipeline — Hybrid AI Workspace

ปรับพฤติกรรม AI โดยเทรน Llama-3.1-8B ซ้ำจาก log ที่คัดสรร (👍) — รันออฟไลน์นอกเวลาใช้งาน

## หลักการ: Curate → Train → Serve (คนละ host)
| Stage | งาน | host | สถานะ |
|---|---|---|---|
| 1. Export | คัด 👍 → JSONL | NAS/Mac (ไม่ต้อง GPU) | ✅ `scripts/export_finetune.py` |
| 2. Train | QLoRA Llama-3.1-8B | **PC RTX 3060 12GB** | ⚠️ `scripts/train_qlora.py` (template) |
| 3. Deploy | GGUF → Ollama | PC .235 | ⚠️ ดูล่าง |

## ⚠️ Prerequisite: DATA
ต้องมี **👍 feedback สะสมพอ** ก่อน (ตั้งเป้า ~200-500 ตัวอย่างคุณภาพ).
เช็กจำนวน: `GET /api/feedback/stats` → ดู `ups`. **ปัจจุบัน = 0** → ต้องกด 👍 ในแชตให้สะสมก่อน

---

## Stage 1 — Export (NAS/Mac)
```bash
DB_PATH=/var/services/homes/pawin/ui/chat_history.db \
  python scripts/export_finetune.py data/finetune_sft.jsonl
# → data/finetune_sft.jsonl (chat format: {"messages":[system,user,assistant]})
```
ดึงเฉพาะคำตอบที่ได้ 👍 + คำถามก่อนหน้า (exclude 👎, skip orphan)

## Stage 2 — Train (PC RTX 3060, ใน WSL/Linux + CUDA)
```bash
pip install -r requirements-train.txt          # unsloth + เพื่อน
python scripts/train_qlora.py data/finetune_sft.jsonl
# → kwan-ft/ (GGUF q4_k_m)
```
Config (`train_qlora.py`) ปรับให้ 3060 12GB: 4-bit, seq 2048, LoRA r=16, batch 2×accum 4.
ถ้า OOM → ลด `MAX_SEQ_LEN=1024` หรือ `BATCH_SIZE=1`

## Stage 3 — Deploy (PC Ollama → NAS)
```bash
# 1) Modelfile ชี้ GGUF ที่เทรนได้ + persona เดิม
cat > Modelfile.kwan-ft <<'EOF'
FROM ./kwan-ft/unsloth.Q4_K_M.gguf
PARAMETER temperature 0.7
PARAMETER num_ctx 8192
SYSTEM """คุณชื่อ ขวัญ ..."""   # copy จาก Modelfile.kwan
EOF
# 2) สร้าง model ใน Ollama
ollama create kwan-ft -f Modelfile.kwan-ft
# 3) ชี้ NAS .env → OLLAMA_MODEL=kwan-ft → recreate hybrid-ai
```
**Eval gate ก่อนใช้จริง:** ทดสอบ kwan-ft กับ kwan เดิมด้วยชุดคำถาม → ถ้าไม่ดีกว่า อย่าสลับ. เก็บตัวเก่าไว้ rollback

---

## ข้อควรรู้
- **fine-tune ≠ จำข้อมูล** — สำหรับ "จำ" ใช้ RAG/memory ดีกว่า. fine-tune คุ้มกับ **style/format/พฤติกรรม** ที่ prompt ทำไม่ได้
- เทรนเป็นครั้งคราว (สะสม data พอ) ไม่ใช่ทุกคืน — ต่างจาก Dream cycle (memory mgmt รายคืน)
- ลองทางนุ่มก่อนเสมอ: Modelfile (persona) → skills/RAG → ค่อย fine-tune
- DPO (จากคู่ 👍/👎) เหมาะกับ "behavior" มากกว่า SFT — ทำเพิ่มได้เมื่อมีคู่ข้อมูลพอ
