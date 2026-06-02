# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## System Overview

**Hybrid AI Workspace** — a FastAPI backend serving a React SPA, deployed on a Synology NAS (DS923+) and exposed via Cloudflare Tunnel at `https://ai.pawinhome.com`.

Stack: Python FastAPI + React (pre-built static) + SQLite + ChromaDB + Ollama / LMStudio (local) + Gemini (cloud) + APScheduler.

## Commands

### Local Development
```bash
pip install -r requirements.txt
RELOAD=true python server.py
# หรือ
uvicorn server:app --host 0.0.0.0 --port 8000 --reload
```

### Tests
```bash
pytest tests/
pytest tests/test_main.py -v
pytest tests/test_main.py::TestHealthEndpoints::test_root_endpoint -v
```

### Docker (NAS Deploy)
```bash
cd /var/services/homes/pawin/ui
sudo git pull
sudo docker compose up -d hybrid-ai --force-recreate
docker compose logs hybrid-ai -f
```

⚠️ **Volume mount gotcha**: `skills/` ในโค้ด ไม่ใช่ที่ container อ่าน. Container อ่านจาก `${NAS_DATA_PATH}/skills` (default `./data/skills/`). ถ้าเพิ่ม .md ใหม่ใน git → ต้อง `cp skills/*.md data/skills/` ด้วย

### Frontend (pre-built)
`static/` คือ React build output — mount เป็น Docker volume. แก้แล้ว rebuild แยกแล้วแทนที่ `static/`. overlay แบบ vanilla (ไม่ต้อง build, ทำงานคู่ React bundle):
- `static/enhanced.js` — FAB (Claude/Agent/Search/Export/Vault), token counter, draft autosave, slash quick-prompts, hardware bar, **Dream stats applier** (เขียนทับ % ปลอมใน React ด้วยข้อมูลจริง), handle SSE เพิ่มเติม
- `static/dream_stats.js` — pure mapper `dreamCardValues(report)` → Light/REM/Deep จริง (dual-export node/browser, โหลดก่อน enhanced.js)
- ⚠️ React bundle minified แก้ตรงไม่ได้ → ค่า hardcode ใน bundle (เช่น sleep %) ต้องเขียนทับผ่าน enhanced.js overlay. หลังแก้ static → **hard refresh + bump `?v=` cache-bust** ใน `index.html`

## Architecture

