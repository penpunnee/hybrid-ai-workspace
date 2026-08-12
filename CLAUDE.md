# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## System Overview

**Hybrid AI Workspace** — a FastAPI backend serving a React SPA, deployed on a Synology NAS (DS923+) and exposed via Cloudflare Tunnel at `https://ai.pawinhome.com`.

Stack: Python FastAPI + React (pre-built static) + SQLite + ChromaDB + Ollama / LMStudio (local) + Gemini (cloud) + APScheduler.

⚠️ **`legacy/app.py` is a retired Streamlit UI (moved out of the image 2026-07-12) — not the active frontend.** The real UI is the React SPA in `static/`, served by `server.py`. `streamlit`/`streamlit-ace` + 15 orphan transitives ถูกตัดจาก requirements แล้ว — อย่า import อะไรจาก `legacy/`.

📖 **`CONTEXT.md`** — domain glossary (Session/Assistant/Skill vs Tool/Agent Mode/ReAct/Dream Promotion/etc.). Read it before touching memory, agent, or routing code — it disambiguates terms used loosely elsewhere.

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
CI (`.github/workflows/tests.yml`) มี 2 job — `tests/conftest.py` ชี้ host ไป `localhost` + ตั้ง `UI_PASSWORD=""` และ temp `DB_PATH` จึงรันได้โดยไม่ต้องมี ChromaDB/Ollama/NAS จริง:
- **`pytest`** (ด่านจริง) — `docker buildx build` แล้ว `docker run --rm hybrid-ai:ci pytest tests/ -q`
  **เทสรันในอิมเมจที่ deploy จริง** ไม่ใช่ในสภาพแวดล้อมที่ประกอบใหม่ใน runner (ปิดข้อ 22 · `e251cb6`)
  → python/เวอร์ชัน lib/system deps มาจาก Dockerfile ที่เดียว · ~2 นาที (cache `type=gha`)
- **`lint-and-js`** — ruff + `node --test tests/*.test.js` (ไม่ได้เทสพฤติกรรม Python ของ prod จึงไม่ต้องอยู่ในอิมเมจ)

**`.github/workflows/canary.yml`** (แยกไฟล์) — ตอบคนละคำถาม: *"ถ้าอัป lock วันนี้ จะพังไหม"*
จันทร์ 03:00 UTC + `workflow_dispatch` · python 3.11 → `pip install -r requirements.txt` → `scripts/deps_drift.py` → `pytest`
- **ไม่มี trigger `pull_request`** → แดงได้เต็มที่ (เห็นใน Actions + อีเมล) แต่บล็อก merge ไม่ได้
- ⚠️ **ห้ามเปลี่ยนไปใช้ `continue-on-error: true`** — flag นั้นทำให้ job รายงานเป็น `success` แม้ข้างในแดง (`tests/test_ci_matches_prod.py` จะแดง)
- ดู drift ล่าสุด: Actions → canary → หน้า Summary (`deps_drift.py` เขียนลง `GITHUB_STEP_SUMMARY`) · รันมือ: `gh workflow run canary.yml`

⚠️ **อย่าเปลี่ยน `pytest` job กลับไป `pip install -r requirements.txt` + `setup-python`** — `tests/test_ci_matches_prod.py` จะแดง เพราะเดิม CI ต่างจาก prod ทั้ง 3 แกน (python 3.12 vs 3.11.15 · lib ~34/121 ตัวไม่ตรง lock · ไม่มี poppler-utils) และ pin ใน `requirements.txt` **ไม่มีผลกับ prod เลย** (Dockerfile ลงจาก `requirements.lock` อย่างเดียว) — ไฟล์เทสนั้นตรึงไว้ด้วยว่า lock ต้องทำตาม spec ใน `requirements.txt` จริง

### Docker (NAS Deploy)
ทางเร็วสุด (ใช้ได้ตั้งแต่ 2026-06-12 — SSH key auth + sudo docker ไม่ต้องรหัส):
```bash
# จาก Mac: push แล้วสั่ง NAS pull + restart ในคำสั่งเดียว (โค้ด = volume mount ไม่ต้อง rebuild)
git push origin main && ssh -o BatchMode=yes pawin@192.168.51.49 \
  'cd /var/services/homes/pawin/ui && git fetch origin main && git reset --hard origin/main \
   && sudo -n /usr/local/bin/docker restart ai-backend-1'
```
- `static/` ไม่ต้อง restart เลย (เสิร์ฟจาก disk) · rebuild เฉพาะ requirements.txt/Dockerfile เปลี่ยน
- SSH ตัน (Auto Block) → fallback: DSM Task Scheduler `deploy-hybrid-ai`

แบบ shell บน NAS เอง:
```bash
cd /var/services/homes/pawin/ui
sudo git pull
sudo docker compose up -d hybrid-ai --force-recreate
docker compose logs hybrid-ai -f
```

⚠️ **Volume mount gotcha**: `skills/` ในโค้ด ไม่ใช่ที่ container อ่าน. Container อ่านจาก `${NAS_DATA_PATH}/skills` (default `./data/skills/`). ถ้าเพิ่ม .md ใหม่ใน git → ต้อง `cp skills/*.md data/skills/` ด้วย

⚠️ **แก้ `skills/*.md` แล้วต้อง resync `skills_db.json` — และต้องรัน "ในคอนเทนเนอร์" เท่านั้น:**
```bash
# dry-run ก่อนเสมอ (ไม่ใส่ --apply = แค่รายงาน)
ssh nas 'sudo -n /usr/local/bin/docker exec ai-backend-1 \
  sh -c "cd /app && python scripts/clean_skills_db.py --resync --apply"'
```
`SKILLS_DB_PATH` = `<repo>/skills_db.json` → **รันบน Mac หรือบน NAS host จะไปสร้าง/แก้ไฟล์คนละตัวกับ
ที่ prod ใช้ แล้วรายงานว่าสำเร็จ** (ตัวจริงคือ `data/skills_db.json` ที่ mount เป็น `/app/skills_db.json`
— บนเครื่อง dev ไม่มีไฟล์นี้เลย). ก่อน 2026-08-03 คำสั่งนี้ยัง**รันในคอนเทนเนอร์ไม่ได้**ด้วยซ้ำ
เพราะ `scripts/` เป็นโค้ดดิร์เดียวที่ไม่ได้ mount (เป็นสำเนาค้างจากตอน build ที่ไม่มีไฟล์นี้)

### Frontend
`static/` คือ vite build output จาก **React source ที่ `~/appscript.ui`** (git repo local แยก ไม่มี remote):
```bash
cd ~/appscript.ui
npm run build                 # tsc + vite → dist/
bash scripts/sync_static.sh   # copy index.html + assets/ เข้า static/ (ไม่แตะ overlay files)
npx vitest run utils/         # tests ของ chatflags ฯลฯ
```
- ⚠️ **ห้าม**ตั้ง vite `outDir` ชี้ `static/` ตรงๆ — `emptyOutDir` จะล้าง overlay files ทิ้ง (เคยเป็น config เดิม แก้แล้ว 2026-06-10)
- overlay `<script>` tags อยู่ใน `~/appscript.ui/index.html` (template) — **bump `?v=` ที่นั่น** แล้ว rebuild+sync (static/index.html เป็น generated file แล้ว อย่าแก้มือ)
- **ChatBox อยู่ใน React แล้ว (2026-06-10)**: mode pills/skills/agent pill/status dot อยู่ใน `app.tsx` ส่ง `tool_agent`/`plan_mode`/`obsidian_inject` ตรงใน body (`utils/chatflags.ts`) — `app.tsx` ตั้ง `window.__hwReactChatBox` ให้ enhanced.js ข้าม §22 overlay (โค้ด overlay คงไว้เป็น fallback สำหรับ bundle เก่า)

overlay แบบ vanilla (ไม่ต้อง build, ทำงานคู่ React bundle):
- `static/enhanced.js` — FAB (Claude/Agent/Search/Export/Vault), token counter, draft autosave, slash quick-prompts, hardware bar, **Dream stats applier** (เขียนทับ % ปลอมใน React ด้วยข้อมูลจริง), handle SSE เพิ่มเติม
- `static/dream_stats.js` — pure mapper `dreamCardValues(report)` → Light/REM/Deep จริง (dual-export node/browser, โหลดก่อน enhanced.js)
- `static/chat_intercept.js` — pure logic ของ fetch interceptor §22 (`applyChatBodyMutations` + `reconcileMode`, dual-export, โหลดก่อน enhanced.js) — กติกา Claude-ชนะ/plan_mode-flag อยู่ที่นี่ที่เดียว, test: `tests/chat_intercept.test.js` (`node --test`, รันใน CI ด้วย)
- ⚠️ React bundle minified แก้ตรงไม่ได้ → ค่า hardcode ใน bundle (เช่น sleep %) ต้องเขียนทับผ่าน enhanced.js overlay. หลังแก้ static → **hard refresh + bump `?v=` cache-bust** ใน `index.html`

## Architecture

