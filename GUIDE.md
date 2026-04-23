# 📘 คู่มือใช้งาน Hybrid AI Workspace

## 🖥️ การรันระบบ

### บน Mac
```bash
# Terminal 1 — Streamlit
cd /Users/pawin/Desktop/ui
streamlit run app.py
# เปิด http://localhost:8501

# Terminal 2 — Portfolio
cd /Users/pawin/Desktop/portfolio
npm run dev
# เปิด http://localhost:3000
```

### บน PC ที่บ้าน (Windows)
```powershell
# PowerShell 1 — เปิด Ollama (เปิด app จาก system tray ก่อน)
ollama serve

# PowerShell 2 — Streamlit
cd C:\Users\penpu\hybrid-ai-workspace
streamlit run app.py
# เปิด http://localhost:8501

# PowerShell 3 — Portfolio
cd C:\Users\penpu\my-web-app\portfolio
npm run dev
# เปิด http://localhost:3001
```

---

## 🤖 การใช้งาน AI

### สลับ AI Engine
- **🏠 Local (Llama)** — ข้อมูลไม่ออก Internet ปลอดภัย เหมาะกับงานองค์กร
- **☁️ Cloud (Gemini)** — เร็ว วิเคราะห์กว้าง เหมาะกับงานทั่วไป

### 3 Assistant
| Assistant | ความเชี่ยวชาญ | Shortcut |
|-----------|--------------|---------|
| 🩵 ฟ้า | Frontend, UI/UX, React, Tailwind | ออกแบบ UI / Review โค้ด |
| 🧡 หมี | Backend, Python, API, Database | หา Bug / ออกแบบ API |
| 💙 ขิม | Planning, Docs, Roadmap | สรุป / เขียน README |

### Prompt Templates
กดปุ่ม shortcut ใต้หัวข้อแต่ละ tab เพื่อใช้คำสั่งสำเร็จรูป

---

## 📎 RAG System (ให้ AI อ่านไฟล์)

### Auto-load
- `identity.json` — โหลดอัตโนมัติทุกครั้ง AI จะรู้จักพี่และงานพมจ.

### Upload ไฟล์
- Sidebar → **📎 RAG Context** → อัปโหลดไฟล์ (.txt, .md, .json, .py)
- AI จะอ่านไฟล์เหล่านี้ก่อนตอบ

### Skills Folder
- ใส่ path โฟลเดอร์ที่มีไฟล์ความรู้ เช่น `/path/to/skills`

---

## 💾 ประวัติแชท

| ปุ่ม | การทำงาน |
|------|---------|
| 🗑️ | ลบประวัติแชทของ assistant นั้น |
| 💾 | Export ประวัติเป็นไฟล์ .md |

- ประวัติบันทึกใน `chat_history.db` อัตโนมัติ
- ปิด-เปิด browser ประวัติยังอยู่

---

## 🔧 แก้ไขการตั้งค่า

### เปลี่ยน Model
แก้ไฟล์ `.env`:
```
OLLAMA_MODEL=llama3        # เปลี่ยน local model
GEMINI_MODEL=gemini-2.5-flash  # เปลี่ยน cloud model (หรือ 3.1-flash-lite / 3.1-pro-preview)
```

### เพิ่ม/แก้ข้อมูลตัวเอง
แก้ไฟล์ `identity.json` — AI จะรู้จักข้อมูลใหม่ทันที

### เพิ่ม Assistant หรือ Prompt Templates
แก้ไฟล์ `assistants/config.py`

---

## 🌐 Portfolio Online

**URL:** https://portfolio-one-chi-tqe9o6hpfb.vercel.app

### อัพเดทเนื้อหา Portfolio
```bash
cd /Users/pawin/Desktop/portfolio
# แก้ไฟล์ที่ต้องการ
git add .
git commit -m "update"
git push
vercel --prod
```

---

## 🔄 Sync โค้ดระหว่าง Mac ↔ PC

### Mac → Push ขึ้น GitHub
```bash
cd /Users/pawin/Desktop/ui
git add . && git commit -m "update" && git push

cd /Users/pawin/Desktop/portfolio
git add . && git commit -m "update" && git push
```

### PC → Pull ลงมา
```powershell
cd C:\Users\penpu\hybrid-ai-workspace
git pull

cd C:\Users\penpu\my-web-app\portfolio
git pull
```

---

## ⚠️ แก้ปัญหาที่พบบ่อย

| ปัญหา | วิธีแก้ |
|-------|---------|
| 🔴 Ollama offline | เปิด Ollama app จาก system tray |
| 🟡 Gemini key ไม่มี | ใส่ key ใน `.env` จาก aistudio.google.com |
| Token counter แดง | กด 🗑️ ล้างประวัติแชทเพื่อเคลียร์ context |
| PC รัน streamlit ไม่ได้ | ใช้ `python -m streamlit run app.py` แทน |

---

## 📁 โครงสร้างไฟล์

```
hybrid-ai-workspace/
├── app.py              # หน้าหลัก Streamlit
├── identity.json       # ข้อมูลตัวเอง (auto-load)
├── .env                # API keys (ห้าม push git)
├── chat_history.db     # ประวัติแชท SQLite
├── assistants/
│   └── config.py       # ตั้งค่า assistant + templates
└── utils/
    ├── llm.py          # Ollama + Gemini
    ├── rag.py          # RAG system
    ├── history.py      # SQLite history
    └── tokens.py       # Token counter

portfolio/
├── app/
│   ├── page.tsx        # หน้าหลัก
│   ├── globals.css     # Liquid Glass theme
│   └── components/     # Navbar, Hero, BentoGrid, Skills, Contact
```
