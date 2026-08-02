# Project Architecture — Hybrid AI Workspace

## Stack Overview

```
Frontend:  React + TypeScript + TailwindCSS + Vite (pre-built)
Backend:   Python FastAPI + uvicorn
AI:        Gemini (Cloud) + Ollama (Local LLM)
Memory:    ChromaDB (vector) + SQLite (history)
Infra:     Docker + Synology NAS + Cloudflare Tunnel
```

## File Structure

```
ui/
├── server.py              ← FastAPI main app (1200+ lines)
├── legacy/app.py          ← Streamlit ที่ปลดระวางแล้ว (ถอดออกจาก image 2026-07-12 — ห้าม import)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env                   ← secrets (ไม่ commit)
├── CLAUDE.md              ← project instructions
├── Modelfile.kwan         ← Ollama custom model
├── assistants/
│   └── config.py          ← ฟ้า/ขวัญ/ขิม system prompts
├── utils/
│   ├── llm.py             ← Ollama + Gemini streaming
│   ├── memory.py          ← ChromaDB memory system
│   ├── home_tools.py      ← NAS API + WoL + Ping
│   ├── skills.py          ← skills management
│   ├── skills_search.py   ← ChromaDB skills search
│   ├── history.py         ← SQLite chat history
│   ├── rag.py             ← context injection
│   ├── dream.py           ← Dream Cycle (memory consolidation)
│   ├── obsidian_sync.py   ← Obsidian vault sync
│   ├── tts.py             ← Text-to-Speech
│   ├── notify.py          ← LINE Notify
│   └── tokens.py          ← token counting
├── static/
│   ├── index.html         ← entry point (inject enhanced.js)
│   ├── enhanced.js        ← UI layer (auth, home control, etc.)
│   └── assets/            ← built React bundle
├── skills/                ← .md knowledge base files
├── tests/
│   ├── test_main.py       ← API integration tests
│   └── test_memory.py     ← ChromaDB unit tests
└── data/                  ← persistent data (NAS volume)
    ├── chat_history.db
    ├── skills_db.json
    └── skills/
```

## Request Flow

```
Browser → Cloudflare Tunnel → NAS:8080 → Docker:8000
                                         ↓
                                    FastAPI (server.py)
                                    ├── Auth Middleware
                                    ├── /api/chat → LLM (Gemini/Ollama)
                                    ├── /api/memory → ChromaDB
                                    ├── /api/tools/home → NAS API / WoL
                                    └── /static → React bundle
```

## AI Chat Flow

```
User prompt
→ detect_home_tools() → call NAS/WoL API (ถ้า prompt เกี่ยวกับบ้าน)
→ search_memory() → ChromaDB lessons + preferences
→ search_skills() → ChromaDB skills_collection (top 3)
→ load_skills_folder() → .md files ใน skills/
→ inject_context_to_system() → รวม context ทั้งหมดใส่ system prompt
→ stream_response() → Gemini or Ollama
→ save_message() → SQLite
→ save_memory() → ChromaDB (async background)
```

## Network Topology

```
Internet → Cloudflare → NAS (192.168.51.49:8080)
                              ↓
                         Docker: ai-backend-1
                              ↓
                    ChromaDB (192.168.51.49:8000)
                    LM Studio PC (192.168.51.235:1234) ← local หลัก
                    Ollama PC   (192.168.51.235:11434) ← fallback
```

## Auth System

- **LAN access** (192.168.x.x Host header): ผ่านเสมอ ไม่ต้อง token
- **Cloudflare access**: ต้อง `x-auth-token: UI_PASSWORD` ใน header
- **Protected GET paths**: `/api/history/`, `/api/memory/`, `/api/sessions/`, `/api/tools/home/`
- **Public paths**: `/`, `/api/config`, `/api/status`, `/static/*`
