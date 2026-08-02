# Hybrid AI Workspace — Project Overview

ระบบ AI Assistant ส่วนตัวที่รวม Local LLM (Ollama/LMStudio) + Cloud LLM (Gemini/Claude API) เข้าด้วยกัน
พร้อม Memory + Skills + Dream Cycle + Obsidian Vault integration

**Live:** `https://ai.pawinhome.com` (Cloudflare Tunnel)
**Deploy:** Synology DS923+ NAS, Docker Compose

## 🏗️ Stack

| Layer | Tech |
|---|---|
| Frontend | React 18 + Vite + Tailwind CSS (pre-built static) — source อยู่ที่ `~/appscript.ui` |
| Backend | FastAPI (Python), single `server.py` + routers/ |
| Local LLM | **LM Studio (`qwen/qwen3.5-9b`)** = ตัวหลัก · Ollama (`llama3`) = dormant fallback |
| Cloud LLM | Gemini 2.5 Flash, Gemini Live (voice) |
| Memory | ChromaDB (vector store) + SQLite (chat history) |
| Tunnel | Cloudflare Tunnel |
| Scheduler | APScheduler (cron-style) |

## 🔄 Request Flow

```
User → React UI → POST /api/chat
    ↓
1. teach() — ตรวจ "จำไว้ว่า..." pattern
2. response_cache.lookup() — ถ้า Q ใกล้ thumbs-up → bypass LLM (Phase E)
3. Context assembly (stable-first → KV cache hit):
   • base_prompt — persona
   • prefs + lessons (ChromaDB)
   • skills_md — .md file match
   • search_skills — semantic via ChromaDB
   • memory_ctx — 3-tier recall (working/episodic/long-term)
   • vault_ctx — Obsidian notes (optional)
   • home_tool_ctx — NAS real-time (auto-trigger)
   • docs_ctx — uploaded documents RAG (Phase B)
   • citations.legend — source list (Phase B)
4. Active learning check — ถ้าคำถามกำกวม → instruct AI ถามกลับ (Phase C)
5. Route → Ollama / LMStudio / Gemini (per reasoning/router.py)
6. Stream SSE → chunks + citations + reflection + cache_hit + done events
7. Post-stream:
   • save_message → SQLite + return message_id
   • remember() → ChromaDB
   • reflect_answer() → critic LLM (opt-in)
   • _learn thread → save_lesson + save_preference
```

## 🌙 Dream Cycle (ตี 2 ทุกคืน)

```
APScheduler cron (Asia/Bangkok 02:00)
    ↓
Phase 1 Light:  ChromaDB → memory 24 ชม.
Phase 2 REM:    AI วิเคราะห์ pattern → themes (provider: gemini ถ้ามี, fallback ollama)
Phase 2.5 Decay: ลด confidence ของ memory เก่า
Phase 3 Deep:   themes ที่ผ่านเกณฑ์ → skills_db.json + long_term_memory collection
    ↓
dream_reports/dream_YYYYMMDD_HHMMSS.json
```

## 📂 โครงสร้างโปรเจกต์

```
ui/
├── server.py              # FastAPI entry + middleware + lifespan
├── legacy/app.py          # Streamlit UI ที่ปลดระวางแล้ว (ถอดออกจาก image 2026-07-12 — ห้าม import)
├── core/
│   ├── config.py          # env vars
│   ├── auth.py            # auth middleware (LAN bypass + token)
│   ├── scheduler.py       # APScheduler — dream nightly
│   └── observability.py   # request_id + timing + structured logs
├── routers/               # FastAPI routers (chat, sessions, memory, skills, dream, vault, tools, system, agent, documents, feedback, sandbox)
├── memory/                # tiered memory (working, episodic, long-term)
├── reasoning/             # router (model selection) + classifier + active_learning
├── agents/                # multi-step tool-use orchestrator + tool registry
├── utils/                 # llm, memory, skills, dream, embed, citations, chunking, documents, reflection, feedback, skill_discovery, code_sandbox, fs_tools, retrieval_cache, response_cache, context_budget, query_rewrite
├── assistants/config.py   # 3 personas (ฟ้า/ขวัญ/ขิม)
├── skills/                # .md knowledge base
├── static/                # React build output
└── tests/                 # pytest
```

## 🧠 Memory System (3 tiers)

1. **Working memory** — in-memory ring buffer per session_id (volatile)
2. **Episodic** — ChromaDB `memory_{assistant_slug}` (ล่าสุด, decay over time)
3. **Long-term** — ChromaDB `long_term_memory` (Dream-promoted themes only)

## 📚 Skills System

- **`skills/*.md`** — manual knowledge files
- **`skills_db.json`** — extracted skill index (topic, summary, source)
- **ChromaDB `skills_search`** — semantic search (synced from JSON)
- Phase C: `/api/skills/discover` auto-cluster prompts → propose new skills

## 🤖 Personas

3 AI personalities (`assistants/config.py`):
- 🩵 **ฟ้า** (`fa`) — UI/UX, frontend
- 🧡 **ขวัญ** (`kwan`) — Logic, system, debugging
- 💙 **ขิม** (`khim`) — Docs, planning, writing

ทั้งหมดตอบไทยเท่านั้น (hard constraint), มี chain-of-thought instructions ใน system prompt

## 📊 Status Endpoints

| Endpoint | Use |
|---|---|
| `GET /api/status` | Ollama/Gemini/memory/skills/dream schedule |
| `GET /api/cache/stats` | Phase E cache layers |
| `GET /api/memory/stats` | Memory inventory |
| `GET /api/dream/report` | Latest cycle output |
