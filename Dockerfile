# ── Stage 1: Build React frontend ──────────────────────────────
FROM node:20-slim AS frontend
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci --silent
COPY frontend/ ./
RUN npm run build

# ── Stage 2: Python FastAPI backend ────────────────────────────
FROM python:3.11-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Copy built React app → FastAPI static folder
COPY --from=frontend /frontend/dist/ ./static/

EXPOSE 8000
CMD ["python", "server.py"]
