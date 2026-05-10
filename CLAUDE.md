# 📋 บันทึกข้อมูลสำคัญ Hybrid AI Workspace

## 1️⃣ Persona & Style ที่ต้องรักษา
- **ตอบภาษาไทยเสมอ** - ห้ามตอบอังกฤษโดยเด็ดขาด
- **ขั้นตอนสั้นกระชับ** - 1, 2, 3 แบบเข้าใจง่าย
- **กฎเหล็ก: ส่งโค้ดเต็มไฟล์เสมอ** - copy-paste-save-run ได้ทันที

## 2️⃣ Context ของระบบ
- **ชื่อระบบ**: Hybrid AI Workspace ของพี่ปอย
- **Tech Stack**: FastAPI + React + Docker + Gemini + Ollama
- **ที่ติดตั้ง**: NAS (Synology DS923+) และ PC บ้าน
- **URL**: https://ai.pawinhome.com
- **เชื่อมต่อภายนอก**: Cloudflare Tunnel

## 3️⃣ 3 AI Assistants หลัก
| 🩵 ฟ้า (UI) | 🧡 ขวัญ (Logic) | 💙 ขิม (Docs) |
|---|---|---|
| Frontend, React, Tailwind | Backend, Python, API | Planning, Docs, Writing |
| เสียง: Kore | เสียง: Aoede | เสียง: Zephyr |

## 4️⃣ คำสั่ง Deploy บน NAS (สำคัญ)
```bash
cd /var/services/homes/pawin/ui
sudo git pull
sudo docker compose up -d hybrid-ai --force-recreate
```

## 5️⃣ IP & Port ที่ใช้
- **NAS IP**: 192.168.51.49
- **Ollama PC**: 192.168.51.235:1234
- **ChromaDB**: port 8000
- **AI Backend**: port 8080→8000

## 6️⃣ Features หลักที่ต้องรู้
- **Agent Mode** 🤖: Gemini + Google Search + Code
- **Voice Mode** 🎙️: คุยเสียงสดแบบ real-time
- **TTS** 🔊: AI อ่านข้อความ
- **Multi-AI Debate** 🧩: 3 AI ตอบพร้อมกัน
- **Obsidian Mode** 🌙: Inject notes เข้า context
- **Memory System** 🧠: จำข้อมูลข้าม session
- **Dream Cycle** 🌙: ปรับปรุง memory quality
- **Skills Management** 🗂️: Knowledge Base ส่วนตัว (ไฟล์ .md ใน skills/)
- **File Upload** 📤: อัปโหลดไฟล์รูป/ข้อความผ่าน `/api/upload`
- **Vault Search** 🔍: ค้นหาใน Obsidian vault ผ่าน `/api/vault/search`

## 7️⃣ Environment Variables สำคัญ
```env
GEMINI_API_KEY=your_key
GEMINI_MODEL=gemini-2.0-flash
OLLAMA_MODEL=llama3
CHROMA_PATH=/app/data/chroma
OBSIDIAN_VAULT_PATH=/volume1/obsidian
```

## 8️⃣ Tech Stack ของพี่ปอย
- **Frontend**: React, TypeScript, TailwindCSS, Vite
- **Backend**: Python FastAPI, ChromaDB, SQLite
- **AI**: Ollama (Local) + Gemini (Cloud)
- **Infrastructure**: Synology NAS, Docker, Cloudflare Tunnel
- **Scripting**: Google Apps Script, PowerShell
- **Database**: Firebase Firestore, SQLite

## 9️⃣ สไตล์การทำงาน
- ชอบ code สั้นกระชับ อ่านง่าย
- ชอบ dark mode UI แบบ glass morphism
- ชอบ emoji ในการสื่อสาร
- ตอบภาษาไทยเป็นหลัก อังกฤษสำหรับ technical terms
- ชอบ step-by-step ที่ชัดเจน พร้อม code ที่ copy-paste ได้เลย

## 🔟 API Endpoints สำคัญที่เพิ่มใหม่
| Endpoint | การทำงาน |
|---|---|
| `POST /api/upload` | อัปโหลดไฟล์รูป/ข้อความ |
| `GET /api/dream/report` | รายงาน Dream ล่าสุด |
| `GET /api/dream/history` | ประวัติรายงาน Dream |
| `POST /api/skills/extract` | สกัด content → skill `.md` |
| `GET /api/skills` + `/api/skills/list` | รายการ skills |
| `DELETE /api/skills/{topic}` | ลบ skill |
| `POST /api/admin/sync-skills` | sync skills → ChromaDB |
| `GET /api/vault/search?q=...` | ค้นหาใน Obsidian vault |
| `POST /api/memory/cleanup` | ล้าง memory เก่า |
| `PATCH /api/sessions/{ai}/{sid}` | แก้ไขชื่อ session |
| `DELETE /api/sessions/{ai}/{sid}` | ลบ session |

## 1️⃣1️⃣ แก้ปัญหาที่พบบ่อย
- **ปุ่มใหม่ไม่ขึ้น**: `git pull && docker compose up -d --force-recreate` + `Cmd+Shift+R`
- **Agent Mode error**: เปลี่ยน `GEMINI_MODEL=gemini-2.0-flash`
- **AI ไม่ตอบ**: `docker compose logs hybrid-ai`
- **TTS ไม่มีเสียง**: เช็ค API key + browser mute + 🔊 toggle
- **Voice ไม่เชื่อม**: อนุญาต mic + ใช้ HTTP
- **Share Link หาย**: ✅ ตอนนี้ persist ลง SQLite แล้ว — ไม่หาย
- **ChromaDB error**: ChromaDB container ถูก comment ใน docker-compose.yml — ระบบ fallback ใช้ SQLite

---
*อัพเดทล่าสุด: 10 พฤษภาคม 2026*