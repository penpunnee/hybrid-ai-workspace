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


## Architecture · Env · เสียง · ค้นเว็บ · Known Quirks → `docs/reference/` (ย้ายออก 2026-10-01)

ยกทั้งดุ้นไม่แก้เนื้อ (ไฟล์นี้โตถึง 103 KB · `tests/test_claude_md_budget.py` คุมงบ 50 KB) — **เปิดอ่านก่อนแตะส่วนนั้น**

| หัวข้อ | เปิดที่ |
|---|---|
| Request flow · Context assembly · Anti-hallucination · LLM routing · Data persistence/backups · Key files · SSE schema · Memory tiers · Dream · Caches · Image gen · Routing/classifier · OCR/สรุปเอกสาร · Fine-tune · Admin unlock · **Known Quirks** | [`docs/reference/architecture.md`](docs/reference/architecture.md) |
| Environment Variables (บล็อก ```env เต็ม — `tests/test_env_docs_ratchet.py` สแกนไฟล์นี้) | [`docs/reference/env-vars.md`](docs/reference/env-vars.md) |
| Voice WS · เสียงต้องเป็นคนเดิม (ตารางโมเดล × temperature/seed) · `/api/tts` + โควตา · `AudioLevelMeter` | [`docs/reference/voice-tts.md`](docs/reference/voice-tts.md) |
| Web search (Brave → CSE → DDG) · บทเรียน 08-31 · พื้นคะแนน web/skills · `rewrite_query()` ตายกับ Qwen | [`docs/reference/web-search.md`](docs/reference/web-search.md) |

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


## ▶️ เซสชันหน้าเริ่มตรงนี้ (อัปเดต 2026-10-01 · **ที่เดียว**)

> บล็อก ▶️ ทั้งหมดจนถึง 09-28 (ก้อน 1–11 · config ก้อน 1–4 · reader/voice 08-17→09-22 · ไมค์ 08-24/26)
> ถูกยก**ทั้งดุ้นไม่แก้**ไปไว้ที่ devlog **[2026-09-28 ต่อ 24]** — ที่นี่เหลือแค่งานเปิด + กติกาที่ยังมีผล
> ⚠️ **ไฟล์นี้ถูกฉีดทุกเซสชัน** — ปิดเซสชันแล้วให้ย้ายรายละเอียดลง devlog เหลือบรรทัดเดียวต่อเรื่องที่นี่

### 🔧 ก่อนเริ่มทุกครั้ง
`gh run list --limit 3` ต้องเขียว · venv ทดสอบสร้างจาก **`requirements.lock`** (ไม่ใช่ `.txt` — lib ใหม่กว่า prod) ·
`ssh -o ConnectTimeout=10 nas-cf true` ก่อนงานที่แตะ prod
```bash
uv venv /tmp/uivenv --python 3.12 && VIRTUAL_ENV=/tmp/uivenv uv pip install -r requirements.lock
LOG_FILE=/tmp/test.log /tmp/uivenv/bin/python -m pytest -q   # LOG_FILE= สำคัญ ไม่งั้นเขียนทับ server.log
uvx ruff check . && (cd ~/appscript.ui && npx vitest run utils/ && npx tsc --noEmit)
```
**ขั้นตอนต่อก้อน:** ค้น 2 ชั้น (เป็นบั๊กจริงไหม · วิธีแก้ที่ถูกจากเอกสาร/ซอร์ส lib ที่ติดตั้ง — **รวม log/วัด prod**) → รายงานแผน
→ /scrutinize → เคาะ → เทสแดง → แก้ → mutation → ชุดเต็ม → deploy → verify prod (ยืนยันว่าเส้นที่แก้ถูกวิ่งจริง)
→ **รอ CI เขียวก่อนเริ่มก้อนถัดไป** → devlog

### 🥇 งานแรกเซสชันหน้า
ไม่มีงานเร่ง — เลือกจาก 📋 / ⏳ รอ user เคาะ (แนะนำ: ถอด Google CSE ที่ 403 ทุกครั้งออกจาก chain ค้นเว็บ)
ถ้า user ส่งภาพหน้าแจ้ง error ของ `AppErrorBoundary` มา → ใช้ชื่อ error บนจอหาจุดพังแล้วแก้ที่ต้นเหตุ

### ✅ ปิดแล้ว (สรุป: devlog [2026-09-30 ปิดเซสชัน 2] · [2026-09-30 ปิดเซสชัน] · [2026-09-29 ปิดเซสชัน 2])
**09-30 (2):** เอกสาร `:8080`/Gemini · agent ไม่แนะนำ "เปิด Agent mode" · ถอด `CHROMA_PATH` + ลบ collection ว่าง 3 · ที่คั่นโหมดอ่าน 0.6 วิ → 0 ms
**09-30:** กุญแจกำพร้าหลัง Dream = 0 · ดิสก์ NAS busy = healthcheck exec (autoheal 5s→5m นอกรีโป) · REM 0 ธีม = AI ตัดสินใจเอง (log raw + SKIP เกม) ·
insight object → จอขาว (แก้ 2 ชั้น) · `AppErrorBoundary` ครอบทั้งแอป
**09-29:** dbId · DELETE sessions · save_reply อะตอม · skills sync 0 วิ · โหมดเสียงบันทึก memory · fsync NAS/WAL · delete_keys · SSD cache **พักไว้**

### 🔑 กติกาใหม่จากเซสชัน 09-30
- system ของ agent ประกอบผ่าน `orchestrator._agent_system()` เท่านั้น (ตัด `SUGGEST_AGENT_MODE`) · ห้ามแก้ถ้อยคำ `_NO_FABRICATION` (sha persona/เสียง)
- sqlite ที่เขียนถี่บน NAS: ตัวที่ได้ผลคือ **connection ค้าง** + WAL + NORMAL (WAL อย่างเดียวช้ากว่าเดิม) · **เช็คผล `PRAGMA journal_mode`** (เปลี่ยนไม่สำเร็จแบบเงียบได้)
- โหมดอ่าน: 📖 = พัก (WS ค้างโดยตั้งใจ ไม่มี log "ปิด") · ⏹ = ปิดจริง · log `งาน sync บน loop` ขึ้นเฉพาะตอนปิด
- Dream/REM: **ไม่เก็บความรู้ทั่วไปที่หาจากเน็ตได้ + เนื้อหาเกม** (user เคาะ) · ข้อมูลส่วนตัวให้ user สั่ง "จำไว้ว่า" → `user_facts` ·
  อย่าลด temperature ของ Gemini 3 (docs แนะนำ 1.0 · วัดแล้ว 0.0 ยังแกว่ง) · insight ต้องผ่าน `_normalize_insights`
- ค่าจาก API ที่ render ใน React ต้องเป็น string/number — object เป็น child = จอขาว (ตอนนี้เหลือหน้าแจ้งของ `AppErrorBoundary`) · ใช้ `dreamText` แบบเดียวกันเมื่อเจอ
- verify frontend บน prod: ดัก `window.fetch` ในหน้า**ตอบแทนทั้งหมด** (ห้าม pass-through เส้นที่มีผลข้างเคียง เช่น `/api/dream`) · อย่าใช้ "เริ่มแชทใหม่" (สร้างเซสชันจริง)
- NAS: healthcheck ทุกครั้ง = `docker exec` เขียนดิสก์ ~2.3 MB (RAID5) · วัดด้วย `/proc/diskstats` md2 + `docker events --filter event=exec_start`

### 🔑 กติกาใหม่จากเซสชัน 09-29 (ที่มาใน devlog)
- 🔴 **`chat_history.db` เป็น WAL** (`DB_PATH=/app/data/chat_history.db` · mount โฟลเดอร์) — **ห้าม cp ไฟล์ DB เดี่ยวๆ** (ใช้ `sqlite3 .backup`/backup API)
  · **ห้าม mount ไฟล์เดี่ยวกลับ** (`tests/test_db_path_dir_mount.py`) · NAS ไม่มี UPS (user รับความเสี่ยง NORMAL) · ถอย: `PRAGMA journal_mode=DELETE`
- บันทึกคำตอบหลังรอ LLM → `save_reply(…, user_msg_id)` · short-circuit ใหม่ที่ save user → ส่ง `user_message_id` · error ที่ save แถว → ส่ง `message_id`
  · เทสที่ mock `save_message` ด้วย id ปลอมต้อง mock `save_reply` คู่
- งาน Chroma ที่ไม่ embed (get/delete/update meta) → `get_collection_noembed` · add/query ใช้ wrapper (มี EF) · "ไม่มี collection" = `NotFoundError`
- `/ws/voice`: memory ผ่าน `remember_voice_turn` (daemon thread · ข้ามแค่ interrupted/no text) · `_save_msg` ผ่าน bgwriter (FIFO worker เดียว)
  · ห่อที่บรรทัด import เท่านั้น — call site `_save_msg(`/`_marks.set(` ถูกเทสยึดไว้ · แตะ server.py = `--force-recreate` + inode + sha เสียง
  (`sha256(repr(cfg))[:16]` live `dbff1a358e00ef03` · reader `8c5dbf9603eb3630` · sysprompt `8bddd1cae4be22b1`)
- `log_timing` ไม่เขียน log (contextvar ให้ /api/chat) — วัด WS ใช้ `utils/looptiming` · Gemini free **15 req/นาที/โมเดล**
- เทส route ใช้ `app.openapi()["paths"]` (`app.routes` ห่อ `_IncludedRouter` = ผ่านฟรี) · เปลี่ยนเส้นทางโค้ดแล้วต้องพิสูจน์ว่าเทสเดิมวิ่งถึงจุดวัด
- `nas-cf` ค้าง = Cloudflare Access หมดอายุ → ให้ user login · NAS ใช้ `sh` (ไม่มี `<(...)`)

### 📋 งานเปิดอื่น
- **backend:** ✅ reader `marks.set` verify รอบอ่านจริงแล้ว (ต่อ 50) · ข้อสังเกตเล็ก: `books.text` 90.9 ms บน loop ครั้งเดียวตอนเปิดเล่ม (ยังไม่คุ้มแก้)
- **จดแยก:** Dream REM วัดด้วย `auto` ตอนมี memory ≥ 5 (รอ memory จากโหมดเสียงสะสม)

### ⏳ รอ user เคาะ
(ข) response cache ข้าม session · คิวเล็กจาก 09-24 (**เช็คสถานะจริงก่อน**): voice idle 1008-loop ตอนคุยธรรมดา (client reconnect วนทุก
151 วิ · ทางแก้ keepalive ยังไม่เคาะ) · ต่อ `scripts/reconcile_keys.py` เข้ารอบกลางคืน · ถอด Google CSE จาก chain
(`utils/websearch.py`) ถ้าไม่แก้ Cloud project

### 🧪 รอ user ทดสอบด้วยมือ
โหมดอ่าน **พัก → อ่านต่อ** หลังตั้ง `audioSession=playback` (เสียงดังพอไหม) · กดลิงก์ `export_file` · ChatBox pills ·
File Manager drag&drop/กล้อง · voice retry ยังไม่เคยถูกกระตุ้นบน prod · "เสียงเบา" รอข้อมูลจาก user (ไม่แตะจอเลยไหม ·
Low Power/ความร้อน) — `underruns` อ่านแล้ว = ไม่ใช่ต้นเหตุ

### ⚪ งานเล็กค้าง
`GEMINI_LIVE_MODEL` จะยกขึ้น `.env` ไหม · AnythingLLM ตกรุ่น (หรือปิดทิ้ง 3.34 GB) · โมเดล local ไม่มีใครใช้ ~14 GB ·
`pythainlp` ไม่มีในอิมเมจ ⇒ เทส `utils/thaiscatter.py` 14 ตัวถูกข้ามทุกที่ · `enhanced.js` map สีตามตระกูลเฉด ·
ป้าย "กำลังค้น" ในโหมดเสียง ·
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
- overlay ที่ React ทำเองแล้วต้อง gate `if (window.__hwReactChatBox) return;` (ตอนนี้: tee/`_parseChatSSE` · Ctrl+E · ↑/↓ · paste · §19/§20 · §22) —
  เพิ่ม feature ใน React แล้วไล่ overlay ที่ทำซ้ำด้วย · เทส `tests/overlay_gating.test.js`
- bookreader: server ปิดสาย = เก็บกวาดหลังเสียงค้างเล่นหมด (`playEnd` + ticker) **ห้าม disconnect ทันที** (ตัดท้ายเล่ม) · สีผู้ช่วยผ่าน `paletteFor()` เท่านั้น
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

