# Troubleshooting Guide — Hybrid AI Workspace

## AI ไม่ตอบ / Error

| ปัญหา | วิธีแก้ |
|---|---|
| Ollama ไม่ตอบ | ตรวจว่า PC เปิดอยู่ + `curl http://192.168.51.235:1234/v1/models` |
| Gemini error 401 | ตรวจ `GEMINI_API_KEY` ใน `.env` |
| Gemini quota หมด | auto-fallback ไป LMStudio + web search (ดู routers/chat.py) |
| AI ตอบทั้ง 2 ฝั่ง | ดู enhanced.js fetch override — ต้องมีแค่ 1 layer |
| AI ตอบเป็นอังกฤษทั้งที่ถามไทย | system_prompt มี "ตอบเป็นภาษาไทยเท่านั้น" — ตรวจ assistants/config.py |

## Container ไม่ start

```bash
sudo docker logs ai-backend-1 --tail 30
# หา: ImportError, SyntaxError, port conflict
```

## ChromaDB Error

```bash
# ตรวจ ChromaDB container
sudo docker ps | grep chroma
curl http://192.168.51.49:8000/api/v2/heartbeat

# ถ้า ChromaDB ไม่มี → ระบบ fallback ใช้ SQLite อัตโนมัติ
```

## Memory ไม่บันทึก (ขวัญ/ฟ้า/ขิม)

- เดิม: emoji ในชื่อ collection ทำให้ fail
- แก้แล้ว: `_safe_slug()` ใน `utils/memory.py` ตัด emoji ออก
- Collection names: `memory_logic`, `memory_ui`, `memory_docs`

## UI ไม่อัปเดต หลัง deploy

```
Cmd+Shift+R  (hard refresh — ล้าง browser cache)
```

## Port Conflict

```bash
# ตรวจว่า port 8080 ถูกใช้งานอยู่ไหม
sudo netstat -tulpn | grep 8080
```

## TTS ไม่มีเสียง

1. ตรวจ browser ไม่ได้ mute
2. ตรวจ `GEMINI_API_KEY` ใช้งานได้
3. กดปุ่ม 🔊 ใน header เพื่อเปิด TTS

## Voice Mode ไม่เชื่อมต่อ

1. อนุญาต microphone ใน browser
2. ใช้ HTTP (ไม่ใช่ HTTPS) สำหรับ LAN
3. ตรวจ WebSocket: `ws://192.168.51.49:8080/ws/voice/kwan`

## Home Control Panel ไม่แสดงข้อมูล NAS

```bash
# ตรวจ env vars
sudo docker exec ai-backend-1 env | grep NAS
# ต้องมี: NAS_IP, NAS_USER, NAS_PASS, NAS_PORT=5000
```

## Wake-on-LAN ไม่ทำงาน

- ตรวจ `PC_MAC` ใน `.env` ถูกต้อง (`D8:BB:C1:DF:17:70`)
- WoL ส่งไปยัง `192.168.51.255:9` (LAN broadcast)
- PC ต้องเปิด WoL ใน BIOS + Network adapter settings

## Skills ไม่พบในการค้นหา

```bash
# sync skills → ChromaDB
curl -X POST http://localhost:8080/api/admin/sync-skills \
  -H 'Content-Type: application/json' -d '{}'
```

## Auth 401 จาก Cloudflare

- ต้องใส่ `UI_PASSWORD` ใน localStorage: `hw_auth_token`
- หรือเข้าผ่าน LAN (`192.168.51.49:8080`) ไม่ต้องใส่ password

## ⚠️ DELETE /api/skills/{id} ลบ .md file ด้วย (Bug)

`routers/skills.py:92-108` — endpoint ลบทั้ง JSON entry **และ .md file** บน disk โดยไม่มี option แยก

```python
for fname in [skill_id, f"{skill_id}.md"]:
    fp = os.path.join(skills_dir, fname)
    if os.path.exists(fp):
        os.remove(fp)
```

**กู้ไฟล์ที่ลบไป:** ใช้ Synology Btrfs Snapshot → DSM → File Station → คลิกขวา folder → Browse previous versions

**ป้องกัน:** เพิ่ม `keep_file` query param ใน DELETE call หรือใช้ `POST /api/admin/cleanup-skills` ที่ลบเฉพาะ JSON entry (ถ้า filter จับ)

## /api/memory/stats คืน total: 0 (Bug pre-existing)

endpoint นับ collection ผิด — data จริงยังอยู่ใน ChromaDB
ตรวจผ่าน:
```bash
curl http://192.168.51.49:8080/api/dream/report   # ดู phase1_light.raw_count
curl "http://192.168.51.49:8080/api/memory/recall/kwan?q=test"   # manual recall
```

## Phase B-E Features (หลัง deploy commits 6835518–3c06261)

### Citations ไม่แสดงใน UI
- ตรวจว่า frontend version v8 ขึ้นไป (มี `_parseChatSSE` ใน enhanced.js)
- ตรวจ SSE event `data: {"citations": [...]}` ใน Network tab

### Response cache ไม่ hit
- เคย thumbs-up หรือยัง? cache เก็บเฉพาะ Q ที่ผู้ใช้ rate up
- prompt ใกล้ของเดิมแค่ไหน? threshold 0.92 (env `RESPONSE_CACHE_THRESHOLD`)
- ตรวจ `/api/cache/stats` field `response.entries`

### Reflection ไม่ทำงาน
- ต้องส่ง `{"reflect": true}` ใน chat request (opt-in)
- ต้องมี LMStudio reasoning model loaded (`qwen/qwen3.5-9b`)

### Active learning ถามกลับบ่อยเกิน
- ปิดผ่าน `{"active_learning": false}` ใน chat request
- หรือลด threshold ใน `reasoning/active_learning.py:decide()`

### Code sandbox blocked
- ต้องมี Docker daemon รันบน host → `docker info`
- หรือเปิด local: `CODE_SANDBOX_ALLOW_LOCAL=true` ใน `.env` (ระวังความปลอดภัย)