### Request Flow (`/api/chat`)
1. Middleware ใน `server.py` → gen `X-Request-Id` + log timing
2. Auth middleware (`core/auth.py`): **fail-closed** — ทุก request ต้อง `x-auth-token` เว้นแต่อยู่ใน `_OPEN_PATHS`/`_OPEN_PREFIXES` (/, config, status, health, auth/*, /static, /shared, /api/shared, /ws). LAN/loopback peer IP bypass (`is_local_request`, spoof-resistant). **เพิ่ม endpoint sensitive ใหม่ = ปลอดภัยโดย default** (ไม่ต้องไป maintain denylist). middleware order (outer→inner): request_id → rate_limit → auth (rate_limit wrap auth เพื่อเห็น 401 → feed brute-force lockout)
3. `routers/chat.py:chat()` builds context (ดู Context Assembly ด้านล่าง)
4. Stream SSE: `chunk` (incremental) + `citations` + `reflection` + `cache_hit` + `active_learning` + `done`

### Context Assembly (stable-first → KV cache friendly)
1. **Response cache short-circuit** (Phase E) — ถ้า prompt ใกล้ thumbs-up เดิม (cosine ≥ 0.92) → bypass LLM, return cached
2. **Stable block** (เปลี่ยนน้อย, คาจ KV cache hit):
   - `prefs` — user preferences (ChromaDB)
   - `lessons` — auto-learned (ChromaDB)
   - `skills_md` — keyword-matched .md files (`load_skills_relevant`)
3. **Volatile block** (เปลี่ยนทุก turn):
   - `memory_ctx` — 3-tier recall (working + episodic + long_term)
   - `search_skills` — semantic top-3 จาก ChromaDB skills index
   - `vault_ctx` — Obsidian notes (ถ้า `obsidian_inject: true`)
   - `docs_ctx` — uploaded documents RAG (Phase B, `retrieve_chunks` + cache)
   - `home_tool_ctx` — real-time NAS data (auto-triggered โดย keyword ผ่าน `detect_home_tools`). tools: `disk`/`docker`/`wol`/`ping_pc`/**`ping_network`** (ping Router+NAS+PC จริงด้วย TCP check เมื่อถามถึง router/เครือข่าย). **ฉีดข้อมูลจริงแล้วต่อท้ายด้วย `_TOOL_GUARD`** เสมอ — ห้ามโมเดลแต่งผล/IP/คำสั่ง/output สมมติ (ดู Anti-hallucination ด้านล่าง)
   - `citations.format_inline_legend()` — `[1] [2] [3]` reference list
4. **Active learning instruction** (Phase C) — ถ้า prompt กำกวม → inject "ถ้าข้อมูลไม่พอ ให้ถามกลับ"

### Anti-hallucination (session 2026-05-31) — กันโมเดลเล็กกุข้อมูล real-time
โมเดล local (llama3) ชอบ "เล่า" ผล ping/ราคา/เว็บ ให้ดูจริง — กันด้วย **4 ชั้น**:
1. **system prompt guard** (`assistants/config.py:_NO_FABRICATION`) — ห้ามแต่งข้อมูล real-time ทุกผู้ช่วย + reword ขวัญ (เลิก "ไม่เคยปฏิเสธ"). guard นี้เข้า seed fine-tune ผ่าน `gen_seed_sft` อัตโนมัติ
2. **home_tool guard** (`utils/home_tools.py:_TOOL_GUARD` + `_join_with_guard`) — แนบกติกาท้ายข้อมูลที่ฉีด (ใกล้ attention กว่า system prompt) — ห้ามแต่ง IP/ping/คำสั่ง/output สมมติ, ถ้าไม่มีข้อมูลให้บอก "ยังไม่ได้เช็ค"
3. **quality gate** (`reasoning/learn_gate.py:should_auto_learn`) — กัน auto-learn บันทึก lesson จาก negative_feedback ("ไม่ใช่ละ") หรือ realtime_home_tool → กัน **feedback loop ปนเปื้อน** (คำตอบกุ→save เป็น lesson→recall→กุซ้ำ)
4. **ข้อมูลจริง** (`ping_network`) — ป้อนผล ping จริงแทนให้โมเดลเดา (วิธีที่ได้ผลที่สุด)
- ⚠️ **เพดาน:** ชั้น 1-3 = prompt-based ลด hallucination ได้แต่ไม่ 100% บนโมเดลเล็ก. ปิดสนิทต้องสถาปัตยกรรม **Agent mode** (รัน tool จริง โชว์ผลดิบ — โมเดลกุไม่ได้). ดู "สิ่งที่จะทำต่อ"

Ollama branch: context cap 2000 chars; trim history to <3000 tokens.

### LLM Routing
**ปุ่มแยกชัด — แต่ละ provider ไปตัวเดียวกันเสมอ (ไม่มี redirect ข้ามตัว)**
- `provider: "ollama"` → **Ollama เสมอ** (`OLLAMA_BASE_URL`, model `llama3`) — ไม่ redirect ไป LM Studio อีกต่อไป
- `provider: "lmstudio"` / `"lmstudio_web"` → LM Studio (รองรับ vision via `LMSTUDIO_VISION_MODEL`)
- `provider: "gemini"` / `"gemini_agent"` → Gemini (force ถ้ามี `image_b64` หรือ `agent_mode: true`)
- `provider: "claude"` / `"claude_agent"` → **Claude (Anthropic)** via official SDK — opt-in ด้วย `ANTHROPIC_API_KEY`. system prompt = cached block (`cache_control: ephemeral`, prefix-stable → ประหยัด cost), รองรับ vision, adaptive thinking (opt-in `CLAUDE_THINKING=adaptive`). branch อยู่**ก่อน** gemini catch-all ใน `stream_response` → Claude จัดการ vision ของตัวเอง. **auto router**: เปิดด้วย `CLAUDE_AUTO=reasoning` (เฉพาะคำถามยาก) หรือ `=all` (ทุก text) — ต้องมี `ANTHROPIC_API_KEY`, default `off` (ไม่แตะ). UI: ปุ่ม FAB ✨ Claude ใน `static/enhanced.js` (override `provider=claude` ผ่าน fetch intercept, exclusive กับ Agent)
- `provider: "auto"` → `reasoning/router.py:route()` decides (LM Studio ถ้า `LMSTUDIO_BASE_URL` ตั้ง, internet/vision → Gemini, ไม่งั้น Ollama)
- ⚠️ **ค่า address ทั้งหมดมาจาก `.env`** (`OLLAMA_BASE_URL`, `LMSTUDIO_BASE_URL`) — source ไม่ hardcode IP. default ของ `LMSTUDIO_BASE_URL` = `""` (ต้องตั้งใน `.env` ถ้าจะใช้ LM Studio/embeddings/vision/agent)
- Fallback: Gemini quota exhausted → local model + web search (LM Studio ถ้าตั้ง `LMSTUDIO_BASE_URL`, ไม่งั้น **Ollama**)

### Data Persistence
| Data | Storage |
|---|---|
| Chat history, sessions, pins, shares | `chat_history.db` (SQLite) |
| Feedback (thumbs up/down) | `chat_history.db` table `feedback` (Phase C) |
| Long-term + episodic memory | ChromaDB (external service) |
| Skills knowledge base | `skills/*.md` (file system) + `skills_db.json` + ChromaDB `skills_search` |
| Dream reports | `dream_reports/dream_YYYYMMDD_HHMMSS.json` |
| Document chunks (Phase B) | ChromaDB collection `documents` |
| Embedding cache (Phase E) | `data/embed_cache.db` (SQLite WAL, float32 blobs) |
| Response cache (Phase E) | `data/response_cache.db` (SQLite WAL) |

**Backups (DSM Task Scheduler รายวัน, user=root):**
- `scripts/db_backup.sh` — `chat_history.db` (sessions/messages/**feedback**/pins) + `data/*.db` → `sqlite3 .backup` (online, WAL-safe) → tar.gz เก็บ 7 วัน ที่ `$DB_BACKUP_DEST` (default `/volume1/homes/pawin/db_backups`). แนะนำ **03:30** (ก่อน chroma 04:00)
- `chroma_backup.sh` — ChromaDB volume `ui_chroma_data` (อยู่บน NAS, 04:00)

