# 📘 คู่มือใช้งาน Hybrid AI Workspace
> อัพเดทล่าสุด: เมษายน 2026 — FastAPI + React + Docker + Gemini Live

---

## 🖥️ การเปิดใช้งาน

### บน NAS (หลัก)
```bash
# Pull โค้ดล่าสุด + restart
cd /var/services/homes/pawin/ui
sudo git pull
sudo docker compose up -d hybrid-ai

# ดู log
sudo docker compose logs -f hybrid-ai
```
เปิด browser: **http://[NAS-IP]:8000**

### Build ใหม่ (หลัง requirements.txt เปลี่ยน)
```bash
sudo docker compose build hybrid-ai && sudo docker compose up -d hybrid-ai
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

## � การแชท

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

### Session ใหม่
กดปุ่ม **+ New chat** ด้านบน Sidebar

---

## 🔊 TTS — ให้ AI อ่านออกเสียง

### เปิด/ปิด Auto-speak
กดปุ่ม **🔊** ใน header (ข้างปุ่ม 🎙️)
- **สีเขียว** ✅ = เปิด — AI พูดทุกครั้งที่ตอบเสร็จ
- **ไม่มีสี** = ปิด
- แสดง **⏸** ขณะกำลังเล่นเสียง

### เล่นซ้ำข้อความที่ผ่านมา
1. **Hover** เมาส์บน bubble ข้อความของ AI
2. กดปุ่ม **🔊** ที่โผล่ขึ้นมา
3. กด **⏸ หยุด** เพื่อหยุดเสียงกลางคัน

### เสียงแต่ละ Assistant
| Assistant | เสียง | ลักษณะ |
|---|---|---|
| 🩵 ฟ้า | Kore | นุ่ม ใส สดใส |
| 🧡 ขวัญ | Aoede | อบอุ่น มั่นใจ |
| � ขิม | Zephyr | เบา ร่าเริง |

> **ต้องการ:** `GEMINI_API_KEY` ใน `.env`
> **Model:** `gemini-2.5-flash-preview-native-audio-dialog`

---

## 🎙️ Voice Mode — คุยด้วยเสียงสดแบบ Real-time

### วิธีเริ่มต้น
1. กดปุ่ม **🎙️** ใน header
2. Browser ถามขอ mic permission → กด **Allow**
3. หน้า Voice overlay จะเปิดขึ้นอัตโนมัติ

### หน้า Voice Overlay

```
        ╭─────────────────╮
        │  [  Avatar  ]   │  ← pulse ม่วง = ฟัง
        │                 │    pulse เขียว = AI พูด
        │  ขวัญ AI        │
        │  🎧 กำลังฟัง    │
        │  ▓▓▓▓▓▓▓▓▓▓▓   │  ← waveform
        │                 │
        │  [ ⏎ ส่ง ] [ ⏹ จบ ] │
        ╰─────────────────╯
```

### ปุ่มควบคุม
| ปุ่ม | การทำงาน |
|---|---|
| **⏎ ส่ง** | บอก Gemini ว่าพูดจบแล้ว ให้ตอบได้เลย |
| **⏹ จบ** | ปิด Voice Mode + หยุด mic ทั้งหมด |

### สถานะ (Status)
| สีและข้อความ | ความหมาย |
|---|---|
| 🔗 เหลือง — กำลังเชื่อมต่อ | WebSocket กำลัง connect กับ Gemini |
| 🎧 ม่วง — กำลังฟัง | พูดได้เลย Gemini รับเสียงอยู่ |
| 🔊 เขียว — AI กำลังพูด | รอสักครู่ แล้วค่อยพูดต่อ |

> **Model:** `gemini-live-2.0-flash-001`
> ตั้งค่าได้ที่ `GEMINI_LIVE_MODEL` ใน `.env`

---

## 📌 Pin/Bookmark ข้อความสำคัญ

### วิธี Pin
1. **Hover** เมาส์บน bubble ข้อความ
2. กดปุ่ม **📌 Pin** ที่โผล่ขึ้นมา
3. ขอบ bubble จะเปลี่ยนเป็น **สีทอง**

### ดูข้อความที่ Pin ไว้ทั้งหมด
กดปุ่ม **📌** ใน header (มีตัวเลขแดงแสดงจำนวน)
→ เปิด Panel ด้านขวา แสดงทุกข้อความที่ Pin ในเซสชันนี้

### Unpin
- กด **✕** ในปุ่ม Panel, หรือ
- Hover บน bubble แล้วกด **📌 Pinned** อีกครั้ง

---

## 💾 Export แชท

กดปุ่ม **💾** ใน header
→ ดาวน์โหลดไฟล์ `[AI-name]_[session-id].md` อัตโนมัติ

ไฟล์ที่ได้จะมีทุกข้อความในเซสชัน พร้อม timestamp

---

## 🔍 ค้นหาข้อความ

กล่อง **🔍 ค้นหา...** ใต้ปุ่ม New chat ใน Sidebar

1. พิมพ์คำที่ต้องการค้นหา
2. ผลลัพธ์ขึ้นทันที (ค้นจาก **ทุก session** และ**ทุก assistant**)
3. กดที่ผลลัพธ์ → เปิด session นั้นทันที

---

## 🧠 Memory System

AI จำข้อมูลสำคัญของคุณ **ข้ามเซสชัน** ได้ เช่น ชื่อ งาน ความชอบ ทักษะ

### ดู Memory Stats
ดูตัวเลขใน Sidebar ซ้าย ส่วน Memory

### บันทึก Memory ด้วยตัวเอง
พิมพ์ใน chat: `จำไว้ว่า [ข้อมูล]`
เช่น `จำไว้ว่า ฉันชอบ Tailwind มากกว่า Bootstrap`

---

## 🌙 Dream Cycle — Memory Consolidation

ระบบ **ปรับปรุง memory** ให้มีคุณภาพขึ้น — AI ฉลาดขึ้นหลังรัน

### วิธีรัน
กดปุ่ม **🌙 Dream** ใน Sidebar ล่าง

### 3 Phases
| Phase | การทำงาน | เวลา |
|---|---|---|
| � Light Sleep | วิเคราะห์ pattern จาก raw memory | ~10 วิ |
| 🌀 REM Sleep | สกัด theme และ insight | ~15 วิ |
| 🌊 Deep Sleep | promote ข้อมูลสำคัญ → long-term | ~10 วิ |

### Auto-trigger Alert ⚠️
เมื่อ memory เกิน **100 รายการ** จะมี popup ถามว่า:
- **🌙 รัน Dream เลย** — แนะนำกดนี้
- **ปิด** — ปิด popup แต่ยังไม่รัน

### ตั้งเวลาอัตโนมัติ
Dream Cycle รันอัตโนมัติตามกำหนด — ดู schedule ใน header ใต้ปุ่ม Dream

---

## ⚙️ การตั้งค่า Environment (`.env`)

```env
# ============ AI Models ============
GEMINI_API_KEY=your_key_here          # จาก aistudio.google.com
GEMINI_MODEL=gemini-2.5-flash         # model สำหรับแชท
GEMINI_TTS_MODEL=gemini-2.5-flash-preview-native-audio-dialog  # TTS
GEMINI_LIVE_MODEL=gemini-live-2.0-flash-001                    # Voice

