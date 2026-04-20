# คู่มือและผังภาพรวมระบบ Hybrid AI Workspace

## ภาพรวมระบบ (Architecture)

```
[พี่ปอย / ผู้ใช้]
     │
     ▼ HTTPS
[Cloudflare CDN]  ──────────────────────────────────┐
     │                                               │
     ▼ Tunnel                                        │
[NAS Synology 192.168.51.49]                         │
     │                                               │
     ├─ Container: ai-backend (Port 8080→8000)        │
     │     ├─ FastAPI (Python)                        │
     │     ├─ React UI (static files)                 │
     │     ├─ /api/chat → LM Studio (PC)              │
     │     ├─ /api/vault/sync → Obsidian Vault        │
     │     └─ /api/status, /api/sessions, /api/history│
     │                                               │
     ├─ Container: chromadb (Port 8000)               │
     │     └─ Vector database (ความจำระยะยาว)          │
     │                                               │
     └─ Container: ai-cloudflared                     │
           └─ Cloudflare Tunnel → ai.pawinhome.com ──┘

[Windows PC 192.168.51.235]
     └─ LM Studio (Port 1234)
           └─ meta-llama-3.1-8b-instruct
```

---

## Ports ที่ใช้งานอยู่

| Port | Service | หมายเหตุ |
|------|---------|----------|
| 8080 | ai-backend (FastAPI) | เข้าถึงจาก NAS local |
| 8000 | chromadb | Vector DB ความจำ AI |
| 1234 | LM Studio (PC) | Local LLM server |
| 443/80 | Cloudflare Tunnel | เชื่อมอินเทอร์เน็ต |

---

## ขั้นตอนเริ่มระบบ

### วิธีที่ 1 — ใช้ Script อัตโนมัติ (Windows PC)
```
รัน: start-ai.ps1
1. เปิด LM Studio
2. Start LM Studio server (port 1234)
3. Container ai-backend บน NAS จะทำงานอัตโนมัติ
4. เปิด https://ai.pawinhome.com
```

### วิธีที่ 2 — Manual
1. **เปิด LM Studio** บน PC → โหลด model → Start Server
2. **ตรวจ NAS** — Container ai-backend และ chromadb ต้องรันอยู่
   ```bash
   sudo docker ps | grep -E "ai-backend|chromadb|ai-cloudflared"
   ```
3. **เปิดเว็บ** → https://ai.pawinhome.com

---

## วิธีแก้ปัญหาที่พบบ่อย

### หน้าเว็บไม่ขึ้น / 524 Timeout
```bash
# เช็ค container
sudo docker ps | grep ai-backend

# ดู logs
sudo docker logs ai-backend --tail 20

# Restart
cd /var/services/homes/pawin/ui && sudo docker compose up -d hybrid-ai
```

### AI ไม่ตอบ
- ตรวจว่า LM Studio เปิดและ Start Server แล้ว
- เช็ค `/api/status` → `ollama` ต้องเป็น `true`
  ```bash
  curl http://localhost:8080/api/status
  ```

### Memory ไม่ทำงาน (memory: false)
```bash
# ตรวจ CHROMA_HOST ใน .env
sudo grep CHROMA /var/services/homes/pawin/ui/.env
# ต้องเป็น CHROMA_HOST=chromadb

# ถ้าไม่ถูก ให้แก้แล้ว recreate container
sudo docker compose up -d hybrid-ai
```

---

## Containers ที่จำเป็น

| Container | Image | ต้องรัน? |
|-----------|-------|---------|
| ai-backend | ui-hybrid-ai:latest | ✅ หลัก |
| chromadb | chromadb/chroma:latest | ✅ ความจำ |
| ai-cloudflared | cloudflare/cloudflared | ✅ internet access |
| cloudflare-tunnel | cloudflare/cloudflared | ของ Home Assistant |

---

## Git Repository
- **GitHub**: https://github.com/penpunnee/hybrid-ai-workspace
- **Mac project**: /Users/pawin/Desktop/ui (backend)
- **Mac project**: /Users/pawin/appscript.ui (frontend React)
- **NAS path**: /var/services/homes/pawin/ui

### Workflow อัปเดต code
```bash
# บน Mac
cd /Users/pawin/appscript.ui && npm run build
cd /Users/pawin/Desktop/ui && git add -A && git commit -m "..." && git push

# บน NAS
cd /var/services/homes/pawin/ui
sudo git pull
sudo docker compose build hybrid-ai && sudo docker compose up -d hybrid-ai
```

---

## ฟีเจอร์ที่มีอยู่

| ฟีเจอร์ | วิธีใช้ |
|---------|---------|
| Chat AI | พิมพ์ข้อความ → ส่ง |
| เปลี่ยน AI | กดปุ่ม Assistant บน header (ฟ้า / ขมิ้น / ดิ๊ก) |
| ความจำ | AI จำอัตโนมัติจากบทสนทนา |
| อัปโหลดไฟล์ | กด 📎 แนบ .md, .txt, .json, .py |
| Obsidian Sync | วางไฟล์ใน /volume1/obsidian-vault → กด 🔮 Sync |
| ประวัติแชท | เก็บใน SQLite บน NAS |
| Export | กดปุ่ม Export บน header |

---

## .env ที่สำคัญ (NAS)

```env
OLLAMA_BASE_URL=http://192.168.51.235:1234/v1
CHROMA_HOST=chromadb
CHROMA_PORT=8000
DB_PATH=/app/chat_history.db
OBSIDIAN_VAULT_PATH=/vault
OBSIDIAN_VAULT_NAS_PATH=/volume1/obsidian-vault
```