### Key Files

**Core**
- `server.py` — FastAPI entry + middleware + lifespan + router registration
- `core/observability.py` — request_id (contextvars), log_timing, structured logs (Phase F)
- `core/auth.py` — auth middleware (LAN bypass + token)
- `core/scheduler.py` — APScheduler — Dream cycle nightly 02:00

**Routers** (`routers/`): auth, chat, sessions, memory, skills, dream, vault, tools, system, agent, documents, feedback, sandbox

**LLM/AI**
- `utils/llm.py` — `stream_response()` + provider routing
- `reasoning/router.py` — model selection per query
- `reasoning/classifier.py` — complexity / needs_internet classifiers
- `reasoning/active_learning.py` — ambiguity detection (Phase C)
- `reasoning/learn_gate.py` — `should_auto_learn()` quality gate (กัน lesson ปนเปื้อน, session 2026-05-31)
- `assistants/config.py` — persona system prompts + `_NO_FABRICATION` guard
- `utils/home_tools.py` — `detect_home_tools`/`build_tool_context` + `ping_network` (ping จริง) + `_TOOL_GUARD`

**Memory & Skills**
- `memory/operations.py` — `recall()`, `remember()`, `teach()`, `push_working()` (unified API)
- `memory/store.py` — ChromaDB CRUD
- `memory/working.py` — in-memory session buffer
- `utils/memory.py` — legacy memory helpers + ChromaDB host detection
- `utils/skills.py` — skills_db.json CRUD, `search_skills()`, `cleanup_junk_skills()`
- `utils/skill_discovery.py` — auto-cluster prompts → propose new skills (Phase C)

