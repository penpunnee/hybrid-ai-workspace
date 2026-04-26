# 📘 คู่มือใช้งาน Hybrid AI Workspace
> อัพเดทล่าสุด: เมษายน 2026 — FastAPI + React + Docker + Gemini Live + All Features

---

## 🖥️ การเปิดใช้งาน

### บน NAS (หลัก)
```bash
# Pull โค้ดล่าสุด + restart
cd /var/services/homes/pawin/ui
sudo git pull
sudo docker compose up -d hybrid-ai --force-recreate

# ดู log
sudo docker compose logs -f hybrid-ai
```
เปิด browser: **http://[NAS-IP]:8000**  
หลัง deploy ใหม่: กด `Cmd+Shift+R` (hard refresh) เพื่อล้าง browser cache

### Build ใหม่ (หลัง requirements.txt เปลี่ยน)
```bash
sudo docker compose build hybrid-ai && sudo docker compose up -d hybrid-ai --force-recreate
```

### บน Mac (dev mode)
```bash
cd /Users/pawin/Desktop/ui
pip install -r requirements.txt
uvicorn server:app --reload --port 8000
# เปิด http://localhost:8000
```

### Sync โค้ด Mac → NAS
```bash
cd /Users/pawin/Desktop/ui
git add . && git commit -m "update" && git push
# แล้ว pull บน NAS ตามขั้นตอนข้างบน
```

---

## 🤖 3 AI Assistants

| | Assistant | ความเชี่ยวชาญ | เสียง (TTS/Voice) |
|---|---|---|---|
| 🩵 | **ฟ้า** | Frontend, UI/UX, React, Tailwind | Kore |
| 🧡 | **ขวัญ** | Backend, Python, API, Database | Aoede |
| 💙 | **ขิม** | Planning, Docs, Roadmap, Writing | Zephyr |

### สลับ Assistant
กดชื่อ Assistant ใน **Sidebar ซ้าย** — ประวัติแชทแยกต่างหากแต่ละคน

### สลับ AI Engine (ปุ่มบน header)
| ปุ่ม | คำอธิบาย |
|---|---|
| 🏠 Ollama | Local model — ข้อมูลไม่ออก internet |
| ☁️ Gemini | Cloud — เร็วและฉลาดกว่า |
| ⚡ Failover | Ollama offline → สลับ Gemini อัตโนมัติ |

---

## 💬 การแชท

### ส่งข้อความ
พิมพ์ใน input box แล้วกด **Enter** หรือปุ่มส่ง

### Prompt Templates
กดปุ่มลัดใน header เพื่อเติม template อัตโนมัติ เช่น:
- 🎨 ออกแบบ UI
- 🐛 หา Bug
- 🏗️ ออกแบบ API
- 📋 สรุป Bullet

### แนบไฟล์ (📎)
1. กดปุ่ม **📎** ข้างช่องพิมพ์
2. เลือกไฟล์ (.txt .md .py .json)
3. AI จะอ่านเนื้อหาไฟล์ก่อนตอบ

### แนบรูป (🖼️)
1. กดปุ่ม **🖼️** ข้างช่องพิมพ์ (หรือ icon รูปภาพ)
2. เลือกไฟล์รูป
3. AI วิเคราะห์รูปและตอบ (ต้องใช้ Gemini)

### Session ใหม่
กดปุ่ม **+ New chat** ด้านบน Sidebar หรือกด `Ctrl+N`

---

## � Regenerate Response

สั่งให้ AI **ตอบใหม่** โดยไม่ต้องพิมพ์ซ้ำ

1. **Hover** เมาส์บน bubble ของ AI
2. กดปุ่ม **🔄** ที่โผล่ขึ้นมา
3. AI ลบคำตอบเดิมและ stream คำตอบใหม่ทันที

---

## ✏️ Edit & Resend

**แก้ข้อความที่ส่งไปแล้ว** และส่งใหม่ (ลบประวัติหลังจากนั้นอัตโนมัติ)

1. **Hover** เมาส์บน bubble ของ User
2. กดปุ่ม **✏️** ที่โผล่ขึ้นมา
3. แก้ข้อความในกล่องที่เปิดขึ้น
4. กด **Enter** หรือ **✓ ส่ง** เพื่อส่งใหม่
5. กด **Esc** เพื่อยกเลิก

