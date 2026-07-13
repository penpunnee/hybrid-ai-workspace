# ROADMAP — Hybrid AI Workspace (Khim AI)

> จัดทำจากการ audit ทั้งโปรเจกต์ 2026-07-12 · สถานะ ณ วันตรวจ: backend 690 tests ผ่านหมด ·
> frontend (appscript.ui) 111 vitest ผ่านหมด, git clean, backup 2 remotes ✅ ·
> โครงหลักแข็งแรง — งานที่เหลือส่วนใหญ่เป็น "ปิด loose ends" ไม่ใช่สร้างใหม่
> ⚠️ สถานะฝั่ง NAS prod ในเอกสารนี้อ้างจากบันทึกล่าสุด (2026-06-18/07-05) — session นี้ตรวจสดไม่ได้ ให้ verify ตอนลงมือ

---

## P0 — ปัญหาที่เจอจริงวันนี้ / เสี่ยงข้อมูล-เสถียรภาพ

### 1. Icon\r recur — ✅ ต้นตอเจอแล้ว + mitigation วางครบ 2026-07-13 (session 3)
- **ต้นตอจริง = Google Drive for desktop ไม่ใช่ iCloud** (iCloud Drive ปิดอยู่จริง `Enabled=0`) — DriveFS mirror ทั้ง `~/Desktop` (root ใน `root_preference_sqlite.db`) แล้วแปะ custom folder icon (รูป home 163KB rsrc) ให้**ทุกโฟลเดอร์** ใน mirror root: sweep ใหญ่ตอน Drive start (~15k ไฟล์/8 นาที) + แปะโฟลเดอร์ใหม่ real-time ภายใน ~60s
- พิสูจน์: trap folder (Icon โผล่ใน 90s) + A/B ปิด Drive (ไม่โผล่ใน 120s) + relaunch แล้วกลับมา · `~/appscript.ui` นอก Desktop ไม่โดน = ยืนยัน scope
- [x] global gitignore: `Icon\r` ใน `~/.config/git/ignore` — คุ้มกันทุก repo (verified `git check-ignore`)
- [x] cleanup script `~/.local/bin/icon-cleanup.sh` (ลบ+log ที่ `~/.local/state/icon-cleanup.log`) — ลบรอบ 6 แล้ว ~25k ไฟล์ (Drive re-stamp ระหว่างลบ)
- [x] **SessionStart hook** ใน `~/.claude/settings.json` รัน script ทุกครั้งที่เปิด Claude Code (async) — เส้นทางที่ทำงานได้จริงเพราะรันใน TCC context ของ Terminal
- [x] LaunchAgent `com.pawin.icon-cleanup` (hourly) ติดตั้งแล้วแต่**โดน TCC บล็อก** (`Operation not permitted` — launchd-bash ไม่มีสิทธิ์ Desktop) — จะ active ก็ต่อเมื่อ user ให้ Full Disk Access กับ `/bin/bash` ใน System Settings (เลือกเองว่าจะให้หรือถอน agent ทิ้ง)
- [ ] ทางแก้ขาดจริง (user ตัดสินใจ): เลิก mirror Desktop ใน Google Drive (Settings → Folders from your computer) หรือย้ายโปรเจกต์ dev ไป `~/dev/` — แถม: ตอนนี้ Drive เผาโควตา/CPU checksum `node_modules` ทั้งยวงด้วย
- 📝 รายละเอียดเต็ม: vault `wiki/concepts/google-drive-icon-cr.md`

### 2. Backup ฐานข้อมูล prod ✅ จบ 2026-07-12
- เจอ+แก้บั๊กจริง: script หยิบ `ui/chat_history.db` (ค้างเก่า 12KB) แทน `ui/data/chat_history.db` (ตัวจริง 933KB) → backup เปล่า
- [x] backup รายคืน 03:30 — ฝังเป็น APScheduler job ในแอป (`utils/db_backup.py`) แทน DSM task (ตั้งจาก SSH ไม่ได้) — verified ได้ archive 143KB จริง
- [x] `chroma_backup` ยืนยันรันจริงทุกคืน 00:01 (ไม่ใช่ 04:00 ตาม docs เดิม)
- [ ] เช็คหลัง 2026-07-13 03:30: `ls ui/data/db_backups/` ต้องมีไฟล์ใหม่รายวัน

