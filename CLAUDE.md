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
GEMINI_LIVE_MODEL=gemini-2.5-flash-native-audio-latest   # ⚠️ gemini-2.0-flash-exp/gemini-live-2.0-flash-001 ถูกถอดจาก Live API (bidiGenerateContent → 1008 not found, เจอจริง 2026-06-16). เช็ค model ที่ใช้ได้: ListModels filter supportedGenerationMethods มี bidiGenerateContent
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

## Image Generation (2026-06-12)
⛔ **พักฟีเจอร์ไว้ (user ตัดสินใจ 2026-06-12)** — โค้ดทำงานถูกทั้งเส้น (verified prod) แต่ Google ไม่เปิดโมเดลสร้างรูป**ทุกตัว**ให้ free tier (429 `limit: 0` — gemini-2.5-flash-image, gemini-3.1-flash-image; imagen = paid-only). ใช้ได้เมื่อเปิด billing (~$0.04/รูป) — ไม่ต้องแก้โค้ด. ดู `skills/gemini-api-quota-sdk-gotchas.md`
- `utils/image_gen.py` — `generate_image(prompt)` ผ่าน Gemini (`IMAGE_GEN_MODEL`, default `gemini-2.5-flash-image`) → เซฟ PNG ที่ `${NAS_DATA_PATH}/gen_images/` เสิร์ฟผ่าน `/gen/<file>` (open path — <img> ส่ง auth header ไม่ได้)
- chat: `detect_image_request()` จับ "วาดรูป/สร้างภาพ/ออกแบบโลโก้" → short-circuit ก่อน teach/cache → ตอบ markdown `![..](/gen/xxx.png)` (persist ลง history เป็น text ปกติ)
- React `renderMarkdown` แปลง `![..](/path)` → `<img class="md-img">` (รับเฉพาะ path ภายใน กัน external)
- agent mode: tool `generate_image` ใน registry
- ⚠️ คำสั่งวาดรูปห้ามเข้า response cache / teach / memory — short-circuit อยู่ก่อนทุกอย่างแล้ว

## Coding Conventions
- All UI strings + comments **ภาษาไทย**; technical terms remain English
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
  แล้วคืน `None` ถ้าไม่ใช่ cosine → fail-closed (`_handle_unscorable_results` log ERROR
  พร้อมคำสั่ง `recreate_collection()` ที่รันได้จริง) · prod ตอนนี้เป็น cosine อยู่แล้ว ✅
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
4. 🧪 **verify + ปิดงานค้าง**: ดู File Manager drag&drop/กล้อง/index ด้วยตาบน browser · #34 web-search grounding classifier (test ยังไม่เสร็จ) · เคลียร์ WIP `components/` ใน appscript.ui (untracked ไม่ได้ import) · quality gate ฝั่ง recall (optional)
5. 💾 **ยืนยัน infra**: DSM `db_backup.sh` รายวัน 03:30 มีจริงไหม (เช็คไม่ขึ้นเมื่อ 2026-06-18) · `poppler-utils` บน NAS (OCR PDF scan — เช็คไม่ได้ตอน backend down)
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