> ประวัติแชทหลังจากข้อความนั้นจะถูกลบออกทั้งจาก UI และ Database

---

## 📋 Copy ข้อความ

1. **Hover** เมาส์บน bubble ใดก็ได้
2. กดปุ่ม **📋** ที่โผล่ขึ้นมา
3. ข้อความถูก copy ไปยัง clipboard

---

## 🤖 Agent Mode — Gemini + Google Search + Code

เปิดให้ AI ใช้ **Google Search** และ **Code Execution** จริงๆ ผ่าน Gemini Tools

### เปิด/ปิด
กดปุ่ม **🤖** ใน header
- **สีเหลือง** = Agent Mode ON
- **ไม่มีสี** = ปิด (ตอบจาก knowledge เดิม)

> ⚠️ ต้องใช้ `GEMINI_MODEL=gemini-2.0-flash` ขึ้นไป (ไม่รองรับ gemini-1.5-flash)

---

## 🧩 Multi-AI Debate Mode

ส่งคำถามเดียวกันให้ **ทั้ง 3 AI ตอบพร้อมกัน** ใน 3 column

### วิธีใช้
1. กดปุ่ม **🧩** ใน header (เปลี่ยนเป็นสีชมพู)
2. พิมพ์คำถามแล้วกด Enter
3. หน้า Debate Overlay เปิด — ทั้ง 3 AI stream คำตอบพร้อมกัน
4. กด **✕** หรือ **Esc** เพื่อปิด

> ใช้ Gemini เป็น provider เสมอ — ไม่ขึ้นกับ engine ที่เลือกไว้

---

## � Obsidian Vault Mode — inject notes เข้า context

เมื่อเปิด AI จะ **ค้นหา Obsidian notes ที่เกี่ยวข้อง** แล้วแนบเข้า context ก่อนตอบ

### เปิด/ปิด
กดปุ่ม **🌙** ใน header (เปลี่ยนเป็นสีม่วง)

### Setup ครั้งแรก
```env
# .env บน NAS
OBSIDIAN_VAULT_PATH=/volume1/obsidian
```
แล้ว sync vault ก่อน:
```
GET /api/vault/sync
```

---

## 🔗 Share Chat Link

แชร์แชทเซสชันให้คนอื่นดูได้ (read-only)

1. กดปุ่ม **🔗** ใน header
2. Link ถูก copy ไปยัง clipboard อัตโนมัติ
3. ส่ง link ให้ใครก็เปิดดูได้ที่ `/shared/{token}`

> ⚠️ Link อยู่ใน memory — **reset เมื่อ restart server**

---

## 📅 Daily Digest — สรุปแชทเมื่อวาน

เปิดแอปครั้งแรกของวัน → popup สรุปแชทเมื่อวานอัตโนมัติ (Gemini สรุป ≤ 5 bullet)

- แสดงที่ **มุมล่างขวา** ของหน้าจอ
- กด **✕** เพื่อปิด
- จะไม่แสดงอีกจนกว่าจะเป็นวันถัดไป

> ต้องการ Gemini API key และมีแชทจากวันก่อน

---

## 🔊 TTS — ให้ AI อ่านออกเสียง

### เปิด/ปิด Auto-speak
กดปุ่ม **🔊** ใน header
- **สีเขียว** = เปิด — AI พูดทุกครั้งที่ตอบเสร็จ
- แสดง **⏸** ขณะกำลังเล่นเสียง

### เล่นซ้ำข้อความที่ผ่านมา
1. **Hover** เมาส์บน bubble ของ AI
2. กดปุ่ม **🔊** ที่โผล่ขึ้นมา

### เสียงแต่ละ Assistant
| Assistant | เสียง | ลักษณะ |
|---|---|---|
| 🩵 ฟ้า | Kore | นุ่ม ใส สดใส |
| 🧡 ขวัญ | Aoede | อบอุ่น มั่นใจ |
| 💙 ขิม | Zephyr | เบา ร่าเริง |

> **Model:** `gemini-2.5-flash-preview-native-audio-dialog`