### 3. Pin dependencies ✅ จบ 2026-07-12 (ดึงมาทำก่อน rebuild poppler)
- [x] `requirements.lock` จาก `pip freeze` ของ container prod จริง (137 packages) — Dockerfile install จาก lock, `requirements.txt` เป็น spec หลวมไว้อ่าน
- [x] ถือโอกาสไล่ dep ตาย: `streamlit`, `streamlit-ace` ✅ 2026-07-12 (ดู P2-8 — lock regen ด้วย pip dry-run resolve บน py3.11 container: 138→121 pkgs)

---

## P1 — ปลดฟีเจอร์ที่เขียนเสร็จแล้วแต่ยังไม่ทำงาน (งานสั้น, คุ้มสุด)

### 4. ใส่ key ใน NAS `.env` + recreate (ยืนยันสด 2026-07-12: ว่างทั้ง 4 — **user เลือกข้ามไปก่อน**, Kimi ยังไม่มีบัญชี)
- [ ] `ANTHROPIC_API_KEY` → ปลด Claude ใน Model picker (โค้ด+UI พร้อมหมดแล้ว รวม prompt caching)
- [ ] `MOONSHOT_API_KEY` → ปลด Kimi K2.6
- [ ] `HA_URL` + `HA_TOKEN` → Agent สั่ง Home Assistant ได้จริง (tools เขียนเสร็จ 3 ตัว: search/get_state/call_service)
- recreate: `cd /var/services/homes/pawin/ui && sudo docker compose up -d hybrid-ai --force-recreate` (จำ gotcha: `docker restart` ไม่ reload .env)

### 5. ติดตั้ง `poppler-utils` ✅ จบ 2026-07-12
- [x] เจอว่าพังสองชั้น: ไม่มีทั้ง poppler **และ** `pdf2image` ใน requirements — ใส่ทั้งคู่ใน image (Dockerfile apt + lock) verified `pdftoppm 25.03.0` + import ผ่านใน container
- [x] **เทส upload PDF scan จริงผ่าน backend จริง ✅ 2026-07-13** — สร้าง synthetic scan (PIL render ข้อความไทย+อังกฤษเป็นรูป → PDF ไม่มี text layer, verify ด้วย `pdftotext` คืนว่างเปล่าจริง) upload ผ่าน `curl` จาก trusted network ของ NAS เอง (หลีกเลี่ยงกรอก `UI_PASSWORD` เข้า browser form — ไม่ทำแทนแม้เป็น app ของ user เอง) log ยืนยัน auto-detect ทำงานถูก: "PDF scan detected → OCR" → Gemini Vision อ่านได้ 492 ตัวอักษรตรงกับที่ฝังไว้ ✅ **OCR pipeline เองไม่มีปัญหา**
  - 🐛 **เจอบั๊กจริงคนละตัวตอน verify**: `POST /api/documents/search` คืน `results: []` เสมอ ทุกครั้ง แม้เพิ่ง index สำเร็จ — log: `Collection expecting embedding with dimension of 768, got 384`. root cause: `utils/documents.py:index_document()` insert ด้วย vector explicit จาก `embed_texts()` (LM Studio nomic-embed-text, 768-dim) แต่ `retrieve_chunks()` เดิมส่ง `query_texts` เฉยๆ ให้ ChromaDB auto-embed ด้วย **default embedder (MiniLM 384-dim)** — มิติไม่ตรงกับที่ persist ไว้ ไม่เกี่ยวกับ Thai-embedding migration (บั๊กนี้น่าจะมีมาตั้งแต่ Phase B ถูกสร้าง) **แปลว่า document RAG ใน chat (`docs_ctx`) น่าจะไม่เคย retrieve อะไรได้เลย** แก้แล้ว: `retrieve_chunks()` embed query ด้วย `embed_texts()` ตัวเดียวกันส่ง `query_embeddings` แทน (fallback `query_texts` ถ้า embed ล้ม) — เทส 3 เคสใหม่ (`tests/test_documents.py`) suite รวม 738 ผ่านหมด — **ยังไม่ deploy**

