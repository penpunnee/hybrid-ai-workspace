# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## System Overview

**Hybrid AI Workspace** — a FastAPI backend serving a React SPA, deployed on a Synology NAS (DS923+) and exposed via Cloudflare Tunnel at `https://ai.pawinhome.com`.

Stack: Python FastAPI + React (pre-built static) + SQLite + ChromaDB (optional) + Ollama (local LLM) + Gemini (cloud LLM).

## Commands

### Local Development
```bash
# Install deps
pip install -r requirements.txt

# Run server (with hot reload)
RELOAD=true python server.py
# or
uvicorn server:app --host 0.0.0.0 --port 8000 --reload
```

### Tests
```bash
# All tests
pytest tests/

# Single test file
pytest tests/test_main.py -v

# Single test
pytest tests/test_main.py::TestHealthEndpoints::test_root_endpoint -v
```

### Docker (NAS Deploy)
```bash
# Deploy on NAS
cd /var/services/homes/pawin/ui
sudo git pull
sudo docker compose up -d hybrid-ai --force-recreate

# View logs
docker compose logs hybrid-ai -f
```

### Frontend (pre-built)
The `static/` folder is a pre-built React app mounted as a Docker volume. To update the frontend, build it separately and replace `static/`.

## Architecture

### Request Flow
1. All HTTP requests → FastAPI `server.py`
2. Auth middleware checks `UI_PASSWORD` env var; LAN IPs (192.168.x, 10.x, 127.x) bypass auth; Cloudflare requests require `x-auth-token` header
3. `/api/chat` → builds context from memory + skills + Obsidian vault → calls `utils/llm.py` → streams SSE chunks to client
4. `/` → serves `static/index.html` (React SPA)

### Key Files
- `server.py` — all FastAPI routes; the only entry point
- `assistants/config.py` — 3 AI assistant definitions (ฟ้า/ขวัญ/ขิม): slugs, system prompts, prompt templates
- `utils/llm.py` — `stream_response()` routes to `_stream_ollama()` or `_stream_gemini()`; Ollama uses OpenAI-compatible client, Gemini uses `google-genai` SDK
- `utils/memory.py` — ChromaDB-backed long-term memory; auto-detects ChromaDB host; falls back gracefully if unavailable
- `utils/history.py` — SQLite-backed per-session chat history (`chat_history.db`)
- `utils/rag.py` — injects skills folder content + memory search results into system prompt
- `utils/dream.py` — Dream Cycle: nightly APScheduler job (02:00 Asia/Bangkok) that consolidates and promotes memories
- `utils/tts.py` — Gemini Native Audio TTS; voice mapped per assistant slug
- `utils/skills.py` + `skills_search.py` — skills stored as `.md` files in `skills/` and indexed in `skills_db.json`, synced to ChromaDB on startup
- `utils/obsidian_sync.py` — searches Obsidian vault mounted at `OBSIDIAN_VAULT_PATH`
- `utils/home_tools.py` — NAS/PC status tools injected into context when prompt mentions home network keywords

### Context Assembly (per chat request)
`/api/chat` assembles the system prompt from (in order):
1. Assistant base system prompt
2. ChromaDB memory search results
3. Long-term memory (lessons + preferences)
4. Skills search (ChromaDB) + skills folder `.md` files
5. Obsidian vault notes (if `obsidian_inject: true` in request)
6. Home tools real-time data (if prompt contains home-related keywords)

For Ollama, context is hard-capped at 2000 chars and messages trimmed to stay under ~3000 tokens.

### LLM Routing
- `provider: "ollama"` → local Ollama (OpenAI-compatible API)
- `provider: "gemini"` → Gemini cloud; also forced when `image_b64` or `agent_mode: true` is set
- No automatic failover between providers — Ollama failure shows error message

### Data Persistence
| Data | Storage |
|---|---|
| Chat history, sessions, share links, pins | `chat_history.db` (SQLite) |
| Long-term memory (ChromaDB) | External ChromaDB service (auto-detected) |
| Skills knowledge base | `skills/` folder (`.md` files) + `skills_db.json` |
| Dream reports | `dream_reports/` folder |

### Environment Variables
```env
GEMINI_API_KEY=          # required for Gemini/TTS/Agent mode
GEMINI_MODEL=gemini-2.0-flash
GEMINI_LIVE_MODEL=gemini-2.0-flash-exp
OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_MODEL=llama3
OLLAMA_TIMEOUT=120
OLLAMA_NUM_CTX=4096
UI_PASSWORD=             # optional; empty = no auth required
DB_PATH=/app/chat_history.db
OBSIDIAN_VAULT_PATH=/vault
CHROMA_HOST=             # optional; auto-detected from candidates if unset
CORS_ORIGINS=            # comma-separated; defaults to localhost + NAS IP
```

### WebSocket: Voice Chat
`/ws/voice/{assistant_slug}` — bidirectional WebSocket connecting to Gemini Live API. Client sends PCM audio chunks (`type: "audio"`) and receives audio back. Transcripts are saved to `chat_history.db` on turn completion.

## Coding Conventions
- All UI strings and comments are in Thai; technical terms remain English
- Every new API endpoint must be added to `server.py` directly (no separate routers)
- Skills `.md` files in `skills/` must also be registered in `skills_db.json` to appear in the API
- ChromaDB is optional — all memory functions must handle its absence gracefully (the `is_memory_available()` check)
- Auth test setup: set `os.environ["UI_PASSWORD"] = ""` before importing `server` in tests
