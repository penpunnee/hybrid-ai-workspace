# Environment Variables Reference — .env บน NAS

## AI Models

```env
GEMINI_API_KEY=your_key          # ขอฟรีที่ aistudio.google.com
GEMINI_MODEL=gemini-2.5-pro      # หรือ gemini-2.0-flash
GEMINI_LIVE_MODEL=gemini-2.0-flash-exp

OLLAMA_BASE_URL=http://192.168.51.235:1234/v1
OLLAMA_MODEL=llama3               # หรือ kwan (custom Modelfile)
OLLAMA_TIMEOUT=120
OLLAMA_MAX_RETRIES=2
OLLAMA_RETRY_DELAY=2

# Ollama tuning parameters
OLLAMA_TEMPERATURE=0.7            # 0.0=แม่น, 1.0=สร้างสรรค์
OLLAMA_TOP_P=0.85
OLLAMA_NUM_CTX=4096               # context window size
OLLAMA_REPEAT_PENALTY=1.1
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
UI_PASSWORD=Sapoil                # รหัสผ่าน UI (ว่าง = เปิดสาธารณะ)
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