### 6. แยก `GEMINI_SEARCH_MODEL` ✅ ปิด 2026-07-13 (พบว่า implement ไปแล้ว)
- [x] ตรวจพบโค้ดรองรับอยู่แล้วตั้งแต่ `7087f88` (2026-06-20): `utils/llm.py` — precedence `model arg > GEMINI_SEARCH_MODEL > GEMINI_MODEL` (รายการ "ค้าง" ใน memory/ROADMAP stale)
- [x] เก็บส่วนที่ขาดจริง: test precedence 3 เคส (`test_gemini_web_search.py`) + docs env ใน CLAUDE.md
- ตั้งค่าใน NAS `.env` = optional tuning (ว่าง = ใช้ `GEMINI_MODEL` flash ตามเดิม ซึ่งโอเคอยู่) — ตั้งเมื่ออยากแยกโควตา grounding ออกจาก chat จริงๆ

---

## P2 — คุณภาพโค้ด / ลดหนี้เทคนิค

### 7. เก็บ pyflakes findings ✅ จบ 2026-07-12
- [x] `cached_mid` — ตรวจแล้ว**ไม่ใช่** logic หล่นหาย (ทุก short-circuit path ส่งเฉพาะ assistant id ใน `done` เหมือนกันหมด) → ลบ binding
- [x] `nonlocal messages` — ใน `generate()` มีแต่ `messages[0] = {...}` (item assignment ไม่ต้อง nonlocal) → ตัดออกจากบรรทัด nonlocal
- [x] `genai_types` loop shadow — **แก้ไปแล้ว**ตอนงาน `Part.from_text` 2026-06-12 (ruff สะอาด) ไม่เหลืออะไรทำ
- [x] กวาด ruff F ทั้ง repo 58 จุด (43 unused import + 9 f-string + 6 unused var) — 697 tests ผ่าน
- [x] **ruff เข้า CI แล้ว** — `ruff.toml` (F-rules, exclude legacy/) + step `Lint (ruff)` ใน workflow (pin 0.15.17)

### 8. ตัด Streamlit legacy ✅ จบ 2026-07-12
- [x] ย้าย `app.py` → `legacy/app.py` + ตัด mount `./app.py` ใน compose + ตัด `streamlit`/`streamlit-ace` จาก requirements.txt
- [x] regen lock แบบแม่น: pip dry-run resolve บน `python:3.11-slim` (ตรง image) constraint=lock เดิม → ตัด 17 pkgs (streamlit×2 + orphan transitives: altair/pandas/pyarrow/pydeck/jinja2/gitpython ฯลฯ) 138→121, เวอร์ชันที่เหลือไม่ขยับ, grep ยืนยันไม่มี source import ตัวที่ตัด
- [x] ตัด layer pre-download ONNX MiniLM ใน Dockerfile — EF จริง = Ollama multilingual; fallback MiniLM ถ้าถูกใช้ recall ก็เพี้ยนอยู่แล้ว, จำเป็นจริง chromadb download เองลง volume `chroma_model_cache`