**Phase B — Smart Retrieval**
- `utils/query_rewrite.py` — LMStudio rewrite + sub-queries + cache
- `utils/chunking.py` — smart paragraph/sentence/char chunker
- `utils/documents.py` — chunk + embed + ChromaDB `documents` collection
- `utils/citations.py` — `CitationTracker` accumulator

**Phase C — Self-improvement**
- `utils/reflection.py` — critic LLM post-stream (opt-in `reflect: true`)
- `utils/feedback.py` — thumbs up/down + memory confidence propagation
- `reasoning/active_learning.py` — heuristic prompt ambiguity check

**Phase D — Multi-modal Agent**
- `utils/code_sandbox.py` — Python in Docker / subprocess sandbox
- `utils/fs_tools.py` — whitelist-restricted FS ops
- `agents/tools.py` — tool registry (18 tools: web/wiki/memory/`run_python`/`fs_*` + home: `nas_disk`/`nas_docker`/`ping_network`/`ping_device`/`wol_pc`)

**Phase E — Performance**
- `utils/embed.py` — LMStudio embed + sqlite persistent cache + LRU
- `utils/retrieval_cache.py` — per-session in-memory (cosine ≥ 0.85)
- `utils/response_cache.py` — semantic Q&A cache (sqlite, cosine ≥ 0.92)
- `utils/context_budget.py` — filter low-score + token cap

### SSE Event Schema (`POST /api/chat`)
```jsonc
data: {"chunk": "text"}                              // streamed AI response
data: {"citations": [{id, type, source, snippet, score, url}]}   // Phase B
data: {"reflection": {score, verdict, issues, revised}}          // Phase C (opt-in)
data: {"active_learning": {should_ask, reason, signals}}         // Phase C
data: {"cache_hit": {similarity, source_prompt}}                 // Phase E
data: {"agent": {type, step, name, args, ...}}                   // tool-agent timeline
data: {"done": true, "model", "provider", "message_id",
       "request_id", "timings": {context_assembly, retrieval, llm_stream}}
```

Response headers: `X-Request-Id`, `X-Provider-Used`, `X-Model-Used`

### Memory Tiers
1. **Working** (in-mem ring buffer per session_id) — `memory/working.py`
2. **Episodic** — ChromaDB `memory_{assistant_slug}` (confidence-based, decays via Dream)
3. **Long-term** — ChromaDB `long_term_memory` (Dream-promoted themes only)

### Dream Cycle (02:00 Asia/Bangkok)
- Phase 1 Light: pull 24h memories
- Phase 2 REM: AI extracts themes (`Gemini` ถ้ามี, fallback Ollama)
- Phase 2.5 Decay: lower confidence of stale memories
- Phase 3 Deep: promote themes (count ≥ `PROMOTE_MIN_HITS`) → `skills_db.json` + `long_term_memory`
- Report: `dream_reports/dream_YYYYMMDD_HHMMSS.json`

### Caches (Phase E)
| Layer | Storage | TTL/Size | Threshold |
|---|---|---|---|
| Embed | sqlite WAL `data/embed_cache.db` | unlimited | exact text |
| Retrieval (per-session) | in-memory dict | 10min / 200 sessions | cosine ≥ 0.85 |
| Response (semantic) | sqlite WAL `data/response_cache.db` | 30 days / 1000 entries | cosine ≥ 0.92 |

Stats: `GET /api/cache/stats`

