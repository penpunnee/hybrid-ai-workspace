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

# Pre-download ONNX embedding model — ไม่ต้อง download ใหม่ทุกครั้งที่ start
RUN python3 -c "from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2; ONNXMiniLM_L6_V2()" || true

COPY . .

EXPOSE 8000
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
