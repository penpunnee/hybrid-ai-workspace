#!/usr/bin/env python3
"""Stage 2+3 — QLoRA fine-tune Llama-3.1-8B + export GGUF (รันบน PC RTX 3060 12GB)

⚠️ TEMPLATE — ต้อง validate บนเครื่องจริง (GPU + Unsloth ติดตั้งแล้ว + มี dataset)
ยังไม่ผ่านการรันจริง (เครื่อง dev ไม่มี GPU) — ปรับ config ตามผลรอบแรก

Prereq (บน PC, ใน WSL/Linux + CUDA):
  pip install -r requirements-train.txt   # unsloth, trl, transformers, datasets, ...

Usage:
  python scripts/train_qlora.py data/finetune_sft.jsonl

Pipeline:
  1. โหลด Llama-3.1-8B 4-bit (Unsloth)
  2. ใส่ LoRA adapter → เทรนบน JSONL จาก Stage 1
  3. export เป็น GGUF (q4_k_m) → พร้อม ollama create

หลัง export → deploy ด้วย:
  ollama create kwan-ft -f Modelfile.kwan-ft   # FROM ./kwan-ft.gguf + SYSTEM/PARAMETER
  แล้วชี้ OLLAMA_MODEL=kwan-ft บน NAS .env
"""
import sys

# ── config (ปรับตาม 3060 12GB) ─────────────────────────────────────────────
BASE_MODEL   = "unsloth/Meta-Llama-3.1-8B-Instruct-bnb-4bit"
MAX_SEQ_LEN  = 2048          # 3060 12GB รับไหว; ลดเป็น 1024 ถ้า OOM
LORA_R       = 16            # rank — 16-32 พอสำหรับ behavior tuning
LORA_ALPHA   = 16
BATCH_SIZE   = 2             # per-device; ใช้ grad-accum ชดเชย
GRAD_ACCUM   = 4             # effective batch = 2*4 = 8
EPOCHS       = 2             # 1-3; ระวัง overfit ถ้า data น้อย
LR           = 2e-4
OUT_DIR      = "kwan-ft"
GGUF_QUANT   = "q4_k_m"


def main(jsonl_path: str):
    from unsloth import FastLanguageModel
    from datasets import load_dataset
    from trl import SFTTrainer, SFTConfig

    # 1) โหลด base 4-bit
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=BASE_MODEL,
        max_seq_length=MAX_SEQ_LEN,
        load_in_4bit=True,
    )
    # 2) ใส่ LoRA
    model = FastLanguageModel.get_peft_model(
        model, r=LORA_R, lora_alpha=LORA_ALPHA, lora_dropout=0,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
        use_gradient_checkpointing="unsloth",
    )

    # 3) dataset (JSONL จาก Stage 1: {"messages":[...]}) → chat template
    ds = load_dataset("json", data_files=jsonl_path, split="train")

    def _fmt(ex):
        return {"text": tokenizer.apply_chat_template(
            ex["messages"], tokenize=False, add_generation_prompt=False)}
    ds = ds.map(_fmt)
    print(f"[train] {len(ds)} examples")
    if len(ds) < 50:
        print("⚠️ data < 50 ตัวอย่าง — fine-tune อาจ overfit/ไม่คุ้ม แนะนำสะสมเพิ่ม")

    # 4) เทรน
    trainer = SFTTrainer(
        model=model, tokenizer=tokenizer, train_dataset=ds,
        dataset_text_field="text", max_seq_length=MAX_SEQ_LEN,
        args=SFTConfig(
            per_device_train_batch_size=BATCH_SIZE,
            gradient_accumulation_steps=GRAD_ACCUM,
            num_train_epochs=EPOCHS, learning_rate=LR,
            warmup_ratio=0.05, logging_steps=5,
            optim="adamw_8bit", output_dir="outputs", seed=42,
        ),
    )
    trainer.train()

    # 5) export GGUF (Stage 3) → พร้อม ollama create
    model.save_pretrained_gguf(OUT_DIR, tokenizer, quantization_method=GGUF_QUANT)
    print(f"✅ GGUF → {OUT_DIR}/  → ต่อด้วย: ollama create kwan-ft -f Modelfile.kwan-ft")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/train_qlora.py <dataset.jsonl>")
        sys.exit(1)
    main(sys.argv[1])
