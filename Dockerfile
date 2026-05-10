FROM python:3.11-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download ONNX embedding model — ไม่ต้อง download ใหม่ทุกครั้งที่ start
RUN python3 -c "from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2; ONNXMiniLM_L6_V2()" || true

COPY . .

EXPOSE 8000
CMD ["python", "server.py"]