### Environment Variables
```env
# AI
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash
GEMINI_LIVE_MODEL=gemini-2.0-flash-exp
# Claude (Anthropic) — provider "claude"; ปล่อยว่าง=ปิด
ANTHROPIC_API_KEY=
CLAUDE_MODEL=claude-sonnet-4-6   # default คุ้ม; claude-opus-4-8 = ฉลาดสุด/แพงสุด, claude-haiku-4-5 = ถูกสุด
CLAUDE_MAX_TOKENS=4096           # เพดานคำตอบ = คุม cost
CLAUDE_THINKING=off            # off | adaptive (adaptive=คิดลึกขึ้น แต่ช้าลง)
CLAUDE_EFFORT=high             # low|medium|high|xhigh|max (ใช้คู่ adaptive)
CLAUDE_AUTO=off                # off | reasoning | all — ให้ provider=auto เลือก Claude (ต้องมี key)
OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_MODEL=llama3
OLLAMA_TIMEOUT=120
OLLAMA_NUM_CTX=4096
OLLAMA_EMBED_MODEL=nomic-embed-text   # ใช้เป็น fallback embeddings เมื่อ LM Studio ล่ม (ต้อง `ollama pull nomic-embed-text`)
LMSTUDIO_BASE_URL=          # opt-in: ปล่อยว่าง=ปิด (local หลักคือ Ollama). ใส่ค่าเฉพาะเมื่อรัน LM Studio จริง
LMSTUDIO_API_KEY=lmstudio   # ⚠️ LM Studio รุ่นใหม่บังคับ token — ใส่ให้ตรง (หรือปิด "Require API key" ใน LM Studio)
LMSTUDIO_CHAT_MODEL=google/gemma-4-e4b
LMSTUDIO_REASON_MODEL=deepseek/deepseek-r1-0528-qwen3-8b
LMSTUDIO_VISION_MODEL=llama-3.2-11b-vision-instruct
LMSTUDIO_EMBED_MODEL=text-embedding-nomic-embed-text-v1.5
LMSTUDIO_TIMEOUT=180
SHOW_THINKING=false

# Home Assistant
HA_URL=https://ha.pawinhome.com   # หรือ http://192.168.51.x:8123 ถ้าใช้ LAN เท่านั้น
HA_TOKEN=                          # Long-Lived Access Token (HA → Profile → Security)
HA_TIMEOUT=10                      # วินาที

# Auth + Network
UI_PASSWORD=
CORS_ORIGINS=
# Rate limiting (public exposure) — LAN/loopback bypass; ปิดด้วย false
RATE_LIMIT_ENABLED=true
RATE_LIMIT_RPM=120            # req/นาที/IP
AUTH_FAIL_MAX=8              # 401 กี่ครั้งใน window ก่อน lock IP
AUTH_FAIL_WINDOW=300        # วินาที
NAS_IP=192.168.51.49
NAS_USER=
NAS_PASS=
PC_IP=192.168.51.235
PC_MAC=

# Storage
DB_PATH=/app/chat_history.db
OBSIDIAN_VAULT_PATH=/vault
CHROMA_HOST=
NAS_DATA_PATH=./data

# Phase B-E feature toggles
QUERY_REWRITE_ENABLED=true
QUERY_REWRITE_TIMEOUT=8
REFLECTION_MODEL=
REFLECTION_THRESHOLD=0.7
EMBED_CACHE_ENABLED=true
EMBED_CACHE_DB=./data/embed_cache.db
RESPONSE_CACHE_ENABLED=true
RESPONSE_CACHE_THRESHOLD=0.92
RESPONSE_CACHE_TTL_DAYS=30
RESPONSE_CACHE_MAX=1000

# Phase D sandbox
CODE_SANDBOX_IMAGE=python:3.11-slim
CODE_SANDBOX_TIMEOUT=10
CODE_SANDBOX_MAX_TIMEOUT=60
CODE_SANDBOX_MEM=256m
CODE_SANDBOX_CPU=0.5
CODE_SANDBOX_ALLOW_LOCAL=false        # ⚠️ true = run on host without Docker
FS_TOOLS_ROOTS=                       # colon-separated; default ~/Desktop/ui/sandbox

# Phase F observability
LOG_LEVEL=INFO
LOG_FORMAT=plain                      # plain | json
LOG_FILE=server.log
```

### WebSocket: Voice Chat
`/ws/voice/{assistant_slug}` — bidirectional WS connecting to Gemini Live API. Client sends PCM `{type: "audio"}`, receives audio. Transcripts saved on turn completion.

## Coding Conventions
- All UI strings + comments **ภาษาไทย**; technical terms remain English
- Each feature area → own router file in `routers/`, registered in `server.py`
- Skills `.md` files in `skills/` should be registered in `skills_db.json` for semantic search (`load_skills_relevant()` reads .md directly as fallback)
- ChromaDB is optional — wrap calls with try/except + `is_memory_available()` check
- Auth test setup: `os.environ["UI_PASSWORD"] = ""` before importing `server`
- ⚠️ **DELETE `/api/skills/{id}`**: lebt `delete_file` query param (default false). ส่ง `?delete_file=true` ถ้าต้องลบ .md ด้วย — กัน data loss

