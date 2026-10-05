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
| สถาปัตยกรรม backend/routing · env · เสียง · ค้นเว็บ · Known Quirks | หัวข้อ **Architecture → `docs/reference/`** ข้างล่าง (ตารางชี้ไฟล์) + [`CONTEXT.md`](CONTEXT.md) (glossary) |
| ประวัติงานย้อนหลัง | [`docs/session-log/`](docs/session-log/README.md) — `devlog.md` + `from-memory-status.md` |
| infra NAS / LMStudio / ChromaDB / deploy channel | [`docs/reference/infra-nas.md`](docs/reference/infra-nas.md) 🔴 อ่านก่อน deploy |
| โหมดขวัญอ่านนิยาย (`/ws/reader`) | [`docs/reference/reader-mode.md`](docs/reference/reader-mode.md) |
| แผนระยะยาว / ดีไซน์ / คู่มือ | [`ROADMAP.md`](ROADMAP.md) · [`DESIGN.md`](DESIGN.md) · [`GUIDE.md`](GUIDE.md) |
| React source ของ SPA | `~/appscript.ui/` (มี `CLAUDE.md` ของตัวเอง) — **แก้ UI ที่นั่น ไม่ใช่ overlay** |
| ส่วนบนจอนี้ใครเป็นเจ้าของ (React/overlay/API) | [`docs/ui-map.md`](docs/ui-map.md) · subagent `ui-investigator` |

### 🔴 กฎการจดตั้งแต่ 2026-08-17
1. **จบเซสชัน → เขียน `docs/session-log/devlog.md`** แล้วอัปเดตหัวข้อ ▶️ ในไฟล์นี้
2. **memory `hybrid_ai_status` / `hybrid_ai_infra` / `project_khim_reader` เป็นตัวชี้แล้ว
   ห้ามจดเนื้อหาลงไป** — git ตรวจย้อนได้ด้วย `git log -S` · memory ตรวจย้อนไม่ได้
3. `MEMORY.md` เก็บได้แค่ "เปิดไฟล์ไหนก่อน + ข้อห้ามที่ยังมีผล"
4. ⚠️ ไฟล์นี้ถูกฉีดเข้า context **ทันทีที่แตะไฟล์ใดก็ตามในรีโป** (nested CLAUDE.md ·
   เพดาน CLI = 4 MB จึงไม่มีการตัดให้) ⇒ **มันโตเมื่อไหร่เสียโควตาทุกเซสชันทันที**
   **งบ 50 KB มีเทสคุม** (`tests/test_claude_md_budget.py` — แดงเมื่อเกิน · **อย่าขยับเพดานขึ้น** ให้ย้ายลง `docs/`) ·
   2026-10-01 ย้าย Architecture/Env/เสียง/ค้นเว็บ/Quirks ลง `docs/reference/` (103 → ~42 KB · เคยถึง ~197 KB) · บทเรียนเต็มที่ vault `wiki/concepts/claude-md-context-budget.md`
5. **ถังความจำของโปรเจกต์นี้:** `~/.claude/projects/-Users-pawin-Desktop-ui/memory/`
   — เปิดงานด้วย **`cc khim`** เท่านั้นถึงจะได้ถังนี้ (เปิดจาก `~` = ได้ถังกลาง คนละใบ)
   · `MEMORY.md` ในถัง = หน้าแรก (ตัวชี้/ข้อห้าม/งานค้าง) · โน้ตข้างเคียงเป็น **symlink
   ไปถังกลาง** = ไฟล์เดียวกัน **ห้ามแทนที่ด้วยสำเนา**
   · **จบเซสชัน → จดที่ `docs/session-log/devlog.md` แล้วอัปเดตหัวข้อ ▶️** ห้ามจดเนื้อหาลง memory
