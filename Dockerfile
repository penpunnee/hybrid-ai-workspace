FROM python:3.11-slim
WORKDIR /app

# poppler-utils — pdf2image ใช้แปลง PDF scan → PNG สำหรับ OCR (utils/ocr.py)
RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# requirements.lock = pip freeze จาก container ที่รันได้จริง (pin ทุกตัวกัน silent break
# ตอน rebuild — requirements.txt เป็น spec หลวมไว้อ่าน/อัปเกรดโดยตั้งใจเท่านั้น)
# อัปเกรด dependency: แก้ requirements.txt → build ด้วย lock ใหม่จาก pip freeze
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock

# หมายเหตุ: layer pre-download ONNX MiniLM ถูกตัดออก (2026-07-12) — embedding จริงใช้
# Ollama multilingual (EMBEDDING_MODEL ใน .env) ตั้งแต่ 5a26ba5; MiniLM เหลือแค่ fallback
# ที่ถ้าถูกใช้จริง recall ก็เพี้ยนอยู่แล้ว (คนละ model กับข้อมูลใน collection) — ถ้าจำเป็น
# chromadb จะ download เองครั้งเดียวลง volume chroma_model_cache
COPY . .

EXPOSE 8000
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
