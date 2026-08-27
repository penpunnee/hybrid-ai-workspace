# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 🗺️ อะไรอยู่ที่ไหน (จัดโครงใหม่ 2026-08-17)

**กติกา: ของโปรเจกต์อยู่ในโปรเจกต์** — เดิมบันทึกกระจาย 5 ที่ และวัดแล้วพบว่า
**ทั้งสามแหล่งจดคนละชุด ไม่ใช่สำเนากัน**: บรรทัดยาว >40 อักษรที่เหมือนกันเป๊ะ
`CLAUDE.md` ∩ `DEVLOG` = **0** · memory ∩ `DEVLOG` = **0** · memory ∩ `CLAUDE.md` = **2**
⇒ เซสชันที่โหลดมาทางเดียวได้ประวัติไม่ครบโดยไม่มีสัญญาณอะไรบอก · ยกเข้ารีโปหมดแล้ว

| ต้องการอะไร | เปิดที่ไหน |
|---|---|
| **เริ่มเซสชัน / งานถัดไป / ข้อห้าม** | หัวข้อ **▶️ เซสชันหน้าเริ่มตรงนี้** ในไฟล์นี้ — **ที่เดียว** |
| คำสั่งรัน/deploy/ทดสอบ | `## Commands` ข้างล่าง |
| สถาปัตยกรรม backend/FE/routing | `## Architecture` + [`CONTEXT.md`](CONTEXT.md) (glossary) |
| ประวัติงานย้อนหลัง | [`docs/session-log/`](docs/session-log/README.md) — `devlog.md` + `from-memory-status.md` |
| infra NAS / LMStudio / ChromaDB / deploy channel | [`docs/reference/infra-nas.md`](docs/reference/infra-nas.md) 🔴 อ่านก่อน deploy |
| โหมดขวัญอ่านนิยาย (`/ws/reader`) | [`docs/reference/reader-mode.md`](docs/reference/reader-mode.md) |
| แผนระยะยาว / ดีไซน์ / คู่มือ | [`ROADMAP.md`](ROADMAP.md) · [`DESIGN.md`](DESIGN.md) · [`GUIDE.md`](GUIDE.md) |
| React source ของ SPA | `~/appscript.ui/` (มี `CLAUDE.md` ของตัวเอง) — **แก้ UI ที่นั่น ไม่ใช่ overlay** |

### 🔴 กฎการจดตั้งแต่ 2026-08-17
1. **จบเซสชัน → เขียน `docs/session-log/devlog.md`** แล้วอัปเดตหัวข้อ ▶️ ในไฟล์นี้
2. **memory `hybrid_ai_status` / `hybrid_ai_infra` / `project_khim_reader` เป็นตัวชี้แล้ว
   ห้ามจดเนื้อหาลงไป** — git ตรวจย้อนได้ด้วย `git log -S` · memory ตรวจย้อนไม่ได้
3. `MEMORY.md` เก็บได้แค่ "เปิดไฟล์ไหนก่อน + ข้อห้ามที่ยังมีผล"
4. ⚠️ ไฟล์นี้ถูกฉีดเข้า context **ทันทีที่แตะไฟล์ใดก็ตามในรีโป** (nested CLAUDE.md ·
   เพดาน CLI = 4 MB จึงไม่มีการตัดให้) ⇒ **มันโตเมื่อไหร่เสียโควตาทุกเซสชันทันที**
   ตอนนี้ ~88 KB · บทเรียนเต็มที่ vault `wiki/concepts/claude-md-context-budget.md`
5. **ถังความจำของโปรเจกต์นี้:** `~/.claude/projects/-Users-pawin-Desktop-ui/memory/`
   — เปิดงานด้วย **`cc khim`** เท่านั้นถึงจะได้ถังนี้ (เปิดจาก `~` = ได้ถังกลาง คนละใบ)
   · `MEMORY.md` ในถัง = หน้าแรก (ตัวชี้/ข้อห้าม/งานค้าง) · โน้ตข้างเคียงเป็น **symlink
   ไปถังกลาง** = ไฟล์เดียวกัน **ห้ามแทนที่ด้วยสำเนา**
   · **จบเซสชัน → จดที่ `docs/session-log/devlog.md` แล้วอัปเดตหัวข้อ ▶️** ห้ามจดเนื้อหาลง memory

---

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

## ⏭️ งานค้าง ณ 2026-08-05/06 (ล่าสุดสุด — อ่านอันนี้ก่อน)

### ▶️ เซสชันหน้าเริ่มตรงนี้ (อัปเดต **2026-08-26 เย็น — ย้าย Gemini key + โมเดล**)