### 9. Admin API ลบ episodic memory ✅ จบ 2026-07-13 (แก้ pain "memory ปนเปื้อนจากการเทส")
- เดิมเทส `/api/chat` บน prod แล้วต้องต่อ ChromaDB ตรงเพื่อลบขยะ (Known Quirks) — ทำผิดพลาดง่ายและเคยเกิด contamination จริง (2026-06-11)
- [x] `GET /api/admin/memory/{assistant}?q=...` (list+preview) + `DELETE /api/admin/memory/{assistant}/{id}` — LAN-only เหมือน `/api/admin/unlock` (`memory/store.py:list_entries/delete_entry`, commit `5e03fca`)
- [x] `X-Test-Request` header ให้ `/api/chat` ข้าม `remember()`/`teach()`/auto-learn lesson thread ทั้งเส้น — ตัดปัญหาที่ต้นทางแทนต้องลบทีหลัง (`routers/chat.py:_is_test_request`, ครอบทั้ง path ปกติและ agent/`tool_agent` ผ่าน `persist_agent_turn`)
- test: 15 เคสใหม่ (`tests/test_memory_package.py`, `tests/test_routers.py`, `tests/test_test_request_header.py`) — suite รวม 714 ผ่านหมด

### 10. โครงไฟล์เริ่มโต — เฝ้าดู ยังไม่ต้องผ่า
- `utils/llm.py` 860 บรรทัด (5 provider ในไฟล์เดียว), `routers/chat.py` 597, `agents/tools.py` 675
- [ ] ถ้าจะเพิ่ม provider ใหม่อีกตัว → ค่อยแยก `utils/llm/` package ต่อ provider ตอนนั้น (อย่า refactor ลอยๆ)

---

## P3 — งานฟีเจอร์ค้าง (ตามลำดับคุ้ม)

### 11. Local model: หาตัวแทน qwen3.5-9b ที่นิ่งกว่า
- ปัญหาที่บันทึกไว้: ไทย leak จีน/รัสเซีย + ปิด thinking ผ่าน API ไม่ได้ → timeout + บับเบิลว่าง (guard กันไว้แล้ว แต่เป็นปลายเหตุ)
- [ ] ทดลอง candidates ตาม checklist ใน vault `concepts/local-llm-selection-lessons.md`: Typhoon 2.1 / Qwen2.5-Instruct / Gemma3
- [ ] เกณฑ์ผ่าน: ไทยไม่ leak · คุม thinking ได้ (หรือไม่มี) · tool-calling ใช้ได้ · ตอบใน timeout
- [ ] แถม: timeout safety net ฝั่ง server (cap เวลารวมต่อ request แล้วตอบ partial + ขอโทษ แทนปล่อยค้าง 131s)

### 12. Web-search grounding classifier ✅ จบ 2026-07-13 (#34 ค้างตั้งแต่ 2026-06-11)
- **ตัดสินใจ**: คงตัว `needs_internet()` แบบ pattern-based ตามบริบท (ไม่เปิด grounding ทุก call ของ Gemini) — เหตุผล: Gemini free tier มี quota จำกัด (429 limit=0 เจอมาแล้วหลายเคส) เปิด grounding ทุก call จะเผา quota กับ chitchat/coding โดยเปล่าประโยชน์ + เพิ่ม latency ทุกข้อความ ส่วน pattern-based มี test coverage หนาแน่น (45+ เคส) เป็น deterministic ไม่มี side-effect
- **integration test ที่ "ค้าง" จริงๆ มีอยู่แล้ว** พบตอนตรวจ — `tests/test_chat_input.py` เทส wiring ใน `routers/chat.py` ครบ 3 เคส (local model ยืม Gemini grounding / Gemini ใช้ built-in google_search ไม่ inject DDG / casual query ไม่เสิร์ช) เข้าใจผิดว่ายังไม่มีจาก session เก่า
- **วัดผลก่อน-หลัง**: เขียน probe script ยิงคำถาม real-time 16 แบบ (ราคาทอง/อากาศ/ข่าว + กีฬา/จราจร/หุ้น/ภัยพิบัติ/ไฟฟ้าขัดข้อง) ผ่าน `needs_internet()` ตรงๆ → **เจอ 10 gap จริง** (เช่น "ทองคำตอนนี้ราคาเท่าไหร่" สลับลำดับคำไม่ตรง `ราคาทอง`, ไม่มีหมวดกีฬา/จราจร/หุ้น/ภัยพิบัติ/ไฟดับเลย) → เพิ่ม pattern ปิดครบ 8 หมวดใหม่ (`reasoning/classifier.py`) — รันซ้ำผ่านหมด 16/16 + กัน over-trigger คำใกล้เคียง (เช่น "ชอบดูบอลไหม" ไม่ trigger)
- test: 14 เคสใหม่ใน `tests/test_classifier.py` — suite รวม 728 ผ่านหมด

