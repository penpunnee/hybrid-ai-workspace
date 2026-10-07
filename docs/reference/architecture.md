# Architecture — Khim AI backend (อ้างอิง)

> ยกทั้งดุ้นจาก `CLAUDE.md` เมื่อ 2026-10-01 (ไฟล์นั้นโต 103 KB และถูกฉีดทุกเซสชัน) — **ไม่ได้แก้เนื้อหา**
> หัวข้อ ▶️ / กติกาที่ยังมีผล ยังอยู่ใน `CLAUDE.md` · ประวัติอยู่ใน `docs/session-log/devlog.md`

## Architecture

### Request Flow (`/api/chat`)
1. Middleware ใน `server.py` → gen `X-Request-Id` + log timing
2. Auth middleware (`core/auth.py`): **fail-closed** — ทุก request ต้องมี **session token** (cookie `hw_session` HttpOnly ที่ `/api/auth/login` ออกให้ หรือ header `x-auth-token` = session token · **รหัสดิบใช้ไม่ได้อีกตั้งแต่ 2026-09-24** · token = nonce.exp.HMAC(derive จาก `UI_PASSWORD`) อายุ `SESSION_TTL_DAYS`=30 · เปลี่ยนรหัส = เพิกถอนทุก session) เว้นแต่อยู่ใน `_OPEN_PATHS`/`_OPEN_PREFIXES` (/, config, status, health, auth/*, /static, /shared, /api/shared, /ws). LAN/loopback peer IP bypass (`is_local_request`, spoof-resistant). **เพิ่ม endpoint sensitive ใหม่ = ปลอดภัยโดย default** (ไม่ต้องไป maintain denylist). middleware order (outer→inner): request_id → rate_limit → auth (rate_limit wrap auth เพื่อเห็น 401 → feed brute-force lockout)
   - ⚠️ **middleware ไม่แตะ WebSocket** (`BaseHTTPMiddleware` ลัดผ่าน scope ที่ไม่ใช่ `http`) → WS handler ต้องเรียก `core.ratelimit.websocket_auth_ok(ws, token, authorize=websocket_authorized)` เองก่อน `accept()` (เข้า lockout เดียวกับ http · 2026-09-24). credential หลัก = cookie `hw_session` ที่ browser แนบเองตอน handshake · `?token=` ยังรับ session token ไว้ให้ bundle เก่า/สคริปต์ (log ของ uvicorn ถูก `DropQueryStringFilter` ตัด query ออกแล้ว) · client ไม่ส่ง token ใน URL อีก (`voicelive.ts`/`bookreader.ts` ส่ง `''`) — **เพิ่ม WS endpoint ใหม่ = ต้อง gate เอง ไม่ปลอดภัยโดย default เหมือนฝั่ง HTTP**
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
> ℹ️ **Ollama = dormant fallback only (2026-06-15)** — เลิกใช้เป็นตัวหลักแล้ว. local provider จริง = **LM Studio (qwen3.5-9b)** (`local_provider:lmstudio`). Ollama เหลือบทบาท safety net 2 จุด: routing fallback ตัวสุดท้าย, dream fallback. ⚠️ **ยกเว้น embeddings ที่ทิศกลับกัน — Ollama เป็นตัวหลัก** (`EMBEDDING_MODEL=paraphrase-multilingual` · `utils/embed.py:_create_embeddings`) แล้ว fallback ไป LM Studio ด้วยโมเดล**ชื่อเดียวกัน** (ห้าม fallback ข้ามโมเดล = คนละ vector space cosine เพี้ยนเงียบๆ). คงไว้เพื่อ resilience — `ollama:true` ใน status = PC `.235` ต่อติด ไม่ได้แปลว่ามันรับงานจริง

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
| Skills knowledge base | `skills/*.md` (file system) + `skills_db.json` + ChromaDB `skills_collection` (⚠️ ชื่อ collection ไม่ใช่ `skills_search` — นั่นคือชื่อ *โมดูล* `utils/skills_search.py`) |
| Dream reports | `dream_reports/dream_YYYYMMDD_HHMMSS.json` |
| Document chunks (Phase B) | ChromaDB collection `documents` |
| Embedding cache (Phase E) | `data/embed_cache.db` (SQLite WAL, float32 blobs) |
| Response cache (Phase E) | `data/response_cache.db` (SQLite WAL) |

**Backups (สถานะจริง ยืนยัน 2026-07-12):**
- **DB backup = in-app job 03:30** (`core/scheduler.py` → `utils/db_backup.py`) — sqlite3 backup API (online, WAL-safe) ของ `chat_history.db` + cache dbs → tar.gz เก็บ 7 วันที่ `/app/db_backups` (mount → `ui/data/db_backups` บน NAS). เลือกฝังในแอปเพราะตั้ง DSM task จาก SSH ไม่ได้ (sudo จำกัดแค่ docker) — verified จริง: trigger ใน container ได้ archive 143KB
- `scripts/db_backup.sh` — ทางเลือกรันมือฝั่ง host (dest `/volume1/homes/pawin/db_backups`). ⚠️ แก้แล้ว 2026-07-12: เดิมหยิบ `ui/chat_history.db` (ไฟล์ค้างเก่า 12KB) แทน `ui/data/chat_history.db` (DB จริงที่ compose mount) → backup เปล่า
- **chroma backup = DSM task `chroma-backup` รายคืน 00:00** เก็บ 7 ไฟล์ล่าสุด (ปอยเปิด DSM ดู 10-07: รอบ 00:00:01–00:00:30 สถานะ 0 · เอกสารเก่าเคยเขียน 04:00/00:01 · ตรึงด้วย `tests/test_backup_time_docs.py`) → `/volume1/homes/pawin/chroma_backups/`

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
- `agents/tools.py` — tool registry (`_ALL_TOOLS` 24 ตัว: web/wiki/memory/`run_python`/`fs_*` + home tools + `generate_image`)

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
- Phase 3 Deep: promote themes (count ≥ `DREAM_PROMOTE_MIN_HITS`, default 2) → `skills_db.json` + `long_term_memory`
- Report: `dream_reports/dream_YYYYMMDD_HHMMSS.json`
- **long_term_memory ไม่โต = ผลที่คาดไว้** ตามการตัดสินของปอยเมื่อ 09-30 (ไม่เก็บความรู้ทั่วไปจากเน็ต · เนื้อหาเกม · personal fact ไป `user_facts` ผ่าน "จำไว้ว่า" เท่านั้น) —
  ทดลอง 10-07 (อ่านอย่างเดียว · ความจำ 7 คืนจริง · 300 vs 600 ตัวอักษร · 24 รอบ) ได้ 0 ธีมทุกรอบ: เนื้อหาเป็นเกม/นิยาย/ค้นเว็บ/ขอโค้ดตัวอย่าง/ทักทาย ·
  ส่งเต็มข้อความไม่ช่วย · ดูข้ามวันก็ไม่ช่วย (เนื้อหาชนิดเดียวกัน) ⇒ อย่าไล่แก้ prompt ให้ได้ธีม ·
  report มี `phase2_rem.status`: `ok` · `no_durable_knowledge` (ปกติ + `reason`) · `parse_failed` · `llm_error` (เช่น 429) — สองตัวหลังคือของพังจริง

### Caches (Phase E)
| Layer | Storage | TTL/Size | Threshold |
|---|---|---|---|
| Embed | sqlite WAL `data/embed_cache.db` | unlimited | exact text |
| Retrieval (per-session) | in-memory dict | 10min / 200 sessions | cosine ≥ 0.85 |
| Response (semantic) | sqlite WAL `data/response_cache.db` | 30 days / 1000 entries | cosine ≥ 0.92 |
| Response bypass | — | — | `is_realtime_query()` — ping/disk/docker/ราคา/อากาศ/สถานะระบบ bypass เสมอ |

Stats: `GET /api/cache/stats`


## Image Generation (2026-06-12)
⛔ **พักฟีเจอร์ไว้ (user ตัดสินใจ 2026-06-12)** — โค้ดทำงานถูกทั้งเส้น (verified prod) แต่ Google ไม่เปิดโมเดลสร้างรูป**ทุกตัว**ให้ free tier (429 `limit: 0` — gemini-2.5-flash-image, gemini-3.1-flash-image; imagen = paid-only). ใช้ได้เมื่อเปิด billing (~$0.04/รูป) — ไม่ต้องแก้โค้ด. ดู `skills/gemini-api-quota-sdk-gotchas.md`
- `utils/image_gen.py` — `generate_image(prompt)` ผ่าน Gemini (`IMAGE_GEN_MODEL`, default `gemini-2.5-flash-image`) → เซฟ PNG ที่ `${NAS_DATA_PATH}/gen_images/` เสิร์ฟผ่าน `/gen/<file>` (open path — <img> ส่ง auth header ไม่ได้)
- chat: `detect_image_request()` จับ "วาดรูป/สร้างภาพ/ออกแบบโลโก้" → short-circuit ก่อน teach/cache → ตอบ markdown `![..](/gen/xxx.png)` (persist ลง history เป็น text ปกติ)
- React `renderMarkdown` แปลง `![..](/path)` → `<img class="md-img">` (รับเฉพาะ path ภายใน กัน external)
- agent mode: tool `generate_image` ใน registry
- ⚠️ คำสั่งวาดรูปห้ามเข้า response cache / teach / memory — short-circuit อยู่ก่อนทุกอย่างแล้ว

## Known Quirks / Bugs
- **Memory contamination จากการเทส (เจอจริง 2026-06-11, แก้แล้ว 2026-07-13 — P2-9)**: ทุก Q&A ถูก save เข้า episodic ChromaDB (`memory_kwan` ฯลฯ) รวมถึงคำตอบกุ/error จากการ smoke test → ถูก recall กลับมาให้โมเดลตอบซ้ำแม้เปลี่ยน session/provider. **แก้ที่ต้นทาง**: ส่ง header `X-Test-Request: 1` ไปกับ `/api/chat` ตอนสโมกเทส → ข้าม `remember()`/`teach()`/auto-learn lesson thread ทั้งเส้น (`routers/chat.py:_is_test_request`) ไม่ปนเปื้อนตั้งแต่แรก. **แก้ย้อนหลัง** (ถ้าปนเปื้อนไปแล้วก่อนมี header นี้): `GET /api/admin/memory/{assistant}?q=...` (list/preview) + `DELETE /api/admin/memory/{assistant}/{id}` — LAN-only เหมือน `/api/admin/unlock`, ไม่ต้องต่อ ChromaDB ตรงอีกต่อไป
- **gemini_agent ≠ search_web()**: เส้น `gemini_agent` ใช้ Google Search grounding ในตัว Gemini (`types.Tool(google_search=...)` ใน `utils/llm.py`) — ส่วน `utils/websearch.py` (Google CSE+DDG) ใช้เฉพาะ route `lmstudio_web` + agent tool registry
- ChromaDB uses `/api/v2/heartbeat` (not v1 — returns 410 Gone)
- Cloudflare tunnel returns 530 when origin down → check `cloudflared` container
- `static/skills/` (git) ≠ `data/skills/` (container mount) — copy needed after `git pull`
- **Container name**: docker-compose service `hybrid-ai` → actual container `ai-backend-1` (project name prefix). Use `docker restart ai-backend-1` not `hybrid-ai`
- **`ai-backend-1` "หาย" ซ้ำ → แก้ถาวรแล้ว ✅ 2026-06-17**: อาการ 2 ครั้ง (2026-06-14/15, 2026-06-17) — Container Manager/docker daemon restart → chromadb/cloudflared กลับมาเอง แต่ `ai-backend-1` **ถูกลบหายจาก `docker ps -a`** (restart policy ช่วยไม่ได้เพราะ container ไม่เหลือ). **แก้:** (1) `restart: always` (เหมือน chromadb) (2) healthcheck (python urllib→`/api/config:8000`, start_period 90s) (3) **`backend-watchdog`** (service ใน compose, image `docker:cli`) loop ทุก 60s — ถ้า `ai-backend-1` ไม่ running → `docker compose up -d hybrid-ai` (idempotent). watchdog mount `/volume1/homes/pawin/ui` ที่ path เดียวกับ host → compose-in-container resolve bind-mount ถูก. **recovery path verified** (boot-race ครั้งเดียวกู้สำเร็จจริง ไม่ flap). กู้ด้วยมือถ้าจำเป็น: `cd /var/services/homes/pawin/ui && sudo docker compose up -d hybrid-ai`
- **Port: app = `8080`, ChromaDB = `8000` (เจอจริง 2026-06-15)**: docker-compose map `8080:8000` → verify prod ที่ `http://192.168.51.49:8080` (เช่น `/api/status`, `/api/models`). ⚠️ ChromaDB ใช้พอร์ต `8000` เหมือนกันแต่ **bind `127.0.0.1` บน NAS ตั้งแต่ 2026-10-07** (จาก LAN ต่อไม่ได้แล้ว · ก่อนหน้านั้น `192.168.51.49:8000` = Chroma ตอบ 404 กับ path ของแอป) — อย่าสับสน.
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

## Internet Search / Classifier (2026-06-03)
`reasoning/classifier.py:needs_internet()` patterns เพิ่ม:
- ฝน/อากาศ: `ฝนจะตกไหม`, `วันนี้อากาศ`, `คืนนี้ฝน` ฯลฯ
- เน็ต: `เน็ตมาเลย`, `เช็คเน็ต`, `ไปดูในเน็ต`, `อินเทอร์เน็ต`, `search ให้`

`agents/orchestrator.py` เพิ่ม rule บังคับ:
- user พูด "ไปหาในเน็ต"/"เช็คเน็ต"/"search" → **ต้องเรียก `web_search` ทันที** ทั้งใน `AGENT_SYSTEM_HINT` และ `_REACT_SYSTEM`

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
curl -X POST http://NAS:8080/api/documents/ocr -F "file=@scan.pdf"
# สรุป
curl -X POST http://NAS:8080/api/documents/summarize -F "file=@report.pdf" -F "summary_type=general"
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

## ✅ Admin unlock endpoint (2026-06-01)
`POST /api/admin/unlock` — ล้าง auth-fail lockout สำหรับ IP ที่ระบุ (LAN/loopback เท่านั้น, 403 ถ้ามาจาก Cloudflare/public)
```bash
# ปลด lock IP ที่ระบุ (รันจาก LAN) — ต้องระบุ IP จริงของ client ไม่ใช่ NAS
curl -X POST http://192.168.51.49:8080/api/admin/unlock \
     -H "Content-Type: application/json" -d '{"ip": "CLIENT_IP"}'
# หา IP จาก log: docker logs ai-backend-1 2>&1 | grep "auth_fail\|lock" | tail -10
```
