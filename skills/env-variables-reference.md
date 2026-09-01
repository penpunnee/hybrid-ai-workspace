# Environment Variables Reference — .env บน NAS

## AI Models

```env
GEMINI_API_KEY=your_key          # ขอฟรีที่ aistudio.google.com
GEMINI_MODEL=gemini-2.5-flash    # ⚠️ ห้าม gemini-2.5-pro — free tier limit=0 → 429 ทุก request
GEMINI_LIVE_MODEL=gemini-2.5-flash-native-audio-latest   # voice WebSocket

OLLAMA_BASE_URL=http://192.168.51.235:11434/v1   # ⚠️ 11434 = Ollama (1234 คือพอร์ต LM Studio)
OLLAMA_MODEL=llama3               # dormant fallback — local หลักจริงคือ LM Studio (ดูข้างล่าง)
OLLAMA_TIMEOUT=120
OLLAMA_MAX_RETRIES=2
OLLAMA_RETRY_DELAY=2

# Ollama tuning parameters
OLLAMA_TEMPERATURE=0.7            # 0.0=แม่น, 1.0=สร้างสรรค์
OLLAMA_TOP_P=0.85
OLLAMA_NUM_CTX=4096               # context window size
OLLAMA_REPEAT_PENALTY=1.1
```

### LM Studio — local provider ตัวจริง (ตั้งแต่ 2026-06-15)
Ollama เป็น dormant fallback แล้ว งาน local ทั้งหมดวิ่งผ่าน LM Studio
⚠️ **ยกเว้น embeddings ที่ทิศกลับกัน** — Ollama เป็นตัวหลัก, LM Studio เป็น fallback
และคุมด้วย `EMBEDDING_MODEL` **ตัวเดียว** ทั้งสองฝั่ง (ไม่มี env แยกต่อ provider)

```env
LMSTUDIO_BASE_URL=http://192.168.51.235:1234/v1   # ว่าง = ปิด LM Studio
LMSTUDIO_API_KEY=lmstudio         # ⚠️ รุ่นใหม่บังคับ token ต้องใส่ให้ตรง
LMSTUDIO_CHAT_MODEL=qwen/qwen3.5-9b
LMSTUDIO_REASON_MODEL=qwen/qwen3.5-9b
LMSTUDIO_VISION_MODEL=qwen/qwen3.5-9b
LMSTUDIO_TIMEOUT=180
```

## Storage & Database

```env
CHROMA_HOST=192.168.51.49
CHROMA_PORT=8000

DB_PATH=/app/chat_history.db     # SQLite path ใน container
NAS_DATA_PATH=/volume1/docker/hybrid-ai

OBSIDIAN_VAULT_PATH=/vault        # path ใน container (mount จาก NAS)
OBSIDIAN_VAULT_NAS_PATH=/volume1/obsidian
```

## Auth & Security

```env
UI_PASSWORD=your_ui_password      # รหัสผ่าน UI (ว่าง = เปิดสาธารณะ)
CORS_ORIGINS=http://192.168.51.49:8080,https://ai.pawinhome.com
```

## Home Network Tools

```env
NAS_IP=192.168.51.49
NAS_PORT=5000                     # Synology DSM HTTP port
NAS_USER=pawin
NAS_PASS=your_nas_password
PC_IP=192.168.51.235
PC_MAC=D8:BB:C1:DF:17:70         # Wake-on-LAN MAC address
```

## Notifications

```env
LINE_NOTIFY_TOKEN=your_token      # แจ้งเตือน Dream Cycle fail
```

## Path References ใน Docker

| ENV | Path ใน Container | ที่มา |
|---|---|---|
| `DB_PATH` | `/app/chat_history.db` | volume mount |
| `OBSIDIAN_VAULT_PATH` | `/vault` | volume mount |
| skills folder | `/app/skills/` | `NAS_DATA_PATH/skills` |
| dream reports | `/app/dream_reports/` | `NAS_DATA_PATH/dream_reports` |
