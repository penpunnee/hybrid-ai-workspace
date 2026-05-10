#!/bin/bash
# Deploy Modelfile.kwan ไปยัง PC Ollama แล้วสร้าง model
# Usage: ./deploy_ollama.sh <PC_USER> <PC_PASS>

PC_IP="192.168.51.235"
PC_USER="${1:-pawin}"
PC_PASS="$2"
MODEL_NAME="kwan"

if [ -z "$PC_PASS" ]; then
    echo "Usage: $0 <username> <password>"
    exit 1
fi

echo "=== Step 1: Copy Modelfile.kwan ไปยัง PC ==="
sshpass -p "$PC_PASS" scp -O Modelfile.kwan "${PC_USER}@${PC_IP}:/tmp/Modelfile.kwan"

echo "=== Step 2: Pull llama3.1 (ถ้ายังไม่มี) ==="
sshpass -p "$PC_PASS" ssh "${PC_USER}@${PC_IP}" "ollama pull llama3.1"

echo "=== Step 3: สร้าง custom model '$MODEL_NAME' ==="
sshpass -p "$PC_PASS" ssh "${PC_USER}@${PC_IP}" "ollama create ${MODEL_NAME} -f /tmp/Modelfile.kwan"

echo ""
echo "=== เสร็จแล้ว! ==="
echo "แก้ .env บน NAS ด้วย:"
echo "  OLLAMA_MODEL=${MODEL_NAME}"
echo "แล้ว recreate container:"
echo "  sudo docker compose up -d hybrid-ai --force-recreate"