## Known Quirks / Bugs
- ChromaDB uses `/api/v2/heartbeat` (not v1 — returns 410 Gone)
- Cloudflare tunnel returns 530 when origin down → check `cloudflared` container
- `static/skills/` (git) ≠ `data/skills/` (container mount) — copy needed after `git pull`
- **Container name**: docker-compose service `hybrid-ai` → actual container `ai-backend-1` (project name prefix). Use `docker restart ai-backend-1` not `hybrid-ai`
- `detect_home_tools` over-broad: `_DOCKER_KW` มี "รัน" → prompt ที่มีคำว่า "รัน" (เช่น "ทำไมรันผิด") trigger docker tool โดยไม่ตั้งใจ (low-harm, ฉีด context เกิน)
- โมเดลเล็ก (ollama llama3) **ไม่ทำตาม guard 100%** — งาน real-time ที่ต้องการความถูกต้องเป๊ะ ให้ใช้ Agent mode / Claude / Gemini
- **Auth lockout false-positive (แก้แล้ว 2026-06-02)**: React app โหลดหน้าแรกยิง API ไม่มี token → นับเป็น auth-fail → lock ก่อน login. แก้: นับเฉพาะ request ที่มี `x-auth-token` แต่ผิด (`core/ratelimit.py`)
- **Login modal loop (แก้แล้ว 2026-06-02)**: fetch monkey-patch เปิด login overlay ทุก 401 แม้มี token → แก้ให้เปิดเฉพาะ `!_authToken` (`static/enhanced.js`)
- **Provider UI**: เมื่อตั้ง `LMSTUDIO_BASE_URL` แล้ว React UI แสดงเฉพาะ 2 ปุ่ม (LMStudio + Gemini) — Ollama ถูกรวมเป็น local เดียวกัน

## Routing Architecture (2026-06-03)
**"auto" เป็น default เดียวทั้งโปรเจค — `reasoning/router.py` เป็น single source of truth**

```
ทุก request (chat / regenerate / dream / stream_response)
    ↓ provider = "auto"
    ↓
reasoning/router.py → LMStudio/DeepSeek → Gemini → Ollama (last resort)
```

- `utils/llm.py:stream_response()` default = `"auto"` (ไม่ใช่ `"ollama"` อีกต่อไป)
- `routers/chat.py:/api/regenerate` default = `"auto"`
- `utils/dream.py:rem_sleep/run_dream_cycle` default = `"auto"` + resolve ผ่าน router
- Gemini fallback → router เลือก local model (ไม่ hardcode ollama)
- **Ollama ปรากฏเฉพาะใน** `reasoning/router.py` fallback สุดท้าย + true cascade error ใน `llm.py`

## UX Features (enhanced.js) — session 2026-06-03
| Section | Feature | วิธีใช้ |
|---|---|---|
| §18 | 📎 File Manager | ปุ่มซ้ายล่าง — upload PDF/DOCX/XLSX/รูป, drag&drop, 📷 กล้อง |
| §19 | Copy AI message | hover AI bubble → ปุ่ม "คัดลอก" มุมขวาบน |
| §20 | ✏️ Edit + Resend | hover user bubble → แก้ข้อความ → ส่งใหม่ (truncate + resend) |
| §20 | 🗑️ Delete pair | hover user bubble → ลบ user+AI message คู่นั้น |
| §21 | Mobile keyboard | visualViewport resize → scroll textarea พ้น keyboard |

**File upload flow:**
- รูปภาพ → `/api/upload` → base64 → `hw_pending_image` → ส่งพร้อม chat
- เอกสาร (PDF/DOCX/XLSX) → `/api/documents/upload` (index ChromaDB) + pending context bar
- ขนาดสูงสุด 10 MB | รองรับ: `.pdf .docx .xlsx .xls .txt .md .csv .jpg .png .webp`
- **New API**: `DELETE /api/message/{db_id}` — ลบ message เดี่ยว (`utils/history.py:delete_message_by_id`)

