# Pawin (พี่ปอย) — Personal Context

## ข้อมูลเจ้าของระบบ

- **ชื่อ**: พี่ปอย (Pawin)
- **ระบบที่ใช้**: Hybrid AI Workspace ที่ติดตั้งบน Synology NAS ส่วนตัว
- **URL**: https://ai.pawinhome.com
- **สไตล์การสื่อสาร**: ไทยปนอังกฤษ ชอบกระชับ ตรงประเด็น

## Tech Stack ที่ใช้งาน

- **Frontend**: React, TypeScript, TailwindCSS, Vite
- **Backend**: Python FastAPI, ChromaDB, SQLite
- **AI**: Ollama (Local LLM) + Gemini (Cloud LLM)
- **Infrastructure**: Synology NAS DS923+, Docker, Cloudflare Tunnel
- **Scripting**: Google Apps Script (GAS), PowerShell
- **Database**: Firebase Firestore, SQLite

## โปรเจกต์ที่กำลังพัฒนา

- **Hybrid AI Workspace** — ระบบ AI ส่วนตัวบน NAS นี้
- **Google Apps Script Tools** — automation ใน Google Workspace
- **Home automation** — ผ่าน Home Assistant บน NAS

## ความชอบและสไตล์

- ชอบ code ที่สั้น กระชับ อ่านง่าย
- ชอบ dark mode UI แบบ glass morphism
- ชอบ emoji ในการสื่อสาร
- ตอบภาษาไทยเป็นหลัก อังกฤษสำหรับ technical terms
- ชอบ step-by-step ที่ชัดเจน พร้อม code ที่ copy-paste ได้เลย

## การตั้งค่าระบบ NAS

- **NAS IP**: 192.168.51.49
- **Ollama PC IP**: 192.168.51.235 (port 1234)
- **ChromaDB**: container `chromadb` port 8000
- **AI Backend**: container `ai-backend` / `hybrid-ai` port 8080→8000
- **NAS path**: /var/services/homes/pawin/ui

## คำสั่ง Deploy บน NAS

```bash
cd /var/services/homes/pawin/ui
sudo git pull
sudo docker compose up -d hybrid-ai --force-recreate
```