---

## 🎙️ Voice Mode — คุยด้วยเสียงสดแบบ Real-time

### วิธีเริ่มต้น
1. กดปุ่ม **🎙️** ใน header
2. Browser ถามขอ mic permission → กด **Allow**
3. หน้า Voice overlay จะเปิดขึ้น

### สถานะ
| สีและข้อความ | ความหมาย |
|---|---|
| 🔗 เหลือง — กำลังเชื่อมต่อ | WebSocket กำลัง connect กับ Gemini |
| 🎧 ม่วง — กำลังฟัง | พูดได้เลย Gemini รับเสียงอยู่ |
| 🔊 เขียว — AI กำลังพูด | รอสักครู่ แล้วค่อยพูดต่อ |

### Voice → Chat History
transcript ทั้ง **User** และ **AI** จะถูกบันทึกลง chat history อัตโนมัติเมื่อปิด Voice Mode

> **Model:** `gemini-live-2.0-flash-001` — ตั้งค่าที่ `GEMINI_LIVE_MODEL` ใน `.env`

---

## 📌 Pin ข้อความสำคัญ

1. **Hover** บน bubble → กดปุ่ม **📌 Pin**
2. ขอบ bubble เปลี่ยนเป็น **สีทอง**
3. กดปุ่ม **📌** ใน header เพื่อดูทั้งหมด
4. Unpin: กด **✕** ในปุ่ม Panel

---

## 📊 Usage Dashboard

กดปุ่ม **�** ใน header → เปิด modal แสดง:
- จำนวนข้อความทั้งหมดแต่ละ AI
- Tokens ที่ใช้งาน
- สถิติ Memory (lessons, preferences, long-term)

---

## 💾 Export แชท

กดปุ่ม **💾** ใน header หรือ `Ctrl+E`
→ ดาวน์โหลดไฟล์ `.md` พร้อม timestamp

---

## 🔍 ค้นหาข้อความ

กล่อง **🔍 ค้นหา...** ใน Sidebar หรือกด `Ctrl+K`
- ค้นจาก **ทุก session** และ **ทุก assistant**
- กดที่ผลลัพธ์ → เปิด session นั้นทันที

---

## ⌨️ Keyboard Shortcuts

| Shortcut | การทำงาน |
|---|---|
| `Ctrl+K` | Focus ช่องค้นหา |
| `Ctrl+N` | เปิด Session ใหม่ |
| `Ctrl+E` | Export แชท |
| `Esc` | ปิด modal / Voice Mode / Debate |

---

## 🧠 Memory System

AI จำข้อมูลสำคัญของคุณ **ข้ามเซสชัน** เช่น ชื่อ งาน ความชอบ ทักษะ

### บันทึกด้วยตัวเอง
พิมพ์: `จำไว้ว่า [ข้อมูล]`

### ดู Stats
ส่วน **GBRAIN Memory** ใน Sidebar ซ้าย

---

## 🌙 Dream Cycle — Memory Consolidation

ระบบ **ปรับปรุง memory** ให้มีคุณภาพขึ้น

### วิธีรัน
กดปุ่ม **🌙 Dream** ใน Sidebar ล่าง

### 3 Phases
| Phase | การทำงาน |
|---|---|
| 💤 Light Sleep | วิเคราะห์ pattern จาก raw memory |
| 🌀 REM Sleep | สกัด theme และ insight |
| 🌊 Deep Sleep | promote ข้อมูลสำคัญ → long-term |

> Auto-trigger เมื่อ memory เกิน **100 รายการ**

---

## ⚙️ การตั้งค่า Environment (`.env`)

```env
# ============ AI Models ============
GEMINI_API_KEY=your_key_here

# ⚠️ ต้องเป็น gemini-2.0-flash ขึ้นไป (สำหรับ Agent Mode)
GEMINI_MODEL=gemini-2.0-flash

GEMINI_TTS_MODEL=gemini-2.5-flash-preview-native-audio-dialog
GEMINI_LIVE_MODEL=gemini-live-2.0-flash-001

# ============ Ollama (Local) ============
OLLAMA_MODEL=llama3
OLLAMA_BASE_URL=http://host.docker.internal:11434

# ============ Storage ============
CHROMA_PATH=/app/data/chroma
OBSIDIAN_VAULT_PATH=/volume1/obsidian   # สำหรับ 🌙 Obsidian Mode
```