6. **กติกาใหม่ → ใส่หมวดใน "🔑 กติกาที่ยังมีผล" (backend/config/เทส/frontend/deploy/Gemini/หลักคิด)
   หรือลง `docs/reference/<เรื่อง>.md` ตามเรื่อง** ⛔ ห้ามสร้างหัวข้อแบบลงวันที่ (`กติกาใหม่จากเซสชัน MM-DD`) อีก

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
`SKILLS_DB_PATH` (**ค่าคงที่คำนวณใน `core/config.py` ไม่ใช่ env ที่ตั้งได้**) = `<repo>/skills_db.json` → **รันบน Mac หรือบน NAS host จะไปสร้าง/แก้ไฟล์คนละตัวกับ
ที่ prod ใช้ แล้วรายงานว่าสำเร็จ** (ตัวจริงคือ `data/skills_db.json` ที่ mount เป็น `/app/skills_db.json`
— บนเครื่อง dev ไม่มีไฟล์นี้เลย). ก่อน 2026-08-03 คำสั่งนี้ยัง**รันในคอนเทนเนอร์ไม่ได้**ด้วยซ้ำ
เพราะ `scripts/` เป็นโค้ดดิร์เดียวที่ไม่ได้ mount (เป็นสำเนาค้างจากตอน build ที่ไม่มีไฟล์นี้)

### Frontend
`static/` คือ vite build output จาก **React source `~/appscript.ui`** (remote `origin`=NAS + `github` · pre-commit hook):
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


## Architecture · Env · เสียง · ค้นเว็บ · Known Quirks → `docs/reference/` (ย้ายออก 2026-10-01)

ยกทั้งดุ้นไม่แก้เนื้อ (ไฟล์นี้โตถึง 103 KB · `tests/test_claude_md_budget.py` คุมงบ 50 KB) — **เปิดอ่านก่อนแตะส่วนนั้น**