## Internet Search / Classifier (2026-06-03)
`reasoning/classifier.py:needs_internet()` patterns เพิ่ม:
- ฝน/อากาศ: `ฝนจะตกไหม`, `วันนี้อากาศ`, `คืนนี้ฝน` ฯลฯ
- เน็ต: `เน็ตมาเลย`, `เช็คเน็ต`, `ไปดูในเน็ต`, `อินเทอร์เน็ต`, `search ให้`

`agents/orchestrator.py` เพิ่ม rule บังคับ:
- user พูด "ไปหาในเน็ต"/"เช็คเน็ต"/"search" → **ต้องเรียก `web_search` ทันที** ทั้งใน `AGENT_SYSTEM_HINT` และ `_REACT_SYSTEM`

## สิ่งที่จะทำต่อ (Next Steps)
**ลำดับความสำคัญ — งานที่ค้าง/ต่อยอดได้:**
1. ✅ **[สถาปัตยกรรม] wire home tools เข้า Agent registry**
2. ✅ **[Agent mode] provider-aware orchestrator (2026-06-01)**
3. ✅ **[detect_home_tools] แก้ "รัน" over-broad (2026-06-01)**
4. ✅ **[HA Agent] Home Assistant tools + ReAct (2026-06-02)**
5. ✅ **[UI] จัด toolbar (2026-06-02)**
6. ✅ **[Auth] แก้ lockout + login loop (2026-06-02)**
7. ✅ **[Dream] ใช้ DeepSeek R1 via auto routing (2026-06-03)**
8. ✅ **[LMStudio] เปลี่ยนเป็น DeepSeek-R1 (2026-06-02)**
9. ✅ **[Routing] "auto" default ทั้งโปรเจค — single source of truth (2026-06-03)**
10. ✅ **[UX] copy/edit/delete message + mobile keyboard (2026-06-03)**
11. ✅ **[Files] PDF/DOCX/XLSX upload + File Manager UI (2026-06-03)**
12. ✅ **[Classifier] เพิ่ม pattern เน็ต/อากาศ/ฝน + agent web_search rule (2026-06-03)**
13. 🔑 **ตั้ง `ANTHROPIC_API_KEY` ใน NAS `.env`** → recreate → ปุ่ม ✨ Claude โผล่อัตโนมัติ
14. 🏠 **ตั้ง `HA_URL` + `HA_TOKEN` ใน NAS `.env`** → recreate → Agent สั่ง HA ได้จริง
15. 💾 **ตั้ง DSM task `db_backup.sh`** รายวัน 03:30 (user=root)
16. 👍 **สะสม feedback** ~200-500 → fine-tune บน PC GPU (RTX 3060, `.235`)
17. 🧹 **(optional) quality gate ฝั่ง recall**

## ✅ Admin unlock endpoint (2026-06-01)
`POST /api/admin/unlock` — ล้าง auth-fail lockout สำหรับ IP ที่ระบุ (LAN/loopback เท่านั้น, 403 ถ้ามาจาก Cloudflare/public)
```bash
# ปลด lock IP ที่ระบุ (รันจาก LAN) — ต้องระบุ IP จริงของ client ไม่ใช่ NAS
curl -X POST http://192.168.51.49:8000/api/admin/unlock \
     -H "Content-Type: application/json" -d '{"ip": "CLIENT_IP"}'
# หา IP จาก log: docker logs ai-backend-1 2>&1 | grep "auth_fail\|lock" | tail -10
```

## ✅ Security hardening — scrutinize audit (2026-06-01, deployed+verified prod)
1. 🔴 **fail-closed auth** (`core/auth.py`)
2. 🟠 **middleware order** (`server.py`)
3. 🟠 **`/api/regenerate`** (`routers/chat.py`)
4. 🟡 **recall ranking** (`memory/store.py`)
5. 🟡 **LM Studio token** (`reasoning/router.py`)

**Deploy:** DSM Task Scheduler `deploy-hybrid-ai` → Run. HEAD ล่าสุด = `66c4f15`
