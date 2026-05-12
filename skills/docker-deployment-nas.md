# Docker Deployment — NAS

## Services (docker-compose.yml)

3 containers รันคู่กันบน DS923+:

| Service | Container | Port | Description |
|---|---|---|---|
| `hybrid-ai` | `ai-backend-1` | 8080:8000 | FastAPI + React static |
| `chromadb` | `chromadb` | 8000:8000 | Vector DB |
| `cloudflared` | `ai-cloudflared` | — | Cloudflare tunnel → `ai.pawinhome.com` |

## Volumes (สำคัญ — mount จาก NAS_DATA_PATH)

```yaml
${NAS_DATA_PATH}/chat_history.db   → /app/chat_history.db
${NAS_DATA_PATH}/skills_db.json    → /app/skills_db.json
${NAS_DATA_PATH}/skills            → /app/skills        # ⚠️ ต้อง mount ไม่งั้น .md หายเมื่อ recreate
${NAS_DATA_PATH}/dream_reports     → /app/dream_reports
${OBSIDIAN_VAULT_NAS_PATH}         → /vault
chroma_data (named volume)         → /chroma/chroma
```

**Code mounts (สำหรับ hot-reload โดยไม่ต้อง rebuild):**
- `./server.py`, `./utils/`, `./routers/`, `./memory/`, `./agents/`, `./reasoning/`, `./core/`, `./assistants/`, `./tests/`, `./static/`

## Deploy Workflow

```bash
# SSH เข้า NAS
ssh pawin@192.168.51.49

cd /var/services/homes/pawin/ui

# Pull โค้ดล่าสุดจาก GitHub
sudo git pull

# Restart hybrid-ai container (rebuild ถ้า requirements.txt เปลี่ยน)
sudo docker compose up -d hybrid-ai --force-recreate

# ดู logs
sudo docker compose logs hybrid-ai -f
```

## Environment Variables (`.env` บน NAS)

ต้องตั้ง:
```env
GEMINI_API_KEY=...
OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_MODEL=llama3
LMSTUDIO_BASE_URL=http://192.168.51.235:1234/v1
LMSTUDIO_CHAT_MODEL=google/gemma-4-e4b
LMSTUDIO_REASON_MODEL=deepseek/deepseek-r1-0528-qwen3-8b
LMSTUDIO_VISION_MODEL=llama-3.2-11b-vision-instruct
UI_PASSWORD=...                          # ป้องกัน public access
DB_PATH=/app/chat_history.db
OBSIDIAN_VAULT_PATH=/vault
NAS_DATA_PATH=/var/services/homes/pawin/ui_data
OBSIDIAN_VAULT_NAS_PATH=/var/services/homes/pawin/Obsidian
```

## Cloudflare Tunnel

Config อยู่ที่ `/var/services/homes/pawin/.cloudflared/config.yml` — bind `ai.pawinhome.com` → `localhost:8080`

ถ้า tunnel ดับ → `https://ai.pawinhome.com` จะคืน HTTP 530 (Cloudflare reaches edge แต่ origin unreachable)

## Troubleshooting

| อาการ | สาเหตุ | แก้ |
|---|---|---|
| HTTP 530 จาก Cloudflare | `cloudflared` container ดับ หรือ tunnel disconnect | `docker compose restart cloudflared` |
| `/api/memory/stats` คืน 0 ทั้งที่มี data | ChromaDB ไม่ขึ้น หรือ HOST detect ผิด | ตรวจ `chromadb` container + `CHROMA_HOST` env |
| Skill .md หายหลัง recreate | ลืม mount `skills/` volume | ตรวจ docker-compose.yml line 15 |
| Dream cycle ไม่รัน | scheduler ใน `core/scheduler.py` ไม่ start หรือ container restart | ดู `[Scheduler]` log line |

## Manual Operations

```bash
# รัน Dream cycle ตอนนี้เลย
curl -X POST http://192.168.51.49:8080/api/dream

# ดู report ล่าสุด
curl http://192.168.51.49:8080/api/dream/report

# Cleanup junk skills
curl -X POST http://192.168.51.49:8080/api/admin/cleanup-skills

# Re-sync skills → ChromaDB search index
curl -X POST http://192.168.51.49:8080/api/admin/sync-skills
```