| หัวข้อ | เปิดที่ |
|---|---|
| Request flow · Context assembly · Anti-hallucination · LLM routing · Data persistence/backups · Key files · SSE schema · Memory tiers · Dream · Caches · Image gen · Routing/classifier · OCR/สรุปเอกสาร · Fine-tune · Admin unlock · **Known Quirks** | [`docs/reference/architecture.md`](docs/reference/architecture.md) |
| Environment Variables (บล็อก ```env เต็ม — `tests/test_env_docs_ratchet.py` สแกนไฟล์นี้) | [`docs/reference/env-vars.md`](docs/reference/env-vars.md) |
| Voice WS · เสียงต้องเป็นคนเดิม (ตารางโมเดล × temperature/seed) · `/api/tts` + โควตา · `AudioLevelMeter` | [`docs/reference/voice-tts.md`](docs/reference/voice-tts.md) |
| Web search (Brave → DDG · CSE ถอดแล้ว 10-01) · บทเรียน 08-31 · พื้นคะแนน web/skills · `rewrite_query()` ตายกับ Qwen | [`docs/reference/web-search.md`](docs/reference/web-search.md) |

**ข้อเท็จจริงที่ใช้บ่อย (ที่มา/รายละเอียดในไฟล์ข้างบน):**
- auth fail-closed ⇒ HTTP endpoint ใหม่ปลอดภัยโดย default · **WS endpoint ใหม่ต้อง gate เอง** (`websocket_auth_ok`)
- provider ทุกปุ่มไปตัวเดียวกันเสมอ (ไม่ redirect) · default `"auto"` → `reasoning/router.py` ที่เดียว · local หลัก = LM Studio qwen3.5-9b ·
  Ollama = fallback **ยกเว้น embeddings** (Ollama หลัก · fallback LM Studio ด้วยโมเดลชื่อเดียวกันเท่านั้น)
- prod: app `:8080` · ChromaDB `:8000` · container ชื่อ `ai-backend-1` (service `hybrid-ai`) · ChromaDB ใช้ `/api/v2/heartbeat`
- สโมกเทส `/api/chat` ต้องส่ง header `X-Test-Request: 1` ไม่งั้น Q&A ทดสอบปนเข้า memory
- `docker-compose` `environment:` ทับ `env_file:` ⇒ `DB_PATH`/`OBSIDIAN_VAULT_PATH`/`LOG_FILE` ตั้งใน `.env` ไม่มีผลในคอนเทนเนอร์
- เสียงทั้งหมดอยู่ `utils/voice.py` ที่เดียว · `utils/tts.py` ใช้สาย `*-tts` เท่านั้น (native-audio = 404) และต้องมี prefix `Say:`
- ค้นเว็บมี 2 pipeline (`utils/websearch.py` + `agents/tools.py:_t_web_search`) แก้ต้องแก้คู่ · error ของ provider ต้องไม่หน้าตาเหมือน "0 results"
- `429 limit: 0` = โมเดล/ฟีเจอร์ไม่เปิดให้ free tier (retry ไม่ช่วย) ≠ โควตาหมดชั่วคราว
- `tool_agent:true` ไม่ส่ง provider ⇒ วิ่ง gemini agent · smoke test Gemini ต้องเทส multi-turn ใน session เดิม

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


## ▶️ เซสชันหน้าเริ่มตรงนี้ (อัปเดต 2026-10-05 รอบ 6 · **ที่เดียว**)

> บล็อก ▶️ ทั้งหมดจนถึง 09-28 (ก้อน 1–11 · config ก้อน 1–4 · reader/voice 08-17→09-22 · ไมค์ 08-24/26)
> ถูกยก**ทั้งดุ้นไม่แก้**ไปไว้ที่ devlog **[2026-09-28 ต่อ 24]** — ที่นี่เหลือแค่งานเปิด + กติกาที่ยังมีผล
> ⚠️ **ไฟล์นี้ถูกฉีดทุกเซสชัน** — ปิดเซสชันแล้วให้ย้ายรายละเอียดลง devlog เหลือบรรทัดเดียวต่อเรื่องที่นี่

### 🔧 ก่อนเริ่มทุกครั้ง
`gh run list --limit 3` ต้องเขียว (a.ui มี CI แล้ว: `gh run list -R penpunnee/appscript-ui --branch main --limit 3`) · venv ทดสอบสร้างจาก **`requirements.lock`** (ไม่ใช่ `.txt` — lib ใหม่กว่า prod) ·
`ssh -o ConnectTimeout=10 nas-cf true` ก่อนงานที่แตะ prod
```bash
uv venv /tmp/uivenv --python 3.12 && VIRTUAL_ENV=/tmp/uivenv uv pip install -r requirements.lock
LOG_FILE=/tmp/test.log /tmp/uivenv/bin/python -m pytest -q   # LOG_FILE= สำคัญ ไม่งั้นเขียนทับ server.log
uvx ruff check . && (cd ~/appscript.ui && npx vitest run utils/ && npx tsc --noEmit)
```
**ขั้นตอนต่อก้อน:** ค้น 2 ชั้น (เป็นบั๊กจริงไหม · วิธีแก้ที่ถูกจากเอกสาร/ซอร์ส lib ที่ติดตั้ง — **รวม log/วัด prod**) → รายงานแผน
→ /scrutinize → เคาะ → เทสแดง → แก้ → mutation → ชุดเต็ม → deploy → verify prod (ยืนยันว่าเส้นที่แก้ถูกวิ่งจริง)
→ **รอ CI เขียวก่อนเริ่มก้อนถัดไป** → devlog

### 🥇 งานแรกเซสชันหน้า — เลือกจากงานเปิด (ถาม user)
**ไม่มีงานโค้ดค้าง** (10-05 รอบ 5 = toast สองระบบปิดโดยไม่แก้โค้ด [ต่อ 109] · แก้ timer ของ toast React [ต่อ 110 · deploy แล้ว] · CI ของ a.ui job `unit` [ต่อ 111] · สรุปปิดเซสชันที่ devlog [ต่อ 112] · รอบ 6 = subagent `ui-reviewer` พิสูจน์แล้ว + verify-ui ขั้น 4.5 [ต่อ 113]) ·
⚠️ a.ui `origin` (NAS) ตามหลัง `github` 1 commit (นอกวง LAN) → กลับเข้าวงแล้ว `git push origin main` · ⏳ มือถือไม่มีปุ่มล้างแชท (`hidden md:flex`) ตั้งใจไหม — รอปอยตอบ [ต่อ 113] · ตัวเลือก: 📋 ย้าย Vault Search เข้า React · ย้าย a.ui ไป Node 24 LTS · ⏳ job e2e บน CI (รอปอยเช็คโควตา) · เลือกจาก ⏳ ข้างล่าง/🧪 (docs) หรือถาม user
1. 🧪 (ต่อ 104) user ถามขวัญแนวเดิมในโหมดเสียง → ตอบ "ที่ใกล้สุดคือ…" แทนถามกลับไหม · ✅ ความจำขยะ ASR (ต่อ 105) · ⏳ ค้นในตัวหนังสือ (`reader.db`) แทนเว็บ · ✅ e2e smoke WebKit (a.ui `npm run test:e2e`)
2. 🧪 log ที่ควรดูรอบหน้า: ~~`[LMStudio] อุ่นเครื่อง`~~ ✅ (ต่อ 102) · `[Chat] timings` ใหม่ (ช้าตรงไหน · 10-05 ยังมีแค่ probe) · `[Voice WS] ห้อง … มีสายเก่ายังค้าง` (เกิดจริงไหม · 10-05 มีแค่ probe) · `[Reader] … ตระกูล 6` (ตอนนำเข้าเล่มใหม่)
3. 🧪 (ต่อ 100) qwen แปลชื่อเฉพาะผิด (Gemini ถูก) — ถาม user ว่าใช้ Gemini เองไหม (⛔ ห้าม redirect)
4. ⏸ (ต่อ 101) ~1.8 วิทุกแชท = `bump_access_count` เขียน Chroma (fsync HDD) · user: ไม่ช้า → พัก · cold ~1.3 วิ ในโปรเซสแอป warmup กันแล้ว (ต่อ 102)
ถ้า user ส่งภาพหน้าแจ้ง error ของ `AppErrorBoundary` มา → ใช้ชื่อ error บนจอหาจุดพังแล้วแก้ที่ต้นเหตุ

### ✅ ปิดแล้ว → ก่อนเช็คว่าเรื่องไหนปิดแล้ว/ดูประวัติ → อ่าน [`docs/session-log/devlog.md`](docs/session-log/devlog.md)
(รายการ 10-02→10-05 ยกไว้ที่ entry [2026-10-05 ต่อ 106])

### 🔑 กติกา 10-02 → 10-05 · ก่อนทำงาน LM Studio/qwen · ค้นเว็บ · usage/meta · ความจำ/RAG · markdown · Live/เสียง · embed · หนังสือ · probe prod → อ่าน [`docs/reference/rules-1002-1005.md`](docs/reference/rules-1002-1005.md)
ข้อห้ามกันความเสียหาย (รายละเอียด/เหตุผลอยู่ในไฟล์นั้น):
- ⛔ อย่าเพิ่งย้ายเสียงไป 3.8 Live · ⛔ ตัวนับ retry 1011 นับข้าม `connected` ห้ามย้ายกลับ · ⛔ ห้ามเปิด retry ของ embed client กลับ
- ⛔ ลบความจำ: แสดง user ก่อนเสมอ ห้ามลบเอง (`memory.store.delete_entry`) · ⛔ ห้ามส่งประวัติทั้งก้อนให้ LM Studio (`_fit_lmstudio_context()`)
- ⛔ กติกาแชทห้ามใส่ `ASSISTANTS[…]["system_prompt"]` (เสียงใช้ร่วม) · ⛔ ห้าม fetch ตามลำดับ provider (`_select_and_fetch()`) · ⛔ คำสั่งเสียงห้ามชวน "ค้นใหม่"
- probe prod: `127.0.0.1:8000` · `X-Test-Request` + ลบ session ทุกรอบ · ไฟล์ `data/` ลบผ่าน `docker exec` · เธรดเบื้องหลังผ่าน `spawn_bg` เท่านั้น

### 🔑 กติกา 09-29 → 10-01 · ก่อนทำงาน Live/iOS ไมค์ · sqlite/`chat_history.db` · `save_reply` · `server.py` deploy · Dream → อ่าน [`docs/reference/rules-0929-1001.md`](docs/reference/rules-0929-1001.md)
ย่อ: `chat_history.db` เป็น WAL ห้าม cp ไฟล์เดี่ยว · `save_reply(…, user_msg_id)` · แตะ server.py = `--force-recreate` + inode + sha เสียง ·
Live ตัดสาย 1008 ~151 วิ → `parkIfUnused` · iOS `ended` = `stopVoice()` เท่านั้น · ⛔ Google CSE · Dream ไม่เก็บความรู้จากเน็ต

### 📋 งานเปิดอื่น
- **frontend (จาก `docs/ui-map.md` 10-05 · ยังไม่แก้):** ย้าย Vault Search (overlay §5 + ปุ่ม 🌿 + ตัวดัก `@vault`) เข้า React แล้ว gate §5 — toast ของ overlay (`#enh-toast`) จะหมดไปเอง ·
  ✅ toast สองระบบ ปิดแล้วโดยไม่แก้โค้ด (ต่อ 109 · ไม่ซ้อนจาก action เดียว · overlay เหลือจุดเดียวที่ Vault) ·
  ข้อสังเกต: §15 badge โมเดลยัง `appendChild` เข้า div ฟองของ React (เพิ่มอย่างเดียว ไม่ลบ ⇒ ไม่ใช่เงื่อนไขจอขาวครั้งก่อน · e2e ยังไม่ครอบ) · ✅ §6 Copy กล่องโค้ด ปิดแล้ว (ต่อ 108)
- **e2e (ต่อ 113):** `expectAlive` ตรวจจอขาวด้วย `#root.childElementCount > 0` — overlay ที่ append เข้า `#root` ตรงๆ จะทำให้ผ่านเสมอ (ตอนนี้ไม่มี) → ให้นับเฉพาะลูกที่ React render
- **เอกสาร:** ไฟล์นี้ 45 KB (งบ 50 · เทสคุม) — ย้ายของออกลง `docs/` อีกรอบก่อนชนเพดาน ⛔ ห้ามขยับเพดาน
- **a.ui build/CI (ต่อ 111):** ย้ายไป Node 24 LTS — ตอนนี้ตรึง 25.8.1 ใน `~/appscript.ui/.nvmrc` (รุ่นที่ build จริง · หมดซัพพอร์ต 2026-06-01) · เปลี่ยนแล้วต้อง build bundle ใหม่ + ตรวจซ้ำ
- **backend:** ✅ reader `marks.set` verify รอบอ่านจริงแล้ว (ต่อ 50) · ข้อสังเกตเล็ก: `books.text` 90.9 ms บน loop ครั้งเดียวตอนเปิดเล่ม (ยังไม่คุ้มแก้)
- **จดแยก:** Dream REM วัดด้วย `auto` ตอนมี memory ≥ 5 (รอ memory จากโหมดเสียงสะสม)

### ⏳ รอ user เคาะ
**ใหม่ 10-05 (ต่อ 111):** ใส่ job e2e ใน CI ของ a.ui ไหม — รอปอยเช็คโควตานาที Actions (Settings → Billing · `phrae-data-map` ใช้ ~2,900 นาที/เดือน) ·
**ใหม่ 10-02 (ต่อ 61):** ขาเข้าหนังสือ (`_ingest`) ไม่ซ่อมตระกูล 6 และไม่เตือน — เตือนใน log/UI หรือใส่ pythainlp (62 MB) ·
(ข) response cache ข้าม session · คิวเล็กจาก 09-24 (**เช็คสถานะจริงก่อน**): ต่อ `scripts/reconcile_keys.py` เข้ารอบกลางคืน ·
ย้ายเสียงไป `gemini-3.8-live` (3.1 = legacy ยังไม่มีวันปิด · ติดล็อกเสียง 🔒 ต้องวัดเสียงใหม่ทั้งชุด) ·
ทาง 1 earpiece: เล่นเสียงผ่าน `MediaStreamAudioDestinationNode` → `<audio>` (WebKit แนะนำ · อาจแก้เสียงเบาด้วย · ทำเป็นสวิตช์ปิดไว้ แล้ว A/B)

### 🧪 รอ user ทดสอบด้วยมือ → ก่อนเลือกงาน / เมื่อปอยรายงานผลทดสอบ / ก่อนแตะฟีเจอร์ในรายการ → อ่าน [`docs/session-log/pending-manual-tests.md`](docs/session-log/pending-manual-tests.md)
(เสียง Live/1011 · โหมดอ่าน · สถิติ token/ไทม์ไลน์ · dropdown/ป้าย Agent · File Manager · ChatBox pills)

### ⚪ งานเล็กค้าง
`GEMINI_LIVE_MODEL` จะยกขึ้น `.env` ไหม · AnythingLLM ตกรุ่น (หรือปิดทิ้ง 3.34 GB) · โมเดล local ไม่มีใครใช้ ~14 GB ·
`pythainlp` ไม่มีในอิมเมจ (ตั้งใจ · รันมือ: `uv run --with pythainlp==5.3.8 --with pytest python -m pytest tests/test_thaiscatter.py --noconftest` 18/18 · ต่อ 61) · `enhanced.js` map สีตามตระกูลเฉด ·
citations ราคาเกมอาจเป็นแหล่งรอง (Steam age-check) ·

### ⛔ พักไว้ (user เคาะแล้ว อย่าเสนอซ้ำ)
`ANTHROPIC_API_KEY`/`MOONSHOT_API_KEY` · Image Gen (free tier limit=0) · fine-tune (รอ 👍 ~200-500) ·
Telegram สำหรับ EWS · TypeScript 5.9→6/7 · `pydantic-settings`

### 🔒 เสียง (user ยืนยัน 09-23: "เสียงโอเคละ อย่าปรับมั่ว")
ห้ามแตะ `READER_PROMPT` · seed/temperature/Aoede · `READ_BLOCK_CHARS` · กฎเลื่อนที่คั่น · jitter prime ·
`build_live_config`/`build_reader_config` · `GEMINI_LIVE_MODEL` · reader/voice regen cap — refactor ที่ผ่านไฟล์เสียงต้องพิสูจน์ด้วย
sha ก่อน=หลัง · ⛔ ห้ามเสนอถอด temperature · ⛔ ห้ามเอา `reader_pacing_wait` กลับ (ตัวการคือตัวอ่านซ้อน) ·
⛔ **โหมดอ่านห้ามใช้ `resume_handle`** (session ที่ต่อด้วย handle อ่านท่อนก่อนหน้าซ้ำ · เทส `test_reader_no_resume.py`) ·
seek ต้อง**อ่านค่าก่อนเขียน** (user อาจฟังอยู่) · เส้นฐานโมเดล `3.1-flash-live-03-2026`

### 🔑 กติกาที่ยังมีผล (กลั่นจากก้อนที่ปิดแล้ว — ที่มาอยู่ใน devlog)
**backend**
- LM Studio agent step เป็น **stream** แล้ว (ก้อน 12) — ประกอบ tool call เอง ห้าม `ChatCompletionStreamState` (โยนตอน finish=length) ·
  fake ในเทสต้องส่งเป็นชิ้น (`tests/test_agents.py:_as_stream`) · เทสตัดสาย router ต้องตัดตอนเธรด*ค้างรอ LLM อยู่จริง* (`_SSEServerSeen`)
- qwen3.5 ผ่าน LM Studio: `content` ว่างแต่ `reasoning_content` มี = ไม่ปิด `<think>` (LM Studio #1602) · **ปิด thinking ผ่าน API ไม่ได้** (#1990 · วัด 3/6) ·
  ห้ามโชว์ `reasoning_content` แทนคำตอบ · ทางที่ใช้ได้ = ต่อ user turn แล้วขอใหม่
- เส้น SSE ที่ save ลง DB ระหว่าง stream → `_guard_disconnect` + `anyio.lowlevel.checkpoint()` ก่อน yield ทุกชิ้น ·
  เส้นที่เรียก LLM → `_CancellableStreamingResponse` + `_guard_disconnect(cancel=)` + ส่ง `cancel=` ให้ `stream_response`
- หลังลูป stream ตัดสินด้วย **`cancel.aborted`** ไม่ใช่ `cancel.is_set()` · provider ใหม่ต้องลงทะเบียน stream + เช็คธงทุก raw chunk
  \+ ห้าม cascade เมื่อถูกยกเลิก · ปลดตัวอ่านข้าม thread ใช้ `socket.shutdown` ไม่ใช่ `close()`
- ฟิลด์จาก body → `utils/reqparse` (`as_int`/`as_str`) · handler ที่เรียก `json_body_capped` **ห้าม `except Exception`**
  (ดักเฉพาะ `HTTPException` 400) — exception ของ middleware ต้องทะลุ
- ผล `col.get(ids=…)` zip กับ **`res["ids"]`** เสมอ (Chroma คืนตามลำดับ insert) · ค่าจาก `__keys` เป็นแค่ตัวชี้ id
- collection ที่ลบได้ตัดสินด้วย `is_episodic_collection()` ที่เดียว · โค้ดที่แตะ ChromaDB ก่อน connect ผ่าน `_get_client()`
- ห้ามถือ `_db_transaction` ระหว่าง embed/Chroma upsert · ห้ามส่ง mapping บางส่วนเข้า `sync_from_db` (upsert เดี่ยวใช้ `add_skill`)
- error ของ LLM client → `_classify_api_error()` (type/status ก่อน substring) · ทางเข้า Dream ทุกทางผ่าน `run_dream_cycle()`
- `lru_cache` ห้ามคืน sentinel ตอนล้ม ให้ raise แล้วห่อ · ผล tool "ไม่ได้ข้อมูล" ตัดสินด้วย `_is_informative()`
- Gemini chat ส่ง config ต่อคำขอ = แทนทั้งก้อน → `model_copy` ของเดิม
- ผลจาก `rglob`/glob ผ่าน `_resolve_safe` ต่อไฟล์ · ความลับห้ามอยู่ใน query string (ใช้ header) + log ผ่าน `_redact_secrets`
- เพิ่ม WS endpoint = ต้อง gate เอง (`websocket_auth_ok`) · async handler ห้ามงาน sync ช้าตรงๆ (`run_in_threadpool`)

**config (`core/env_registry.py` · `os.getenv` ดิบในโค้ด prod = 0)**
- env ใหม่ → helper ของ registry + เติมโมดูลใน `MODULES` + `python scripts/gen_env_example.py --write` (ไม่ regenerate = CI แดง)
- ชื่อที่มีเจ้าของแล้วให้ **import ค่า** ห้ามลงซ้ำ (fail-loud ตอน import) · ค่าที่มี parser เดิม (`off`/ไม่บวก→default) ลงเป็น
  `env_str("NAME"` literal ที่ call site — ห่อผ่าน wrapper แล้ว ratchet มองไม่เห็น
- doc ที่ลงทะเบียนห้ามมี `/app/...` (Mac เขียว CI แดง) · default ที่คำนวณ → ลง `""` แล้วคำนวณเมื่อว่าง ·
  `LMSTUDIO_API_KEY_RAW` = ค่าดิบ (router แนบ Authorization จากตัวนี้เท่านั้น)

**เทส**
- reload `core.config` ต้องมี teardown reload กลับ · **ห้าม reload โมดูลที่มีคลาส exception** (ใช้ `_fresh_module()`/`_reload_with()`)
  · เทสที่โยน exception ให้ router ใช้คลาสที่ router ผูกไว้ (`rd.X`)
- เทสที่อาจแขวน (GIL) รันใน subprocess · macOS ไม่มี `timeout` → background + kill
- mutation ต้อง fail-loud (baseline gate · แยก `INVALID` จาก `SURVIVED`) · ดูว่าแดงกี่ตัว · mutant ที่รอดอ่านซ้ำว่าเปลี่ยนพฤติกรรมจริงไหม
- ถามเสมอ: assertion ยืนยันฝั่ง*ที่ส่งไป*หรือ*ที่ได้กลับ* · เทสที่อ่าน global state ต้อง assert ว่าไม่ว่าง ·
  เทสที่ผ่าน/แดงตามจังหวะต้องมีคู่ที่บังคับลำดับได้ · อ่านซอร์สเป็นสตริง → ใช้ `ast` · ก่อนแก้ฟังก์ชัน `grep -rl <ชื่อ> tests/`
- ❌ ห้ามรัน pytest ในคอนเทนเนอร์ prod (fixture ปน log)

**frontend**
- ก่อนแก้ UI ที่ไม่แน่ใจว่าอยู่ไหน (React หรือ overlay) → ใช้ subagent `ui-investigator` (แผนที่ [`docs/ui-map.md`](docs/ui-map.md) · ตัวจริง `.claude/agents/` symlink จาก `~/.claude/agents/` เรียกได้ทุกรีโป ·
  เครื่องใหม่/ลิงก์หาย: `mkdir -p ~/.claude/agents && ln -sfn ~/Desktop/ui/.claude/agents/ui-investigator.md ~/.claude/agents/ui-investigator.md`) ·
  ตัวยึดในแผนที่ตรึงด้วย `tests/test_ui_map_anchors.py` (static/) + `~/appscript.ui/utils/uimap.test.ts` (React) — rename แล้วต้องแก้แผนที่ตาม
- ก่อน commit diff ฝั่ง UI ระดับกลางขึ้นไป หรือที่แตะ `*.test.ts`/`e2e/` → ให้ subagent `ui-reviewer` ตรวจ (เงื่อนไข/วิธี = skill verify-ui ขั้น 4.5 ใน `~/appscript.ui` · ตัวจริง+symlink แบบเดียวกับ `ui-investigator` · ⛔ เรียกชื่อไม่ได้ ห้ามใช้ agent อื่นแทน)
- overlay ที่ React ทำเองแล้วต้อง gate `if (window.__hwReactChatBox) return;` (ตอนนี้: tee/`_parseChatSSE` · Ctrl+E · ↑/↓ · paste · §6 · §19/§20 · §22) —
  เพิ่ม feature ใน React แล้วไล่ overlay ที่ทำซ้ำด้วย · เทส `tests/overlay_gating.test.js`
- ก่อน commit การแก้ `static/*.js` (overlay) → รัน `npm run test:e2e` ใน `~/appscript.ui` ต้องเขียวทั้งหมด → ทำตาม skill verify-ui ใน ~/appscript.ui ·
  ⛔ ธง `__hwReactChatBox` (`app.tsx`) ห้ามหาย — หายแล้ว overlay ฉีดปุ่มซ้ำ + ซ่อนช่องพิมพ์ (พิสูจน์ใน e2e 10-05)
- bookreader: server ปิดสาย = เก็บกวาดหลังเสียงค้างเล่นหมด (`playEnd` + ticker) **ห้าม disconnect ทันที** (ตัดท้ายเล่ม) · สีผู้ช่วยผ่าน `paletteFor()` เท่านั้น
- toast ของ React ผ่าน `showToast` (`utils/toast.ts » createToaster`) เท่านั้น ห้าม `setToast(` ตรงๆ (timer ตัวเก่าจะลบข้อความใหม่) · e2e ที่ขึ้นกับเวลาใช้ `page.clock` ⛔ ห้ามรอเวลาจริง
- stream ใหม่ใช้ `sseEvents()` + `settleStream()` ใน finally + `streamFailureText()` ใน catch — ห้ามลูป `getReader()` เอง
- overlay ห้าม `.remove()`/แก้ DOM ที่ React เป็นเจ้าของ (จอขาว) · แก้ `enhanced.js` แล้ว `?v=YYYYMMDD-<md5 8 ตัว>`
- เครื่องหลักคือ iPhone ไม่มี hover → สถานะต้องเป็นแถบข้อความ ไม่ใช่ tooltip
- Chrome MCP: `computer key/type` อาจไม่ถึงหน้าเว็บ (หน้าต่างไม่ได้ focus) → ใช้ event ที่ dispatch ด้วย JS · ดัก `window.fetch` ในหน้าแทนการยิงจริงเมื่อทดสอบบน prod
- probe ใน Chrome: ห้ามอ่าน `innerText` ของ node ใหญ่วนซ้ำ · ลูปรอ < 45 วิ · ข้อความทดสอบต้องเก็บกวาด (session + memory)

**deploy / infra**
- นอก LAN ใช้ `nas-cf` · ค้างทั้งที่ tunnel healthy = Access หมดอายุ → `cloudflared access login https://ssh.pawinhomelab.com`
  · แยก "NAS ดับ" จาก "อยู่นอกวง" ด้วย `curl https://ai.pawinhome.com/api/config` ก่อนสรุป
- rebuild: `compose build hybrid-ai` แล้ว `compose up -d hybrid-ai` แยกคำสั่ง · ห้าม `--no-cache` ถ้าไม่จำเป็น ·
  คอนเทนเนอร์ไม่มี `/app/.env` (env มาจาก `env_file:`) · `image prune` รายงานต่ำกว่าจริง ดู `system df`
- verify บน prod ต้องรอ handler ที่มาช้ายิงจบก่อนเก็บกวาด

**Gemini**
- โควตาเป็น**รายโมเดล** · โควตา ≠ เครดิต (แถบโควตาไม่ใช่หลักฐานว่าใช้ได้) · prod: `GEMINI_MODEL=gemini-3.5-flash-lite`
  \+ fallback `gemini-3.1-flash-lite` · grounding บน free tier = `limit: 0`

**หลักคิด**
- ตัวกันต้องผูกกับ*คุณสมบัติ* ไม่ใช่*ชื่อ*/รูปแบบการเขียน · "อ่านไม่ได้" ต้องไม่หน้าตาเหมือน "ว่าง" ·
  helper ใน `scripts/` ไม่มีผลกับ prod · ของที่เพิ่มทีหลังต้องไล่ดูตัวกวาดที่ใช้เงื่อนไขกว้าง ·
  กับดักที่จดไว้ล่วงหน้าต้องเช็คว่ายังจริงก่อนเชื่อ · ถอดของ "ไม่มีประโยชน์" ต้องถามว่ามันเคยกันอะไรไว้โดยบังเอิญ

