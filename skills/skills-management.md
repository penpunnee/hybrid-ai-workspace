# Skills Management — วิธีจัดการ Knowledge Base

## โครงสร้าง Skills

```
skills/                    ← .md files (mounted volume: NAS_DATA_PATH/skills)
skills_db.json             ← index/metadata ของ skills
ChromaDB skills_collection ← vectorized สำหรับ semantic search
```

## API Endpoints

| Endpoint | วิธีใช้ |
|---|---|
| `GET /api/skills` | รายการทั้งหมด + count |
| `GET /api/skills/list` | รายชื่อไฟล์ .md ใน folder |
| `POST /api/skills/extract` | สกัด skill ใหม่ด้วย Gemini |
| `DELETE /api/skills/{topic}` | ลบ skill |
| `POST /api/admin/sync-skills` | sync skills_db.json → ChromaDB |

## สร้าง Skill ใหม่ (Extract)

```bash
curl -X POST http://localhost:8080/api/skills/extract \
  -H 'Content-Type: application/json' \
  -d '{
    "topic": "ชื่อ-topic",
    "content": "เนื้อหาที่ต้องการสกัด..."
  }'
```

Gemini จะสร้าง Markdown reference แล้วบันทึกเป็น `{topic}.md`

## Sync หลังเพิ่ม/แก้ไข Skills

```bash
curl -X POST http://localhost:8080/api/admin/sync-skills \
  -H 'Content-Type: application/json' -d '{}'
# Response: {"ok":true,"synced":50}
```

## เพิ่ม .md ไฟล์โดยตรง

1. วาง `.md` ไฟล์ใน `NAS_DATA_PATH/skills/`
2. รัน sync-skills เพื่อ index เข้า ChromaDB
3. AI จะใช้ในการตอบคำถามทันที

## ลบ Skill

```bash
curl -X DELETE http://localhost:8080/api/skills/topic-name
```

## Skills ที่มีอยู่ปัจจุบัน (50 skills)

**จากโปรเจค (7 ไฟล์):**
- `hybrid-ai-workspace-overview` — overview ระบบ
- `home-network-tools-nas-wol` — NAS API + Wake-on-LAN
- `ollama-gemini-llm-integration` — LLM config
- `ai-assistants-config` — ฟ้า/ขวัญ/ขิม prompts
- `docker-deployment-nas` — Docker deployment
- `api-endpoints-reference` — API routes
- `memory-system-chromadb` — ChromaDB + threading

**จาก GUIDE.md (43 chunks):** quick reference ทุก feature ของระบบ

## Skills Search Flow

```
User prompt → semantic search ใน skills_collection
→ top 3 relevant skills ดึงมาใส่ context
→ AI ตอบพร้อม knowledge จาก skills
```