### 13. สะสม 👍 → fine-tune ขวัญ (pipeline พร้อมทั้งเส้นแล้ว)
- [ ] เช็คยอดปัจจุบัน: `GET /api/feedback/stats` (เป้า ~200-500)
- [ ] ระหว่างรอ: รัน `scripts/auto_score.py` (RLAIF) สะสมคู่ auto-scored แยกไว้
- [ ] ครบเป้า → `scripts/improve_loop.sh` บน PC GPU (.235) — **ห้าม deploy ถ้า eval gate FAIL**

### 14. Verify ด้วยตาที่ค้าง (งานเปิด browser 15 นาที)
- [ ] File Manager: drag&drop / กล้อง 📷 / index toast บน prod จริง
- [x] Dream cycle บน prod ✅ เจอ+แก้บั๊กจริง 2026-07-13: `ls dream_reports/` มีไฟล์ทุกคืนจริง แต่ report กลวง (278 bytes, "no memories") **ทุกคืนตั้งแต่ 2026-07-09** (วันที่ deploy Thai-embedding migration) — root cause: `light_sleep()` (Phase 1, `utils/dream.py`) ครอบ loop สแกน `memory_*` collection ทั้งหมดด้วย try/except **เดียว** (ไม่เหมือน `memory_decay`/`memory_prune` ที่ทำ per-collection ถูกอยู่แล้ว) พอเจอ collection backup จาก migration (`*__minilm_backup_20260709`, ยังผูก default embedder เดิม) → embedding function conflict กับ ollama ef ปัจจุบัน → **ทั้งฟังก์ชัน return `[]` ทันที แม้ `memory_kwan`(79)/`memory_logic`(69) ตัวจริงจะมีข้อมูลจริงอยู่ก็ตาม** — Dream ไม่เห็น memory เลยเงียบๆ 4+ คืนติด. แก้เป็น per-collection try/except แบบเดียวกับอีก 2 phase (commit ถัดไป) + เทส 5 เคสใหม่ (`tests/test_dream_light_sleep.py`)
  - ✅ **แก้แล้ว 2026-07-13 (ต่อ session เดียวกัน) — สาเหตุที่ APScheduler ยิงผิดเวลา (09:00 แทน 02:00 บางกอก)**: `core/scheduler.py` สร้าง `CronTrigger(hour=2, minute=0)` โดยไม่ส่ง `timezone=` ตรงๆ — `BackgroundScheduler(timezone="Asia/Bangkok")` **ไม่** inject timezone เข้า `CronTrigger` ที่สร้างแยกไว้ก่อน `add_job()` เอง (พิสูจน์ด้วย script จริง: `CronTrigger(hour=2, minute=0).timezone` → OS-local ของ container ที่ไม่ได้ตั้ง `TZ` = UTC) → ยิงเพี้ยนไป 7 ชม.ตรงเป๊ะ. แก้โดยส่ง `timezone="Asia/Bangkok"` ให้ทั้ง `dream_nightly` และ `db_backup_nightly` ตรงๆ + เทส regression 2 เคส (`tests/test_scheduler.py`) — suite รวม 735 ผ่านหมด
  - ✅ **หาต้นตอ external `POST /api/dream` เจอแล้ว 2026-07-13**: `/etc/crontab` (อ่านได้ไม่ต้อง sudo) ชี้ไป **DSM Task Scheduler task id=3 ("Task 3")** — `curl -s -X POST http://localhost:8080/api/dream -d '{"provider":"gemini"}'` รันทุกวัน 02:00 (DSM local = Bangkok). ไฟล์ `3.task` สร้าง **2026-04-22** ส่วน in-app scheduler (`core/scheduler.py`) เพิ่งมีตั้งแต่ **2026-05-11** — ยืนยันว่าเป็น task เก่าจากก่อนมี in-app scheduler ที่ไม่เคยถูกลบ ไม่ใช่ automation ตัวใหม่
  - ✅ **deploy ครบทั้ง 2 code fix แล้ว 2026-07-13** (`3d479b5` light_sleep + `84e255d` scheduler timezone) — verified prod: `ai-backend-1` healthy + `/api/status.next_dream_schedule` = `"2026-07-14 02:00"` (เวลาบางกอกถูกต้อง)
  - [ ] **ค้างจริง (ต้อง user รันเอง — ต้อง sudo password, ให้คำสั่งไว้แล้วแต่ยังไม่ยืนยันว่ารันแล้ว)**: `sudo /usr/syno/bin/synoschedtask --set id=3 enable=no` ผ่าน `ssh -o ProxyCommand="cloudflared access ssh --hostname %h" pawin@ssh.pawinhomelab.com` — **สำคัญ: ถ้าไม่ปิดก่อนคืนนี้ (2026-07-13 ~02:00 น. บางกอก) Dream Cycle จะรันซ้ำ 2 รอบพร้อมกันเป๊ะ** (DSM task เดิม + in-app scheduler ที่เพิ่ง fix เวลาให้ตรงพอดีแล้ว) — เช็คผลด้วย `sudo /usr/syno/bin/synoschedtask --get id=3 | grep state` ต้องได้ `state=disabled`