---

## 📁 โครงสร้างไฟล์

```
ui/
├── server.py               # FastAPI: API endpoints + WebSocket
├── requirements.txt
├── Dockerfile / docker-compose.yml
├── .env                    # API keys (ห้าม push git)
├── chat_history.db         # SQLite (auto-created)
├── static/                 # React build output
├── assistants/config.py    # ตั้งค่า AI + templates
└── utils/
    ├── llm.py              # Ollama + Gemini + agent_mode
    ├── tts.py              # TTS
    ├── history.py          # SQLite + pin + truncate
    ├── memory.py           # Memory CRUD
    ├── dream.py            # Dream Cycle
    ├── obsidian_sync.py    # Obsidian vault sync
    ├── skills.py           # Skills DB
    └── tokens.py           # Token counter
```

---

## 🌐 API Endpoints (ทั้งหมด)

| Method | Path | การทำงาน |
|---|---|---|
| GET | `/api/config` | ดึง config assistants |
| POST | `/api/chat` | แชท streaming SSE (`agent_mode`, `obsidian_inject`) |
| POST | `/api/regenerate` | ลบ AI response ล่าสุด + stream ใหม่ |
| DELETE | `/api/truncate/{db_id}` | ลบประวัติตั้งแต่ db_id ขึ้นไป (Edit & Resend) |
| GET | `/api/history/{ai}/{sid}` | ประวัติแชท |
| GET | `/api/sessions/{ai}` | รายการ sessions |
| POST | `/api/sessions/{ai}` | สร้าง session ใหม่ |
| POST | `/api/pin/{db_id}` | pin / unpin |
| GET | `/api/pinned/{ai}/{sid}` | ข้อความที่ pin |
| GET | `/api/export/{ai}/{sid}` | export markdown |
| GET | `/api/search?q=...` | ค้นหาข้อความ |
| POST | `/api/tts` | สร้างเสียง WAV |
| WS | `/ws/voice/{slug}?session_id=...` | Voice Mode + transcript save |
| POST | `/api/dream` | รัน Dream Cycle |
| GET | `/api/stats` | Usage Dashboard |
| GET | `/api/digest` | Daily Digest (Gemini summary) |
| POST | `/api/share` | สร้าง share token |
| GET | `/api/shared/{token}` | ดึงข้อมูล shared chat (JSON) |
| GET | `/shared/{token}` | หน้า shared chat (HTML read-only) |
| GET | `/api/vault/sync` | Sync Obsidian vault → ChromaDB |
| GET | `/api/vault/stats` | สถิติ Obsidian vault |
| GET | `/api/status` | สถานะ Ollama / Gemini |

---

## ⚠️ แก้ปัญหาที่พบบ่อย

| ปัญหา | วิธีแก้ |
|---|---|
| **ปุ่มใหม่ไม่ขึ้น** | `sudo git pull && docker compose up -d --force-recreate` แล้ว `Cmd+Shift+R` |
| **Agent Mode error 404** | เปลี่ยน `.env` → `GEMINI_MODEL=gemini-2.0-flash` |
| **AI ไม่ตอบ / หน้าขาว** | `sudo docker compose logs hybrid-ai` ดู error |
| **TTS ไม่มีเสียง** | ① เช็ค `GEMINI_API_KEY` ② browser ไม่ได้ mute ③ เปิด 🔊 toggle |
| **Voice ไม่เชื่อม** | ① อนุญาต mic ใน browser ② ใช้ HTTP ไม่ใช่ HTTPS |
| **Share link หาย** | restart server จะ reset — feature นี้ in-memory |
| **Obsidian ไม่ inject** | ① ตั้ง `OBSIDIAN_VAULT_PATH` ② sync vault ก่อน ③ เปิด 🌙 |
| **Memory เต็ม** | รัน 🌙 Dream Cycle ใน Sidebar |
| **Build ล้มเหลว** | `sudo docker compose build --no-cache hybrid-ai` |