> ## ⚡ อ่านก่อน: โปรเจกต์ Gemini เปลี่ยนแล้ว (2026-08-26 เย็น)
> เครดิต prepay ของโปรเจกต์เดิม**หมด** ⇒ ทั้งแชทและเสียงยิงไม่ออกเลย (429 / Live 1011)
> · ย้ายไปโปรเจกต์ **free tier** แล้ว พร้อมเปลี่ยน `GEMINI_MODEL` → **`gemini-3.5-flash`**
> (ต้องเปลี่ยนคู่กัน — `gemini-2.5-flash` คืน 404 "no longer available to new users"
> บนโปรเจกต์ใหม่) · verify ครบวงบน prod แล้ว (แชท 200 + Live ได้เสียง 7,682 ไบต์)
> · rollback = สลับ key กลับจาก `.env.bak-20260826` · รายละเอียดเต็มใน devlog "08-26 เย็น"
>
> 🔴 **โควตา ≠ เครดิต** — หน้าโควตา AI Studio แถบยังไม่เต็มทั้งที่ยิงไม่ออกสักครั้ง
> ⇒ ห้ามใช้แถบโควตาเป็นหลักฐานว่า "ยังใช้ได้"
> 🔴 **ผลข้างเคียงที่ยอมรับไปแล้ว:** วาดรูปพัง (429 image quota) · เสียงเข้าชุดข้อมูล Google
> (free tier) — แชทข้อความไม่กระทบ เพราะ `route()` ส่งไป LM Studio ในบ้านอยู่แล้ว
> 🟡 **TTS ยังไม่พิสูจน์** ว่าใช้ได้บนโปรเจกต์ใหม่
>
> ## ✅ ตัวกู้ไมค์ **สำเร็จจริงแล้ว** (2026-08-26 14:59 · `sig=1`)
> `signal=0 → 61` หลังกดปุ่ม · ตัวจุดชนวนที่ยิงคือ **`zeros`** ไม่ใช่ `ended`
> · รูที่เจอตามมา (`recover-result` หายเพราะ WS ยังไม่ OPEN) **ปิดแล้ว** (`a5bfc93`)
> · bundle ปัจจุบัน **`index-D_Yv5ltW.js`**
>
> ## ⚡ โมเดลแชทเปลี่ยนแล้ว (2026-08-27)
> `GEMINI_MODEL=gemini-3.5-flash-lite` · `GEMINI_FALLBACK_MODEL=gemini-3.1-flash-lite`
> — ตัว `gemini-3.5-flash` บนโปรเจกต์นี้ **โควตาเต็ม + กะพริบ** (OK 5s / OK 6.8s /
> timeout 25s) ส่วน Lite ตอบ 0.8 วิเสมอ
> 🔑 **โควตา Gemini เป็นรายโมเดล ไม่ใช่รายโปรเจกต์** — วัดแล้ว: flash 429 แต่ Lite OK
> และสายเสียงได้เสียง 8,642 ไบต์ในนาทีเดียวกัน ⇒ อย่าเหมาว่า "Gemini ล่ม"
>
> ## 🥇 งานแรก: **อ่าน `underruns` จาก heartbeat หลังใช้เสียงจริงอีกรอบ**
> เพิ่งใส่ตัวนับ worklet underrun เพื่อตอบอาการ "เสียงดังบ้างเบาบ้าง"
> · `[VoiceLevel]` พิสูจน์แล้วว่า**ต้นทางนิ่ง** (-15.8 ถึง -17.8 dBFS ทุกตัวอย่าง)
> ⇒ ถ้า `underruns>0` ตรงกับช่วงที่หูได้ยินว่าเบา = เจอตัวการ · ถ้าเป็น 0 ตลอด
> = **ไม่ใช่ underrun** ต้องไปดู audio session ของ iOS แทน
> ```bash
> ssh nas 'sudo -n /usr/local/bin/docker exec ai-backend-1 \
>   sh -c "grep -a underruns /app/logs/server.log | tail -30"'
> ```
> ⚠️ ห้ามแตะค่าเสียง/จังหวะก่อนมีตัวเลข (ของต้องห้ามเดิม)
> ตัวกู้ไมค์ (ก1) **deployed + verified บน prod แล้ว** (`e97c9ac` appscript.ui ·
> `80cfe69` ui · bundle **`index-DZsRgW3D.js`** md5 ตรง host=container)
> แต่ **ยังไม่เคยมีใครกดปุ่มนี้บนเครื่องจริง** ⇒ ยังไม่มีข้อมูลของรอบกู้สักบรรทัด
>
> 🎁 **repro:** เปิดโหมดคุยด้วยเสียงบน iPhone (รีเฟรชเอา bundle ใหม่) →
> **ปัดขอบบนลงจนสุด** (ตัวจุดชนวนที่พิสูจน์แล้ว) → กลับมา → ปุ่ม "🔄 แตะเพื่อกู้ไมค์"
> ต้องขึ้น → กด → อ่านผล
> ```bash
> ssh nas-cf 'sudo -n /usr/local/bin/docker exec ai-backend-1 \
>   sh -c "grep -aE \"recover-|mic_probe\" /app/logs/server.log | tail -40"'
> ```
> **สิ่งที่ต้องอ่านให้ออก:** `recover-attempt n=1 reason=…` → `recover-result n=1 ok/fail
> ready= sig=` (+250ms) → `recover-health n=1 … sig=1` (+10 วิ) ·
> 🔑 **`sig=1` ใน `recover-health` คือบรรทัดเดียวที่แปลว่า "กู้สำเร็จจริง"**
> — `ready=live` ไม่ใช่ (โหมด `zeros` เกิดบน track ที่ live ทุกประการ)
>
> ## ✅ ตัวกู้ไมค์ (ก1) — ทำอะไรไปแล้ว (อย่ารื้อ)
> - ตัวจุดชนวน **3 ทางครบ**: `no-callback` (2 วิ) · `zeros` (10 วิ) · **`ended`** (ใหม่ ·
>   แน่นอนที่สุด ไม่ต้องรอนับ) — ทั้งสามใช้ `micSilentReported` เป็น edge-trigger ตัวเดียวกัน
> - `micHealth()` คืน 2 ค่า **ห้ามยุบเป็นค่าเดียว**: `ready` (เร็ว/ไม่ชี้ขาด) ·
>   `sigSeen` (ช้า/ชี้ขาด — เฟรมศูนย์ล้วนไม่นับ)
> - `utils/micrecover.ts` เพดาน **3 รอบ** · 🔴 **`end(true)` ไม่ล้างตัวนับ** มีแต่
>   `reset()` ตอน `sigSeen` ที่ล้างได้ ⇒ กันลูป "กู้แล้วตายแล้วกู้"
> - `recoverMic()` เดิน `stopVoice()`+`startVoice()` (เส้นทางที่ทุกสายเดินอยู่แล้ว) ·
>   `getUserMedia` ถูกเรียกก่อน await ตัวแรก ⇒ ยังอยู่ใน gesture task
> - mutation **8/8 ถูกฆ่า** · เทส 442/442 · รายละเอียดเต็มใน devlog "2026-08-26 บ่าย"
>
> ## 🔜 งานถัดไปหลัง repro
> - ✅ **ปิดแล้วทั้งสองข้อ (`0c8e331`)**: default โมเดล → `GEMINI_MODEL_DEFAULT`
>   (`gemini-3.5-flash`) + `RETIRED_GEMINI_MODELS` มีเทสตรึง · `/api/status` มี
>   **`gemini_ok` / `gemini_message`** ที่ยิง `:generateContent` จริง แยก "เครดิตหมด"
>   ออกจาก "โควตาเต็ม" (cache 5 นาที) · พิสูจน์กับ key เก่าที่เครดิตหมดบน prod แล้ว
>   ✅ **ขึ้นจอแล้วด้วย** (`e3be2bb`/`95f32cb` · bundle `index-CWv847Pl.js` md5 ตรง) —
>   แถบเหนือ ChatBox จาก `utils/cloudstatus.ts` (มีเทส · mutation 8/8)
>   🔴 **ต้องเป็นแถบข้อความ ไม่ใช่ tooltip** — เครื่องหลักคือ iPhone ไม่มี hover
> - 💡 **`ssh nas-cf` ค้าง/timeout ทั้งที่ tunnel healthy = Cloudflare Access หมดอายุ**
>   (มันพยายามเปิดเบราว์เซอร์ให้ล็อกอินแล้วรอค้าง) — แก้ด้วย
>   `cloudflared access login https://ssh.pawinhomelab.com` · อยู่ในบ้านใช้ **`ssh nas`** ได้เลย
>   🔴 อาการที่เห็น ("timed out during banner exchange") ไม่ได้บอกสาเหตุ — ต้องดู output
>   ของคำสั่งที่ค้างจริง ๆ ถึงจะเห็นบรรทัด "If the browser failed to open…" 
> - **ก2** (`getUserMedia` ใหม่ ไม่แตะ WS ⇒ ความจำอยู่ครบ) — ยกระดับเมื่อ user รำคาญ
>   ว่าขวัญลืมเรื่องที่คุยทุกครั้งที่กู้ · ก1 เป็นฐานที่วัดผลได้แล้ว
> - เสียงลำโพงแตกตอนปัดจอลง (ของเก่า ไม่ใช่ regression · ยังไม่มีตัวเลขวัด — ดูข้างล่าง)
>
> ## 📦 (ปิดแล้ว) ทางเลือกตอนยังไม่เคาะ — เก็บไว้อ้างอิงราคาของ ก1/ก2
>
> | | วิธี | ราคา |
> |---|---|---|
> | **ก1** | ตรวจเจอ → ขึ้นปุ่ม "แตะเพื่อกู้ไมค์" → รีสตาร์ตสายเสียงทั้งเส้น (ใช้เส้นทาง `stopVoice()`+`startVoice()` ที่รันทุกสายอยู่แล้ว = พิสูจน์แล้วด้วยการใช้งาน) | 🔴 **ความจำบทสนทนาหาย** (`resume_handle` เป็น local ของ WS handler `server.py:287`) |
> | **ก2** | `getUserMedia` ใหม่ + สร้าง graph ใหม่ **ไม่แตะ WS** | ✅ ความจำอยู่ครบ · ผิวสัมผัสใหม่ ต้องเทสหนัก |
>
> **จุดชนวนต้องครอบ 3 ทาง** (มี 2 โหมดความล้มเหลว พิสูจน์แล้วทั้งคู่):
> `silent reason=no-callback` (เร็ว 2 วิ) · `silent reason=zeros` (10 วิ) · `track.onended` (แน่นอน)
> - ⚠️ **ยังไม่เคยเห็น "กู้สำเร็จในหน้าเดิม" สักครั้ง** — ใส่ probe `recover-attempt`/
>   `recover-result` ตั้งแต่แรก ไม่งั้นเคสแรกก็ต้องเดาอีก
> - ต้องคัด constraint เดิม (`echoCancellation`/`noiseSuppression`/`autoGainControl`
>   `voicelive.ts:154`) + **เทสตรึง** · เพดาน 3 รอบ + ตรวจซ้ำ 250ms · ล้มแล้วโชว์ error จริง
> - 🔴 `getUserMedia` รอบใหม่บน iOS ต้องมี **user gesture** ⇒ ปุ่มคือทางที่ปลอดภัยที่สุด
>
> ## ✅ พิสูจน์แล้วทั้งหมด (อย่ารื้อ อย่าไล่ซ้ำ)
> - **อาการมี 2 โหมด ไม่ใช่โหมดเดียว**
>   | | `no-callback` | `zeros` |
>   |---|---|---|
>   | เห็นอะไร | `frames=0 armed_ms≈5000` | `frames=59 **signal=0**` |
>   | เกิดเมื่อ | 08:32 · 10:08 น. | 12:53 น. |
>   | `resume-failed` | ✅ มี | ❌ ไม่มี |
> - **จบที่ `MediaStreamTrack.readyState === 'ended'` ทั้งคู่** — iOS ฆ่า track เอง
>   (`track.stop()` ของเรามีที่เดียวใน `disconnect()`) ⇒ ปลุกไม่ได้ตามสเปก
>   **ต้อง `getUserMedia()` ใหม่เท่านั้น**
> - **`resume()` ตอนจอถูกซ่อน ไม่ใช่ต้นเหตุ** — `8ae9785` กันได้จริง (`resume-failed` 0 ครั้ง
>   ทั้งที่ `vis=hidden` เกิดจริง) **แต่ไมค์ยังตาย** ⇒ สหสัมพันธ์ 3/3 ก่อนหน้าเป็นตัวแปรกวน
>   · **เก็บ gate ไว้** ไม่มีผลเสีย แต่ป้องกันไม่พอ
> - **การแก้ ticker (`0f3b17d`) ไม่ใช่ตัวแก้อาการนี้** — WS ไม่เคยหลุด · เก็บไว้ ไม่ revert
> - **ธง `muted`/`enabled`/`cap` ไม่เคยชี้ขาด** มีแค่ `readyState` + `signal_frames`
> - **ตัวจุดชนวนฝั่งผู้ใช้ = ปัดขอบบนลงจนสุด** ไม่ใช่สายโทรเข้าอย่างที่เข้าใจมา 5 วัน
>
> ## 🔬 ชั้นวัดที่มีแล้ว (bundle **`index-BYJck1po.js`**) — ใช้อ่านผลได้เลย
> ```bash
> ssh nas-cf 'sudo -n /usr/local/bin/docker exec ai-backend-1 \
>   sh -c "grep -a mic_probe /app/logs/server.log | tail -40"'
> ```
> `heartbeat` ทุก 5 วิ (`frames`/`signal`/`armed_ms`) · `vis=` · `user-mute`/`user-unmute` ·
> `resume-failed` แยกรายขา · `[Voice WS] เปิดสาย` (นับครั้ง + ระยะห่าง)
> 🔑 **`armed_ms` คือตัวหาร**: `frames=0 armed_ms=5069` = ไมค์ตาย · `frames=0 armed_ms=0` = ประตูปิด
> 🔑 **`signal_frames` คือตัวชี้ขาดโหมด `zeros`** — `frames=59 signal=0` ดูเหมือนปกติถ้าดูแค่ `frames`
> 🔑 `ready=ended` แต่ `frames>0` **ไม่ขัดกัน** — ScriptProcessor ขับด้วย AudioContext ไม่ใช่ track
>
> ## 🔊 เสียงลำโพงแตกตอนปัดจอลง — **ของเก่า ไม่ใช่ regression**
> user รายงานคำเดียวกันตั้งแต่ 08-24 ก่อนแตะโค้ด · vault `ios-web-audio-playback-distortion.md`
> ⚠️ **ยังไม่เคยมีตัวเลขวัด** — ไอเดียที่ถูกที่สุด: เด้งจำนวน underrun ของ worklet
> (`primed=false` ตอนคิวหมด `WORKLET_SRC`) กลับมาแบบเดียวกับ heartbeat
> ⚖️ ข้อสรุปเดิม: ย้าย playback ไป ManagedMediaSource = **ไม่คุ้ม**
>
> ## 🔴 บทเรียนของเซสชันนี้
> - **ถอดของที่ "ไม่มีประโยชน์" ต้องถามว่ามันเคยกัน *อะไร* ไว้โดยบังเอิญ** — ถอด rAF
>   ออกจาก ticker ด้วยเหตุผลที่ถูก แต่มันเคยกันการเรียก `resume()` ตอน hidden ไว้
> - **สรุปจาก "ความเงียบใน log" ผิด 2 รอบ** — `[VoiceLevel]` วัดเสียง**ขวัญ** ไม่ใช่ไมค์
> - **สรุปโหมดความล้มเหลวจากตัวอย่างโหมดเดียว ผิด** — ประกาศว่า "`zeros` ไม่ใช่อาการนี้"
>   แล้ววันเดียวกันก็เจอ `zeros` ของจริง
> - **`toBeDefined()` ปล่อย `null` ผ่าน** · **เทสที่เรียกเมธอดตรงไม่เคยตรวจว่ามีใครเรียกมัน**
>   (mutation จับได้ 3 รอบในเซสชันเดียว: M6 · H1 · เทส rAF ที่ผ่านด้วย tick เดียว)
> - **mutation ต้อง fail-loud** — regex ที่ไม่ match รายงาน "pass" ครบ
>
> 📋 งานเล็กที่ค้าง (ยังเหมือนเดิม) ดูบล็อกเก่าข้างล่าง ·
> 🆕 `utils/bookreader.ts:114` คอมเมนต์อ้าง "ห้ามใช้ rAF แบบ voicelive.ts" — **ตกรุ่นแล้ว**