### 15. พักไว้ตามการตัดสินใจเดิม (อย่าหยิบมาทำจนกว่าเงื่อนไขเปลี่ยน)
- ⛔ Image Gen — โค้ดพร้อม รอเปิด billing Google (~$0.04/รูป)
- ⛔ Ollama เป็น provider หลัก — คงเป็น dormant fallback

---

## สิ่งที่ตรวจแล้ว "ดีอยู่แล้ว" (ไม่ต้องแตะ)

| ด้าน | สถานะ |
|---|---|
| Test coverage | 690 backend + 111 frontend + JS `node --test` ใน CI — ครอบดีมากสำหรับโปรเจกต์ส่วนตัว |
| Security | fail-closed auth, rate limit + brute-force lockout, LAN bypass spoof-resistant, secrets ใน .env/PropertiesService ไม่ hardcode |
| Resilience prod | restart:always + healthcheck + backend-watchdog (recovery path พิสูจน์จริงแล้ว) |
| Anti-hallucination | 4 ชั้น (system guard / tool guard / learn gate / ข้อมูลจริง) + Agent mode |
| Backup โค้ด | ui → GitHub ✅ · appscript.ui → NAS + GitHub ✅ (เพิ่งปิดช่องโหว่ 2026-07-05) |
| Thai embedding | แก้ทั้งระบบแล้ว (`5a26ba5`) — MiniLM → Ollama multilingual |
| Docs | CLAUDE.md / CONTEXT.md / DEVLOG.md ละเอียดผิดปกติ (ในทางดี) — รักษาวินัยนี้ไว้ |

---

## ลำดับแนะนำ (ถ้าทำทีละ session)

1. **Session แรก (infra, ~1 ชม.):** P0-2 backup task + P1-4 ใส่ key 3 ตัว + P1-5 poppler — งาน NAS ล้วน จบแล้วฟีเจอร์ที่จ่ายเงินเขียนไปแล้วเริ่มทำงานครบ
2. **Session สอง (คุณภาพ, ~1-2 ชม.):** P0-3 pin requirements + P2-7 pyflakes/ruff เข้า CI + P2-8 ตัด streamlit — ลดความเสี่ยง rebuild + กัน regression ระยะยาว
3. **Session สาม (ต้นตอ):** P0-1 Icon\r ถาวร + P2-9 admin memory API
4. **จากนั้น:** P3 ตามลำดับ 11 → 12 → 13 (13 ขึ้นกับยอด 👍 ไม่ใช่ effort)