# ============ Ollama (Local) ============
OLLAMA_MODEL=llama3
OLLAMA_BASE_URL=http://host.docker.internal:11434

# ============ Storage ============
CHROMA_PATH=/app/data/chroma          # ChromaDB path
VAULT_PATH=/volume1/obsidian          # Obsidian vault (ถ้ามี)
```

### เพิ่ม Assistant ใหม่
แก้ไฟล์ `assistants/config.py` — เพิ่ม entry ใหม่ใน dict `ASSISTANTS`

---

## 📁 โครงสร้างไฟล์

```
ui/
├── server.py               # FastAPI: API endpoints + WebSocket
├── requirements.txt        # Python dependencies
├── Dockerfile
├── docker-compose.yml
├── .env                    # API keys (ห้าม push git)
├── chat_history.db         # ประวัติแชท SQLite (auto-created)
├── static/                 # React build output
│   └── assets/
├── assistants/
│   └── config.py           # ตั้งค่า AI + templates
└── utils/
    ├── llm.py              # Ollama + Gemini + failover
    ├── tts.py              # TTS — Gemini Native Audio
    ├── voice.py            # Voice constants — Gemini Live
    ├── history.py          # SQLite history + pin/unpin
    ├── memory.py           # Memory CRUD
    ├── dream.py            # Dream Cycle (3 phases)
    ├── rag.py              # RAG / file context inject
    ├── skills.py           # Skills DB
    ├── tokens.py           # Token counter
    └── obsidian_sync.py    # Obsidian vault sync
```

---

## 🌐 API Endpoints

| Method | Path | การทำงาน |
|---|---|---|
| GET | `/api/config` | ดึง config assistants |
| POST | `/api/chat` | ส่งข้อความ (streaming SSE) |
| GET | `/api/history/{ai}/{sid}` | ประวัติแชท |
| GET | `/api/sessions/{ai}` | รายการ sessions |
| POST | `/api/pin/{db_id}` | pin / unpin ข้อความ |
| GET | `/api/pinned/{ai}/{sid}` | ข้อความที่ pin |
| GET | `/api/export/{ai}/{sid}` | export เป็น markdown |
| GET | `/api/search?q=...` | ค้นหาข้อความ |
| POST | `/api/tts` | สร้างไฟล์เสียง WAV |
| WS | `/ws/voice/{slug}` | Voice Mode WebSocket |
| POST | `/api/dream` | รัน Dream Cycle |
| GET | `/api/memory/stats` | stats memory |
| GET | `/api/status` | สถานะ Ollama / Gemini |

---

## ⚠️ แก้ปัญหาที่พบบ่อย

| ปัญหา | วิธีแก้ |
|---|---|
| **AI ไม่ตอบ / หน้าขาว** | `sudo docker compose logs hybrid-ai` ดู error |
| **TTS ไม่มีเสียง** | ① เช็ค `GEMINI_API_KEY` ② browser ไม่ได้ mute ③ เปิด 🔊 toggle |
| **Voice ไม่เชื่อม** | ① อนุญาต mic ใน browser ② ใช้ HTTP ไม่ใช่ HTTPS บน local |
| **⚡ Failover badge ค้าง** | Ollama ยัง offline — กด engine button สลับเป็น Gemini |
| **Pin ไม่บันทึก** | refresh หน้า แล้วลองใหม่ |
| **Memory เต็ม / ช้าลง** | รัน 🌙 Dream Cycle ใน Sidebar |
| **Build ล้มเหลว** | `sudo docker compose build --no-cache hybrid-ai` |