---

### ▶️ (บล็อกเดิม 2026-08-24 — ตารางอ่านผล mic_probe ตกรุ่นแล้ว ดูข้างบนแทน)

> ## 🥇 งานแรก: **ถามผล `mic_probe` จาก user ก่อน**
>
> ชั้นวัดสภาพไมค์ deploy แล้ว (`2fa1cbd` · bundle **`index-Bmuq8taZ.js`**) **แต่ยังไม่มี
> ใครทำ repro** ⇒ ยังไม่มีข้อมูลสักบรรทัด
>
> 🎁 **repro:** เปิดโหมดคุยด้วยเสียงบน iPhone (รีเฟรชเอา bundle ใหม่) → **เรียก Siri
> กลางสาย → ปัดออก → พูดต่อ** (หรือรอสายเข้าจริง)
>
> ```bash
> ssh nas-cf 'sudo -n /usr/local/bin/docker exec ai-backend-1 \
>   sh -c "grep -ah mic_probe /app/logs/server.log | tail -30"'
> ```
>
> **อ่านผลยังไง — นี่คือทางแยกของงาน ค. ทั้งก้อน:**
> | เห็นอะไร | แปลว่า | ทำอะไรต่อ |
> |---|---|---|
> | `muted=?` หรือ `muted=False` และ**ไม่มี**บรรทัด `mic_probe unmute` | iOS ไม่ตั้งธง (Twilio #941 ถูก) | ใช้เกณฑ์นับศูนย์เป็นตัวจุดชนวนต่อไป — ยอมรับ 10 วิ |
> | `muted=True` + มีบรรทัด `mic_probe unmute` | ธง+event ใช้ได้ (Twilio/LiveKit/Chime ถูก) | **เปลี่ยนตัวจุดชนวนเป็น `unmute` → ไวขึ้นจาก 10 วิเหลือทันที** + debounce 5000ms แบบ LiveKit |
> | `cap=interrupted` ตอนป้ายขึ้น | context ค้างด้วย (คนละอาการ) | ไล่ `wakeAudio()` ก่อน อย่าเพิ่งไป ค. |
> | `reason=no-callback` (ขึ้นใน ~2 วิ) | callback หยุดยิง ไม่ใช่ track ตาย | **คนละบั๊ก** ต้องแยกไล่ |
>
> ---
>
> ## 🔵 งาน ค. ปุ่ม/ตัวกู้ไมค์ — **แบบตกผลึกแล้ว รอแค่ตัวจุดชนวน**
>
> 3 SDK ใหญ่ (Twilio · LiveKit · Amazon Chime) ทำเหมือนกันหมด — ไม่ต้องคิดเอง:
> ```
> จุดชนวน:  ← รอผล mic_probe ตัดสิน (ตารางข้างบน)
>    ↓  ถ้านิยายเล่นอยู่ → ไม่ทำอัตโนมัติ ขึ้นปุ่มอย่างเดียว
> กู้:      track.stop() → capCtx.close() → getUserMedia(constraint ชุดเดิม) → สร้าง graph ใหม่
>    ↓
> ตรวจซ้ำ:  200–250ms ว่าไม่เงียบจริง → ยังเงียบ? ทำซ้ำ **เพดาน 3 รอบ**
>    ↓
> ล้ม/error/เด้ง prompt → ขึ้นปุ่ม "แตะเพื่อกู้ไมค์" + **โชว์ error จริง**
> ```
> - 🔴 **`stop()` ก่อน `getUserMedia` เสมอ** — คอมเมนต์ใน production ของ Twilio ยืนยัน
>   *"ไม่งั้นเสียงที่ได้กลับมาจะยังเงียบอยู่ดี"*
> - 🔴 **ต้องคัด constraint เดิมมาด้วย** (`echoCancellation`/`noiseSuppression`/
>   `autoGainControl` — `voicelive.ts:153`) · `{audio:true}` เปล่าๆ = AEC หาย = บั๊กที่
>   ปิดไป 3 ชั้นกลับมาทันที ⇒ **ต้องมีเทสตรึง constraint**
> - 🥇 **ตรวจซ้ำ + เพดาน 3 รอบคือคำตอบของความกลัว "infinite retry loop"** — ทางแก้ไม่ใช่
>   "ห้าม retry" แต่คือ "ตรวจให้แน่ว่าตัวใหม่ใช้ได้ + ใส่เพดาน" (`workaround180748.js`)
> - ⚠️ **ปิดปุ่มระหว่างนิยายเล่น** — `getUserMedia` บน iOS บังคับ output ไปลำโพงในตัว
>   + attenuate เสียงที่เล่นอยู่ · (แต่ Khim เล่นผ่าน AudioWorklet ล้วน ไม่มี `<audio>`
>   ⇒ ความเสี่ยงต่ำกว่าที่เคยเตือน) · โหมดแชท user เคาะแล้ว: **หยุดเสียงขวัญก่อนแล้วกู้**
> - ⚠️ **iOS 26.1 beta: `getUserMedia` พังทั้งดุ้น** (`No AVAudioSessionCaptureDevice
>   device`) ⇒ ตัวกู้ต้องโชว์ error จริง ห้ามเงียบแล้ว retry
> 🔑 วิธีทำทั้งหมด + แหล่งอ้างอิง 20 กว่ารายการ: vault
> `wiki/concepts/ios-audio-interruption-recovery.md` (368 บรรทัด · **อ่านก่อนลงมือ**)
>
> ## ⏳ งาน ก. ยังไม่ verify — ต้องเปิดอ่านนิยายจริงสัก 1 ตอน
> `grep -c "ป้อนท่อน|ท่อนจบ|ที่คั่น"` ทั้ง `server.log` = **0 ตั้งแต่ 18 ส.ค.**
> ⇒ ยังไม่มีใครใช้โหมดนี้เลย · repro: ฟังนิยาย → Siri → ปัดออก → เสียงกลับมาเองใน ~1 วิไหม
>
> ## 📋 งานเล็กที่ค้างอยู่
> 1. **ล้าง env ผีในเอกสาร 4 จุด** — โค้ดไม่อ่านแล้วแต่เอกสารยังโฆษณา:
>    `CLAUDE.md:313` `LMSTUDIO_EMBED_MODEL` · `CLAUDE.md:307` `OLLAMA_EMBED_MODEL`
>    (+ ชวนให้ `ollama pull nomic-embed-text` = ตัวที่มีบั๊กไทย!) ·
>    `CLAUDE.md:165` อธิบายทิศทาง fallback **กลับหัวกลับหาง** (ของจริง Ollama = ตัวหลัก) ·
>    `skills/env-variables-reference.md:32`
> 2. `GEMINI_LIVE_MODEL` ไม่มีใน `.env` เลย = ใช้ค่า hardcode `utils/voice.py:62`
>    (`gemini-3.1-flash-live-preview`) — จะยกขึ้น `.env` ไหม
> 3. **AnythingLLM ตกรุ่น 4 ตัว** (v1.14.0 → 1.16.0) — หรือจะปิดทิ้งถ้าไม่ได้ใช้ (image 3.34 GB)
> 4. โมเดล local 5 ใน 8 ตัวไม่มี env อ้างถึง ~14 GB · `llama3` ที่ผูกไว้เป็น Q4_0
>    ทั้งที่มี `llama3.1:8b` Q4_K_M นอนอยู่ข้างๆ
>
> ---
>
> ## ✅ ปิดคดีแล้ว 08-21 → 08-24 (อย่ารื้อ)
> - **"คำตอบหลังค้นเว็บหาย"** (เปิดมาตั้งแต่ 08-14) — 08-24 เช้ามีสายจริง 12 นาที
>   ค้น 5 ครั้ง `ค้นเสร็จ ตอบกลับ 1 ตัว` **5/5** · interrupt 5 ครั้งไม่มีอันไหนที่จังหวะค้นเสร็จ
>   (ตัวชี้ขาดคือ field `เสร็จเมื่อ N ก่อน` — อันเดียวที่แตะการค้นคือ 41.4s = สลับตาพูดปกติ)
> - **ธง ⚠️ over-fire** · **watchdog Gemini ตายเงียบ** · **`sync_vault` ไม่ prune** · `fe0279c` `c1a10aa`
> - **ก. ปลุก AudioContext ของ reader** `4a77c9c` — deploy แล้ว ⏳ ยังไม่ verify
> - **ข. ป้ายไมค์เงียบ** `ef4ea7b` — ✅ **verify ผ่าน 08-24 ด้วยสายเข้าจริง**
> - 🆕 **บั๊ก embedding พิษ** `61ca0bf` + `81ef69d` — deploy + verify บน prod แล้ว ·
>   ตรวจย้อนหลังครบทุกแถว **ไม่มีของเสียปน**
> รายละเอียดทั้งหมด: `docs/session-log/devlog.md` หัวข้อ [2026-08-24]
>
> ## 🔴 กติกาที่ได้บทเรียนมาแล้ว — อ่านก่อนลงมือ
> - ✅ **รันชุดเต็มบนเครื่องได้ ~45 วินาที — ทำทุกครั้งก่อน push**
>   ```bash
>   uv venv /tmp/uivenv --python 3.12 && VIRTUAL_ENV=/tmp/uivenv uv pip install -r requirements.txt
>   LOG_FILE=/tmp/test.log /tmp/uivenv/bin/python -m pytest -q     # 1640 passed / 15 skipped
>   uvx ruff check .
>   cd ~/appscript.ui && npx vitest run utils/ && npx tsc --noEmit  # 397 passed
>   ```
>   🔑 **`LOG_FILE=` สำคัญ** — ไม่ตั้ง = เขียนทับ `server.log` ที่ใช้ verify
> - ❌ **ห้ามรัน pytest ในคอนเทนเนอร์ prod** — 08-24 พิสูจน์แล้วว่าทำให้ **log อ่านผิด**:
>   fallback 33 ครั้งใน log กลายเป็น fixture ของเทส (`'x'` `'q'` `'test'`) ไม่ใช่ traffic จริง
> - 🔴 **ก่อนแก้ฟังก์ชันไหน `grep -rl "<ชื่อ>" tests/` ก่อนเสมอ**
> - 🔴 **ก่อนค้นเว็บเรื่องที่เคยไล่มาก่อน เปิด `wiki/index.md` ก่อน**
> - **mutation test ทุกชิ้นที่แก้ + ล้าง `__pycache__` ทุกรอบ** — 08-24 ยิง 10 แบบ **รอด 1**
>   (ถอด `watchMicTrack()` ออกจาก `connect()` แล้วเทสเขียว 65/65 เพราะเทสเรียกเมธอดตรง
>   ไม่เคยตรวจว่ามีใครเรียกมันจริง) ⇒ **ปิดด้วยด่านอ่านซอร์ส**
> - 🆕 **assertion ที่อยู่ผิดฝั่ง = เทสที่ผ่านฟรี** — `test_embed_fallback_uses_same_model_name`
>   ตรวจ *request* ว่าขอถูกโมเดล ไม่เคยตรวจ *response* ว่าได้อะไรมา ⇒ บั๊กรอดมา 22 วัน
>   **ถามเสมอ: เทสนี้ยืนยันฝั่งไหน — สิ่งที่เราส่งไป หรือสิ่งที่เราได้กลับมา**
> - 🆕 **สุ่มตัวอย่างตอบคำถาม "มีของเสียปนไหม" ไม่ได้** — ต้องตรวจครบทุกแถว
> - 🆕 **ลำดับความน่าเชื่อของแหล่ง: เทสของเอนจิน > ซอร์ส production > บล็อกทดลอง >
>   issue tracker** · หน้าสรุปเอกสารก็โกหกได้ (MDN เขียนแค่ "experimental" ต้องเปิด
>   browser-compat-data ตัวดิบ)
> - **deploy backend = `git reset --hard` + `docker restart`** (โฟลเดอร์ `utils/` `routers/`
>   mount เป็น directory เห็นทันที) · **ไม่ต้อง rebuild/`--force-recreate`** ซึ่งเคยล้มกลางทาง
>   · ⚠️ `server.py` เป็น bind mount **ไฟล์เดี่ยว** มีกับดัก inode — ถ้าแก้ไฟล์นั้นต้องเช็ค
>   `ls -i` host เทียบ container (`docs/reference/infra-nas.md`)
> - **ก่อน `sync_static.sh`** — 08-24 ใช้วิธีถูกและเร็ว: CSS hash ที่ build ได้ตรงกับที่
>   prod เสิร์ฟอยู่ = toolchain reproduce ของเดิมได้ ⇒ sync ปลอดภัย

#### ▼ สถานะรอบ 2026-08-17 บ่าย

> ✅ **แก้ครบ 4 อาการของโหมดอ่านนิยาย + deploy + ยืนยันด้วย log จริงแล้ว**
> commit: `f4e62e8` → `5f190d4` (server+bundle) · `4ec0cb7` → `a627f3f` (React source)
> bundle ที่เสิร์ฟจริงตอนนี้ = **`index-DD3rJ0CH.js`**

#### สิ่งที่ปิดไปแล้ว (พิสูจน์จาก log prod ไม่ใช่จากเทสอย่างเดียว)

| อาการ | ตัวแก้ | หลักฐานบน prod |
|---|---|---|
| **ตัวอ่านซ้อน** | `bookToggleAction()` คลุมครบ 4 ค่าของ `ReaderStatus` + `app.tsx` เรียกตัวตัดสินตัวเดียว + `disconnect()` ก่อน `new BookReader()` เสมอ | `เปิด`/`ปิด` สลับกันเป๊ะ ไม่มี `เปิด` ซ้อน |
| **ประโยคเดิมซ้ำทับกัน** | regen ส่ง `{"type":"flush"}` ก่อนอ่านท่อนซ้ำ | ยังไม่ได้ทดสอบเส้นนี้ (ไม่มี go_away ในรอบเทส) |
| **ขวัญตอบทับเสียงนิยาย** | `HalfDuplexGate` เพิ่ม timeline ที่สอง `extUntil` · เสียงนิยายชนะสวิตช์พูดแทรก | อ่าน 5 นาที 41 วิ ขวัญเงียบสนิท |
| **กดพักแล้วยังพูดต่อ** | `reader_stream_action()` ลูปสตรีมดูธง `paused` ทุก chunk | `12:49:51 พักกลางท่อน → หยุดส่งเสียงทันที` · ที่คั่นไม่ขยับ |
| **🔁 อ่านท่อนนี้ใหม่** (ใหม่) | ปุ่ม + คำสั่ง `reread` (ไมค์ปิดตอนอ่าน จึงสั่งด้วยเสียงไม่ได้) | ยังไม่ได้กดทดสอบ |

🔑 **ตัวเลขที่ปิดคดีข้อถกเถียงเก่า:** ที่คั่นเดินที่ **13.8 ตัวอักษร/วินาที** (12253→16965 ใน 5:41)
เทียบกับตอนพัง 08-14 ที่ **185.9 ตัว/วินาที** = ช้าลง **13.5 เท่า ทั้งที่ไม่มี pacing เลย**
⇒ **"ที่คั่นวิ่งหนี" เกิดจากตัวอ่านซ้อน ไม่ใช่จากป้อนเร็วเกิน** · `reader_pacing_wait` ของ
`55b8594` เป็นการรักษาปลายเหตุ — **ไม่ต้องเอากลับแล้ว** (`stash@{0}` ที่ผูกกับมันก็ทิ้งได้)

#### 🔴 งานค้าง เรียงตามที่ควรทำ

> ✅ **08-18: เติม log ครบแล้ว (`2df117b` deployed+verified ในคอนเทนเนอร์)** — ข้อ 4 ปิด ·
> ด่านที่บล็อกข้อ 1 (พิสูจน์ไม่ได้เพราะไม่มี log) ปลดแล้ว **เหลือแค่รอข้อมูลจากการใช้จริง**

1. **คำตอบหลังค้นเว็บหาย เหลือแต่ข้อความบนจอ** (โหมดแชท — ✅ **ชี้ขาดแล้ว 08-18 ดูบล็อก 🥇**)
   ต้นเหตุที่ยืนยันแล้ว: **ไมค์เปิดกลาง turn** (turn ยังเปิดตอนโดน `interrupted` — พิสูจน์จาก
   สเปก + พยาน `search_count`) → เสียงแวดล้อมเข้าไป → ตัด turn → `flushPlayback()`
   ล้างเสียงทิ้ง **แต่ไม่แตะข้อความ** = ลายเซ็นตรงกับที่ user เล่าเป๊ะ · เหลือยืนยันซ้ำ
   1 รอบบน prod สะอาด (หลัง `dd8f273`) ก่อนลงมือแก้ประตู
   ▶️ **ขั้นถัดไป: คุยด้วยเสียง + ถามคำถามที่ต้องค้นเว็บสัก 2-3 รอบ แล้วอ่าน log**
   ```bash
   ssh nas-cf 'sudo -n /usr/local/bin/docker exec ai-backend-1 \
     sh -c "grep -hE \"interrupted|เริ่มค้น|ค้นเสร็จ\" /app/logs/server.log.1 /app/logs/server.log | tail -40"'
   ```
   - เห็น `interrupted` ที่ยังพิมพ์ **"ค้น N ครั้งใน turn นี้"** (= turn ยังเปิด) ⇒ ลายเซ็น
     ยืนยันซ้ำ → ลงมือแก้ประตู: `HalfDuplexGate` รู้สถานะ turn ผูกกับ event `done`
   - เห็นแต่ `interrupted` ที่ **"ไม่ได้ค้นใน turn นี้"** + เงียบเศษวินาที ⇒ เป็นการพูดแทรก
     ปกติ ไม่ใช่บั๊ก — เช็คสวิตช์พูดแทรก (ต้อง**ปิด**) ก่อนสรุปอะไรต่อ
2. **Gemini ตายเงียบกลางท่อน ไม่ฟื้นเอง** — prod ไม่มี watchdog (revert `2670c8e` ตั้งแต่ 08-15)
   ถ้าจะเอากลับ **เอาเฉพาะ watchdog อย่าเอา pacing** (ข้อ 🔑 ข้างบน)
   · ตอนนี้ลายเซ็นอ่านจาก log ได้แล้ว: `ป้อนท่อน …` ที่**ไม่มี** `ท่อนจบ …` ตามมา
3. **voice idle 1008-loop** ยังอยู่ · และตอนนี้**แย่ลงโดยอ้อม**: ไมค์ปิดตอนอ่านนิยาย ⇒ session
   แชทเสียง idle ตลอดเวลาที่ฟังนิยาย ⇒ 1008 ทุก ~151 วิ ตลอดทั้งเล่ม (เห็นจริง `05:52:19` UTC)
4. ✅ **log ต่อท่อน — ปิดแล้ว 08-18** (`reader_feed_log_line` / `reader_turn_log_line`
   ใน `utils/voice.py` · 1 คู่/ท่อน ≈ 1 คู่/นาที · รายงานวินาทีของเสียงเทียบเวลาจริง)

#### 🔑 บทเรียนเซสชันนี้

- 🔴 **CI แดงมา 3 commit ตั้งแต่ `f4e62e8` โดยไม่มีใครรู้ — เจอเพราะรัน `ruff check .` เอง**
  (08-18) สาเหตุ: `elif t == "reread"` ถูกก๊อปจาก `/ws/reader` ไปวางใน handler **เสียง**
  ซึ่งไม่มีธง `reread` ⇒ `F821` · และถ้ามี client ยิงคำสั่งนั้นเข้าสายเสียงจริงจะได้
  `NameError` → `except Exception` → `stop.set()` = **ตัด session เสียงทิ้งทั้งเส้น**
  ⚠️ **prod deploy ผ่านได้ทั้งที่ CI แดง** (deploy ไม่ได้ผูกกับ CI) ⇒ "ใช้งานได้อยู่"
  ไม่ใช่หลักฐานว่า CI เขียว — **เปิด `gh run list` ดูก่อนเริ่มงานทุกครั้ง**
- ⚠️ **assertion ที่อ่าน "ตัวหนังสือ" แทน "โค้ด" วัดผิดสิ่ง** — เทส `"reread" not in src`
  แดงเพราะไปโดน**คอมเมนต์ที่อธิบายบั๊กนั้นเอง** ⇒ เปลี่ยนไปเดินด้วย `ast` (เก็บเฉพาะ
  `ast.Name` ในฟังก์ชันจริง) · เทสที่ผูกกับ source เป็นสตริงมีกับดักนี้เสมอ
- **จุดบอด log เจอ 2 ที่ในวันเดียว** — `/ws/reader` มี log แค่ 3 บรรทัดใน 17 วัน และ
  `interrupted` ไม่ถูก log เลย ⇒ อาการทุกข้อ **พิสูจน์ไม่ได้โดยโครงสร้าง ไม่ใช่หาแล้วไม่เจอ**
  · ก่อนสรุปว่า "log ไม่พบ" ต้องเช็คก่อนว่า **เครื่องมือวัดมีตาไหม**
- 🔴 **ก๊อปโครงสร้างมาแล้วต้องก๊อป *เหตุผล* มาด้วย** — `clearExternal()` ตั้ง `extUntil = 0`
  ตาม `reset()` แต่ `reset()` ถูกเรียกตอนผู้ใช้*ตั้งใจ*แทรก (อยากให้ไมค์เปิดทันที) ส่วน
  `clearExternal()` ถูกเรียกตอนเสียงจบเอง = คนละเจตนา ⇒ ข้ามหาง 350ms ⇒ กด ⏹ หยุดนิยาย
  แล้วขวัญแทรกทันที (เสียง "ป๊อก" ตอน flush กลางบัฟเฟอร์เข้าไมค์) — **แก้แล้วใน `a627f3f`**
- 🔴 **`obj.cb?.(f(x))` — optional call ที่ `undefined` ไม่ประเมิน argument เลย**
  เขียน `this.cb.onAudio?.(this.playChunk(msg.data))` = เสียงไม่ถูกเล่นถ้าไม่มี callback
- 🔴 **`now < X + tail` ต้องเช็ค `X > 0` ก่อนเสมอ** — ตอนเปิดหน้าใหม่ๆ `performance.now()`
  ยังน้อยกว่า tail ⇒ เงื่อนไขเป็นจริงทั้งที่ไม่มีเสียงอะไรเล่นเลย
- ⚠️ **บันทึกเดิมที่ว่า "เวลาที่จดไว้ทุกที่คลาด 7 ชม." กว้างเกินไป** — เวลาที่มาจาก **user บอก**
  เป็นเวลาไทยและถูกอยู่แล้ว (เช็คแล้ว: 08-14 10:15-10:20 ตรงกับ log `03:18:11`/`03:20:43` UTC เป๊ะ)
  ที่คลาดคือเวลาที่ **อ่านจาก log แล้วจดโดยไม่แปลง** — อย่าไปแก้บันทึกที่ถูกอยู่แล้ว
- ⚠️ **รัน pytest ใน sandbox `/tmp/verify` ที่ symlink `logs` ไป `/app/logs` = เขียนลง log prod ด้วย**
  (บรรทัด `http://testserver/...` · `FAKE_NO_NETWORK` ที่ `05:36-05:39` UTC 08-17 เป็นของผมเอง)
  · `test_skills_db_cross_process` แดงใน sandbox นี้เสมอ — **พิสูจน์แล้วว่ากลุ่มควบคุมโค้ดเดิม
  ก็แดง** ไม่ใช่ regression · deselect ได้
- 🔒 **user สั่งปิดคดีค่าเสียง/จังหวะการอ่าน (08-17)** — ห้ามแตะ `READER_PROMPT` ·
  seed/temperature/Aoede · `READ_BLOCK_CHARS` · กฎเลื่อนที่คั่น · jitter prime
  ⛔ **ข้อเสนอ "ถอด temperature" พักถาวร ห้ามเสนอซ้ำ** (`build_reader_config` สืบ
  `build_live_config` ทั้งก้อน ⇒ ถอดแล้วเสียงอ่านเปลี่ยนด้วย · มีเทสตรึงจะแดง)
  · เส้นฐานโมเดลที่วัดไว้ **`gemini-3.1-flash-live-preview` ver = `3.1-flash-live-03-2026`**
  (วัด 2026-08-17) — ถ้าวันหนึ่งเสียงเปลี่ยนเอง ให้เทียบค่านี้ก่อน

---

## ⏭️ backlog เก่า — ย้ายประวัติไป `docs/session-log/devlog.md` แล้ว (2026-08-18 · ไฟล์ย้ายที่ 08-17)

ประวัติเซสชัน 08-05→08-16 · backlog 08-04 · backlog 06-18 · overlay §22/Model Picker
**ย้ายลง `docs/session-log/devlog.md` ทั้งหมด** (CLAUDE.md ลดจาก 223 KB → ~83 KB เพราะ 53% เป็นประวัติ)

⚠️ **ยังไม่ได้กวาดว่าอะไรปิดไปแล้ว — อย่าถือว่าปิด** กวาดจาก 49 รายการที่ยังไม่ติด ✅
เหลือที่ยังเปิดอยู่จริงเท่าที่ตรวจได้:

- 🔴 **DB backup ตายมา 36 วัน — ตรวจจริง 2026-08-18** ตัวล่าสุด `db_backup_20260712_194423.tar.gz`
  (12 ก.ค.) · `/usr/syno/etc/synoschedule.d/root/*.task` **ไม่มีตัวไหนเรียก `db_backup.sh`**
  ⇒ `data/chat_history.db` (1.6 MB · sessions/messages/**feedback 👍👎**/pins/shares) และ
  `data/reader.db` (**130 MB** ข้อความหนังสือ) **ไม่มีสำเนาสำรองเลย**
  🔑 **กับดักที่ทำให้เรื่องนี้ถูกมองข้ามมา 36 วัน:** `db_backups/phrae-data-map/` อัปเดตทุกวัน
  (งานคนละโปรเจกต์) ⇒ `ls` โฟลเดอร์แล้วเห็นวันที่สด **จึงดูเหมือน backup ยังเดินอยู่**
  — ต้องดูชื่อไฟล์ให้ตรงงาน ไม่ใช่ดูวันที่ของโฟลเดอร์
  ▶️ ทำ: ตั้ง DSM task รายวัน 03:30 (user=root) เรียก `scripts/db_backup.sh`
- ⚪ **ไม่มีป้าย "กำลังค้น" ในโหมดเสียง** — ค้นใช้ 15-45 วิ = ผู้ใช้ได้ยินความเงียบล้วน
  🔗 **เกี่ยวโดยตรงกับงานค้างข้อ 1 ข้างบน** (ประตูไมค์หมดอายุระหว่างค้น) — ถ้า server
  ต้องบอก client ว่า "กำลังค้นอยู่" เพื่อกันประตูเปิด ป้ายนี้ก็ได้มาฟรีจาก event เดียวกัน
- 🧪 verify ด้วยตาบน browser จริง: File Manager drag&drop / กล้อง / index toast ·
  ChatBox pills (Plan/Code · สลับผู้ช่วย · status dot · Shift+Enter)
- 🧪 **voice retry ยังไม่เคยถูกกระตุ้นจริงบน prod** — ยืนยันได้แค่ unit test + โค้ดอยู่ในบันเดิล
- 🧹 `AI_PALETTE` ใน `~/appscript.ui` ยังมี `fa`/`khim` ค้าง (ถอดจาก backend ตั้งแต่ 06-16) = ซากโค้ด
- 🎨 `enhanced.js` map สีตามตระกูลเฉด ยังไม่ได้ไล่ความหมายรายจุด
- ⛔ **พักไว้ (user เคาะแล้ว อย่าเสนอซ้ำ):** `ANTHROPIC_API_KEY`/`MOONSHOT_API_KEY` ใน NAS `.env`
  · Image Gen (free tier limit=0) · fine-tune (รอ 👍 ~200-500) · Telegram สำหรับ EWS

## ✅ Admin unlock endpoint (2026-06-01)
`POST /api/admin/unlock` — ล้าง auth-fail lockout สำหรับ IP ที่ระบุ (LAN/loopback เท่านั้น, 403 ถ้ามาจาก Cloudflare/public)
```bash
# ปลด lock IP ที่ระบุ (รันจาก LAN) — ต้องระบุ IP จริงของ client ไม่ใช่ NAS
curl -X POST http://192.168.51.49:8000/api/admin/unlock \
     -H "Content-Type: application/json" -d '{"ip": "CLIENT_IP"}'
# หา IP จาก log: docker logs ai-backend-1 2>&1 | grep "auth_fail\|lock" | tail -10
```