### Request Flow (`/api/chat`)
1. Middleware ใน `server.py` → gen `X-Request-Id` + log timing
2. Auth middleware (`core/auth.py`): **fail-closed** — ทุก request ต้อง `x-auth-token` เว้นแต่อยู่ใน `_OPEN_PATHS`/`_OPEN_PREFIXES` (/, config, status, health, auth/*, /static, /shared, /api/shared, /ws). LAN/loopback peer IP bypass (`is_local_request`, spoof-resistant). **เพิ่ม endpoint sensitive ใหม่ = ปลอดภัยโดย default** (ไม่ต้องไป maintain denylist). middleware order (outer→inner): request_id → rate_limit → auth (rate_limit wrap auth เพื่อเห็น 401 → feed brute-force lockout)
   - ⚠️ **middleware ไม่แตะ WebSocket** (`BaseHTTPMiddleware` ลัดผ่าน scope ที่ไม่ใช่ `http`) → WS handler ต้องเรียก `core.auth.websocket_authorized(ws, token)` เองก่อน `accept()`. token มาทาง query param `?token=` เพราะ browser ตั้ง header บน WS ไม่ได้ (client: `~/appscript.ui/utils/voicelive.ts:voiceWsUrl`) — **เพิ่ม WS endpoint ใหม่ = ต้อง gate เอง ไม่ปลอดภัยโดย default เหมือนฝั่ง HTTP**
   - brute-force lockout นับ 401 เมื่อมี header `x-auth-token` **หรือ** path เป็น `/api/auth/login` (login ส่งรหัสใน body — เคยหลุดจากการนับทั้งหมด ดู backlog ข้อ 7)
3. `routers/chat.py:chat()` builds context (ดู Context Assembly ด้านล่าง)
4. Stream SSE: `chunk` (incremental) + `citations` + `reflection` + `cache_hit` + `active_learning` + `done`

### Context Assembly (stable-first → KV cache friendly)
1. **Response cache short-circuit** (Phase E) — ถ้า prompt ใกล้ thumbs-up เดิม (cosine ≥ 0.92) → bypass LLM, return cached
2. **Stable block** (เปลี่ยนน้อย, คาจ KV cache hit):
   - `prefs` — user preferences (ChromaDB)
   - `lessons` — auto-learned (ChromaDB)
   - `skills_md` — keyword-matched .md files (`load_skills_relevant`)
3. **Volatile block** (เปลี่ยนทุก turn):
   - `memory_ctx` — 4-tier recall (working + episodic + **user_facts** + long_term)
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
> ℹ️ **Ollama = dormant fallback only (2026-06-15)** — เลิกใช้เป็นตัวหลักแล้ว. local provider จริง = **LM Studio (qwen3.5-9b)** (`local_provider:lmstudio`). Ollama เหลือบทบาทแค่ safety net 3 จุด: routing fallback ตัวสุดท้าย, embeddings fallback ตอน LM Studio embed ล่ม (`OLLAMA_EMBED_MODEL`), dream fallback. คงไว้เพื่อ resilience — `ollama:true` ใน status = PC `.235` ต่อติด ไม่ได้แปลว่ามันรับงานจริง

**ปุ่มแยกชัด — แต่ละ provider ไปตัวเดียวกันเสมอ (ไม่มี redirect ข้ามตัว)**
- `provider: "ollama"` → **Ollama เสมอ** (`OLLAMA_BASE_URL`, model `llama3`) — ไม่ redirect ไป LM Studio อีกต่อไป
- `provider: "lmstudio"` / `"lmstudio_web"` → LM Studio (รองรับ vision via `LMSTUDIO_VISION_MODEL`)
- `provider: "gemini"` / `"gemini_agent"` → Gemini (force ถ้ามี `image_b64` หรือ `agent_mode: true`)
- `provider: "claude"` / `"claude_agent"` → **Claude (Anthropic)** via official SDK — opt-in ด้วย `ANTHROPIC_API_KEY`. system prompt = cached block (`cache_control: ephemeral`, prefix-stable → ประหยัด cost), รองรับ vision, adaptive thinking (opt-in `CLAUDE_THINKING=adaptive`). branch อยู่**ก่อน** gemini catch-all ใน `stream_response` → Claude จัดการ vision ของตัวเอง. **auto router**: เปิดด้วย `CLAUDE_AUTO=reasoning` (เฉพาะคำถามยาก) หรือ `=all` (ทุก text) — ต้องมี `ANTHROPIC_API_KEY`, default `off` (ไม่แตะ). UI: เลือกผ่าน **Model picker** ใน ChatBox (ดู section Model Picker) — *FAB ✨ Claude ใน enhanced.js ถูกตัดออกแล้ว 2026-06-15*
- `provider: "kimi"` → **Kimi K2.6 (Moonshot AI)** via OpenAI-compatible API (`KIMI_BASE_URL` default `https://api.moonshot.ai/v1`, model `kimi-k2.6`) — opt-in ด้วย `MOONSHOT_API_KEY`. `_stream_kimi()` ใน `utils/llm.py` (streaming, รองรับ vision MoonViT, ปิด thinking ผ่าน `extra_body={"thinking":{"type":"disabled"}}`)
- `provider: "auto"` → `reasoning/router.py:route()` decides (LM Studio ถ้า `LMSTUDIO_BASE_URL` ตั้ง, internet/vision → Gemini, ไม่งั้น Ollama)
- **Per-request model/thinking/effort (2026-06-15)**: `/api/chat` รับ `model` (→ `model_override`), `thinking` (bool, `None`=ใช้ default ของ provider), `effort` (`low|medium|high|xhigh|max`) แล้ว thread เข้า `stream_response` → `_stream_gemini`/`_stream_claude`/`_stream_kimi`/`_stream_ollama` (Gemini map effort→`thinking_budget`, Claude→`output_config.effort`+adaptive, Kimi→`thinking.type`). โมเดล local (Qwen) ปิด thinking ผ่าน API ไม่ได้จริง → toggle มีผลกับ cloud เท่านั้น
- ⚠️ **ค่า address ทั้งหมดมาจาก `.env`** (`OLLAMA_BASE_URL`, `LMSTUDIO_BASE_URL`) — source ไม่ hardcode IP. default ของ `LMSTUDIO_BASE_URL` = `""` (ต้องตั้งใน `.env` ถ้าจะใช้ LM Studio/embeddings/vision/agent)
- Fallback: Gemini quota exhausted → local model + web search (LM Studio ถ้าตั้ง `LMSTUDIO_BASE_URL`, ไม่งั้น **Ollama**)
- **Health (2026-06-10)**: `/api/status` รายงาน `lmstudio`/`lmstudio_message` (`check_lmstudio_health` ใน `utils/llm.py` — `/v1/models` + Bearer token, cache 30s) + `local_provider`/`local_ok` — local หลักจริงคือ **DeepSeek R1 via LM Studio** ดังนั้น `ollama:false` อย่างเดียวไม่ใช่ปัญหา ให้ดู `local_ok`. §22 status dot ใช้ `local_ok` (เขียว/แดง + tooltip, poll 60s)

### Data Persistence
| Data | Storage |
|---|---|
| Chat history, sessions, pins, shares | `chat_history.db` (SQLite) |
| Feedback (thumbs up/down) | `chat_history.db` table `feedback` (Phase C) |
| Long-term + episodic memory | ChromaDB (external service) |
| User facts (shared ทุก assistant) | ChromaDB `user_facts` — บันทึกจาก "จำไว้ว่า" / prefer / correction |
| Skills knowledge base | `skills/*.md` (file system) + `skills_db.json` + ChromaDB `skills_search` |
| Dream reports | `dream_reports/dream_YYYYMMDD_HHMMSS.json` |
| Document chunks (Phase B) | ChromaDB collection `documents` |
| Embedding cache (Phase E) | `data/embed_cache.db` (SQLite WAL, float32 blobs) |
| Response cache (Phase E) | `data/response_cache.db` (SQLite WAL) |

**Backups (สถานะจริง ยืนยัน 2026-07-12):**
- **DB backup = in-app job 03:30** (`core/scheduler.py` → `utils/db_backup.py`) — sqlite3 backup API (online, WAL-safe) ของ `chat_history.db` + cache dbs → tar.gz เก็บ 7 วันที่ `/app/db_backups` (mount → `ui/data/db_backups` บน NAS). เลือกฝังในแอปเพราะตั้ง DSM task จาก SSH ไม่ได้ (sudo จำกัดแค่ docker) — verified จริง: trigger ใน container ได้ archive 143KB
- `scripts/db_backup.sh` — ทางเลือกรันมือฝั่ง host (dest `/volume1/homes/pawin/db_backups`). ⚠️ แก้แล้ว 2026-07-12: เดิมหยิบ `ui/chat_history.db` (ไฟล์ค้างเก่า 12KB) แทน `ui/data/chat_history.db` (DB จริงที่ compose mount) → backup เปล่า
- **chroma backup = DSM task รายคืน 00:01** (ไม่ใช่ 04:00 ตามที่เคยเขียน) → `/volume1/homes/pawin/chroma_backups/` — ยืนยันมีไฟล์รายวันจริง

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
- `agents/tools.py` — tool registry (22 tools: web/wiki/memory/`run_python`/`fs_*` + home tools + `generate_image`)

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
2.5. **User Facts** — ChromaDB `user_facts` (shared ทุก assistant) — บันทึกผ่าน `memory/teach.py`, ค้นหาผ่าน `search_user_facts(min_score=0.6)`. inject ใน `recall()` ทุก turn ใต้ header `[ข้อมูลของคุณ]`
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
| Response bypass | — | — | `is_realtime_query()` — ping/disk/docker/ราคา/อากาศ/สถานะระบบ bypass เสมอ |

Stats: `GET /api/cache/stats`

### Environment Variables
```env
# AI
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash   # ⚠️ ห้ามใช้ gemini-2.5-pro บน free tier (quota limit=0 → 429 ทุก request, เจอจริง 2026-06-11)
GEMINI_SEARCH_MODEL=            # โมเดลเฉพาะ gemini_web_search() (grounding ให้ local/Claude/Kimi) — ว่าง = ใช้ GEMINI_MODEL; precedence: arg > env นี้ > GEMINI_MODEL (มีตั้งแต่ 7087f88, test ใน test_gemini_web_search.py)
GEMINI_LIVE_MODEL=gemini-3.1-flash-live-preview   # default อยู่ที่ `utils/voice.py:GEMINI_LIVE_MODEL_DEFAULT` ที่เดียว (ดูหัวข้อ "เสียงต้องเป็นคนเดิม") ⚠️ ห้ามสลับไปสาย native-audio โดยไม่ถอด `VOICE_TEMPERATURE` — วัดแล้วเสียงหายเงียบๆ 0 ไบต์ · gemini-2.0-flash-exp/gemini-live-2.0-flash-001 ถูกถอดจาก Live API แล้ว (1008 not found). เช็ค model ที่ใช้ได้: ListModels filter supportedGenerationMethods มี bidiGenerateContent
GEMINI_TTS_MODEL=gemini-2.5-flash-preview-tts   # ⚠️ ต้องเป็นสาย `*-tts` เท่านั้น (`utils/tts.py` เรียก generateContent ไม่ใช่ bidi) · ห้ามใส่สาย native-audio เด็ดขาด = 404 ทุก request · free tier 10 req/วัน/โมเดล · ทางเลือกที่วัดแล้วใช้ได้: gemini-3.1-flash-tts-preview · ดูหัวข้อ "🔊 /api/tts"
# Claude (Anthropic) — provider "claude"; ปล่อยว่าง=ปิด
ANTHROPIC_API_KEY=
CLAUDE_MODEL=claude-sonnet-4-6   # default คุ้ม; claude-opus-4-8 = ฉลาดสุด/แพงสุด, claude-haiku-4-5 = ถูกสุด
CLAUDE_MAX_TOKENS=4096           # เพดานคำตอบ = คุม cost
CLAUDE_THINKING=off            # off | adaptive (adaptive=คิดลึกขึ้น แต่ช้าลง)
CLAUDE_EFFORT=high             # low|medium|high|xhigh|max (ใช้คู่ adaptive)
CLAUDE_AUTO=off                # off | reasoning | all — ให้ provider=auto เลือก Claude (ต้องมี key)
# Kimi K2.6 (Moonshot AI) — provider "kimi"; ปล่อยว่าง=ปิด (โชว์ใน Model picker แบบ disabled)
MOONSHOT_API_KEY=
KIMI_BASE_URL=https://api.moonshot.ai/v1   # .cn สำหรับ endpoint จีน
KIMI_MODEL=kimi-k2.6
KIMI_TIMEOUT=180
OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_MODEL=llama3
OLLAMA_TIMEOUT=120
OLLAMA_NUM_CTX=4096
OLLAMA_EMBED_MODEL=nomic-embed-text   # ใช้เป็น fallback embeddings เมื่อ LM Studio ล่ม (ต้อง `ollama pull nomic-embed-text`)
LMSTUDIO_BASE_URL=          # opt-in: ปล่อยว่าง=ปิด (local หลักคือ Ollama). ใส่ค่าเฉพาะเมื่อรัน LM Studio จริง
LMSTUDIO_API_KEY=lmstudio   # ⚠️ LM Studio รุ่นใหม่บังคับ token — ใส่ให้ตรง (หรือปิด "Require API key" ใน LM Studio)
LMSTUDIO_CHAT_MODEL=qwen/qwen3.5-9b
LMSTUDIO_REASON_MODEL=qwen/qwen3.5-9b
LMSTUDIO_VISION_MODEL=qwen/qwen3.5-9b
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
SKILLS_SEARCH_MIN_SCORE=0.38          # พื้นคะแนนของ search_skills() (ปิด =off) — ดูหัวข้อท้ายไฟล์
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

**พิมพ์แทรกได้ระหว่างคุยด้วยเสียง** (2026-08-05) — client ส่ง `{type:"text", text}` →
`send_client_content(turn_complete=True)` · UI = กล่องพิมพ์ในหน้าจอ voice (`app.tsx`,
`VoiceController.sendText()`) · วัดกับ Gemini Live จริง: **ส่งตอนโมเดลกำลังพูดอยู่ →
`interrupted` แล้วตอบใหม่จริง 8.1 วิ · ส่งตอนเงียบ → 5.3 วิ** = ใช้ได้ทั้งสองจังหวะ
- ⚠️ กันข้อความว่าง — turn เปล่าจะไปตัดเสียงที่กำลังพูดทิ้งโดยไม่ได้อะไรกลับมา
- ⚠️ **เขียน probe ทดสอบ Live API ต้องวน `while` รอบ `session.receive()`** — มัน yield
  แค่ turn เดียวแล้วจบ generator · ใช้ `async for` ชั้นเดียวจะ "ไม่ได้ยิน" turn ถัดไป
  แล้วสรุปผิดว่าโมเดลเงียบ (พลาดมาแล้ว 2026-08-05 ทั้งที่ `send_loop` เตือนไว้ตรงๆ)

#### เสียงต้องเป็น "คนเดิม" ทุกครั้ง (2026-08-04 — user: "เหมือนสลับเป็นคนละคน")
**ทุกอย่างที่เกี่ยวกับเสียงอยู่ที่ `utils/voice.py` ที่เดียว** (`resolve_voice()` +
`build_live_config()` + `GEMINI_LIVE_MODEL_DEFAULT`) — `server.py`/`utils/tts.py`/`core/config.py`
ดึงจากที่นั่นทั้งหมด · เทส `tests/test_voice_consistency.py` (20)
- **ก่อนหน้านี้มี default 2 ที่ที่ไม่ตรงกันเงียบๆ ตั้งแต่ `369f18e` (2026-06-19)**:
  `core/config.py` = 3.1-flash-live (ตัวที่ prod ใช้จริง) ส่วน `utils/voice.py` ค้างที่
  2.5-native-audio-latest **พร้อมคอมเมนต์ที่เขียนว่า "ให้ default ตรงกับ core/config.py"**
  → ไฟล์ที่ชื่อตรงกับงานที่สุดคือไฟล์ที่ตายแล้ว (`VOICE_MAP` ก็ซ้ำ 2 ที่แบบเดียวกัน)
- ตรึงการสุ่มด้วย `seed=VOICE_SEED` + `temperature` + `enable_affective_dialog=False`
  → session ใหม่ (go_away regen / client retry) ฟังเหมือนเดิม
- ⚠️ **ค่าพวกนี้ขึ้นกับโมเดล — วัดจริงบน prod เคสละ 2 รอบ นับไบต์เสียง ไม่ใช่ "ไม่ throw"**

  | โมเดล | `temperature` | `seed` | `affective=True` |
  |---|---|---|---|
  | `2.5-native-audio-preview-12-2025` | 🔴 **0 ไบต์ เงียบสนิท ไม่ error** | ไม่ตรึง | ok |
  | `3.1-flash-live-preview` ← ใช้ตัวนี้ | ok | ✅ ตรึงได้ (67230,67230) | 🔴 APIError 1011 |

  ยืนยันด้วย `build_live_config()` ตัวจริงในคอนเทนเนอร์: 3 รอบได้ `[67202, 67202, 67202]`
- ⚠️ **ความเสี่ยงที่ยังไม่ปิด:** สาย 3.1-live **ไม่มี snapshot ปักวันที่ให้เลือก** (เช็ค
  ListModels แล้ว) → Google อัปเดต preview ทับได้ ถ้าเสียงเปลี่ยนอีกโดยเราไม่ได้แตะอะไร
  ให้สงสัยตัวนี้ก่อน · **ห้าม "แก้" ด้วยการถอยไป 2.5 โดยไม่รันตารางข้างบนใหม่**
- ℹ️ `utils/tts.py` (`/api/tts`) เป็นคนละเส้นกับเสียงคุยสด — แก้ที่นั่นไม่มีผลกับ Live API
  (เดิมเขียนว่า "ไม่เคยถูกเรียกเลยบน prod" ซึ่งจริง **แต่เหตุผลคือมันพัง** ดูหัวข้อถัดไป)

#### 🔊 `/api/tts` — ปุ่มอ่านออกเสียง (แก้ 2026-08-06 · เคยพังเงียบมาตลอด)
ปุ่ม 🔊 ทั้งใน composer (toggle อ่านคำตอบอัตโนมัติ) และบนข้อความ **ไม่เคยอ่านออกเสียงได้เลย** —
`/api/tts` ตอบ **HTTP 200** แต่ body เป็น error → frontend ขึ้น toast `❌ TTS: …` แล้วเงียบ
(ไม่มีใครสังเกตเพราะ endpoint นี้แทบไม่ถูกเรียก — และไม่ถูกเรียกเพราะมันพัง เป็นวงกลม)

**สองเส้นเสียงใช้โมเดลคนละสาย ห้ามสลับกัน:**

| ไฟล์ | เรียกด้วย | โมเดลที่ใช้ได้ |
|---|---|---|
| `utils/tts.py` | `generate_content()` | สาย **`*-tts`** |
| `utils/voice.py` | Live API (`bidiGenerateContent`) | สาย **`*-live`** / `native-audio` |

`GEMINI_TTS_MODEL` เคย default เป็น `gemini-2.5-flash-preview-native-audio-dialog` ซึ่งเป็น
**bidi-only** → ยัดเข้า `generate_content()` = 404 ทุก request · `tests/test_tts_model.py`
ตรึงกติกานี้ไว้แล้ว (ตรวจ *ต้นเหตุ* คือ "ห้ามเป็นสาย native-audio" ไม่ใช่ตรึงชื่อโมเดล)

⚠️ **ต้องมี prefix `Say:` เสมอ** — ส่งข้อความดิบสั้นๆ โมเดลจะตีความว่าเป็นคำถามแล้วตอบ
`400 Model tried to generate text, but it should only be used for TTS`
วัดจริงในคอนเทนเนอร์ (ไบต์ PCM @48kB/วิ) — **นับไบต์ ไม่ใช่แค่ "ไม่ throw"**:

| input | ผล |
|---|---|
| `2.5-flash-preview-native-audio-dialog` (ของเดิม) | **404, 404** |
| `สวัสดีค่ะ` ดิบ | **400** |
| `Say: สวัสดีค่ะ` | 48,526 (~1.01 วิ) = พอดีตัวข้อความ **prefix ไม่ถูกอ่าน** |
| ประโยคยาว ดิบ ×4 | 150,286 / 156,046 / 159,886 / 177,166 (3.13–3.69 วิ) |
| ประโยคยาว + `Say:` | 169,486 (3.53 วิ) = อยู่ในช่วงเดียวกัน |
| `gemini-3.1-flash-tts-preview` | 180,480 / 176,640 (ใช้ได้ เป็นทางเลือก) |
| `gemini-2.5-pro-preview-tts` | **429** (free tier ไม่เปิด) |

🔴 **เพดาน free tier = 10 requests/วัน/โมเดล** (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`,
`quotaValue: 10`) เดิม `generate_tts()` แบ่งข้อความเป็น sentence แล้วยิง **1 request ต่อ 1 ประโยค**
(parallel 4 workers) → คำตอบเดียว 5 ประโยค = กินครึ่งโควตาวัน ⇒ **ใช้ได้จริง ~2 คำตอบ/วัน**

✅ **แก้แล้ว 2026-08-06 — จัดกลุ่มประโยคเป็น chunk** (`_pack_sentences` + `_apply_chunk_cap`)
รวมประโยคจนใกล้ `TTS_MAX_CHARS` (2000) แล้วจำกัดที่ `TTS_MAX_CHUNKS` (3) · **1 chunk = 1 request**
- วัดจาก **คำตอบจริงบน prod 469 ข้อความ**: median 323 ตัวอักษร · p90 907 · p99 6,856 · max 9,610
  ⇒ **95.3% ของคำตอบกิน 1 request** (10 คำตอบ/วัน ตามเป้า) · 4.7% เกิน 2,000 → 2-3 request
  · 1.3% เกิน 6,000 → ชนเพดานแล้วถูกตัด
- นโยบายที่ user เคาะ: **ตัดทิ้ง** `chunks[:max_chunks]` แต่ **ต้อง `logger.warning` เสมอ**
  (ตรึงด้วย `test_ตัดทิ้งแล้วต้องมีร่องรอยใน_log` + กลุ่มควบคุม `test_ไม่ตัดก็ต้องไม่เตือน`)
- 🔴 **มีสองเส้นที่กินโควตา ไม่ใช่เส้นเดียว** — `/api/tts` (frontend เรียก) และ
  **`/api/tts/stream`** (`routers/system.py`) ที่ **แบ่งประโยคเองอีกชั้น** · audit รอบแรกมองข้าม
  เพราะนับ caller ใน bundle prod ได้ `api/tts` 1 ครั้ง / `api/tts/stream` **0 ครั้ง** แต่
  endpoint ยังเปิดอยู่ ⇒ ตอนนี้ทั้งคู่เรียก `_group_sentences` ตัวเดียวกันแล้ว
- ⚠️ **บั๊กที่เจอระหว่างทาง: `_split_sentences` จับไม่ได้เมื่อไม่มีเว้นวรรคหลัง `.`**
  (regex ต้องการ `(?<=[.!?…])\s+`) → ข้อความ 4,900 ตัวอักษรกลายเป็น "1 ประโยค" แล้วโดน
  `text[:2000]` **ตัดทิ้ง 2,900 ตัวอักษรเงียบๆ** · แก้โดย `_pack_sentences` หั่นแข็งเองเมื่อ
  ประโยคเดี่ยวยาวเกินเพดาน — เพดานทั้งหมดรวมมาที่ `TTS_MAX_CHARS` ที่เดียว
- 🔴 **สองข้อที่ CodeRabbit จับได้ใน PR #46 (เทสรอบแรกปล่อยผ่านทั้งคู่)**
  · `TTS_MAX_CHARS=0` ทำให้ `_pack_sentences` **วนไม่รู้จบ** (`s[:0]` ว่าง แล้ว `s[0:]` เท่าเดิม)
  — วัดจริงแล้วค้างจน SIGALRM ต้องตัด · **hang แย่กว่า crash** เพราะ worker ตายเงียบไม่มี traceback
  → กันสองชั้น: `_positive_env()` ถอยไปใช้ default พร้อม warning (ไม่ raise เพราะ
  `backend-watchdog` จะทำให้กลายเป็น **crashloop ทั้งระบบเพราะปุ่มลำโพงตัวเดียว`)
  \+ `_pack_sentences` เองโยน `ValueError` ไม่ว่าใครเรียก
  · `generate_tts` เป็นงาน **blocking ~3.5 วิ/chunk** ถูกเรียกตรงๆ ใน handler `async`
  ⇒ ทุกคำขอของทุกคนหยุดรอ → ห่อด้วย `run_in_threadpool` ทั้ง `/api/tts` และ `/api/tts/stream`
  (convention มีอยู่แล้วที่ `routers/skills.py:7`)
  · 🔧 **วิธีเทสว่า "ไม่ได้รันบน event loop" โดยไม่ผูกกับชื่อ thread ของ anyio:**
  ใน worker thread จะ **ไม่มี** running loop ⇒ `asyncio.get_running_loop()` ต้องโยน `RuntimeError`
- อาการเวลาโควตาหมด: toast `❌ TTS: 429 RESOURCE_EXHAUSTED`
- ⚠️ `_generate_one()` เดิมอ่าน `candidates[0].content.parts[0]` ตรงๆ → เจอ `content=None`
  (เกิดจริงตอน probe) พังเป็น `AttributeError` ที่อ่านไม่ออกว่าเกิดอะไร · ตอนนี้โยน
  `RuntimeError` พร้อม `finish_reason` และ **ไม่ปล่อยเสียง 0 ไบต์ผ่านเป็น WAV เปล่า**
- ⚠️ เทส live ต้อง opt-in ด้วย `TTS_LIVE_TEST=1` **ห้าม gate ด้วยแค่ `if GEMINI_API_KEY`** —
  เทสตัวอื่นในชุดเดียวกัน set คีย์ปลอมไว้ใน env ทำให้มันตื่นมายิงจริงด้วยคีย์ปลอมแล้วแดงมั่ว

#### 🔬 `AudioLevelMeter` — ตัววัด "เสียงเบาลง" (ชั่วคราว ถอดออกได้)
`utils/voice.py:AudioLevelMeter` วัด RMS/peak ของ PCM ที่ Gemini ส่งมา ตรงจุดที่รับ
**ก่อน**ส่งเข้าเบราว์เซอร์ (`server.py:send_loop`) → log ทุก 10 วินาทีของเสียง
- **จุดประสงค์เดียว: ตัด "เสียงเบาลง" ออกเป็นสองฝั่งให้ขาด**
  · ตัวเลขแบนราบ แต่ user ได้ยินว่าเบาลง → ปัญหาอยู่**ปลายทาง** (OS/AEC/Bluetooth HFP)
  · ตัวเลขลดลงตามเวลา → **Gemini ส่งเสียงเบาลงจริง** ไม่เกี่ยวกับหูฟัง/เครื่องเลย
- **baseline วัดจากเสียงจริงบน prod: พูดปกติ −15 ถึง −18 dBFS · peak ~24k–28k**
  (แกว่ง ~3 dB เป็นธรรมชาติของคำพูด — ต้องเทียบ *แนวโน้ม* ไม่ใช่ค่าเดี่ยว)
- meter ถูกสร้าง**นอกลูป reconnect** โดยตั้งใจ → นาฬิกาไม่รีเซ็ตตอน go_away นาทีที่ 10
  ซึ่งเป็นจุดที่สงสัยพอดี · รายงานทั้ง `audio_sec` และ `wall_sec` เพราะ user เล่าอาการ
  เป็นเวลานาฬิกา แต่ช่องว่างระหว่าง turn ทำให้สองค่าต่างกันมาก
- ปิดด้วย `VOICE_LEVEL_LOG=off` · ปรับหน้าต่างด้วย `VOICE_LEVEL_WINDOW_SEC`
- ดูผล: `docker exec ai-backend-1 sh -c "grep VoiceLevel /app/logs/server.log"`
- ⚠️ **ตัวเลขแบนราบไม่ได้แปลว่า "ไม่มีปัญหา"** แปลว่า "ปัญหาไม่ได้อยู่ก่อนจุดนี้" เท่านั้น

## Image Generation (2026-06-12)
⛔ **พักฟีเจอร์ไว้ (user ตัดสินใจ 2026-06-12)** — โค้ดทำงานถูกทั้งเส้น (verified prod) แต่ Google ไม่เปิดโมเดลสร้างรูป**ทุกตัว**ให้ free tier (429 `limit: 0` — gemini-2.5-flash-image, gemini-3.1-flash-image; imagen = paid-only). ใช้ได้เมื่อเปิด billing (~$0.04/รูป) — ไม่ต้องแก้โค้ด. ดู `skills/gemini-api-quota-sdk-gotchas.md`
- `utils/image_gen.py` — `generate_image(prompt)` ผ่าน Gemini (`IMAGE_GEN_MODEL`, default `gemini-2.5-flash-image`) → เซฟ PNG ที่ `${NAS_DATA_PATH}/gen_images/` เสิร์ฟผ่าน `/gen/<file>` (open path — <img> ส่ง auth header ไม่ได้)
- chat: `detect_image_request()` จับ "วาดรูป/สร้างภาพ/ออกแบบโลโก้" → short-circuit ก่อน teach/cache → ตอบ markdown `![..](/gen/xxx.png)` (persist ลง history เป็น text ปกติ)
- React `renderMarkdown` แปลง `![..](/path)` → `<img class="md-img">` (รับเฉพาะ path ภายใน กัน external)
- agent mode: tool `generate_image` ใน registry
- ⚠️ คำสั่งวาดรูปห้ามเข้า response cache / teach / memory — short-circuit อยู่ก่อนทุกอย่างแล้ว

## Coding Conventions
- All UI strings + comments **ภาษาไทย**; technical terms remain English
- ⚠️ **`async def` handler ห้ามเรียกงาน sync ที่ช้าตรงๆ** — ต้องผ่าน `run_in_threadpool()`
  (LLM / embedding / ChromaDB / OCR / sqlite) · handler ที่เป็น `def` ธรรมดาไม่ต้องทำ
  FastAPI โยนเข้า threadpool ให้เองอยู่แล้ว · **sync generator ที่ส่งให้ `StreamingResponse`
  ก็ปลอดภัยอยู่แล้ว** เพราะ starlette ห่อด้วย `iterate_in_threadpool()` — จุดที่ต้องระวังคือ
  โค้ดที่อยู่ **ก่อน** `return StreamingResponse(...)` (ดู `tests/test_chat_router_concurrency.py`)
- ⚠️ **รับ body ต้องมีเพดานก่อนอ่าน** — ใช้ `utils/http_limits.py`
  (`read_capped()` / `json_body_capped()`) ห้าม `await file.read()` / `await request.json()` ดิบ
  เพราะจะกิน RAM เต็มก้อนก่อนถูกปฏิเสธ (`ai-backend-1` มี `mem_limit: 2g` เป็นด่านสุดท้าย)
  - ✅ **บังคับใช้ครบ 27/27 เส้นแล้ว** (2026-08-06) · ค่าเพดานอยู่ที่
    `utils/http_limits.MAX_BODY_BYTES` ที่เดียว — **อย่าประกาศ 10 MB ซ้ำในไฟล์ตัวเอง**
    · `tests/test_body_cap_ratchet.py` จะแดงทันทีถ้ามี endpoint ใหม่อ่าน body ดิบ
- ⚠️ **เขียน `skills_db.json` ต้องผ่าน `save_skill()`/`cleanup_junk_skills()`** ซึ่งถือ `_db_lock`
  และเขียนแบบ atomic — dream cycle (APScheduler) กับเส้นแชทเขียนไฟล์เดียวกันคนละ thread
- Each feature area → own router file in `routers/`, registered in `server.py`
- Skills `.md` files in `skills/` should be registered in `skills_db.json` for semantic search (`load_skills_relevant()` reads .md directly as fallback)
- ChromaDB is optional — wrap calls with try/except + `is_memory_available()` check
- Auth test setup: `os.environ["UI_PASSWORD"] = ""` before importing `server`
- ⚠️ **DELETE `/api/skills/{id}`**: lebt `delete_file` query param (default false). ส่ง `?delete_file=true` ถ้าต้องลบ .md ด้วย — กัน data loss

## Known Quirks / Bugs
- **Memory contamination จากการเทส (เจอจริง 2026-06-11, แก้แล้ว 2026-07-13 — P2-9)**: ทุก Q&A ถูก save เข้า episodic ChromaDB (`memory_kwan` ฯลฯ) รวมถึงคำตอบกุ/error จากการ smoke test → ถูก recall กลับมาให้โมเดลตอบซ้ำแม้เปลี่ยน session/provider. **แก้ที่ต้นทาง**: ส่ง header `X-Test-Request: 1` ไปกับ `/api/chat` ตอนสโมกเทส → ข้าม `remember()`/`teach()`/auto-learn lesson thread ทั้งเส้น (`routers/chat.py:_is_test_request`) ไม่ปนเปื้อนตั้งแต่แรก. **แก้ย้อนหลัง** (ถ้าปนเปื้อนไปแล้วก่อนมี header นี้): `GET /api/admin/memory/{assistant}?q=...` (list/preview) + `DELETE /api/admin/memory/{assistant}/{id}` — LAN-only เหมือน `/api/admin/unlock`, ไม่ต้องต่อ ChromaDB ตรงอีกต่อไป
- **gemini_agent ≠ search_web()**: เส้น `gemini_agent` ใช้ Google Search grounding ในตัว Gemini (`types.Tool(google_search=...)` ใน `utils/llm.py`) — ส่วน `utils/websearch.py` (Google CSE+DDG) ใช้เฉพาะ route `lmstudio_web` + agent tool registry
- ChromaDB uses `/api/v2/heartbeat` (not v1 — returns 410 Gone)
- Cloudflare tunnel returns 530 when origin down → check `cloudflared` container
- `static/skills/` (git) ≠ `data/skills/` (container mount) — copy needed after `git pull`
- **Container name**: docker-compose service `hybrid-ai` → actual container `ai-backend-1` (project name prefix). Use `docker restart ai-backend-1` not `hybrid-ai`
- **`ai-backend-1` "หาย" ซ้ำ → แก้ถาวรแล้ว ✅ 2026-06-17**: อาการ 2 ครั้ง (2026-06-14/15, 2026-06-17) — Container Manager/docker daemon restart → chromadb/cloudflared กลับมาเอง แต่ `ai-backend-1` **ถูกลบหายจาก `docker ps -a`** (restart policy ช่วยไม่ได้เพราะ container ไม่เหลือ). **แก้:** (1) `restart: always` (เหมือน chromadb) (2) healthcheck (python urllib→`/api/config:8000`, start_period 90s) (3) **`backend-watchdog`** (service ใน compose, image `docker:cli`) loop ทุก 60s — ถ้า `ai-backend-1` ไม่ running → `docker compose up -d hybrid-ai` (idempotent). watchdog mount `/volume1/homes/pawin/ui` ที่ path เดียวกับ host → compose-in-container resolve bind-mount ถูก. **recovery path verified** (boot-race ครั้งเดียวกู้สำเร็จจริง ไม่ flap). กู้ด้วยมือถ้าจำเป็น: `cd /var/services/homes/pawin/ui && sudo docker compose up -d hybrid-ai`
- **Port: app = `8080`, ChromaDB = `8000` (เจอจริง 2026-06-15)**: docker-compose map `8080:8000` → verify prod ที่ `http://192.168.51.49:8080` (เช่น `/api/status`, `/api/models`). ⚠️ `192.168.51.49:8000` คือ **ChromaDB** (ตอบ 404 สำหรับ path ของแอป) — อย่าสับสน. (admin curl ตัวอย่างเก่าใน doc ที่ใช้ :8000 น่าจะคลาด — ใช้ :8080)
- `detect_home_tools` keyword precision: `_DOCKER_KW` ใช้ compound เท่านั้น (`"docker รัน"`, `"docker หยุดทำงาน"` ฯลฯ) — standalone `"รัน"` / `"หยุด"` / `"หยุดทำงาน"` ถูกตัดออกแล้ว (session 2026-06-03)
- โมเดลเล็ก (ollama llama3) **ไม่ทำตาม guard 100%** — งาน real-time ที่ต้องการความถูกต้องเป๊ะ ให้ใช้ Agent mode / Claude / Gemini
- **Auth lockout false-positive (แก้แล้ว 2026-06-02)**: React app โหลดหน้าแรกยิง API ไม่มี token → นับเป็น auth-fail → lock ก่อน login. แก้: นับเฉพาะ request ที่มี `x-auth-token` แต่ผิด (`core/ratelimit.py`)
- **Login modal loop (แก้แล้ว 2026-06-02)**: fetch monkey-patch เปิด login overlay ทุก 401 แม้มี token → แก้ให้เปิดเฉพาะ `!_authToken` (`static/enhanced.js`)
- **Provider UI**: เมื่อตั้ง `LMSTUDIO_BASE_URL` แล้ว React UI แสดงเฉพาะ 2 ปุ่ม (LMStudio + Gemini) — Ollama ถูกรวมเป็น local เดียวกัน
- **429 "limit: 0" ≠ quota หมดชั่วคราว (เจอจริง 3 เคส)**: limit=0 = โมเดลนั้นไม่เปิดให้ free tier เลย retry ไม่ช่วย (gemini-2.5-pro, โมเดล image gen ทุกตัว) — error message ฝั่งเราต้องแยก 2 เคสนี้ (ดู `utils/image_gen.py` + `skills/gemini-api-quota-sdk-gotchas.md`)
- **`[TOOL_RESULT]` echo จาก chat template (แก้แล้ว 2026-06-12)**: LM Studio render role `tool` ด้วย marker → โมเดลเลียนแบบขึ้นต้นคำตอบ agent → ตัดด้วย `agents/orchestrator.py:_MarkerFilter` (stateful, รอด marker แบ่งข้าม chunk — pattern เดียวกับ `<think>` ใน parser). ดู `skills/stream-template-marker-sanitization.md`
- **google-genai SDK: `Part.from_text(text=...)` keyword-only (แก้แล้ว 2026-06-12)**: ส่ง positional = TypeError → gemini agent พังทุก request ที่มี history (request แรกของ session รอดเพราะ history ว่าง — **smoke test ต้องเทส multi-turn ใน session เดิมด้วย**)
- **agent default = gemini**: `routers/chat.py` — `tool_agent:true` โดยไม่ส่ง provider → วิ่ง gemini agent; จะใช้ local agent ต้องส่ง `"provider":"lmstudio"` มาด้วย

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
| React | Stream status (2026-06-12) | "กำลังคิด… (2m 31s · ↓ 7.1k tokens)" ใต้ bubble ระหว่าง stream — `~/appscript.ui/utils/streamstatus.ts` (vitest) + wire 3 เส้น send/regenerate/edit-resend ใน `app.tsx`, tick 1s, token≈chars/4 |

**File upload flow:**
- รูปภาพ → `/api/upload` → base64 → `hw_pending_image` → ส่งพร้อม chat
- เอกสาร (PDF/DOCX/XLSX) → `/api/documents/upload` (index ChromaDB) + pending context bar
- ขนาดสูงสุด 10 MB | รองรับ: `.pdf .docx .xlsx .xls .txt .md .csv .jpg .png .webp`
- **New API**: `DELETE /api/message/{db_id}` — ลบ message เดี่ยว (`utils/history.py:delete_message_by_id`)

## §22 — Custom Chat Input Bar (ChatBox redesign overlay, session 2026-06-07/08)
> ✅ **ported เข้า React แล้ว (2026-06-10)** — ChatBox ตัวจริงอยู่ใน `~/appscript.ui/app.tsx` + `utils/chatflags.ts`. enhanced.js ข้าม section นี้เมื่อเจอ `window.__hwReactChatBox` (bundle ใหม่ตั้งให้). เนื้อหาด้านล่างคงไว้เป็น reference ของ overlay fallback
แปลง React `ChatBox.tsx` mockup (mode pills/agent switcher/skills/local-model picker) เป็น vanilla-JS overlay ทับ native input — สถาปัตยกรรม **"skin + proxy"**: React ยังเป็นเจ้าของ render/streaming/SSE ทั้งหมด เราแค่ตั้งค่า native input ผ่าน native value setter + `nativeForm.requestSubmit()` แล้วซ่อน form เดิม (`display:none`)

| Pill/Toggle | ผลจริงต่อ backend |
|---|---|
| **Code mode** | proxy คลิก `_agentBtn` → เปิด Agent Mode จริง (`tool_agent: true`) |
| **Ask mode** | proxy คลิก `_agentBtn` → ปิด Agent Mode |
| **Plan mode** | fetch interceptor เติม suffix `[ขอให้ช่วยวางแผนเป็นขั้นตอนสั้นๆ...]` ต่อท้าย `prompt` จริงก่อนส่ง |
| **Obsidian skill** | inject `obsidian_inject: true` |
| **Web Search skill** | inject `tool_agent: true` |
| Agent pill | แสดงผู้ช่วยจริงจาก `ctx.assistant`/`/api/config`, คลิกแล้วหาแล้วคลิกปุ่มสลับจริงใน sidebar (match by `textContent`) |
| Dream Cycle / TTS / ChromaDB | cosmetic ล้วน — ไม่มี hook ต่อ backend ต่อข้อความ |

**State persistence**: `localStorage` keys `hw_cb_mode`, `hw_cb_skills` (prefix `hw_cb_*`)
**Exposed for fetch interceptor**: `window.__hwChatBoxMode()`, `window.__hwChatBoxSkills()`
**Logic ที่เทสได้**: กติกา body-mutation (Claude ชนะ Agent/webSearch, plan→`plan_mode` flag) + pill reconcile แยกอยู่ใน `static/chat_intercept.js` (`window.hwChatIntercept`) — แก้กติกา = แก้ที่นั่น + รัน `node --test tests/chat_intercept.test.js`

⚠️ **Bug ที่เจอ+แก้แล้ว (chatbox3, 2026-06-08)**: ปุ่มส่งค้าง `disabled` หลังส่งข้อความแรก — `_disabledObs` (MutationObserver) sync `sendBtn.disabled` เฉพาะตอน native input เปลี่ยน attr `disabled` (เริ่ม/จบ stream); ตอนจบ stream `ta.value` ว่างพอดี → ตั้ง `disabled=true` ค้าง ส่วน `input` listener อัพเดทแค่ class `.on` ไม่ sync `.disabled` กลับ → พิมพ์ข้อความถัดไปกดส่งไม่ได้เลย. **แก้โดยให้ `input` listener sync `sendBtn.disabled = nativeInput.disabled || !ta.value.trim()` ทุกครั้งที่พิมพ์ด้วย**

## Model Picker (session 2026-06-15) — ✅ deployed prod `4f3a874`
Dropdown เลือกโมเดลในกล่องแชท (React `~/appscript.ui/app.tsx` + `utils/modelpicker.ts`+vitest) — **ลิสต์เดียว เลือกตัวไหน provider วิ่งตามตัวนั้น** แทนปุ่ม toggle Gemini/Llama เก่า (ถูกตัดออก)

| ส่วน | รายละเอียด |
|---|---|
| **`GET /api/models`** (`routers/system.py`) | คืน `{local, cloud}` แต่ละ item `{provider, model, label, available}`. local = ดึงสดจาก LM Studio/Ollama (`/v1/models`), cloud = curated list (`_CLOUD_MODELS`) + `available` ตามว่ามี key (`GEMINI_API_KEY`/`ANTHROPIC_API_KEY`/`MOONSHOT_API_KEY`) |
| **cloud models** | gemini-3.5-flash, gemini-3-flash-preview, gemini-3.1-flash-lite, gemini-2.5-flash, gemma-4-31b-it (ทั้งหมด provider `gemini` — Gemma วิ่งผ่าน Gemini API เส้นเดียวกัน), claude-opus-4-8/sonnet-4-6/haiku-4-5, kimi-k2.6 |
| **Effort slider** | 5 ระดับ `low/medium/high/xhigh/max` → ส่ง `effort` ใน body |
| **Thinking toggle** | on/off → ส่ง `thinking` (bool) — มีผลกับ cloud เท่านั้น (Qwen local ปิดผ่าน API ไม่ได้) |
| **body ที่ส่ง** | `provider` + `model` + `thinking` + `effort` ที่ 3 จุด (send/regenerate/edit-resend ผ่าน `buildModelBody`) |
| **default** | auto-select local model ตาม `config.ollama_model` ตอนโหลดครั้งแรก (pill กับ body ตรงกัน) |

- **Claude/Kimi โชว์ใน dropdown แต่ disabled** จนกว่าจะตั้ง `ANTHROPIC_API_KEY`/`MOONSHOT_API_KEY` ใน NAS `.env` (+recreate) — ไม่ต้องแก้โค้ด
- **UI cleanup พร้อมกัน**: ตัด cosmetic skills (Dream/TTS/ChromaDB) + Obsidian skill (ซ้ำ header) ใน chatbox + FAB **Export/Agent/Claude** จาก `enhanced.js`
  - ⚠️ ตัด `fab-agent` → `_agentMode` neutralize เป็น `false` ถาวร (tool_agent มาจาก React Code pill แทน). **ผลข้างเคียง: agent step-by-step timeline ของ overlay หายไป** — React ยังไม่ parse `agent` SSE events (งานต่อถ้าอยากได้คืน)
  - ตัด `fab-claude` → `_claudeMode=false` (เลือก Claude ผ่าน Model picker แทน)
- test: `tests/test_model_picker.py` (11), `utils/modelpicker.test.ts` (vitest)

## Internet Search / Classifier (2026-06-03)
`reasoning/classifier.py:needs_internet()` patterns เพิ่ม:
- ฝน/อากาศ: `ฝนจะตกไหม`, `วันนี้อากาศ`, `คืนนี้ฝน` ฯลฯ
- เน็ต: `เน็ตมาเลย`, `เช็คเน็ต`, `ไปดูในเน็ต`, `อินเทอร์เน็ต`, `search ให้`

`agents/orchestrator.py` เพิ่ม rule บังคับ:
- user พูด "ไปหาในเน็ต"/"เช็คเน็ต"/"search" → **ต้องเรียก `web_search` ทันที** ทั้งใน `AGENT_SYSTEM_HINT` และ `_REACT_SYSTEM`

## Web Search (2026-06-04)
`utils/websearch.py` อัปเดต:
- **Google Custom Search API** เป็น provider หลัก (ต้องตั้ง `GOOGLE_SEARCH_API_KEY` + `GOOGLE_SEARCH_CX`) → fallback DDG
- **Domain credibility scoring** — `_domain_score(url)` คืน (score, label):
  - 🟢 แหล่งทางการ (1.2x): `.go.th`, `.gov.`, `.edu.`, `wikipedia.org`, `bbc.com`, `reuters.com` ฯลฯ
  - 🔵 ทั่วไป (1.0x): เว็บทั่วไป
  - 🟡 ระวัง (0.7x): `blogspot`, `pantip.com`, `reddit.com`, `facebook.com` ฯลฯ
- คูณ `_rerank_score × domain_score` ก่อน inject → แหล่งทางการขึ้นก่อน
- inject คำสั่งสังเคราะห์ใน prompt: "เรียบเรียงด้วยภาษาของตัวเอง ห้ามคัดลอก"
- แจ้ง hint "ข้อมูลอาจขัดแย้ง" อัตโนมัติเมื่อมีแหล่ง low credibility

**ENV ที่ต้องตั้งบน NAS:**
```env
GOOGLE_SEARCH_API_KEY=AIza...
GOOGLE_SEARCH_CX=44c7c0b7c3c5049a2
WEB_SEARCH_MIN_SCORE=0.35   # พื้นคะแนนสัมบูรณ์ — ต่ำกว่านี้ไม่ฉีด/ไม่ cite (ปิดด้วย =off)
```

### ⚠️ พื้นคะแนนสัมบูรณ์ (`WEB_SEARCH_MIN_SCORE`, เพิ่ม 2026-08-03 · `b81d988`)
**จัดอันดับอย่างเดียวไม่พอ — "อันดับ 1 ของผลที่ห่วยทั้งหมด" ก็ยังห่วย**
เจอบน prod: ถาม *"Python เวอร์ชันเสถียรล่าสุด"* แล้วได้ **เว็บโป๊เป็น citation `[1]`** ขึ้นจอ
เพราะ `utils/websearch.py` ตัด `results[:top_k]` ตรงๆ ไม่เคยดูคะแนน (0.13 ก็ผ่าน)
- วัดจริงในคอนเทนเนอร์: ผลถูกต้อง **0.5955–0.8234** · ขยะ **0.1024–0.2393** → ช่องว่าง 0.36 = ที่ราบกว้าง
- **ผลที่ไม่มี `_rerank_score` ถูกตัดด้วย** (rerank ล้ม = พิสูจน์ไม่ได้ = ไม่ฉีด) — ปิดด้วย `=off` ถ้า embed ล่มยาว
- ⚠️ มี pipeline ค้นเว็บ **2 ชุด**: `utils/websearch.py:_web_search_impl` และ `agents/tools.py:_t_web_search`
  แก้เส้นหนึ่งต้องแก้อีกเส้นด้วย (`tests/test_websearch_min_score.py` คุมทั้งคู่)
- ⚠️ `safesearch="on"` **ส่งไป DDG จริง (มีเทสยืนยัน) แต่ DDG ไม่กรองให้** — พื้นคะแนนคือด่านที่สอง ไม่ใช่ของฟุ่มเฟือย

### ⚠️ พื้นคะแนนของ skills injection (`SKILLS_SEARCH_MIN_SCORE`, เพิ่ม 2026-08-04)
`search_skills()` เคยฉีด ChromaDB top-3 ดิบทุกเทิร์น — `utils/skills_search.py` คำนวณ
`distance` ใส่ dict ไว้แล้วแต่**ไม่มีใครตัดสินใจด้วยค่านั้น** · เคสที่เปิดบั๊ก: ถาม
*"openclaw คืออะไร"* → `openclaw.md` มาอันดับ 1 ถูกต้อง (sim 0.546) แต่ `mcp-server-export`
(0.296) กับ `project-architecture` (0.280) ถูกฉีดตามไปด้วยทุกครั้ง
- **ที่มาของ 0.38** — sweep กับ ground truth 110 คู่ที่คนมาร์คเอง (`data/skills_pairs.json`
  ของข้อ 21): 0.35 → P 0.438/R 0.636 · **0.38 → P 0.583/R 0.636** · 0.40 → P 0.667/R 0.545
  → 0.38 คือจุดที่ precision ขึ้นฟรีโดย recall ไม่ลด
- ⚠️ **ไม่มี "ที่ราบ" แบบ web search** — positive ต่ำสุด 0.142 · negative สูงสุด 0.430
  (negative 59/99 ตัวสูงกว่า positive อย่างน้อยหนึ่งตัว) → เกณฑ์นี้**ตัดหางล่างทิ้งเฉยๆ
  ไม่ได้แยกของถูก/ผิดออกจากกัน** · positive มีแค่ 11 ตัว **ห้ามจูนละเอียดกว่านี้**
- ⚠️ **ห้ามยืมเลข 0.35 ของ `SKILLS_FALLBACK_MIN_SCORE`/`WEB_SEARCH_MIN_SCORE`** — คนละ scorer
  คนละสเกล เลขใกล้กันเป็นเรื่องบังเอิญ
- `similarity` มาจาก `SkillsSearch._similarity()` ที่**อ่าน `hnsw:space` จริงจาก metadata**
  แล้วคืน `None` ถ้าไม่ใช่ cosine → fail-closed · prod เป็น cosine อยู่แล้ว ✅
- ⚠️ **`_space()` คืน 3 ค่า: `"cosine"` / `"l2"` / `None` (อ่านไม่ได้)** — แก้ 2026-08-04
  เดิมรวม "อ่านไม่ได้" เข้ากับ `"l2"` แล้ว log ERROR **ยืนยันว่า collection ผิด space
  พร้อมสั่งให้ลบทิ้งสร้างใหม่** · เกิดจริงบน prod 08-04 08:20:12 (2 ครั้ง) ทั้งที่
  `collection.id` วันนั้นกับวันนี้เป็น `56c1cde1…` ตัวเดียวกันและเป็น cosine มาตลอด
  → **การทำตามข้อความนั้น = ลบ index 22 รายการทิ้งเพื่อแก้ปัญหาที่ไม่มีอยู่**
  ตอนนี้ `space=None` → บอกให้เช็ค ChromaDB ก่อน และ **ไม่แนะนำคำสั่งที่ลบข้อมูล**
- ⚠️ **`get_skills_search()` ต้องถือ `_search_lock`** — วัดบน prod: ยิง 12 เธรดพร้อมกัน
  ได้ `SkillsSearch` **12 ตัว** (เส้นนี้อยู่ใน threadpool 40 slot ตั้งแต่ PR #23)
  และ **instance ที่ `available=False` ห้าม cache** — ChromaDB สะดุดตอน init ครั้งเดียว
  = ฉีด skill ไม่ได้ตลอดอายุโปรเซส · เทส `tests/test_skills_search_singleton.py` (10)
- วัดใหม่: `scripts/skills_floor_probe.py` (รันในคอนเทนเนอร์)

### 🔴 `rewrite_query()` ที่พึ่ง LLM ตายเงียบกับ Qwen3.5 (พิสูจน์ 2026-08-03)
ยิงตรงไป LM Studio: `finish_reason=length`, `content=''`, `reasoning_content='Thinking Process:...'`
ทั้งที่ `max_tokens` 200 **และ** 800 → เพิ่ม token ไม่ช่วย และปิด thinking ของ Qwen ผ่าน API ไม่ได้
→ `QUERY_REWRITE_ENABLED=true` เป็น no-op มาตั้งแต่เปลี่ยนโมเดล (2026-07-05)
**เส้นที่ทำงานจริงคือ `_fallback()`** ซึ่งตอนนี้เรียก `clean_query()` (กฎล้วน ไม่พึ่ง LLM)
ตัดคำสั่งงานออกจากคำค้น — ผลจริง: คำถามเดิมที่เคยได้เว็บโป๊ กลายเป็นได้
`'Python เวอร์ชันเสถียรล่าสุดคืออะไร'` ที่ 0.7706

## OCR + Document Summarization (2026-06-04)
### `utils/ocr.py` — OCR ด้วย Vision LLM
- **PDF scan** → `pdf2image` แปลง PNG ทีละหน้า → Gemini Vision อ่านข้อความ → fallback LMStudio Vision
- **รูปภาพ** (JPG/PNG/WEBP) → Gemini Vision โดยตรง
- auto-detect ใน upload: PDF ไม่มีข้อความ → OCR อัตโนมัติ
- รองรับ: `.pdf .jpg .jpeg .png .webp`
- ต้องการ: `poppler` (brew install poppler บน Mac, apt install poppler-utils บน NAS)

### `utils/summarize.py` — Map-Reduce Summarization
```
text ยาว → chunk_text() → MAP (สรุปแต่ละ chunk) → REDUCE (รวมเป็น final)
```
- **Model**: DeepSeek-R1 via LMStudio → fallback Gemini (ถ้า LMStudio ต่อไม่ได้)
- **summary_type**: `general` | `legal` | `financial` | `academic`
- chunk_size default = 3,000 chars

### Endpoints ใหม่
| Endpoint | ใช้ทำ |
|---|---|
| `POST /api/documents/ocr` | OCR PDF scan / รูปภาพ → คืน text |
| `POST /api/documents/summarize` | สรุปเอกสาร (Map-Reduce) รองรับ multipart + JSON |

**ตัวอย่าง:**
```bash
# OCR
curl -X POST http://NAS:8000/api/documents/ocr -F "file=@scan.pdf"
# สรุป
curl -X POST http://NAS:8000/api/documents/summarize -F "file=@report.pdf" -F "summary_type=general"
```

**⚠️ NAS ต้องติดตั้ง poppler:**
```bash
sudo apt-get install -y poppler-utils
```

## Self-Improvement / Fine-tune Pipeline (`scripts/`)
Full guide: **`FINETUNE_GUIDE.md`**. Goal: adapt the local Llama model (served via Ollama) toward ขวัญ's persona + the `_NO_FABRICATION` guard, without touching the base model used elsewhere.

```
curate (👍 / auto-score / synthetic seed) → train (QLoRA, PC RTX 3060) → eval gate (Claude judge) → deploy (Ollama) → serve
```
| Stage | Script | Notes |
|---|---|---|
| Seed (bootstrap, no 👍 yet) | `scripts/gen_seed_sft.py` | Synthetic curated pairs in ขวัญ's voice; system prompt pulled live from `assistants/config.py` so it can't drift |
| Export real feedback | `scripts/export_finetune.py` | Pulls 👍'd Q&A pairs from `chat_history.db` → JSONL chat format |
| Auto-score (RLAIF) | `scripts/auto_score.py` | Claude grades past answers (≥ threshold) → `data/finetune_auto.jsonl` (kept **separate** from human-labelled data — weaker signal) |
| Train | `scripts/train_qlora.py` (template, runs on PC GPU via WSL/CUDA) | 4-bit QLoRA, seq 2048, r=16, batch 2×accum 4 → GGUF `kwan-ft/`. OOM → drop `MAX_SEQ_LEN`/`BATCH_SIZE` |
| **Eval gate** | `scripts/eval_kwan.py` | Claude as pairwise judge (positions swapped to cancel bias) vs. baseline → win rate → exit 0=PASS/1=FAIL. **Never deploy on FAIL** — this is what prevents model collapse |
| Deploy | `ollama create kwan-ft -f Modelfile.kwan-ft` then point NAS `.env` `OLLAMA_MODEL=kwan-ft` | Keep the previous model around for rollback |
| Orchestration | `scripts/improve_loop.sh` | Phase 4: runs export → score → train → eval gate → deploy-if-PASS end to end on the GPU box |
| Live smoke test | `scripts/probe_live.sh` | End-to-end probe against `https://ai.pawinhome.com` after NAS/LMStudio changes |
| Cache benchmarking | `scripts/bench_cache.py` | Measures Phase E cache hit rate — `synthetic` (controlled repeat ratio) or `replay` (real prompts from `chat_history.db`) |

⚠️ **fine-tune ≠ memorization** — use RAG/memory for "remembering" things; fine-tune is for style/format/behavior that prompting can't fix. Try Modelfile persona → skills/RAG first; fine-tune is the last resort. Currently gated on accumulating ~200-500 👍 (`GET /api/feedback/stats`).

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
13. ✅ **[Memory] User Facts tier 2.5 — shared `user_facts` ChromaDB collection (2026-06-03)**
14. ✅ **[Cache] `is_realtime_query` bypass response cache สำหรับ real-time query (2026-06-03)**
15. ✅ **[home_tools] แก้ `_DOCKER_KW` "หยุด"/"หยุดทำงาน" over-broad → compound เท่านั้น (2026-06-03)**
16. ✅ **[Tests] score threshold + docker keyword + auth lockout test fixes (2026-06-03)**
17. ✅ **[Search] Google Custom Search + domain credibility scoring (2026-06-04)**
18. ✅ **[OCR] Gemini Vision OCR + auto-detect PDF scan (2026-06-04)**
19. ✅ **[Summarize] Map-Reduce DeepSeek-R1 + Gemini fallback (2026-06-04)**
20. ✅ **[scrutinize §22] แก้ครบทุก finding (2026-06-10)** — Major 1 webSearch hijack Claude, Major 2 plan suffix ปนเปื้อน DB → `plan_mode` flag, M3 overlay ฆ่า draft/token/slash + ghost draft, M4 stale nativeInput, m5 mode pill โกหก, #6 extract `chat_intercept.js` + JS tests เข้า CI
21. ✅ **[Status] LM Studio health check (2026-06-10)** — `local_ok`/`local_provider` ใน /api/status (local จริง = DeepSeek R1)
22. ✅ **[ChatBox → React] เลิกหนี้ skin+proxy (2026-06-10/11)** — port §22 เข้า `~/appscript.ui/app.tsx` + `utils/chatflags.ts`, build pipeline ปลอดภัย (dist + sync_static.sh), deployed `3b181ba`
23. 🧪 **ทดสอบ ChatBox ใหม่บน browser จริง** — Plan/Code pills, สลับผู้ช่วยจาก pill, status dot, Shift+Enter (ผม verify ได้แค่ระดับ curl/marker — ยังไม่เห็นจอจริง)
24. 👍 **สะสม feedback** ~200-500 → fine-tune บน PC GPU (RTX 3060, `.235`) — ปุ่ม 👍/👎 อยู่บน prod แล้ว, ดูยอด `GET /api/feedback/stats`
25. 🔐 **ตั้ง remote/backup ให้ `~/appscript.ui`** — React source เป็น git local-only ไม่มี remote, เครื่อง Mac พัง = source หาย (สำคัญขึ้นมากตอนนี้เพราะ ChatBox อยู่ในนั้นแล้ว)
26. 🔑 **ตั้ง `ANTHROPIC_API_KEY` ใน NAS `.env`** → recreate → ปุ่ม ✨ Claude โผล่อัตโนมัติ
27. 🏠 **ตั้ง `HA_URL` + `HA_TOKEN` ใน NAS `.env`** → recreate → Agent สั่ง HA ได้จริง
28. 💾 **ตั้ง DSM task `db_backup.sh`** รายวัน 03:30 (user=root)
29. 📦 **ติดตั้ง `poppler-utils` บน NAS** → รองรับ OCR PDF scan
30. 🧹 **(optional)** quality gate ฝั่ง recall · ทยอยย้าย overlay features ที่เหลือ (FAB Claude/Agent, File Manager §18) เข้า React · เคลียร์ WIP `components/` ใน appscript.ui (untracked, ไม่ได้ import — ใช้หรือลบ)
31. ✅ **[Agent] `[TOOL_RESULT]` echo + `Part.from_text` keyword-only (2026-06-12)** — `_MarkerFilter` กรอง marker ข้าม chunk + แก้ gemini agent พังเมื่อมี history (commits `db9eb9a`, `138172b`)
32. ✅ **[UX] stream status แบบ Claude Code (2026-06-12)** — verb+เวลา+↓tokens ใต้ bubble (`fb39dad`)
33. ⛔ **[Image Gen] พักไว้ — free tier limit=0 ทุกโมเดล** → ใช้ได้เมื่อเปิด billing (โค้ดพร้อมแล้ว ดู section Image Generation)
34. 🧪 **ขยาย classifier ค้นเว็บตามบริบท + Gemini grounding ทุก call** — เริ่มไว้ 2026-06-11 ยังเขียน test ไม่เสร็จ
35. ✅ **[Model Picker] dropdown เลือกโมเดล + effort + thinking + provider Kimi (2026-06-15)** — ดู section Model Picker, deployed `4f3a874`. **ค้าง: ใส่ `ANTHROPIC_API_KEY`/`MOONSHOT_API_KEY` ใน NAS `.env` → recreate** เพื่อปลดล็อก Claude/Kimi ใน dropdown
36. ✅ **[Agent] คืน agent timeline ใน React (2026-06-16)** — `utils/agentsteps.ts` parse `agent` SSE events → `AgentTimeline` ครบ 3 SSE loop, verified prod (thinking→tool_call→tool_result→answering)
37. ✅ **[Overlay→React] composer helpers + dream stats (2026-06-17, DEVLOG #6)** — token counter (`utils/tokencount.ts`) + draft autosave (`utils/draft.ts`) + slash prompts (`utils/slash.ts`) + dream stats card (`utils/dreamstats.ts`) ย้ายเข้า React, overlay เดิม gate ด้วย `__hwReactChatBox` (enhanced.js 4 guards). deployed `c3432cd`
38. ✅ **[Overlay→React] Home Panel (2026-06-17)** — System(RAM/ChromaDB/Skills)+NAS disk+Docker+PC ping+Wake PC/Ping NAS ย้ายเข้า React (`utils/homepanel.ts` pure view-models + 13 vitest → ปุ่ม 🏠 ใน header + modal ใน `app.tsx`). enhanced.js §14 gate ด้วย `__hwReactChatBox` + ลบปุ่ม `fab-home` overlay กัน trigger ซ้ำ. overlay bump `?v=20260617-home`. **Export เดิมพบว่า port เสร็จอยู่แล้ว** (`exportChat`+Ctrl+E+💾 — todo เก่าคลาด)

## 📌 session 2026-06-17/18 — File Manager §18 + กู้ prod + watchdog (สรุป)
- ✅ **File Manager §18 → React** (`843eca2` / source `02ac73d`): `utils/filemanager.ts` `classifyUpload`+11 vitest (89/89), ขยาย attach รองรับ PDF/DOCX/XLSX + index ChromaDB + ปุ่ม 📷 + drag&drop ลง composer, gate overlay §18, `?v=20260617-filemgr`. **→ port overlay→React ครบทุกตัวแล้ว**
- 🔴→✅ **prod ล่ม (`ai-backend-1` หายรอบ 2) + fix ถาวร** (`4536e57`): กู้กลับ + `restart:always` + healthcheck + `backend-watchdog` (loop 60s `compose up -d hybrid-ai`). recovery path verified จริง. ดู Known Quirks "ai-backend-1 หายซ้ำ"
- ⚠️ ค้าง verify ด้วยตา: File Manager drag&drop/กล้อง/index toast (verify แค่ build+test+prod-asset) · watchdog boot-race (recreate เกิน 1 ครั้งตอน boot ไม่ลูป — refine ด้วย `sleep 90` ก่อน loop แรกถ้าอยากเนียน)

## ⏭️ งานค้าง ณ 2026-08-05/06 (ล่าสุดสุด — อ่านอันนี้ก่อน)

### ▶️ เซสชันหน้าเริ่มตรงนี้ (อัปเดตท้ายเซสชัน 2026-08-12)

> **รอบ 08-12: UI polish 3 เรื่อง — ขอบขาว iPad · สถิติใต้คำตอบ · token จริงจาก provider**
> commits: frontend `543eb06`→`8639580`→`2ab7711` · backend `4139156`→`215a78a`→`1030ddd`
> ทุกตัว deployed + verified (md5 ตรง + probe จริงใน container) · เทส BE 1515 / FE 295 เขียว

**สิ่งที่เพิ่ม/แก้ (2026-08-12):**
- **ขอบขาวบน iPad ✅** — html/body ไม่เคยตั้งสีพื้น (ขาว default) มีแต่ div React `#060810`
  → Safari โชว์ขาวที่แถบสถานะ/rubber-band. แก้: `html,body{background:#060810;overscroll-behavior:none}`
  + `<meta name="theme-color">` (ปิด pull-to-refresh ไปด้วย — ตั้งใจ)
- **สถิติถาวรใต้คำตอบ** (`formatFinalStats`) — `↓ 191 tokens · 5.4s · 35.4 t/s · 15:52`
  ค้างหลัง stream จบ (เดิมหายทันที) + ข้อความในประวัติโชว์เวลา (`formatMsgTime`)
- **token จริงจาก provider** — `usage_sink` (out-param แบบ `sources_sink`) ทะลุ
  `stream_response` → done event มี `usage:{input_tokens,output_tokens}` ทั้ง /api/chat + /api/regenerate
  · มีตัวเลขจริง = ไม่มี `~` · ไม่รายงาน = ถอยไปประมาณ ~4 ตัวอักษร/token

**🔑 บั๊ก/gotcha ที่เจอรอบนี้ (อย่าโดนซ้ำ):**
- **container prod = UTC + `datetime.now()` naive → UI โชว์เวลาเพี้ยน +7 ชม. มาตลอด**
  (pinned modal/ผลค้นหา ไม่มีใครสังเกตเพราะไม่มีจุดเทียบ) — แก้: `save_message` ใช้
  `astimezone().isoformat()` (มี offset) · ฝั่ง UI สตริง naive เก่าให้ถือเป็น UTC เสมอ
- **OpenAI-compat `stream_options.include_usage`: chunk ท้ายมี `choices=[]`** —
  loop เดิม `chunk.choices[0]` จะ IndexError กลาง stream ทันทีที่เปิด ต้อง guard ทุกจุด
  · เซิร์ฟเวอร์เก่าไม่รู้จัก `stream_options` → retry แบบไม่ขอ (คำตอบมาก่อนตัวเลขเสมอ)
- **output_tokens ของ reasoning model นับ think tokens ที่ UI ซ่อนด้วย** — probe จริง:
  ตอบ "สวัสดี" คำเดียว = 841 tokens (qwen3.5-9b คิดใน `<think>`) ⇒ ตัวเลขโดดกว่า
  ข้อความบนจอ = ปกติ ไม่ใช่บั๊ก · t/s สะท้อนความเร็ว generate จริง
- prod อยู่หลัง auth — smoke test จากนอกทำไม่ได้ (ห้าม login แทน user) ให้
  `docker exec ai-backend-1 python -c "...stream_response(...usage_sink=sink)..."` แทน

---

> **รอบ 08-11 สร้าง "ขวัญอ่านนิยาย" ครบวงจรจนใช้จริง — user ฟังต่อเนื่อง 30+ นาทีจากมือถือ**
> commits: backend `ff5daa1`→`ad744c1`→`2d3fdd7`→`e8f033a`→`9b93700` · frontend `4dbaa5c`→`b8ced48`→`c9f0b93`
> ทุกตัว deployed + verified (md5 bundle ตรงถึงปลายทาง)

**ระบบอ่านนิยาย (เส้นทางเต็ม พิสูจน์ทุกข้อ):**
`PDF → pypdf+ซ่อม PUA (utils/thaipdf.py) → BookStore/BookmarkStore (utils/reader.py, data/reader.db)
→ next_block 600 ตัวอักษรตัดที่ช่องว่าง/\n → /ws/reader ป้อนให้ Gemini Live (เสียง Aoede เดิม)
→ BookReader (appscript.ui/utils/bookreader.ts) → ปุ่ม 📖 ในหน้าเสียง`
- **อ่านคำต่อคำ 100.0%** (difflib หลัง normalize) — พิสูจน์ 256/586-598 ตัวอักษร x3 ท่อนต่อเนื่อง
- **ที่คั่นหน้าเลื่อนเมื่ออ่านจบท่อนเท่านั้น** ⇒ กติกาที่สัญญากับ user: "ฟังซ้ำได้ ไม่มีวันข้ามเนื้อหา"
  (pause→resume ย้อนต้นท่อน · go_away กลางท่อน อ่านท่อนนั้นใหม่)
- **go_away โหมดอ่านมาที่ ~13 นาที** (ช้ากว่าโหมดคุย ~9) — เจอจริง 03:35:33 ระหว่าง user ฟัง
  ระบบต่อ session ใหม่เองสำเร็จ ไม่มี error
- `READER_PROMPT` ผ่านการจูน 4 รอบกับ user (เครื่องอ่าน 49.0วิ→กระชับ 39.5→นักพากย์ 61.6
  →**กระชับ+อารมณ์ผ่านน้ำเสียง 40.9 ✅**) — ⚠️ แก้เมื่อไหร่ต้องวัดใหม่ทั้ง 4 รอบ
  🔑 คำว่า "นักพากย์" คำเดียวลากช้าลง 56% · **สั่งสิ่งที่ห้ามทำชัดๆ ชนะการขอสิ่งที่อยากได้เพิ่ม**

**ทำไมเสียงขวัญอ่านได้ทั้งเล่ม:** Gemini TTS ติดเพดาน 10 req/วัน (363 ชม. = ~9.7 ปี)
แต่ **Live API เสียง Aoede เดียวกัน ไม่ชนโควตา** — และรับคำสั่ง "อ่านตามนี้ทุกคำ" ได้จริง 100%
· probe ที่ตัดสิน: เทียบ transcript กับต้นฉบับ ไม่ใช่ "ไม่ throw"

#### 🔴 อุบัติเหตุ prod ที่เกิดและปิดแล้วในรอบนี้
1. **โมเดลวนค้นเว็บจนไม่พูด** (08-10 12:37 — ค้น 5 ครั้งใน 53 วิ เสียง 0 ไบต์) → เพดาน
   `SEARCH_MAX_PER_TURN=2` + `SEARCH_LIMIT_REPLY` สั่งให้ตอบด้วยของที่มี (`2d3fdd7`)
   🔑 ใส่เบรก 3 ชั้นให้ auto-continue แล้ว**ลืมใส่ให้ tool ค้นทั้งที่ลูปโครงสร้างเดียวกัน**
   · probe ตอน verify ใช้คำถามค้นครั้งเดียวจบ เลยไม่เจอ — คำถามกว้างๆ ต่างหากที่ทำให้วน
2. เสียงคุย 1008 x2 ตอนเปิดหน้าเสียง+อ่านพร้อมกัน (สอง Live session) — client retry เอาอยู่
   ⚠️ **คำถามดีไซน์ค้าง: ตอนอ่านหนังสือควรพัก session คุย/ไมค์ไหม** ยังไม่ได้เคาะ

#### 📚 คลังความรู้เรื่องเสียง (วัดจริงทั้งหมด อย่าวัดซ้ำ)
- **เสียงที่ลองแล้ว 12 ตัว:** edge-tts ไทยแท้ 2 (Premwadee/Niwat — **rate ปรับได้ ไม่ตัดข้อความ**
  พิสูจน์ด้วยวิธีผ่าครึ่ง) · multilingual หญิง 5 (อ่านไทยได้แต่ Microsoft ไม่การันตี) ·
  MMS local 3 (FEMALEV1/V2/narrator — รันบนแมค 3.5-5x realtime) · **JaiTTS โคลนเสียง**
- **JaiTTS บน PC .235 ใช้งานได้:** RTF จริง **3.4-4.1x** เมื่อโหลดโมเดลครั้งเดียว
  (subprocess ต่อครั้ง = ค่าโหลด ~15-18 วิ กินหมด — วัดผิดมา 4 รอบเพราะแบบนั้น)
  · โคลนเสียง user สำเร็จ (ref ≤8 วิ ตาม README · ความยาว ref แทบไม่มีผลกับความเร็ว)
  · `speed=` ปรับได้ใน `jaitts_synth.load()` · `chunk_text` ของมัน**หั่นไทยไม่ได้**
  (หั่นตามจุดจบประโยคที่ไทยไม่มี → ก้อนเดียวเสมอ = ระเบิดเวลาถ้าข้อความยาว)
  · เสถียรภาพความดัง: `cfg_strength` 2.5→3.5 ลด swing 28→10.4 dB ฟรี · `nfe` 64 ช้าลงครึ่ง
- **เข้า PC .235:** ssh `penpu@192.168.51.235` — key อยู่ `C:\ProgramData\ssh\administrators_authorized_keys`
  (บัญชี admin → ไฟล์ `~/.ssh` ถูกเมิน!) · JaiTTS ที่ `C:\Users\penpu\JaiTTS-Easy` (+FFmpeg shared 7.1 ใน PATH)
- **โทนดริฟต์ระหว่างท่อน = ~4.4% (F0)** — A/B/C แล้ว: +คำกำกับต่อเนื่อง/temp0.3 ต่างกันแค่ noise
  ⇒ **ตัดสินใจไม่แก้อะไร** · ตัวที่ user ได้ยินจริงคือรอยต่อ go_away (ข้อจำกัด API)
  · ✅ **temp 0.3 บนโมเดล 3.1 เสียงไม่ดับ** (7.14 MB) — บันทึกไว้ ต่างจาก 2.5 ที่ดับ

#### 🐛 harness วัดผลพังเองซ้ำๆ — บทเรียนที่แพงที่สุดของรอบนี้
- A/B โทนดริฟต์พัง 2 รอบ: (1) ป้อนท่อนว่าง 12 ครั้ง (ไฟล์ 3000 ตัวอักษร เริ่ม pos 3000)
  (2) `break` กลาง generator ของ `session.receive()` → บัญชีเสียง/transcript ข้ามท่อนปน
  ให้ดริฟต์ 26.4% กับ 0.9% จากระบบเดียวกัน! 🔑 **ก่อนเชื่อการวัด ต้องเห็นข้อมูลสอดคล้อง
  ภายในตัวเอง** (transcript ตรง + ไบต์สมเหตุสมผล + ครบทุกท่อน พร้อมกัน) + assert input/output
- ตัววัด swing เลือกหน้าต่างตามความดัง → ตัวถูกวัด (compressor) เปลี่ยนสิ่งที่ถูกนับ
  → อันดับกลับด้าน · แก้: **ตรึง mask จากไฟล์ต้นฉบับแล้วใช้ mask เดียวกันวัดทุกไฟล์**
- วัดความเร็ว TTS: **วัดสองขนาดแล้วดูส่วนต่าง** — หักค่าคงที่ (โหลดโมเดล) โดยไม่ต้องรู้ค่ามัน

#### 🔧 gotchas ข้ามเครื่อง (โดนมาแล้วอย่าโดนซ้ำ)
- **Windows encoding โดน 5 ครั้งในวันเดียว:** setup.ps1 ไม่มี BOM → ใช้ `pwsh` · stdout cp1252
  → `sys.stdout.reconfigure(encoding="utf-8")` **ในสคริปต์** (ตั้งจากภายนอกพังทุกรอบ) ·
  ไลบรารีคนอื่นพิมพ์ไทยเองก็พัง · fixture ไทย/PUA ให้สร้างด้วย `chr(0x...)` (Edit ทำ PUA หายเงียบ 3 รอบ)
- **cmd.exe จำกัด 8,191 ตัวอักษร** — ส่งไฟล์ไบนารีไป PC: `ssh nas "cat>/tmp/f"` แล้ว `scp` ต่อใน LAN
  (scp/ProxyJump ผ่าน cloudflared ตรงๆ ใช้ไม่ได้)
- **`ping` ไม่ตอบ ≠ เครื่องปิด** (Windows บล็อก ICMP default) — เช็คพอร์ตบริการจริงแทน
- **แมคเครื่องนี้: Tailscale network extension บล็อก TCP ในวง LAN** (ICMP ผ่าน TCP ตาย
  แม้แต่ gateway) ⏳ ยังไม่แก้ — ใช้ `nas-cf` แทน · token Cloudflare Access หมดอายุเป็นระยะ
  → ให้ user เปิด browser login

#### ⏭️ ค้างไว้ทำต่อ (เรียงตามที่ควรหยิบ)
1. **Perfect World (21.2M ตัวอักษร · 363 ชม.):** ตัวซ่อมช่องว่างแทรก — วัดแล้ว:
   A1 ช่องว่างก่อนมาร์ก 200,045 · A2 หลังมาร์ก 377,533 · B แยกทีละตัวอักษร 26,293 ช่วง
   (สูตร ③ A1+B ทดสอบกับ user แล้วเสียงดีสุด · A2 เสี่ยงกลืนวรรคจริง ระวัง) ·
   mojibake หน้าปก · `จรงๆ` สระหายจาก pypdf เอง — ยังไม่มีตัวซ่อม
2. **เส้นอ่านไฟล์จากดิสก์ NAS** — 56.8 MB เกินเพดาน HTTP 5.7 เท่า ห้ามขยายเพดาน
   (RAM 2.5x/req + เทสตรึง 10MB) · `fs_tools` มี safe-root พร้อม · วางไฟล์ที่ sandbox
   แล้วให้ `/api/reader/add-from-disk` อ่านเอง
3. **อัป Xian Ni เต็มเล่ม** (4.6M ตัวอักษร ตอนนี้มีแค่ 150k แรกใน reader.db)
4. คำถามดีไซน์: อ่านหนังสือควรพัก session คุยไหม (สองเส้นพร้อมกัน = 1008 x2)
5. ⏳ แก้ Tailscale บล็อก LAN บนแมค (พิสูจน์ด้วย `Tailscale down` แล้วลอง nc — ยังไม่ได้ทำ)
6. เทสมือถือ: ปุ่ม 📖 บนมือถือจริง user ใช้แล้ว ✅ แต่ jitter/สะดุดช่วง go_away มีรายงาน
   "สะดุดนิดนึง" 1 ครั้ง — ถ้าบ่อยขึ้นค่อยลดขนาดท่อน 600→300 (ย้อนสั้นลง แลก overhead)

### 🎧 เซสชัน 2026-08-09 (บันทึกเดิม)

> **รอบนี้: user เทสเสียงจริงแล้วเจอ 3 บั๊กคนละเรื่องที่ดูเหมือนเรื่องเดียว**
> ปิดไป 2 · ค้าง 1 (รอ user เทส) · `d16b8b4` + `appscript.ui 4dbaa5c` deployed + verified prod

**อาการที่ user เล่ามา:** "ให้หาข้อมูลแล้วเล่านิยายแบบละเอียดตามที่เขาเขียน แต่มันสรุปมาให้
เล่าข้ามตอนไม่ต่อเนื่อง สั่งให้เรียบเรียงใหม่ก็เหมือนเดิม แล้วเสียงหายบ่อยขึ้น"
→ ฟังเหมือนบั๊กเดียว **จริงๆ เป็นคนละเรื่องกัน 3 อัน แก้อันเดียวไม่พอ**

| # | อาการ | ต้นเหตุจริง | สถานะ |
|---|---|---|---|
| 1 | เล่าไม่ตรงนิยาย / เรียบเรียงใหม่ก็เหมือนเดิม | **โหมดเสียงไม่มี `tools` เลยสักตัว** — ค้นไม่ได้ ได้แต่แต่ง | ✅ ปิด |
| 2 | เสียงหายบ่อยขึ้น + เล่าข้ามตอน | สวิตช์พูดแทรก**ค้างเปิดข้ามเซสชัน** → echo ตัด turn → client ล้าง buffer ~40 วิทิ้ง | ✅ ปิด |
| 3 | เสียงเดี๋ยวดังเดี๋ยวเบา เบาแล้วเบายาว | **ไม่ใช่ต้นทาง** (วัดแล้ว) — อยู่ชั้น OS/ลำโพง | ⏳ รอ user เทส |

#### 🔴 กับดักที่ใหญ่ที่สุดของรอบนี้: **ทางแก้ที่ "ถูกต้อง" ทำให้เสียงดับทั้งระบบ**

ข้อ 1 ทางแก้ที่ตรงที่สุดคือ `tools=[types.Tool(google_search=types.GoogleSearch())]`
ใส่แล้ว **เทสเขียวหมดทุกข้อ** · ยิงของจริงถึงรู้ว่าพัง — วัดซ้ำ 3 ครั้งได้ผลเดิม:

| tools ที่ส่งไป | ผลตอน `connect()` |
|---|---|
| `google_search` | 🔴 `APIError 1011 "exceeded your current quota"` **3/3** |
| `function_declarations` | ✅ ok (audio 51,870 ไบต์) |
| ไม่ส่งเลย (กลุ่มควบคุม) | ✅ ok (audio 229,442–269,762 ไบต์) |

กลุ่มควบคุมผ่านทั้ง**ก่อนและหลัง** เคสที่พัง ⇒ ไม่ใช่โควตาหมด แต่คือ **Google Search
grounding บนสาย Live ถูกกั้นที่ tier ที่คีย์นี้ไม่มี** แล้วรายงานออกมาเป็น "quota"
🔑 **1011 เกิดตอน `connect()` ไม่ใช่ตอนค้น** ⇒ merge ไป = ทุก session ตายตั้งแต่ยังไม่ทันพูด
(รูปแบบเดียวกับ `temperature` บน 2.5-native-audio เป๊ะ — ดูตารางใน `utils/voice.py`)
· มี ratchet กันคนกลับไปใช้: `test_does_not_use_the_tier_gated_google_search_tool`
· ⚠️ `gemini_web_search` (gemini-2.5-flash) **ใช้ได้ปกติบนคีย์เดียวกัน** — โดนกั้นเฉพาะสาย Live

**ทางที่ใช้แทน:** ประกาศ `function_declarations` (`search_web`) → `server.py`
`answer_tool_calls()` ค้นเองด้วย `gemini_web_search` → `session.send_tool_response()`
· ⚠️ **ต้องตอบทุก `function_call` ที่มันส่งมา** แม้ตัวที่เราไม่รับ ไม่งั้นโมเดลรอค้าง
= ผู้ใช้แยกไม่ออกจาก "เสียงหาย" · ค้นต้องผ่าน `to_thread` ไม่งั้น event loop ค้างพร้อมเสียง

**verify ด้วยของจริง ไม่ใช่ "ไม่ throw":** tool_calls 1 · โมเดลแต่งคำค้นเอง
`"เรื่องย่อ Perfect World Chen Dong พระเอกชื่ออะไร เริ่มเรื่องยังไง"` · ผลค้น 920 ตัวอักษร
· audio **1,959,842 ไบต์** (เสียงไม่ดับ) · คำตอบเป็นของจริง (สือเฮ่า · กระดูกสูงสุด ·
สืออี้ชิงกระดูก · เทพธิดาหลิว) · **กลุ่มควบคุม "2+2" → tool_calls 0** = ไม่เรียกมั่ว

#### 🔴 บทเรียนที่สอง: **กติกา "ห้ามแต่ง" ที่เขียนเป็นบัญชีรายชื่อ = ตะแกรงที่มีรู**

persona มี `[ห้ามแต่งข้อมูล — สำคัญมากที่สุด]` อยู่แล้วตั้งแต่แรก **และไม่ได้ช่วยเลย**
เพราะเขียนเป็น *บัญชีหัวข้อปิด*: ping/IP · หุ้น/คริปโต/ทอง · ผลค้นเว็บ · ไฟล์/ลิงก์ ·
real-time · เวลา/วันที่ · อากาศ · NAS — **"เนื้อเรื่องนิยาย" ไม่อยู่ในลิสต์**
⇒ โมเดล **ทำตามกติกาครบทุกข้อ แล้วยังแต่งนิยายได้สบายมาก**
· ของเดิมยังชี้ทางออกไปที่ "เปิด Agent mode" ซึ่ง**ในโหมดเสียงกดไม่ได้** = ทางตัน
🔑 รูปแบบ **"ตรวจในที่ที่นึกออกแล้วสรุปว่าครบ"** ซ้ำอีกครั้ง — คราวนี้อยู่ใน prompt เอง

**หลักฐานว่ามันแต่งจริง** (transcript `probe_item19` 08-09): ถูกขอ "เล่านิยายต่อ"
แล้วแต่ง **คนละเรื่องกัน 3 เรื่องใน 95 วินาที** (12:38:04 ป่าสมุนไพร · 12:38:28 นักสืบ
ไขคดี · 12:39:43 ฝึกวิชาประลอง) + ยืนยันรายละเอียดปลอมอย่างมั่นใจ *"ในอนิเมะก็อยู่
แถวๆ ตอนที่ 278 จริงๆ ด้วยค่ะ"* · 🔑 **สั่ง "เรียบเรียงใหม่" ไม่มีทางช่วย เพราะไม่มี
ต้นฉบับให้เรียบเรียง — คำสั่งนั้นแปลว่า "แต่งใหม่อีกรอบ" เสมอ**

#### 🔴 บทเรียนที่สาม: **สวิตช์ที่มีผลข้างเคียงมองไม่เห็น ห้ามจำค่า**

`app.tsx` จำสวิตช์พูดแทรกไว้ที่ `localStorage['hw_voice_bargein']` ⇒ user เปิดครั้งเดียว
ตอนเทส #61/#62 (08-07) แล้ว **ค้างเปิดข้ามทุก reload ทุกเซสชัน 2 วัน** โดยไม่มีอะไรเตือน

ผลลูกโซ่ที่ตามมา — และเป็นคำตอบของ "เสียงหายบ่อยขึ้น":
1. ไมค์ส่งตลอดแม้ขวัญพูดอยู่ → เสียงขวัญย้อนเข้าไมค์
2. ถูกถอดเป็นภาษาอื่น (`따따` · `lao ta ma` · `Dió, Dió…` · `Ja. Hunger, der kocht…`)
3. VAD จับได้ → ตัด turn → `interrupted` → client `flushPlayback()`
4. **ตอนเล่านิยายมีเสียงค้างในคิวถึง ~40 วินาที → หายทั้งก้อน** แล้วโมเดลไปต่อจากจุดที่
   มัน "คิดว่าเล่าไปแล้ว" = **เล่าข้ามตอน** (ข้อ 2 กับข้อ "ข้ามตอน" คือกลไกเดียวกัน)

**วัดโครงสร้าง turn ได้จาก `[VoiceLevel]`:** โมเดลส่งเสียง ~40 วิ ภายใน ~8 วิจริง
แล้วเงียบ 30–57 วิ (เครื่องกำลังเล่นของที่ค้าง) วนแบบนี้ทุก turn
⇒ **ทุกวินาทีที่ user ฟังอยู่ เครื่องถือเสียงที่ยังไม่ได้เล่นไว้ในมือ ~40 วินาที**

**แก้:** `utils/voicebargein.ts` — `initialBargeIn()` คืน `false` เสมอ + ล้างคีย์เก่าทิ้ง
**โมดูลนี้ไม่มีตัวเซฟเลยโดยตั้งใจ** มีเทสกลุ่มควบคุมที่แดงถ้ามีใครเติมตัวเซฟกลับมา
· user เคาะนโยบาย: *"ปิดตลอดนะ ถ้าจะพูดแทรกฉันถึงจะเปิด พูดเสร็จฉันก็ปิด"*
· ⚠️ **user รายงาน "เสียงหาย" เมื่อไหร่ ให้ถามสถานะสวิตช์นี้ก่อนไล่หาบั๊ก transport**

#### ✅ ข้อ 3 "เสียงเดี๋ยวดังเดี๋ยวเบา" — ตัดต้นทางออกได้แล้ว ยังไม่ต้องแก้โค้ด

`AudioLevelMeter` ที่เขียนไว้ 08-04 ตอบคำถามนี้ได้ตรงๆ (148 จุด ตลอด ~35 นาที 08-09):

| | ค่า |
|---|---|
| dBFS | -18.9 ถึง -16.3 → **เหวี่ยงรวมแค่ 2.6 dB** |
| peak ทุกหน้าต่าง | 25,853–29,894 (เต็มสเกล 32,767) |
| หน้าต่างที่ต่ำกว่า -19 dBFS | **0 จุด** |

+ ไล่เส้นทางเล่นเสียงทั้งเส้นใน `voicelive.ts` แล้ว **ไม่มี GainNode ไม่มีการคูณสเกลใดๆ**
worklet → `destination` ตรงๆ ⇒ **ปัญหาอยู่หลังจุดวัด = ชั้น OS/เบราว์เซอร์/ลำโพง**

ผู้ต้องสงสัยที่ **มีบันทึกไว้แล้ว** ไม่ต้องเดาใหม่ — vault
`wiki/concepts/browser-echo-cancellation-ios.md`: *"เรียก `getUserMedia()` แล้ว routing
เปลี่ยน → เสียงอาจไปออกลำโพงสนทนา (earpiece) แทนลำโพงนอก · สลับกลับต้อง pause/mute-unmute
ซึ่งไม่ใช่ API ที่ควบคุมได้"* ⇒ ตรงกับ "เบาแล้วเบายาว"
**ให้ user เทสแยก 3 ทางก่อนแตะโค้ด:** (1) ตอนเบากด mute→unmute ดังกลับไหม = earpiece
(2) เสียบหูฟังแล้วหายไหม = OS ล้วน (3) ปิดสวิตช์พูดแทรกแล้วลดลงไหม = AEC ducking

#### 🐛 เทสของผมเองผ่านฟรี 2 ข้อ (จำไว้ก่อนเขียน ratchet รอบหน้า)

`assert "ห้ามแต่ง" in prompt` **เขียวทันทีทั้งที่ยังไม่ได้แก้อะไร** เพราะไปแมตช์
`[ห้ามแต่งข้อมูล]` ของเดิมที่คนละความหมาย · `assert "ค้น" in prompt` ก็ผ่านฟรีเพราะ
persona มีคำว่า "ผลค้นเว็บ" อยู่แล้ว
🔑 **ratchet ที่อ้างอิงคำทั่วไปในข้อความยาวๆ ผ่านฟรีเกือบเสมอ** — ต้องผูกกับ
เครื่องหมายเฉพาะที่เพิ่งเติม (`[ค้นก่อนตอบ]` · `ห้ามแต่งเนื้อเรื่อง`)
· ที่สำคัญกว่านั้น: **การไปดูว่าทำไมมันผ่าน คือสิ่งที่เปิดเผยบั๊ก "บัญชีหัวข้อปิด" ข้างบน**

#### 🔧 บทเรียนเครื่องมือรอบนี้

- **`docker exec` ต้องใส่ `-e PYTHONPATH=/app`** — `-w /app` อย่างเดียวไม่พอ
  probe ตายด้วย `ModuleNotFoundError: No module named 'utils'` ทั้งที่ cwd ถูก
- **`timeout` ไม่มีบน macOS** (zsh: command not found) — ใช้ `ssh -o ConnectTimeout`
  หรือ `asyncio.wait_for` แทน
- **นับ occurrence ในบันเดิลที่เสิร์ฟแล้วต้องเปิดดูบริบท** — `grep -c hw_voice_bargein`
  ได้ `1` ดูเหมือนโค้ดเก่ายังอยู่ ที่จริงคือ `removeItem` ที่ตั้งใจไว้
- **docs commit ของเซสชันก่อนถูก squash-merge เป็น PR #63 ไปแล้ว** local จึงถือของซ้ำ
  → `git rebase origin/main` ตรวจ patch-id แล้วข้ามให้เอง (`skipped previously applied`)
  ⚠️ **rebase แล้ว base เปลี่ยน ต้องรัน pytest ซ้ำก่อน push**

#### ⏭️ ค้างจากรอบนี้

1. ⏳ **เสียงเดี๋ยวดังเดี๋ยวเบา — รอผลเทส 3 ทางข้างบนจาก user** (ต้นทางถูกตัดออกแล้ว)
2. ⚪ **ตั้งภาษาไทยให้ตัวถอดเสียง** — `types.AudioTranscriptionConfig` มีฟิลด์
   `language_codes` / `language_hints` อยู่แล้ว **แก้บรรทัดเดียว** · ตอนนี้เสียงไทยของ user
   ถูกถอดเป็นเกาหลี/สเปน/เยอรมัน/จีน/เวียดนาม (ยืนยันแล้ว: แถวเวียดนาม 12:56:48
   แปลตรงกับประโยคไทยที่ user พูดจริง) · user ยังไม่เคาะ ไม่ได้ทำ
3. ⚪ **`interrupted` ยังล้าง buffer ทั้งก้อน** — ปิดความเสี่ยงด้วยการไม่จำค่าสวิตช์แล้ว
   แต่กลไกยังอยู่ ถ้าเปิดสวิตช์เมื่อไหร่ก็เจออีก · ทางเลือกที่คิดไว้: ล้างเฉพาะส่วนที่ยัง
   ไม่เล่นจริง หรือหน่วงสั้นๆ ก่อน flush กัน barge-in ผี · **user ยังไม่สั่งทำ**
4. ⚪ **ไม่มีป้ายบอกว่า "กำลังค้น"** — ค้นใช้ ~5 วิ ในโหมดเสียงคือเงียบ 5 วิ ยังไม่มี event
   บอก UI · รอดูว่า user รำคาญไหมก่อนค่อยเติม
5. 🐛 **partial transcript หายตอน go_away regen** — `user_transcript`/`ai_transcript`
   เป็นตัวแปรใน `send_loop` พอ regen แล้วข้อความ turn ที่ค้างถูกทิ้ง ไม่เคยเซฟ (เจอระหว่างอ่านโค้ด ยังไม่แก้)

#### ✅ ของเดิมที่รอบนี้ยืนยันว่ายังดีอยู่

- **go_away handling ทำงานจริง** — 08-09 เจอ 3 ครั้ง (12:42:07 · 12:51:09 · 13:00:10
  ห่างกัน 9m02s / 9m01s เป๊ะ) ต่อ session ใหม่สำเร็จทุกครั้ง **ไม่มี 1008 เลยสักครั้ง**
  ⇒ #58/#62 ปิดงานได้จริง (เทียบ 08-02→08-05 ที่มี 1008 ถึง 7 ครั้ง)
- **ระดับเสียงจากต้นทางนิ่ง** -17.6 dBFS ตลอด 25 นาที ⇒ "เสียงเบาลงเมื่อคุยนาน" ไม่ใช่ปัญหา

---

### 🎨 เซสชัน 2026-08-07 — ธีม (PR #47)

> **รอบนี้ปิด "ธีม" ที่ค้างมาหลายเซสชัน — PR #47 merged + deployed + verified prod**
> เอกสารเจตนาอยู่ที่ **`DESIGN.md`** (ใหม่ 300+ บรรทัด) — **อ่านก่อนแตะสีทุกครั้ง**
> user เคาะเอง: ตัวตนขวัญ = ชมพู · 3 โหมด ChatBox = teal เฉดเดียวแยกด้วย glyph · error แหกกฎได้

**กติกา:** สีทำหน้าที่ทุกตัวล็อก **L=0.75 C=0.13 หมุนแค่ hue** — ตาอ่าน L/C เป็น
"ลำดับความสำคัญ" แต่อ่าน H เป็น "หมวดหมู่" · ของเดิมหมุนทั้งสามแกนพร้อมกัน
(48 สี · L ห่าง 0.85 · C ต่าง 20 เท่า) ตาจึงได้สัญญาณขัดกัน
· 6 บทบาท: teal โหมด · ฟ้า dream · ม่วง memory · ชมพู ตัวตน · ส้ม เตือน · เขียว สำเร็จ
· **งบเฉดเต็ม 6/6 — ฟีเจอร์รอบหน้าห้ามหยิบเฉดที่ 7 ต้องมาแก้ `DESIGN.md` ก่อน**
· ต้นทาง = `~/appscript.ui/utils/palette.ts` · ตัวนับ = `utils/palette.test.ts`

#### 🔴 บทเรียนแม่บทของรอบนี้: **"ตรวจในไวยากรณ์/ที่ที่นึกออก แล้วสรุปว่าครบ"** — พลาด **7 ชั้น**

| ชั้น | ผมประกาศว่าเสร็จ ทั้งที่เหลือ | เจอเพราะ |
|---|---|---|
| 1 | นับแค่ `#hex` ได้ 48 — มี `rgba()` อีก **201 ครั้ง/39 ค่า** (ต่ำไป ~4 เท่า) | นับ rgba ก่อนลงมือ |
| 2 | สแกนแค่ `app.tsx` — `utils/homepanel.ts` ถือ hex เอง 3 ตัว **หลุดเข้า bundle ทั้งที่เทสเขียว** | วัด bundle ที่ build จริง |
| 3 | ไล่แต่ค่าสี — เหลือ Tailwind class 19 จุด **คนละไวยากรณ์ · bundle ก็เขียวเพราะเก็บเป็นชื่อคลาส** | `getComputedStyle()` บนหน้าจริง |
| 4 | `static/enhanced.js` **ไม่ได้ build จาก `~/appscript.ui`** จึงอยู่นอกสายตาทุกเทส (37 ค่า/192 ครั้ง) | CodeRabbit จับ |
| 5 | regex จับแค่ `color:'rgba(...)'` **ตรงๆ** — ของจริงเป็น ternary **หลุด 17 จุด** · สคริปต์ที่ใช้แก้ก็ใช้ regex เดียวกัน **เทสจึงยืนยันผลงานตัวเอง** | วัด prod หลัง deploy |
| 6 | ด่าน alpha สแกนแค่ `app.tsx` — `enhanced.js` มีอีก **27 จุด** | ไล่ทุกไฟล์ที่ shipped |
| 7 | ด่าน alpha จับแค่สีที่ **มี** alpha — **สีตันที่มืดเกินไปก็อ่านไม่ออก** (`#2A2A40` = **1.14:1**) | วัด prod อีกรอบ |

🔑 **"ของที่ shipped ไม่ได้แปลว่าถูก build"**
🔑 **ratchet ถามว่า "สีอยู่ในระบบไหม" — ไม่เคยถามว่า "อ่านออกไหม"** เป็นคนละคำถามกันตั้งแต่ต้น

#### 🔴 บทเรียนที่ใหญ่ที่สุด: **md5 ตรง ≠ deploy ถึงผู้ใช้**
แก้สีใน `static/enhanced.js` ไป **4 PR ติด (#47 #50 #51) โดยไม่เคย bump `?v=`**
`cf-cache-status: HIT` · `max-age=14400` ⇒ **ที่ปลายทางเป็นของเก่าทั้งหมด**
ผม verify ด้วย md5 มา 4 รอบ และ 3 รอบแรก "ผ่าน" เพราะ **bundle ของ vite เปลี่ยนชื่อไฟล์ทุก build
จึง cache-bust ตัวเอง** แต่ `enhanced.js` ชื่อคงที่ไม่มีอะไรบังคับให้ cache หมดอายุ
✅ **ปิดถาวรแล้ว:** `utils/overlayversion.test.ts` ผูก `?v=` เข้ากับ md5 ของไฟล์จริง
— แก้ไฟล์แล้วลืม bump = เทสแดงทันที

#### 🐛 probe ที่ผมเขียนเองพังอีก 3 จุด (จำไว้ก่อนเขียน probe รอบหน้า)
1. **`\bcolor\s*:` จับ `background-color:` ด้วย** (`\b` อยู่ระหว่าง `-` กับ `c`) → false positive เพียบ
2. **ค้น hex ตัวพิมพ์เล็กอย่างเดียว** → `#2A2A40` ไม่เจอ เกือบทิ้งทั้งที่แย่ที่สุดในชุด
3. **ไต่บรรพบุรุษไม่เจอพื้นทึบแล้วคืนสีโปร่งใสเป็นสีทึบ** → ปุ่ม Stop ได้ `ratio 1.00`
   แบบผิดๆ · **`1.00` เป๊ะคือเบาะแสว่า probe พัง** ไม่ใช่ว่า UI พัง

#### 🔴 บทเรียนที่สอง: **ratchet ตอบได้แค่ "สีอยู่ในระบบไหม" ไม่ได้ตอบ "เอาไปวางคู่กับอะไร"**
- **ตัวอักษรขาวบนพื้นสีบทบาท** — L=0.75 = สีสว่าง · ขาวบนชมพู = **2.36:1**
  (ของเดิม indigo 4.47:1 ก็เฉียดอยู่แล้ว) → ใช้ `#060810` = 8.47:1 · แก้ 10 จุด
- **`#020617` (C=0.041) คือพื้นดำของ login overlay** ถูกตีเป็น "ม่วง" ทั้งแผ่น
  → ยกเกณฑ์ "เทาอมสี" เป็น **C < 0.08**
- **bulk pass กลืนปลายมืดของ gradient** ปุ่ม login (สองสต็อปสีเดียวกัน = แบนราบ)
  → การแก้เจาะจงต้องทำ **หลัง** bulk เสมอ

#### 🔴 บทเรียนที่สาม (ใหญ่สุด): **PR #32 วัด contrast กลับด้านมาตลอด**
`contrast.ts` เขียนไว้ว่า "พื้นเข้มสุด `#060810` = เกณฑ์ที่เข้มที่สุด" — **ผิด**
ตัวอักษรในแอปนี้เป็น**สีอ่อนบนพื้นเข้ม** → พื้นที่ *สว่างขึ้น* ต่างหากที่ทำให้ contrast **ลดลง**
⇒ วัดบน prod จริงแบบไล่บรรพบุรุษ + ผสม alpha: **ตกเกณฑ์ 194 จุด** (alpha 183 · สีตัน 11)
ทั้งที่ `contrast.test.ts` เขียวมาตลอด · `gray-700` ได้ 4.67 บน APP_BG แต่ **3.73 ของจริง**
**แก้แล้ว:** เพิ่ม `PANEL_BG = #192232` (พื้นสว่างสุดที่มีตัวอักษรวางอยู่จริง วัดจาก prod)
· ยกแกนเทา 500/600/700 → `#939ba8`/`#8992a1`/`#808999` (5.69/5.08/4.53 บนพื้นแผง)
· **ถอด alpha ออกจากสีตัวอักษร 28 จุด** — 🔑 **alpha คุมค่า contrast ไม่ได้**
  เพราะผลขึ้นกับว่าไปวางทับอะไร ⇒ ตรวจแบบ static ไม่ได้เลย · สีตันตรวจได้ก่อน render
  (พื้นหลัง/ขอบยังใช้ alpha ได้ — เปลี่ยนเฉพาะ `color:`)

#### 🔒 XSS ที่ CodeRabbit จับได้ (ของจริง)
`renderMarkdown` escape แค่ `& < >` · `<`/`>` กัน "เปิดแท็กใหม่" ได้ แต่**ไม่กันการแตกออกจาก
attribute เดิม**: `![" onerror=alert(1) x="](/a)` → `<img … alt="" onerror=alert(1) …>`
เส้นทางถึงจริง: คำตอบ AI ที่มีเนื้อหาจากเว็บ/เอกสารที่คนอื่นควบคุม (มีทั้ง web search + vault RAG)
· แก้: escape `"` `'` ด้วย · **เทสต้องตรวจด้วย DOM parser ไม่ใช่ regex** —
ข้อความ `onerror=` ที่อยู่ *ข้างใน* ค่า attribute ที่ escape แล้วนั้นไม่มีพิษ regex แยกไม่ได้

#### ⚙️ กระบวนการที่ได้ผลรอบนี้ (ทำซ้ำได้)
1. เขียน `DESIGN.md` **ก่อน**แตะโค้ด — ให้ user เคาะเฉพาะจุดที่โค้ดตอบไม่ได้
2. เขียน ratchet ให้ **แดงก่อน** แล้วค่อยแก้ · mutation ทุกด่าน
3. **วัดที่ปลายทางที่ผู้ใช้เห็น** (`getComputedStyle` บนหน้าจริง) — ด่านนี้จับได้ทุกอย่าง
   ที่เทสกับ bundle จับไม่ได้ · ⚠️ probe วัดพื้น `linear-gradient` ไม่ได้ ต้องคำนวณมือ
4. verify deploy ด้วย **md5 ของไฟล์จริง** — ⚠️ path คือ `/static/...` ไม่ใช่ `/...`
   (ยิงผิดได้ 401 มา 24 ไบต์ แล้วเกือบสรุปว่า deploy ไม่ขึ้น)

#### ✅ ผลวัดปิดงาน (prod จริง 2026-08-07 · 605 element)

| | ก่อน | หลัง |
|---|---|---|
| ตกเกณฑ์เพราะ alpha | 183 | **0** |
| ตกเกณฑ์แบบสีตัน | 11 | **0** |
| ตกเกณฑ์บนพื้น gradient | วัดไม่ได้เลย | **0** (ตรวจ 206 จุด) |
| สีเก่านอกระบบ (ตัวอักษร) | 48 สี | **0** |

วิธีวัดที่เชื่อได้ (เก็บไว้ใช้ซ้ำ): ไล่ `getComputedStyle` ทุก element ที่มีข้อความ →
ไต่บรรพบุรุษหาพื้นทึบ + ผสม alpha ทุกชั้น (ถ้าไม่เจอให้ผสมกับพื้นแอป) →
ถ้าพื้นเป็น gradient ให้เทียบกับ **stop ที่แย่ที่สุด** ไม่ใช่ค่าเฉลี่ย

### 🎙️ เซสชัน 2026-08-07/08 (ต่อ) — งานเสียง PR #58–#62

**เริ่มจาก user ถามเรื่องสี แล้วลามมาถึงระบบเสียง** — ทุกข้อ merged + deployed + verified

| PR | เรื่อง | ต้นเหตุ |
|---|---|---|
| #58 | WebSocket ไม่ retry ตอนปิดแบบไม่มี error | `onclose` ไม่เรียก `scheduleRetry()` (CodeRabbit จับ) |
| #60 | ล้างเสียงทันทีเมื่อถูกแทรก + สวิตช์พูดแทรก | **client ทิ้ง event `interrupted` ที่ backend ส่งมา** |
| #61 | เปิดให้พูดแทรกได้จริง | `activity_handling=NO_INTERRUPTION` = เข็มขัดเส้นที่สอง |
| #62 | กู้เสียงเมื่อสายโทรเข้า | iOS state `'interrupted'` · เช็คแค่ `suspended` |

#### ✅ ปิดคำถามที่ค้างมาตั้งแต่ 06-19 — **Safari หัก echo ของ AudioWorklet ได้จริง**
user ทดสอบ **iPhone 16 Pro Max ลำโพงเครื่อง (ไม่ใช้หูฟัง)** → **พูดแทรกได้ โมเดลไม่สับ turn ตัวเอง**
⇒ คอมเมนต์เดิม *"AEC ไม่ครอบ Web Audio โดยเฉพาะบนมือถือ"* **ผิดสำหรับ Safari** (ถูกสำหรับ Chrome
ซึ่งหักเฉพาะเสียงจาก WebRTC peer) ⇒ **ตัด WebRTC loopback ออกจากแผนได้** — ทางที่แพงที่สุด
· ยังคง half-duplex gate เป็นค่าเริ่มต้นเพราะ Chrome ยังหักให้ไม่ได้
· รายละเอียด + แหล่งอ้างอิง: vault `wiki/concepts/browser-echo-cancellation-ios.md`

#### 🔑 รูปแบบที่ซ้ำอีก: **"มีเข็มขัดสองเส้น ถอดเส้นเดียวไม่พอ"**
ถอด gate ฝั่ง client (#60) แล้วยังพูดแทรกไม่ได้ เพราะ server ยังสั่ง `NO_INTERRUPTION`
· **อาการชี้ตัวเอง: "พูดไม่ได้ พิมพ์ได้"** — พิมพ์ไปคนละเส้น (`send_client_content` = เริ่ม turn ใหม่
ไม่ผ่าน VAD) ถ้าเป็นปัญหา echo หรือไมค์ อาการจะพังทั้งสองทาง

#### 🔧 บทเรียนเครื่องมือรอบนี้
- **`git checkout <file>` ลบงานที่ยังไม่ commit** — พลาด 2 ครั้งตอน restore หลัง mutation
  ⇒ mutation test ให้ backup ด้วย `cp` แล้ว restore ด้วย `cp` **ห้ามใช้ git**
- **`gh pr checks` ตอบสถานะของ "การตรวจ" ไม่ใช่ของ "PR"** — ใช้เช็คว่า PR ปิดหรือยังไม่ได้
  ⇒ ต้อง `gh pr view --json state` · เคยรอ CodeRabbit ไปเปล่าๆ ~55 นาทีเพราะ PR merged ไปแล้ว
- **CodeRabbit ไม่รีวิว PR ที่ปิดแล้ว** ("Pull request is closed") · และ **ไม่ auto-review
  PR ที่ base ไม่ใช่ default branch** (ต้องสั่ง `@coderabbitai review` เป็นคอมเมนต์)
- **vault: push GitHub ไม่ทำให้ไฟล์ไปถึง NAS** — `/var/services/homes/pawin/vault/homepawin`
  **ไม่ใช่ git repo** · `/api/vault/sync` ตอบ `ok:true synced:0` = เขียวหลอก
  ⇒ ส่งไฟล์ด้วย `ssh nas-cf "cat > <path>" < <ไฟล์>` ก่อน (scp/rsync ใช้ไม่ได้ผ่าน tunnel)
  แล้วยืนยันด้วย `synced` > 0

#### ⏭️ ค้าง (สถานะอัปเดต 2026-08-09 — ดูรายการหลักที่หัวข้อบนสุดของไฟล์ด้วย)
0. 🎙️ **รอผลทดสอบ #62** — สายโทรเข้าแล้วเสียงกลับมาเองไหม (ของเดิมพังตั้งแต่ครั้งที่สอง)
   · **08-09: user คุยยาว ~35 นาทีแล้วไม่ได้รายงานเรื่องสายเข้า — แต่ยังไม่ใช่การเทสจริง**
   (ไม่รู้ว่ามีสายเข้าระหว่างนั้นหรือเปล่า) ⇒ **ยังปิดไม่ได้ ต้องให้ user โทรเข้าจริง**
   · ถ้ายังพัง **ต้องแยกให้ออกว่าขาเล่นหรือขาไมค์ที่ตาย** — ถ้าไมค์ตายอย่างเดียวอาจเป็น
   mic track ถูก iOS ปิดถาวร ซึ่ง `resume()` ช่วยไม่ได้ ต้อง `getUserMedia` ใหม่
   = ต้องมีปุ่มให้แตะจริงๆ (user gesture)
1. 🧪 **เทส TTS live** — รอโควตารีเซ็ต
   `docker exec -e TTS_LIVE_TEST=1 ai-backend-1 python -m pytest tests/test_tts_model.py`
2. ✅ **เสียงข้ามนาทีที่ 10 — ปิดได้แล้ว 08-09** · user คุยยาว ~35 นาที ข้าม go_away
   **3 ครั้ง** (12:42:07 · 12:51:09 · 13:00:10 ห่างกัน 9m02s / 9m01s) ต่อ session ใหม่
   สำเร็จทุกครั้ง **ไม่มี 1008 เลย** (เทียบ 08-02→08-05 มี 1008 ถึง 7 ครั้ง) และระดับเสียง
   นิ่ง -17.6 dBFS ตลอด ⇒ #58 ปิดงานได้จริง · ⚠️ user **ไม่ได้รายงานเรื่อง "สลับเป็นคนละคน"**
   รอบนี้ แต่ก็ไม่ได้ถูกถามตรงๆ — ถ้าจะปิดคดี "เสียงเปลี่ยน" ต้องถามให้ชัดอีกรอบ
3. ⚪ ตาราง `feedback` 0 แถว (payload ตรง schema — น่าจะยังไม่มีใครกด)
4. 🎨 **`enhanced.js` map ตามตระกูลเฉด ยังไม่ได้ไล่ความหมายรายจุด**
   (ยกเว้น login modal ที่ทำเจาะจงเป็นชมพู) — ส่วนใหญ่เป็น fallback ที่ถูก gate แล้ว
   ถ้าวันหนึ่ง overlay กลับมาเป็นเส้นหลักต้องทำรอบสอง


### ✅ เซสชัน 2026-08-06 (รอบเย็น) ปิดไป 10 PR — merged + deployed + verified prod ทุกตัว

จุดตั้งต้น: user สั่ง "ไล่ตรวจปุ่มทีละปุ่มว่าอันไหนทำงาน" → ตรวจ 63 ปุ่ม / 33 endpoint
→ เจอพัง 3 + มีปัญหา 3 → ลามไปเจอหนี้เชิงโครงสร้างอีกชุด

| PR | เรื่อง | ต้นเหตุที่แท้จริง |
|---|---|---|
| #35 | แถบ Context เริ่มหลัง sidebar | `left:0` + `z-index:8998` > sidebar `md:z-10` |
| #36 | 3 ปุ่มพัง | ดูตารางล่าง |
| #37 | TTS ลง CLAUDE.md + Debate ข้ามโมเดล | ผู้ช่วยเหลือตัวเดียวตั้งแต่ถอด fa/khim |
| #38 | ตัด local ออกจาก Debate | qwen ใช้ **109,634 ms** กว่าจะปล่อย token แรก vs Gemini ~3 วิ |
| #39 | ลบ session เก็บ `skill_shadow` | `clear_session()` เก็บแค่ 2 ตาราง |
| #40 | ลบ session เพิกถอน share link | **share link เก็บ 2 ที่** (DB + `_share_store`) |
| #41 | แก้คำอ้าง "เพดาน body ครบทุกเส้น" | เท็จ — ปิดจริงแค่ 9/27 |
| #42 | ratchet กัน endpoint อ่าน body ดิบ | ไม่มีอะไรคอยนับให้ เอกสารเลยเน่า |
| #43 | ปิดเพดาน body ครบ 27/27 | — |
| #44 | ปิดฝั่งดิสก์ (ASGI middleware) | `read_capped()` รันหลัง form parse = สายเกินไป |

**3 ปุ่มที่พังจริง (PR #36):**
- **เริ่มแชทใหม่** — `newSession()` เรียก `loadSessions()` ต่อท้ายซึ่ง auto-select
  `sessions[0]` ทับ session ใหม่ · ซ้ำร้าย `POST /api/sessions` ไม่ persist อะไรเลย
  id ใหม่จึงไม่มีวันโผล่ในลิสต์ ⇒ **ไม่เคยเริ่มแชทใหม่ได้เลย**
- **📌 pin ของ overlay ตาย 66/66** — `pinMessage()` จับคู่ประวัติด้วยข้อความเป๊ะ
  แต่ `bubble.innerText` มีป้ายปุ่ม "คัดลอก" (ของ React) ปนอยู่ ⇒ ไม่ยิง API สักครั้ง
  · พร้อมกันนี้ gate ปุ่มซ้ำอีก 132 ตัว (`§19` copy, `§20` edit) ที่ไม่มี `__hwReactChatBox`
  · ⚠️ **`🗑️ ลบ` ไม่มีคู่ใน React** จึงแนบต่อแบบไม่มีเงื่อนไข (มีเทสกลุ่มควบคุมกัน)
- **🔊 TTS** — `GEMINI_TTS_MODEL` เป็นสาย native-audio (bidi-only) ยัดเข้า
  `generate_content()` = 404 ทุก request · และเปลี่ยนโมเดลอย่างเดียวไม่พอ ต้องมี prefix `Say:`

**ล้างข้อมูล:** 39 session / 102 ข้อความ + share link 4 + session name 2
· เปิดอ่านเนื้อหาก่อนลบทุกตัว · **เจอ 2 session ที่ชื่อเหมือนของทดสอบแต่เป็นแชทจริง**
(`verify-opt3` 115 ข้อความ · `test-grounding-local` 70 ข้อความ มีงาน พมจ.แพร่ + ชื่อข้าราชการ)
⇒ **ชื่อ session เชื่อไม่ได้ · เกณฑ์ที่ใช้ได้จริงคือ "จำนวนวันที่มีการคุย"**
(ของจริงกระจาย 3-9 วัน · probe กระจุกในไม่กี่นาทีและ prompt ซ้ำเป๊ะ)

### 🔧 บทเรียนเซสชันนี้ — เครื่องมือวัดโกหก 8 ครั้ง

1. **`scandir` มองไม่เห็นไฟล์ที่ถูก unlink** — `SpooledTemporaryFile` unlink ทันทีที่สร้าง
   วัดได้ 0 MB แล้วเกือบสรุปว่า "ไม่ลงดิสก์ ไม่ต้องแก้" ทั้งที่ **313.3 MB ลงจริง**
   → ต้องไล่ `/proc/<pid>/fd` หา `(deleted)` · `df` ก็ไม่ช่วยบน volume 11 TB
2. **mutation test จับได้แค่ 3/5** เพราะเทสกลุ่มควบคุมของตัวเองอ่อน —
   เช็คแค่ "app ถูกเรียก" (ถอดเงื่อนไข scope ทิ้งก็ยังเขียว) · ส่ง body ว่างไปเทส GET
   → **เทสกลุ่มควบคุมก็ต้องผ่าน mutation เหมือนกัน ไม่ใช่แค่เทสหลัก**
3. **`tail` กินหัว** — รายงานว่าลบ 9 session ทั้งที่ลบจริง 14 เพราะอ่าน output ที่ถูก
   `tail -45` ตัดบรรทัดสรุปทิ้ง → **สคริปต์ที่ทำ destructive op ต้องพิมพ์ยอดรวมท้ายสุด**
4. **`clear_session` ในโปรเซสแยกไม่ล้าง cache ของ uvicorn** — DB ลบสำเร็จแต่ API
   ยังตอบ `ok:true` → งานล้างที่มี in-memory cache ต้องยิงผ่าน endpoint ไม่ใช่แก้ DB ตรง
5. **probe ที่หยุดส่ง body กลางคัน** ทำให้ server รอจน timeout แล้วตกเข้า `except Exception`
   → เห็น 200 แล้วเกือบสรุปว่า `/api/dream` เพดานไม่ทำงาน (จริงๆ ทำงาน 413 ใน 1.7 ms)
6. **`assert count == expect` ช่วยไว้ 2 ครั้ง** — `sandbox.py` มี `await request.json()`
   6 ครั้งแต่ 1 ในนั้นเป็น**คอมเมนต์** · `pickDebateParticipants(models)` มี 2 ที่
7. **เทสที่ผูกกับสถานะที่กำลังจะแก้** — ratchet อิง `/api/chat` ว่า "ยังดิบ" แล้วพังทันที
   ที่ปิดเพดานสำเร็จ = เทสที่ผ่านได้เฉพาะตอนโค้ดยังพัง → ย้ายไปยิง fixture สังเคราะห์
8. **`.venv` ต่างจากอิมเมจ prod** — ไม่มี `pytest-asyncio` ทำให้ 5 เทสแดงทั้งวัน
   จนกระทั่งติดตั้งให้ตรง `requirements.lock` แล้วหายเอง (ไม่ใช่บั๊ก)

🔑 **บทเรียนแม่บท: "ปิดงานแล้ว" ต้องมาจากการนับ ไม่ใช่ความรู้สึกว่าแก้ครบ**
ข้อ B ติดป้าย ✅ อยู่ 1 วันทั้งที่เหลืองาน 2 ใน 3 · เจอเพราะบังเอิญไล่ endpoint ตอน audit ปุ่ม
ไม่ใช่เพราะกลับมาตรวจ → ตอนนี้มี ratchet เป็นตัวนับถาวรแล้ว

### ✅ เซสชัน 2026-08-05/06 ปิดไป 5 เรื่อง (PR #29–#33 merged + deployed + verified prod)

| PR | เรื่อง | ต้นเหตุ / สิ่งที่พบ |
|---|---|---|
| #29 | backup มีตัวตรวจ + dead-man's switch | **"ไม่มี backup" เป็นเท็จ** — บันทึกไปดูผิดโฟลเดอร์ |
| #30 | ชื่อ archive เสีย · ตัวตรวจใน `.sh` · heartbeat retry | ผลกระทบของ #29 เอง |
| #31 | partial success ของ `accept_proposal` + เพดาน body | **คำตอบอยู่ในโค้ดฐานแล้วทั้งคู่** ไม่ต้องรอ user |
| #32 | contrast 59 จุดผ่าน WCAG AA | แก้ที่ `tailwind.config.js` จุดเดียว |
| #33 | sidebar ล้นจอ | `flex-shrink-0` + `md:max-h-none` · **บีบรายการแชทเหลือ 16px** |

**รายละเอียดของแต่ละข้ออยู่ในหัวข้อ A/B/C/C2/C3 ด้านล่าง — เปิดอ่านก่อนแตะของที่เกี่ยวข้อง**

### 🔧 บทเรียนเซสชันนี้ — เครื่องมือวัดโกหก 6 ครั้ง ผมเกือบเชื่อทุกครั้ง

1. **stale `.pyc`** — mutate `if dupes:` → `if False:` **ยาวเท่ากันเป๊ะ** + restore ในวินาที
   เดียวกัน → Python เช็ค cache ด้วย (mtime วินาที + ขนาด) เห็นว่าไม่เปลี่ยน เลยรันของเก่าต่อ
   · หลอกแนบเนียนเพราะ `diff` ตรง, `__file__` ถูก, **`inspect.getsource()` พิมพ์โค้ดที่ถูก
   ออกมาด้วย** (อ่านจาก `.py` แต่ interpreter รันจาก `.pyc`) → **mutation test ต้องล้าง
   `__pycache__` ทุกรอบ**
2. **mutation ไม่ตรงเป้า** — `.replace(old, new, 1)` ไปโดน `exit 1` ตัวแรกของไฟล์
   → รายงานว่า "เทสจับไม่ได้" ทั้งที่เทสดี → **ต้อง `assert old in s` และเลือกสตริงที่ไม่ซ้ำ**
3. **เทสเขียวเพราะเครื่อง dev มีเครื่องมือที่ prod ไม่มี** — `sqlite3` CLI ไม่มีในอิมเมจ
   → CI จับได้ · **ทางที่ไม่เลือกคือเติม sqlite3 ลง Dockerfile** (= แก้เครื่องมือวัดให้เข้ากับ
   ของที่วัด) เลือกให้ตัวตรวจอ่านผ่าน `python3` ที่มีครบทั้งสองที่แทน
4. **`except Exception` กว้างๆ กลืนด่านที่เพิ่งใส่** — `/api/memory/cleanup` ตอบ 200
   ทั้งที่ควร 413 · แล้วตอนแก้ก็เผลอ re-raise **400** (JSON เสีย) ไปด้วยจนทำลายเจตนาเดิม
   → **ใส่ด่านใหม่ต้องไล่ดูว่ามี `except` กว้างๆ อยู่เหนือมันไหม**
5. **grep ผิดรูป 2 ครั้ง** — Tailwind ปล่อยสีเป็น `rgb(142 150 163)` ไม่ใช่ hex · และเขียน
   selector เป็น `.max-h-\[45\%\]` (escape `%`) · ค้นไม่เจอแล้วเกือบสรุปว่า "แก้ไม่มีผล"
6. **เทสตรวจ config แต่เบราว์เซอร์อ่าน CSS** — คนละชั้นกัน ต้องเปิด `dist` อ่าน rule จริง
   แล้วคำนวณใหม่ · และสุดท้ายต้องดึงจาก **CSS ที่ server เสิร์ฟจริง** อีกชั้น

🔑 **บทเรียนแม่บทของเซสชัน: บันทึกที่บอกว่า "ต้องถาม user ก่อน" ก็ต้องถูกตรวจซ้ำ
เหมือนบันทึกอื่น** — เจอ 3 ครั้งในวันเดียว (C = ดูผิดโฟลเดอร์ · A = มีแบบอย่างในไฟล์
เดียวกันอยู่แล้ว · B = เพดานประกาศไว้ใน doc นี้เองแล้ว) บันทึกประเภทนี้อันตรายกว่าบันทึก
ทั่วไปเพราะ**หน้าที่ของมันคือห้ามไม่ให้ใครลงมือ** จึงไม่มีใครกลับไปตรวจ

🔧 **วิธีวัด layout ที่ได้ผลจริง** (ใช้ซ้ำได้): เปิดหน้า prod ด้วย claude-in-chrome
(login ของ user ติดอยู่แล้ว) → `javascript_tool` วัด `getBoundingClientRect()` ของลูก
ทุกตัวเทียบ `innerHeight` → **ทดลองแก้ด้วย inline style ก่อนแตะโค้ด** เทียบหลายค่าได้
ในคำสั่งเดียว ไม่ต้อง build/deploy/รอ

**เซสชัน 08-04/05 ปิดไป 4 เรื่อง (PR #25–#28 merged + deployed + verified prod ทุกตัว)**

| PR | เรื่อง | ต้นเหตุที่แท้จริง |
|---|---|---|
| #25 | เสียง "สลับเป็นคนละคน" | default โมเดล Live ไม่ตรงกัน 2 ที่มา 6 สัปดาห์ + ไม่ตรึง seed |
| #26 | สัญญาณเตือน cosine เป็น false positive | `_space()` ยุบ "อ่านไม่ได้" เข้ากับ `"l2"` + singleton ไม่มี lock |
| #27 | `AudioLevelMeter` วัด "เสียงเบาลง" | (เครื่องมือใหม่ ยังไม่มีข้อมูล — รอ user) |
| #28 | พิมพ์แทรกระหว่างคุยด้วยเสียง | backend รองรับอยู่แล้ว ขาดแค่ UI |

### 🔴 รอ user เท่านั้น — คุยด้วยเสียงยาว 12 นาที **หนึ่งรอบตอบ 2 คำถาม**
ต้องข้ามนาทีที่ 10 (จุดที่ `go_away` ตัด session แล้วต่อใหม่) แล้วบอกว่า:
1. **ยังสลับเป็นคนละคนอีกไหม** — PR #25 ตรึง seed แล้ว (3 รอบได้ไบต์เท่ากันเป๊ะ)
   แต่ไบต์เท่ากันพิสูจน์แค่ว่า*การสุ่มถูกตรึง* ไม่ใช่ว่า*หูได้ยินเหมือนกัน*
2. **ยังเบาลงตามเวลาไหม** — ผมดึง `grep VoiceLevel /app/logs/server.log` มาอ่านให้
   · **baseline: พูดปกติ −15 ถึง −18 dBFS · peak 24k–28k**
   · แบนราบ = ปัญหาอยู่ปลายทาง (OS/AEC/HFP) · ลดลง = Gemini ส่งเบาลงจริง
   · ⚠️ **AirPods เป็นเครื่องมือวัดที่แย่ที่สุด** — iOS สลับ HFP ทันทีที่หน้าเว็บถือ mic stream
     → เบาตั้งแต่วินาทีแรกด้วยเหตุผลคนละอัน · **ปุ่มปิดไมค์ในแอปไม่ช่วย** (`setMuted()`
     แค่พลิก flag ไม่เคยปิด track) · **ห้ามตัดสินจาก "ดัง/เบา" ให้ดูรูปร่างตามเวลา**
     · หูฟังมีสายเคลียร์กว่ามาก · หรือไม่ต้องใช้หูฟังเลยก็ได้ ให้ log ตัดสิน

### 🎨 รอ user เคาะ — ทิศทางธีม (เสนอแล้ว ยังไม่แตะโค้ดสักบรรทัด)
**artifact เปรียบเทียบ:** https://claude.ai/code/artifact/28e28630-e2f8-443c-9fcf-2fab144b3ba4
- **สถานะที่วัดได้:** `app.tsx` มี **12 ตระกูลสี** · L ห่างกัน 25 จุด (indigo 0.585 ↔ amber 0.837)
  · C ต่างเกือบ 2 เท่า (mint 0.119 ↔ purple 0.233) → **นี่คือเหตุผลเชิงกลไกที่มันไม่เข้ากัน**
- **contrast ตกเกณฑ์ 59 จุด** (วัดบนพื้น `rgb(15,20,32)`): `text-gray-700` = **1.79:1** (7 จุด)
  · `-600` = 2.43:1 (25 จุด) · `-500` = 3.81:1 (27 จุด) — **เป็นข้อบกพร่อง ไม่ใช่รสนิยม
  แก้ได้เลยไม่ต้องรอเลือกธีม** (→ `#94a3b8` = 7.18:1)
- **ทิศ C** = สีเดียวจาก `AI_PALETTE` (ขวัญ = ส้ม) · **ทิศ D** = 6 สีล็อก `L 0.75 C 0.13`
  หมุนแค่เฉด + ตัวตนแหกกฎที่ `C 0.18` ตัวเดียว
- ⚠️ **`AI_PALETTE` มี `fa`/`khim` ค้าง** (ถอดจาก backend ตั้งแต่ 2026-06-16) — ซากแบบเดียว
  กับ `VOICE_MAP` ที่เพิ่งเก็บไป · **ถ้าเลือก D ต้องเขียนตารางหน้าที่ลง `DESIGN.md` ก่อนแตะโค้ด**
  ไม่งั้นมันจะกลับไปเป็น 12 สีด้วยกลไกเดิม (หยิบสีมาทีละตัวตอนต้องการ)

### 📋 งานค้างที่ **ตรวจกับโค้ดจริงแล้ว ณ 2026-08-05** ว่ายังเปิดอยู่
> ตรวจด้วย grep ทีละข้อ ไม่ได้ลอกจากบรรทัดเก่า — บันทึกเก่าเคยทำให้เข้าใจผิดว่าปิดแล้ว

**✅ A. `accept_proposal` รายงาน partial success แล้ว** (ปิด 2026-08-06 · ข้อ 7 เดิม)
`utils/skill_discovery.py` คืน `db_updated: bool` + `warning` เพิ่มจาก `ok` —
**ไม่พลิก `ok` เป็น False เพราะไฟล์ .md เขียนสำเร็จจริง** บอกความจริงเป็นสองชั้นแทน
- ⚠️ **ไม่ได้คิดสัญญาใหม่** — ใช้รูปแบบเดียวกับ `routers/skills.py:skills_extract`
  ที่มีอยู่แล้วในโค้ดฐานนี้ (บรรทัด ~121-139) จึงไม่ต้องรอ user เคาะ
- router ส่งต่อ dict ตรงๆ อยู่แล้ว ผู้เรียกจึงเห็นทันทีไม่ต้องแก้ `routers/skills.py`
- เทส `tests/test_accept_proposal_safety.py` +2 (เคสล้ม + **กลุ่มควบคุมเคสปกติ** —
  ถ้าไม่มีตัวหลัง การตั้ง `db_updated=False` ตายตัวก็ผ่านเทสแรกได้)

**✅ B. เพดาน body ครบ 27/27 เส้นแล้ว** (ปิดครบ 2026-08-06 · PR #43)

> 🔴 **หัวข้อนี้เคยเขียนว่า "ครบทุกเส้นแล้ว" ตั้งแต่ PR #31 ทั้งที่ปิดไปแค่ 9 จาก 27**
> — เขียนจากความรู้สึกว่าแก้ครบ ไม่ได้นับ · แก้คำอ้างที่ PR #41 แล้วปิดของจริงที่ PR #43
> **บทเรียน: "ปิดงานแล้ว" ต้องมาจากการนับ** และคราวนี้มี `tests/test_body_cap_ratchet.py`
> เป็นตัวนับให้ถาวร ไม่ต้องพึ่งความจำอีก

ทุก route ที่อ่าน body ใช้ `json_body_capped()` / `read_capped()` ที่ **10 MB** ครบแล้ว
- ค่าอยู่ที่ **`utils/http_limits.py:MAX_BODY_BYTES` ที่เดียว** — เดิมก๊อปไว้ 3 ไฟล์
  (`documents`/`skills`/`memory`) ซึ่งจะกลายเป็น 12 ที่ถ้าปล่อยไว้แล้วปิดครบ
- ⚠️ **3 เส้นที่ body ไม่บังคับ** (`/api/memory/cleanup` · `/api/dream` · `/api/admin/unlock`)
  ต้องใช้รูปแบบ `except HTTPException as e: if e.status_code == 413: raise` —
  **ห้าม re-raise ทั้งก้อน** เพราะ `json_body_capped()` โยน **400** เมื่อ parse JSON ไม่ได้
  ซึ่งเป็นเคสที่เส้นพวกนี้ตั้งใจให้ทนได้ (เคยพลาดมาแล้วตอน PR #31)
- ⚠️ `/api/admin/unlock` ปฏิเสธ **403 ก่อนแตะ body** (LAN-only) ซึ่งถูกกว่า 413 อยู่แล้ว
- **ratchet กันถอยหลัง:** เพิ่ม endpoint ที่อ่าน body ดิบเข้ามาใหม่ → เทสแดงทันที ·
  ปิดเพดานเพิ่มได้แล้วไม่อัปลิสต์ → แดงเหมือนกัน (บังคับให้เอกสารกับโค้ดเดินพร้อมกัน)
- ✅ **ฝั่งดิสก์ปิดแล้ว** (2026-08-06 · PR #44) — `core/body_limit.py`
  เป็น **pure-ASGI middleware** ที่นับไบต์ที่ `receive` ก่อนถึง parser
  - ⚠️ ต้องเป็น pure ASGI **ห้ามใช้ `BaseHTTPMiddleware`** — ตัวนั้นให้ `Request`
    ซึ่งอ่าน body ไปแล้ว = สายเกินไป
  - ⚠️ `_BodyTooLarge` **จงใจไม่สืบทอด `HTTPException`** — ไม่งั้น handler ที่ดัก
    `except HTTPException` (`/api/dream`, `/api/admin/unlock`) จะกลืนมันทิ้งแล้วทำงาน
    ต่อด้วย body ที่ไม่ครบ
  - วางไว้ **ในสุด** (register ก่อน) → auth/rate-limit ปฏิเสธก่อนได้ ถูกกว่า
    แต่ยังอยู่นอก route จึงคุม `receive` ได้ทัน


#### ⚠️ วัด "ไฟล์ลงดิสก์" ให้ถูก — `scandir` มองไม่เห็น
`SpooledTemporaryFile` **`unlink` ไฟล์ทันทีที่สร้าง** → `os.scandir("/tmp")` ได้ 0 ไฟล์เสมอ
ทั้งที่เนื้อที่ถูกใช้จริง · วัดรอบแรกด้วย scandir แล้วเกือบสรุปว่า "ไม่ลงดิสก์ ไม่ต้องแก้"
- วิธีที่ใช้ได้: ไล่ `/proc/<pid>/fd` หา symlink ที่ลงท้าย `(deleted)` แล้ว `os.stat()` เอาขนาด
- วัดจริงบน prod ก่อนแก้: ยิง multipart **315 MB** → ตอบ 413 ถูกต้อง
  **แต่ 313.3 MB ลงดิสก์ไปแล้ว** (1 fd ที่ถูก unlink)
- `df` ไม่ช่วย — volume 11 TB ทำให้ 313 MB จมหายในความคลาดเคลื่อน

เทส: `test_body_cap_all_routes.py` (38) + `test_upload_body_cap.py` (7) +
`test_body_cap_ratchet.py` (6) — ทุกเส้นมีกลุ่มควบคุม "body เล็กต้องไม่โดน 413"

- ⚠️ **10 MB ไม่ใช่ตัวเลขใหม่ จึงไม่ต้องรอ user เคาะ** — `CLAUDE.md` ประกาศ
  "ขนาดสูงสุด 10 MB" ไว้แล้ว และ `routers/documents.py` บังคับใช้ค่าเดียวกันอยู่แล้ว
  งานนี้คือ**บังคับใช้ให้ครบ** ไม่ใช่ตั้งนโยบายใหม่ → ไม่มีไฟล์ที่ "เคยอัปได้" กลายเป็น 413
  เกินกว่าที่เอกสารบอกไว้
- 🔴 **`/api/memory/cleanup` เคยห่อด้วย `except Exception` กว้างๆ ซึ่งกลืน 413 ที่เพิ่งใส่ไป
  แล้วตอบ 200 เหมือนสำเร็จ** (RAM รอดจริง แต่ผู้เรียกไม่มีทางรู้ว่าถูกตัด) → แยกเป็น
  `except HTTPException: raise` ก่อน แล้วค่อย `except Exception` ตามเจตนาเดิม (body ไม่บังคับ)
  **บทเรียน: ใส่ด่านใหม่แล้วต้องไล่ดูว่ามี `except` กว้างๆ อยู่เหนือมันหรือเปล่า**
- multipart ใหญ่ยังเขียนลงดิสก์คอนเทนเนอร์ตอน parse (starlette spool >1 MB) —
  คนละ lever ต้องกันที่ proxy/middleware **ยังเปิดอยู่**
- เทส `tests/test_upload_body_cap.py` (7) มีกลุ่มควบคุมทุกเคส · mutation 5 แบบจับได้ครบ

**⚪ D. voice retry ยังไม่เคยถูกกระตุ้นจริงบน prod** — ยืนยันได้แค่ unit test + โค้ดอยู่ในบันเดิล
**⚪ E. `SKILLS_SEARCH_MIN_SCORE`** — **ห้ามจูนละเอียดกว่านี้** (positive แค่ 11 ตัว)
ถ้าจะขยับต้องมาร์คเพิ่มจาก 187 คู่ว่างใน `data/skills_pairs.json` ก่อน
**⛔ F. key Claude/Kimi (ข้อ 13)** — user ตัดสินใจแล้วว่ายังไม่ใช้ **ห้ามถามซ้ำ**

### 🔧 บทเรียนเครื่องมือวัดของเซสชันนี้ (โดนตัวเอง 3 รอบ)
1. **probe ที่นับ "ไม่ throw" ว่าสำเร็จ** → ขึ้น ✅ ให้เคสที่ `audio=0B` · ถ้าเชื่อจะ pin โมเดล
   2.5-native-audio ที่ `temperature` ทำให้**เสียงหายเงียบสนิท** ทั้งที่เทส 1216 + CI เขียวหมด
2. **`session.receive()` yield แค่ turn เดียวแล้วจบ generator** — ใช้ `async for` ชั้นเดียว
   แล้วสรุปว่า "Gemini ตัดเสียงแล้วเงียบไม่ตอบ" ทั้งที่ตัวเองหยุดฟัง · **คอมเมนต์เตือนเรื่องนี้
   อยู่ใน `send_loop` อยู่แล้ว แต่ผมเขียน probe ใหม่นอกไฟล์นั้นเลยไม่ได้พกกติกาไปด้วย**
3. **เทส race ที่วาง barrier ไว้ใน `__init__`** → พอใส่ lock แล้ว deadlock ตัวเอง
   = เทสที่ผ่านได้เฉพาะตอนโค้ดยังพัง
→ vault `wiki/concepts/measuring-instruments-lie.md` รูปแบบที่ 11–12 + เช็คลิสต์ข้อ 13–14

---

## ⏭️ งานค้าง ณ 2026-08-04 (อ่านต่อจากอันบน)

**สถานะ:** PR #14–#22 merged · CI เขียว · prod deployed+verified · `~/appscript.ui` sync แล้ว
(github + NAS bare) · ⚠️ **ไม่เขียน commit hash ของ repo ตัวเองไว้ตรงนี้** — ไฟล์นี้ถูก commit
ทีหลังเสมอจึงตามหลังหนึ่งก้าวตลอด (เคยเขียนแล้วผิดทันทีที่ commit) ให้ดู `git log` แทน
**audit 24 ข้อ ปิดไป 23** เหลือข้อ 13 (ใส่ `ANTHROPIC_API_KEY`/`MOONSHOT_API_KEY` ใน NAS `.env` — user ตัดสินใจแล้วว่ายังไม่ใช้ **ห้ามถามซ้ำ**)

### 🔴 ต้องใช้ user เท่านั้น
1. **ข้อ 8 voice — เทสหูฟัง** · ใส่หูฟังแล้วหายเบา = ยืนยันสมมติฐาน AEC/AGC หรี่ ·
   ยังเบา = สมมติฐานผิด ต้องรื้อใหม่ · อัดด้วย Screen Recording **ปิดไมค์** (ตัดตัวแปรระยะห่าง)
   เล่าเกิน 11 นาที · AirPods เบาตั้งแต่ต้นเพราะ iOS สลับ HFP — **ดูว่า "แย่ลงตามเวลา" ไม่ใช่ "ดัง/เบา"**

### 🔵 ทำต่อได้เลย
2. ✅ **[ปิดแล้ว 2026-08-04]** `routers/memory.py` · `routers/skills.py` — `async def` + งาน sync
   ปิดครบ 6 endpoint (`memory/teach` · `memory/cleanup` · `memory/{a}` · `skills/extract` ·
   `skills/discover/accept` · `upload`) · เทส `tests/test_memory_skills_router_concurrency.py`
   - ตัวที่หลอกตาที่สุดคือ **`skills/extract`**: เรียก `stream_response()` ตัวเดียวกับ `chat.py`
     แต่ `chat.py` ปลอดภัยเพราะ**ส่ง generator ต่อ**ให้ `StreamingResponse` (starlette ห่อ
     `iterate_in_threadpool()` ให้) ส่วนที่นี่ `"".join()` เอง → Gemini call เต็มรอบบน event loop
     **"sync generator ปลอดภัย" เป็นจริงเฉพาะตอนที่ starlette เป็นคนหมุน**
   - ต้องปิด race บน `skills_db.json` **ก่อน** ย้าย (ตามที่ `test_skills_db_concurrency.py`
     เตือนไว้): เจอ 3 จุดที่ load→แก้→save เองโดยไม่ถือ `_db_lock` — `skills_extract` ·
     `skills_delete` (racy อยู่แล้ววันนั้น เพราะเป็น `def` = อยู่ใน threadpool) ·
     `accept_proposal` (ไม่มี lock **และ** เขียนด้วย `open(w)` = ไม่ atomic)
     → รวมทางเขียนเหลือทางเดียวที่ `utils/skills.py`: `set_skill_entry()` / `delete_skill_entries()`
   - ตัด alias `skill_discovery._SKILLS_DB` ทิ้ง — ค่าคงที่ชี้ไฟล์เดียวกัน 2 ที่ทำให้เทสที่
     patch ได้ตัวเดียว "เขียวโดยวัดผิดไฟล์" (`test_skill_entry_gate.py` เคยต้อง patch ทั้งคู่)
3. **multipart ใหญ่ยังเขียนลงดิสก์คอนเทนเนอร์ระหว่าง parse** — starlette spool ที่ >1 MB
   `read_capped()` ปิดฝั่ง RAM ได้แล้ว ฝั่งดิสก์ต้องกันที่ proxy/middleware (คนละ lever)
   - 🟡 **ปิดไปบางส่วน 2026-08-06 (ข้อ B)** — `/api/upload` ใช้ `read_capped()` · `memory.py`
     3 จุด + `/skills/discover/accept` ใช้ `json_body_capped()` ที่ 10 MB
     **ที่เคยเขียนว่า "ต้องให้ user เลือกเพดานก่อน" นั้นคลาด** — 10 MB ประกาศไว้ใน
     doc นี้เองแล้ว (บรรทัด ~460) และ `documents.py` บังคับใช้อยู่ก่อนแล้ว
     ✅ **ที่เหลืออีก 18 เส้นปิดครบแล้วที่ PR #43** — ดูหัวข้อ "✅ B. เพดาน body" ด้านบน
     · 🔴 **ฝั่งดิสก์ (multipart spool) ยังไม่ได้แตะเลย** — คนละ lever ยังเปิดอยู่
7. ✅ **ปิดแล้ว 2026-08-06 (ข้อ A)** — คืน `db_updated` + `warning` เพิ่มจาก `ok`
   ตามรูปแบบที่ `skills_extract` ใช้อยู่แล้วในไฟล์เดียวกัน (ไม่ใช่ contract ใหม่
   จึงไม่ต้องรอ user เคาะอย่างที่เคยเขียนไว้) · ดูหัวข้อ "✅ A." ด้านบน
4. **voice retry ยังไม่เคยถูกกระตุ้นจริงบน prod** — ยืนยันได้แค่ unit test + โค้ดอยู่ในบันเดิล
5. `SKILLS_SEARCH_MIN_SCORE` ตั้งจาก ground truth ที่มี positive แค่ 11 ตัว — **ห้ามจูนละเอียดกว่านี้**
   ถ้าจะขยับต้องมาร์คเพิ่มจาก 187 คู่ที่ยังว่างใน `data/skills_pairs.json` ก่อน
6. ✅ **[ปิดแล้ว 2026-08-04]** RLock ของ `skills_db` กันได้แค่ process เดียว
   → เพิ่ม `_db_transaction()` ใน `utils/skills.py` = `RLock` (ข้ามเธรด) + **`flock(LOCK_EX)`**
   (ข้ามโปรเซส) · ทุกเส้นที่ read-modify-write ใช้ตัวนี้ · เทส `tests/test_skills_db_cross_process.py`
   - **`scripts/clean_skills_db.py` เป็นตัวปัญหาจริง** — มันไม่เคยใช้ทางของ `utils/skills.py` เลย
     อ่านเองด้วย `open()` เขียนเองด้วย `open(db,"w")` = **ทั้งทับของที่แอปเพิ่งเขียน และ
     ทำให้แอปอ่านเจอไฟล์ truncate ค้าง** · ตอนนี้ `--apply` ทั้งก้อนอยู่ใน transaction เดียว
     และเขียนผ่าน `_save_skills_db()` · **dry-run ไม่ถือ lock** (อ่านอย่างเดียว ปลอดภัยอยู่แล้ว)
   - ⚠️ **lock อยู่บนไฟล์แยก `skills_db.json.lock`** ห้ามล็อกตัว db เอง — `_save_skills_db()`
     ใช้ `os.replace()` = สลับ inode ผู้ที่ล็อก db ไว้จะถือ lock บน inode ที่ถูกทิ้งแล้ว
     = **ล็อกที่ดูเหมือนล็อกแต่ไม่กันอะไรเลย**
   - ⚠️ **การอ่านเฉยๆ ไม่ต้องถือ lock** (เขียน atomic อยู่แล้ว) — ครอบเฉพาะ อ่าน→แก้→เขียน
   - วัดได้ก่อนแก้: **6 โปรเซส × 20 รายการ หายไป 60/120** · reader อ่านเจอ JSON พัง 6 ครั้ง
   - ✅ **เพดานเวลารอ lock** (user เลือก 2026-08-04: **fail-fast + ส่งเสียงดัง**)
     `SKILLS_DB_LOCK_TIMEOUT=5` (env, `off` = รอไม่จำกัด) → ยึดไม่ได้ = โยน `SkillsDbLocked`
     · เหตุผล: ตั้งแต่ PR #23 เส้นนี้อยู่ใน threadpool (40 slot) รอไม่จำกัด =
     โปรเซสค้างตัวเดียวลากทั้งแอป = **อาการเดียวกับที่ PR #23 เพิ่งปิด** แค่เปลี่ยนสาเหตุ
     · เลือกทิศนี้ได้เพราะ**มีเส้นสำรอง** (ผู้ใช้กดบันทึกใหม่ได้ แต่แอปค้างไม่มีทางออก)
     · **`scripts/clean_skills_db.py` ใช้ `--lock-timeout` default 60 วิ โดยตั้งใจ** —
       งานที่คนสั่งเองควรรอให้แอปว่างแล้วทำให้จบ (`0` = รอไม่จำกัด) ยึดไม่ได้ → **exit 1**
     · ทางที่ไม่กลืน error: `save_skill()` คืน `False` + log ERROR (ผู้เรียกวนหลายรายการ
       ปล่อย exception หลุดจะพังทั้งชุด) · `skills_extract` เพิ่ม `db_updated`/`warning`
       ในผลลัพธ์ · `skills_delete`/`cleanup-skills` ตอบ `ok:false`
   - ✅ **`_save_skills_db()` โยน `SkillsDbWriteFailed` แล้ว ไม่กลืนเหมือนเดิม**
     ลำดับชั้น: `SkillsDbError` ← `SkillsDbLocked` / `SkillsDbWriteFailed` (จับตัวแม่ได้ทั้งคู่)
     · เดิม `except Exception` + log warning เฉยๆ → ดิสก์เต็ม/สิทธิ์ไม่พอ = เขียนไม่ลงแต่
       `save_skill()` คืน `True` และสคริปต์ **exit 0** พร้อมพิมพ์ว่าล้างแล้ว
     · ⚠️ **บทเรียน: การย้ายสคริปต์มาใช้ `_save_skills_db()` (ถูกเรื่อง atomic+lock)
       เผลอแปลงความล้มเหลวที่เคย "ดัง" ให้ "เงียบ"** — ของเดิมใช้ `open(w)` ซึ่งพังแล้วมี
       traceback · **การรวมทางเดียวกันเป็นเรื่องดี แต่ต้องเช็คว่าทางกลางนั้นรายงานผลไหม**

---

## ⏭️ ทำต่อ session หน้า (อัปเดต 2026-06-18) — เรียงตามคุ้มสุด
- ✅ **[verified UI จริงบน browser 2026-06-17]** ขับ Chrome (playwright-core, ทดสอบผ่าน LAN `192.168.51.49:8080` = bypass auth) เช็คทั้ง 4 ผ่านหมด: slash menu (พิมพ์ `/` → 7 รายการ, ArrowDown+Enter เลือก "หา bug" ลง input จริง) · token pill ("45 ตัวอักษร · ~12 tokens" มุมขวาบน) · draft restore (`hw_draft_voice_default` → reload คืนค่า) · **Sleep card = Light 22 / REM 2 / Deep 2 ตรง `/api/dream/report` เป๊ะ (ไม่ใช่ 40/40/20%)**. bundle prod = `index-Cn7b8BSq.js` + overlay `?v=20260617`
  - ✅ **[แก้แล้ว 2026-06-17, deployed `02ac0c7`]** `static/enhanced.js:852` `fetch("/config")` → 404 → แก้เป็น `/api/config` (route จริง prefix `/api`, `routers/system.py:61`) + bump overlay `?v=20260617-cfgfix`. FAB Vault โผล่ตาม `OBSIDIAN_VAULT_PATH` ได้แล้ว. verified prod ผ่าน Cloudflare Tunnel. ไม่กระทบ React (ใช้ `/api/config` ถูกอยู่แล้ว)
  - ℹ️ modal "Dream Threshold Alert (memory เกิน 100)" เด้งบังจอตอนโหลด — เป็น modal จริงตามดีไซน์ (มี memory >100 จริง), ปุ่ม "ปิด"/"🌙 รัน Dream เลย"
- ✅ **port overlay ตัวใหญ่ที่เหลือเข้า React เสร็จครบ** (pattern: pure util + vitest → wire → gate `__hwReactChatBox`): ~~Home Panel FAB~~ ✅ (#38) · ~~Export~~ ✅ · ~~Global search modal Ctrl+Shift+F~~ ✅ (`utils/globalsearch.ts`, deployed `390d031` — แก้ field `content`/`timestamp`→`snippet`/`created_at` ด้วย) · ~~File Manager §18~~ ✅ (deployed `843eca2` 2026-06-17 — `utils/filemanager.ts` `classifyUpload`+11 vitest; ขยาย attach รองรับ PDF/DOCX/XLSX + index ChromaDB `/api/documents/upload` สำหรับเอกสารหนัก + ปุ่ม 📷 กล้อง + drag&drop ลง composer; โมเดล "ขยาย attach เดิม" ไม่ทำ document side-panel; overlay `?v=20260617-filemgr`)
1. 🔑 **ใส่ key ใน NAS `.env` → recreate** (เช็คจริง 2026-06-18: ทั้ง 3 ยัง**ว่าง**) — งานเร็วสุด ไม่ต้องแก้โค้ด:
   - `ANTHROPIC_API_KEY` → ปลด Claude ใน Model picker · `MOONSHOT_API_KEY` → ปลด Kimi K2.6 · `HA_URL`+`HA_TOKEN` → Agent สั่ง Home Assistant
   - (GEMINI + GOOGLE_SEARCH ตั้งแล้ว ✅) · recreate: `cd /var/services/homes/pawin/ui && sudo docker compose up -d hybrid-ai`
2. ✅ **off-site GitHub backup ให้ `~/appscript.ui`** (2026-07-05) — เพิ่ม remote `github` (`github.com/penpunnee/appscript-ui`, private) คู่กับ `origin` (NAS bare repo) ใช้ SSH key ที่มีอยู่แล้ว (`id_ed25519_penpunnee`, account-level ไม่ต้องผูก deploy key ใหม่) push ครบทั้ง 2 remote ทุกครั้งที่ commit นับจากนี้
3. ✅ **เปลี่ยน local model → Qwen3.5-9B** (2026-07-05, เลิกใช้ deepseek-r1-0528-qwen3-8b) — `LMSTUDIO_CHAT_MODEL`/`LMSTUDIO_REASON_MODEL`/`LMSTUDIO_VISION_MODEL` ทั้ง 3 ตัวชี้ไป `qwen/qwen3.5-9b`, local `.env` อัปเดตแล้ว, NAS `.env` ยังค้าง `LMSTUDIO_CHAT_MODEL=deepseek/...` (ต้องแก้ + recreate ให้ตรงกัน — ดู session log ล่าสุด)
4. 🧪 **verify + ปิดงานค้าง**: ดู File Manager drag&drop/กล้อง/index ด้วยตาบน browser · #34 web-search grounding classifier (test ยังไม่เสร็จ) · ~~เคลียร์ WIP `components/` ใน appscript.ui~~ ✅ **ตรวจแล้ว 2026-08-04: tree สะอาด ไม่มีโฟลเดอร์ `components/` ไม่มี import ค้าง** · quality gate ฝั่ง recall (optional)
5. 💾 **ยืนยัน infra — ตรวจจริงแล้ว 2026-08-04:**
   - ✅ `poppler-utils` บน NAS: **มี** (`pdftoppm` อยู่ในคอนเทนเนอร์)
   - 🔴 **DSM `db_backup.sh` ไม่เคยถูกตั้งเวลาเลย** — ไล่ task ที่ยังมีชีวิตครบ **24 ตัว**
     ใน `/usr/syno/etc/synoschedule.d/root/*.task` **ไม่มีตัวไหนเรียก `db_backup.sh`**
     สคริปต์มีจริงและทำงานได้ (`scripts/db_backup.sh` → `/volume1/homes/pawin/db_backups`)
     แต่ backup ล่าสุดคือ **2026-07-12** = รันมือครั้งเดียวแล้วไม่มีอีกเลย
     · วิธีตรวจ (sudo -n ครอบแค่ docker ไม่ครอบ `synoschedtask`):
       `docker run --rm -v /usr/syno/etc:/syno:ro python:3.11-alpine` แล้ว decode `cmd=` (base64)
     · ⚠️ `N.backup/` คือประวัติเวอร์ชันที่ DSM เก็บไว้ **ไม่ใช่ task ที่รันจริง** — ดูเฉพาะ `N.task`
     · บทเรียนซ้ำ: **"ตั้ง cron ไว้ไม่ได้แปลว่ามันรัน" — คราวนี้คือไม่เคยตั้งด้วยซ้ำ**
- ⛔ พักไว้: Image Gen (free tier limit=0 ต้องเปิด billing) · fine-tune (รอ 👍 ~200-500)

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

**Deploy:** ทางหลัก = SSH ตรงจาก Mac (ดู Commands→Docker) · fallback = DSM Task Scheduler `deploy-hybrid-ai`. Session 2026-06-12: image gen verify (พัก—free tier limit=0) + `_MarkerFilter` + `Part.from_text` fix + stream status — deployed+verified prod ครบ

## Session 2026-06-10/11 — scrutinize §22 + ChatBox เข้า React (สรุป)
ลำดับงาน 6 commits (`383125c`→`3b181ba`) — รายละเอียดเต็มดู git log + memory:
1. `383125c` scrutinize Major 1+2: webSearch ห้าม hijack Claude (guard `!_claudeMode`) + Plan ส่ง `plan_mode` flag แทน mutate prompt (backend ฉีดเข้า system prompt — DB/fine-tune corpus สะอาด, bypass response cache) — `tests/test_plan_mode.py`
2. `34aa034` LM Studio health: `check_lmstudio_health()` + `/api/status` ได้ `lmstudio`/`local_provider`/`local_ok` — `tests/test_lmstudio_health.py`
3. `4e3bbcf` M3/M4/m5: `_isComposerEl` รู้จัก overlay + กัน ghost draft (`getClientRects`) + `_rebindNative()` + pill reconcile
4. `598af0b` extract `static/chat_intercept.js` (pure dual-export) + `tests/chat_intercept.test.js` + CI รัน `node --test tests/*.test.js`
5. `3b181ba` **ChatBox React จริง** (จาก `~/appscript.ui` commits `5308e46`+`8fce86c`): flags ส่งตรงใน body ผ่าน `buildChatFlags`, `window.__hwReactChatBox` ให้ overlay ข้าม, Claude FAB ถอด `tool_agent` ใน chat_intercept
- **บทเรียน:** (1) React source อยู่ที่ `~/appscript.ui` มาตลอด — build hash ตรง prod เป๊ะ, overlay ที่ผ่านมาคือหนี้ที่ไม่จำเป็น (2) vite `emptyOutDir` ชี้ `static/` = ระเบิด — ใช้ `dist/`+sync เสมอ (3) ~~เครื่อง Mac ไม่มี `gh` CLI~~ **ล้าสมัย — มี `gh` แล้ว (ยืนยัน 2026-08-03)** ใช้ `gh run list` / `gh run watch --exit-status` ได้ตรงๆ
