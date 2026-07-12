
---

## [2026-07-12] SECTION — ROADMAP session 2 (คุณภาพ): ruff เข้า CI + ตัด Streamlit
**เป้าหมาย:** P2-7 (pyflakes findings + ruff CI) + P2-8 (ตัด Streamlit legacy) ตาม ROADMAP

### P2-7 — ตรวจ 3 จุด smell ก่อนกวาด (ไม่ใช่แค่ลบตามเครื่องบอก)
| จุด | ผลตรวจ | สรุป |
|---|---|---|
| `cached_mid` (routers/chat.py) | ทุก short-circuit path (image_gen/active_learning) ก็ save user msg โดยไม่เก็บ id, `done` ส่งเฉพาะ assistant id ตาม schema | ไม่ใช่ logic หล่นหาย → ลบ binding |
| `nonlocal messages` (generate) | ใน generate() มีแต่ `messages[0] = {...}` (item assignment) ไม่มี rebinding | nonlocal ไม่จำเป็น → ตัดออก |
| `genai_types` loop shadow (orchestrator) | ruff สะอาด — ถูกแก้ไปแล้วตอนงาน `Part.from_text` 2026-06-12 | ปิดได้ ไม่มีงาน |

- กวาด ruff F ทั้ง repo: 58 จุด (43 F401 unused import / 9 F541 f-string / 6 F841 unused var) — F841 แก้มือทีละตัว
- ⚠️ บทเรียน: replace `results = _collect(` แบบเหมาโดน 4 จุดทั้งที่ flag แค่ 2 — อีก 2 tests ใช้ `results` ต่อจริง (พังแบบ NameError) → เช็ค grep ก่อน/หลังเสมอ แก้คืนแล้ว
- **ruff เข้า CI:** `ruff.toml` (F-rules, exclude legacy/.venv/data/sandbox) + step `Lint (ruff)` pin `0.15.17` ใน `tests.yml` ก่อน pytest

### P2-8 — ตัด Streamlit legacy
- `git mv app.py legacy/` + ตัด mount `./app.py` ใน compose + ตัด `streamlit`/`streamlit-ace` จาก requirements.txt
- **regen lock แบบแม่น (ไม่มี py3.11 บน Mac):** รัน `pip install --dry-run --report` ใน container `python:3.11-slim` บน NAS โดย `-r requirements.txt -c requirements.lock` (constraint = lock เดิม) → closure 121 pkgs, ตัด 17 (streamlit×2 + orphans: altair/pandas/pyarrow/pydeck/jinja2/markupsafe/gitpython/gitdb/smmap/blinker/cachetools/itsdangerous/narwhals/toml/watchdog), **ADDED 0 / VERSION CHANGED 0** + grep ยืนยันไม่มี source import ตัวที่ตัด
- **ตัด layer pre-download ONNX MiniLM ใน Dockerfile:** EF จริง = Ollama multilingual (`EMBEDDING_MODEL`) ตั้งแต่ `5a26ba5`; MiniLM เหลือเป็น fallback ที่ถ้าถูกใช้จริง recall ก็เพี้ยนอยู่แล้ว (คนละ model กับข้อมูล) — จำเป็นจริง chromadb download เองลง volume `chroma_model_cache`
- 🧿 **หลักฐาน Icon\r P0-1:** `Icon\r` โผล่ใน `.ruff_cache/` ที่เพิ่งสร้างระหว่าง session = ตัวเขียน (iCloud) ยัง active อยู่ตอนนี้ ไม่ใช่ซากเก่า — session 3 ต้องปิดที่ต้นตอ
- **Validation:** suite 697 passed (เพิ่มจาก 690 — มี test ใหม่จาก session 1) · ruff clean · CI #143 เขียว (ruff step แรกผ่าน)
- **Deploy (2026-07-13 00:1x):** rebuild image บน NAS — **1.11GB → 769MB (−341MB)** · recreate ชนซากชื่อ `8d8498f72f30_ai-backend-1` รอบแรก (watchdog race — ซากหายเอง) → `compose up -d` รอบสองผ่าน · verified ใน container: STREAMLIT-GONE, `pdftoppm 25.03.0` อยู่ครบ, `import pdf2image/chromadb/anthropic` ผ่าน, pip 126 รายการ · `/api/status` healthy (local_ok/gemini/memory true)

### P1-6 GEMINI_SEARCH_MODEL — ปิดโดยไม่ต้องเขียนฟีเจอร์
- ตรวจก่อนทำ → **พบว่า implement ไปแล้ว**ตั้งแต่ `7087f88` (2026-06-20): precedence `arg > GEMINI_SEARCH_MODEL > GEMINI_MODEL` — รายการค้างใน ROADMAP/memory stale
- เก็บที่ขาดจริง: test precedence 3 เคส (`test_gemini_web_search.py` 4→7) + docs env ใน CLAUDE.md · ตั้งค่าใน NAS `.env` = optional tuning (ว่าง = flash เดิม)
- บทเรียน: รายการ "ค้าง" ที่จดข้าม session ต้อง grep โค้ดก่อนลงมือเสมอ
---

## [2026-07-12 19:50] SECTION — audit ทั้งโปรเจกต์ + ROADMAP session 1 (งาน NAS)
**เป้าหมาย:** audit ทั้งโปรเจกต์ → `ROADMAP.md` แล้วทำ session 1: backup + key + poppler

### Breadcrumb Ledger (บั๊กหลักที่เจอ: db_backup ได้ archive เปล่า)
| # | สมมติฐาน/สิ่งที่ลอง | วิธีที่ใช้แก้ | ผลที่ได้ | ผ่าน? | เพราะอะไร (ถ้าไม่ผ่าน) |
|---|---------------------|-------------|---------|-------|------------------------|
| repro | test-run `db_backup.sh` จริงบน NAS ก่อนตั้ง schedule | — | ✅ script รันผ่าน แต่ archive แค่ **989 bytes** (DB จริง 933KB) | ❌ | ขนาดผิดปกติ = backup ผิดไฟล์ |
| H1 | script ชี้ path ผิด | เทียบ DBS list กับ compose mounts | script อ่าน `$UI_DIR/chat_history.db` (root repo, 12KB, เม.ย.) แต่ compose mount DB จริงจาก `$UI_DIR/data/chat_history.db` (933KB) | ✅ | root cause: layout host ≠ ที่ script เดา |
| fix | TDD: test seed ทั้ง 2 ตำแหน่ง + marker table → assert ได้ตัว data/ | prefer `data/chat_history.db` ถ้ามี, fallback root | archive 144KB (เดิม 989B) | ✅ | |

- **Root cause:** `scripts/db_backup.sh` เขียนตาม layout dev (Mac: DB อยู่ root repo) แต่ prod mount DB จาก `data/` — root repo มีไฟล์ค้างเก่าชื่อเดียวกันหลอกให้ script "สำเร็จ" ด้วยข้อมูลผิด. บทเรียน: **backup ต้อง test-run + ดูขนาด archive จริงก่อนตั้ง schedule เสมอ**
- **งานอื่นใน session:** in-app backup job 03:30 (`utils/db_backup.py` + APScheduler — ตั้ง DSM task จาก SSH ไม่ได้เพราะ sudo จำกัด docker) + mount `data/db_backups` · poppler จบ (พัง 2 ชั้น: image ไม่มี poppler + `pdf2image` ไม่อยู่ใน requirements) · `requirements.lock` pin 137 pkgs จาก pip freeze container จริง · Icon\r recur รอบ 5 (2,668 ไฟล์ ลามเข้า .venv block pytest — ลบแล้ว)
- **Validation:** suite 697 passed · deployed `ecf005d`+`8d6ac25` rebuild+recreate · verified ใน container: `pdftoppm 25.03.0`, `import pdf2image` OK, trigger `run_db_backup()` ได้ archive 143KB บน host · `/api/status` healthy
- **ค้างเช็ค:** หลัง 2026-07-13 03:30 → `ls ui/data/db_backups/` บน NAS ต้องมีไฟล์ใหม่อัตโนมัติ
---

## [2026-06-16 01:56] SECTION #1 (mode 1 — หาบั๊กในโปรเจค)
**เป้าหมาย/อาการ:** หาบั๊กในโปรเจค — รัน test suite แล้วเจอ 1 fail: `test_claude_llm.py::test_unconfigured_no_key`

### Breadcrumb Ledger
| # | สมมติฐาน/สิ่งที่ลอง | วิธีที่ใช้แก้ | ผลที่ได้ | ผ่าน? | เพราะอะไร (ถ้าไม่ผ่าน) |
|---|---------------------|-------------|---------|-------|------------------------|
| repro | รัน `pytest --ignore=test_mcp_server` | — | 631 passed, 1 failed (test_unconfigured_no_key) + collect-error test_mcp_server (missing `mcp` dep = env, ข้าม) | — | repro ได้ deterministic |
| H1 | `_stream_claude` branch logic ผิด (โค้ดบั๊ก) | อ่าน utils/llm.py:673-680 | branch ถูก: anthropic None→install msg / มี SDK ไม่มี key→ANTHROPIC_API_KEY msg | ❌ | โค้ด production ถูกต้อง ไม่ใช่สาเหตุ |
| H2 | test ขึ้นกับ ambient state (anthropic ลงหรือไม่) | เช็ค `.venv/bin/python -c "import anthropic"` → ImportError; requirements.txt:22 มี anthropic | `llm.anthropic is None` ใน .venv → \_stream\_claude เข้า branch "no SDK" → assert fail. CI ลง anthropic → ผ่าน | ✅ | root cause จริง: test ไม่ pin `llm.anthropic` |

- **Root cause:** `test_unconfigured_no_key` patch แค่ `anthropic_client=None` แล้วพึ่ง module-level `llm.anthropic` ว่าเป็น truthy (SDK ลงจริง) โดยปริยาย → ผลเทสขึ้นกับ env (เขียวบน CI ที่ลง anthropic, แดงบน .venv ที่ไม่ลง). production code ถูกต้อง — เป็น **test bug** (hidden coupling กับ ambient install state)
- **วิธีที่แก้ผ่าน:** pin `monkeypatch.setattr(llm, "anthropic", object())` ใน test ให้ express เจตนา "SDK ลงแล้วแต่ไม่มี key" แบบ deterministic — สมมาตรกับ `test_unconfigured_no_sdk` ที่ set `anthropic=None` ชัดเจน (tests/test_claude_llm.py:67-73)
- **Validation:** `pytest tests/test_claude_llm.py` → 17 passed · full suite → **632 passed** (เดิม 631+1fail)

---

## [2026-06-16 07:23] SECTION #2 (mode 1 — หาบั๊กต่อ: static analysis)
**เป้าหมาย/อาการ:** test เขียวหมดแล้ว → ไล่หาบั๊กที่ test ไม่ครอบ ด้วย pyflakes

### Breadcrumb Ledger
| # | สมมติฐาน/สิ่งที่ลอง | วิธีที่ใช้แก้ | ผลที่ได้ | ผ่าน? | เพราะอะไร (ถ้าไม่ผ่าน) |
|---|---------------------|-------------|---------|-------|------------------------|
| scan | ติดตั้ง pyflakes + scan source | — | เจอ undefined names ใน server.py: GEMINI_API_KEY (209,220), GEMINI_LIVE_MODEL (234), WebSocketDisconnect (258,306) | — | candidate latent NameError |
| repro | เขียน failing test `tests/test_voice_ws.py` (mock genai.Client กัน network) connect /ws/voice | — | RED — แต่ปิดด้วย code 1008 `{loc:['query','websocket'],msg:'Field required'}` ก่อนถึง NameError | ❌ | เจอบั๊กที่ 2 ลึกกว่า: param `websocket` ไม่มี type annotation → FastAPI มองเป็น query param |
| H1 | handler ถูกย้ายเข้า server.py โดยไม่ยก import/annotation ตาม | แก้ 3 จุด | (1) line 7 import `WebSocket, WebSocketDisconnect` (2) line 12 import `GEMINI_API_KEY, GEMINI_LIVE_MODEL` จาก core.config (3) annotate `websocket: WebSocket` | ✅ | root cause จริง — ชื่อทั้งหมดมีนิยามอยู่แล้ว (core/config.py:18,20 · fastapi) แค่ไม่ได้ import |

- **Root cause:** voice WebSocket handler `/ws/voice/{slug}` (server.py) ถูกเขียน/ย้ายเข้ามาโดยไม่ได้ import ชื่อที่ใช้ + ลืม annotate `websocket: WebSocket` → **voice chat พังสนิท**: ทุกการเชื่อมต่อถูก FastAPI ปฏิเสธด้วย validation error (param ไม่ annotate) และถ้าผ่านจุดนั้นก็ NameError ต่อ. test เดิมไม่ครอบเส้น WS เลย จึงไม่เคยจับได้
- **วิธีที่แก้ผ่าน:** server.py — เพิ่ม `WebSocket, WebSocketDisconnect` ใน fastapi import (line 7), เพิ่ม `GEMINI_API_KEY, GEMINI_LIVE_MODEL` ใน core.config import (line 12), annotate `websocket: WebSocket` (line 201)
- **Validation:** `tests/test_voice_ws.py` ผ่าน (hermetic, mock genai กัน network) · pyflakes server.py = no undefined names · full suite **633 passed**

### pyflakes findings ที่เหลือ (ยังไม่แก้ — severity ต่ำกว่า, รอตัดสินใจ)
- `agents/orchestrator.py:224` import `genai_types` ถูก loop variable บัง — อาจเป็นบั๊กจริง ควรดู
- `routers/chat.py:123` `cached_mid` assigned แต่ไม่ใช้ — อาจเป็น logic ที่หล่นหาย
- `routers/chat.py:369` `nonlocal messages` ไม่เคย assign — smell
- `routers/system.py:165` `logger` local assigned ไม่ใช้
- f-string ไม่มี placeholder หลายจุด (memory/teach.py:86, utils/llm.py:233, utils/home_tools.py:233, utils/query_rewrite.py:63-66, scripts/bench_cache.py:195) — ส่วนใหญ่ cosmetic

---

## [2026-06-16 08:33] SECTION #3 (mode 1 — verify pyflakes findings ที่เหลือ)
**เป้าหมาย/อาการ:** ตรวจ findings ที่เหลือจาก SECTION #2 ว่าเป็นบั๊กจริงไหม

### Breadcrumb Ledger
| # | finding | ตรวจสอบ | ผล | บั๊ก? |
|---|---------|---------|-----|------|
| 1 | `agents/orchestrator.py:224` genai_types shadow | line 224 re-import เหมือน line 158 เป๊ะ (module+ชื่อเดียวกัน) | redundant re-import ใน loop, ไม่เปลี่ยน behavior | ❌ ไม่ใช่บั๊ก |
| 2 | `routers/chat.py:123` cached_mid unused | save_message() persist user turn (side effect) — return id ไม่ต้องใช้ (ส่งกลับแค่ cached_aid) | unused return value, side effect ยังทำงาน | ❌ ไม่ใช่บั๊ก |
| 3 | `routers/chat.py:369` nonlocal messages unused | — | smell, ไม่กระทบ | ❌ ไม่ใช่บั๊ก |
| 4 | f-string ไม่มี placeholder (6 จุด) | llm.py:233 log literal · query_rewrite.py:64,66 `f"พรุ่งนี้"`/`f"tomorrow"` ตั้งใจคืน literal (ต่างจาก sibling ที่ interpolate วันที่) · teach.py:86 log · home_tools.py:233 | `f` prefix เกินมาเฉยๆ ไม่มี interpolation ที่ลืม | ❌ ไม่ใช่บั๊ก |

- **สรุป:** ไม่เจอบั๊กใหม่ — findings ที่เหลือเป็น cosmetic ล้วน (unused var / redundant import / unnecessary f-prefix). ไม่แก้ตามกฎเหล็ก (ไม่มี failing behavior). ถ้าจะทำเป็น cleanup pass แยกต่างหากได้ แต่ไม่ใช่บั๊ก

---

## [2026-06-16 09:43] SECTION #4 (verify voice UI end-to-end บน prod)
**เป้าหมาย:** ยืนยัน voice chat ทำงานจริง end-to-end หลัง deploy (ไม่ใช่แค่ test ที่ mock network)

### Breadcrumb Ledger
| # | สิ่งที่ลอง | ผล | บั๊ก? |
|---|----------|-----|------|
| live #1 | ยิง WS จริง /ws/voice/kwan (หลัง deploy a07ba34) | connection ถึง handler (ไม่ 1008 แล้ว) แต่ error event: `gemini-2.0-flash-exp not found for bidiGenerateContent` | ✅ เจอบั๊กที่ 2 (model config เก่า) |
| diag | ListModels (v1alpha) filter bidiGenerateContent | gemini-2.0-flash-exp/gemini-live-2.0-flash-001 ถูกถอด → valid: gemini-2.5-flash-native-audio-latest ฯลฯ | — |
| fix verify | ทดสอบ live turn ตรงกับ google.genai 2 รุ่น | native-audio-latest: audio 46KB + turn_complete=True ✅ | — |
| deploy | DSM Task Scheduler `deploy-hybrid-ai` (SSH โดน Auto Block + WG ไป .49 ไม่ทะลุ — NAS ยังเข้าได้ผ่าน Cloudflare) | restart สำเร็จ (status 200 ผ่าน ai.pawinhome.com) | — |
| live #2 | ยิง WS จริงผ่าน `wss://ai.pawinhome.com/ws/voice/kwan` | **connected → text → done · audio 46 chunks/176KB · "ได้ยินค่ะพี่ปอย 😊"** | ✅ end-to-end PASS |

- **สรุป:** voice chat ทำงานครบสายบน prod — WS connect → Gemini Live session → audio+transcript stream → turn complete
- **บั๊กที่แก้รวม session นี้:** (1) flaky anthropic test (2) voice WS handler พัง (annotation+imports) (3) GEMINI_LIVE_MODEL default เก่า → ทั้งหมาด deploy+verified prod
- **หมายเหตุ (optional, ไม่ใช่ regression):** รุ่น native-audio เปิด thinking → `model_turn` มี part `thought` ปนกับ `text` → handler (server.py ~283-288) append .text ของ thought เข้า transcript ด้วย → reasoning โผล่ใน {type:text} ที่ส่ง UI. เสียงจริงถูกต้อง แต่ถ้าไม่อยากให้ thought โชว์ ควร filter `getattr(part,'thought',False)` — งานต่อแยก

---

## [2026-06-16 21:45] SECTION #5 (จบงาน voice ที่ค้าง + commit React source)
**เป้าหมาย/อาการ:** voice bubble ผู้ช่วยว่างเปล่าบน native-audio (regression ที่ SECTION #4 จดไว้ว่า "งานต่อแยก") — fix เขียนค้างครึ่งทาง

### Breadcrumb Ledger
| # | สมมติฐาน/สิ่งที่ลอง | วิธีที่ใช้ | ผล | ผ่าน? |
|---|---------------------|----------|-----|-------|
| repro | อ่าน server.py:281-283 + utils/voice.py (uncommitted) | — | inline handler สะสม `ot.text` ลง ai_transcript แต่**ไม่** send_json ให้ UI → bubble ว่าง. ฟังก์ชัน pure `live_server_content_events` + test (5) เขียนเสร็จแต่ยังไม่ wire | — |
| H1 | handler ยังใช้ inline เดิม ไม่ได้เรียกฟังก์ชันใหม่ | grep server.py | ยืนยัน: import แค่ `speakable_part_text`, ไม่มี `live_server_content_events` | ✅ root cause = งาน wire ค้าง |
| fix | wire ฟังก์ชันเข้า handler | server.py: import→`live_server_content_events`, แทน inline 277-290 ด้วย `events,user_delta,ai_delta = live_server_content_events(sc)` + ส่ง events | pyflakes clean (speakable import หาย, ไม่มี unused ใหม่) · voice tests 6 · full suite **657 passed** | ✅ |
| deploy | push origin main + NAS reset --hard + restart ai-backend-1 | — | reset → 957fe23, container up HTTP 200, local_ok:true | ✅ |
| live | ยิง WS จริงใน container `ws://localhost:8000/ws/voice/kwan` ส่ง text turn | — | **EVENT_COUNTS {connected:1, text:2, audio:9, done:1}** · AI_TEXT "สวัสดีค่ะพี่ปอย! 😊" | ✅ end-to-end PASS |

- **Root cause:** fix voice transcript เขียนเป็นฟังก์ชัน pure + test เสร็จ แต่ไม่ได้ refactor handler ให้เรียก → production ยังรันโค้ด inline เดิมที่ไม่ส่ง `output_transcription` ให้ UI. native-audio พูดข้อความผ่าน ot (model_turn เป็น audio+thought ที่ถูกกรอง) → bubble ว่าง
- **วิธีที่แก้ผ่าน:** server.py wire `live_server_content_events(sc)` → events {"type":"text"} จาก ot ถึง UI · commit `957fe23` · deployed+verified prod (text:2 จาก text:0)
- **React source ที่ค้าง (`~/appscript.ui`):** commit `5d12043` — agentsteps.ts/markdown.tsx/reveal.ts + tests (vitest 13) ที่ build deploy ไปแล้ว (backend a7c67fe/2e1ad97) แต่ source ไม่เคย commit (ปิด Next Step #25 risk)

---

## [2026-06-17 04:38] SECTION #6 (port overlay features เข้า React — agent timeline + composer helpers + dream stats)
**เป้าหมาย:** ทยอยย้าย overlay ของ enhanced.js เข้า React (Next Step #30/#36) — เลิกหนี้ DOM-patching/document-level event delegation

### งานที่ทำ
| # | ฟีเจอร์ | สถานะก่อนหน้า | วิธี | ผล |
|---|---------|--------------|------|-----|
| 1 | **Agent timeline** | commit 5d12043 wire parsing ไว้แล้ว | verify ครบสาย: parser (agentsteps.ts) ครอบ 5 type ที่ backend ยิง (thinking/tool_call/tool_result/answering/max_steps) + wire 3 SSE loop + render AgentTimeline | ✅ **verified prod** — ยิง agent จริงได้ thinking→tool_call→tool_result→answering. แก้ stale comment chat.py:306 |
| 2 | **Composer helpers** | overlay เดิม (document-level) | port เป็น React-native 3 ตัว: `utils/tokencount.ts` (pill ตัวอักษร/tokens, warn>1500/hot>3000) · `utils/draft.ts` (autosave key เดิม hw_draft_<sid>, save debounce อ่าน sidRef → ไม่ save ตอนสลับ session, restore เมื่อกล่องว่าง) · `utils/slash.ts` (เมนู "/" + ArrowUp/Down/Enter/Tab/Escape) · wire เข้า composer (absolute menu/pill, onKeyDown ดัก slash ก่อน Enter→send) · gate IIFE เดิมด้วย `__hwReactChatBox` | ✅ vitest +17 · deployed `546ae20` |
| 3 | **Dream stats** | overlay DOM-patch ทับ % ทุก 2s | `utils/dreamstats.ts` (port dreamCardValues) → render light/rem/deep counts ตรงใน sleep card แทน hardcoded 40/40/20% (dreamReport โหลดตอน mount) + tooltip phase · gate fetchDreamStats/applyDreamStats ด้วย `__hwReactChatBox` | ✅ vitest +5 · deployed `c3432cd` · **verified prod**: /api/dream/report → light=22 themes=2 |

- **สถาปัตยกรรม:** ทุกตัวทำตาม pattern เดิม (extract pure util + vitest → wire React → gate overlay เดิมด้วย `__hwReactChatBox`). enhanced.js มี 4 guards (initTokenCounter/initDraftAutosave/initSlashPrompts/dream applier) — overlay เป็น fallback ของ bundle เก่าเท่านั้น
- **timing:** React module (index.html บรรทัด 10, type=module) รันก่อน enhanced.js (บรรทัด 19, defer) ใน doc order → `__hwReactChatBox` ถูกตั้งก่อน guard เช็ค ✅
- **deploy:** frontend-only — static เสิร์ฟจาก disk → git pull พอ ไม่ต้อง restart container. vitest รวม utils/ **55 ผ่าน** (10 files)
- **bundle:** index-Cn7b8BSq.js · enhanced.js ?v=20260617-dream
- **เหลือ overlay ที่ยังไม่ port (optional):** Home Panel FAB (System/NAS/Docker/PC/WoL), Export PNG, Global search (Ctrl+Shift+F), File Manager §18 — ตัวใหญ่/UI เยอะ

---

## [2026-06-17] SECTION #7 (แก้บั๊ก enhanced.js เรียก /config → 404)
**เป้าหมาย/อาการ:** bug ที่จดไว้ตอน browser-verify SECTION #6 — `static/enhanced.js` เรียก `/config` ได้ 404 → เข้า `.catch()` → FAB Vault ไม่โผล่ผ่านเส้นนี้

### Breadcrumb Ledger
| # | สมมติฐาน/สิ่งที่ลอง | วิธี | ผล | ผ่าน? |
|---|---------------------|------|-----|-------|
| repro | grep config fetch ใน enhanced.js | — | บรรทัด 852 = `fetch("/config")` · จุดอื่น (1487/2818) = `/api/config` → 852 ตกหล่น prefix `/api` | ✅ |
| verify route | grep backend | routers/system.py:61 `@router.get("/config")` (router prefix `/api`) คืน `has_vault` จาก `OBSIDIAN_VAULT_PATH` → route จริง = `/api/config` | ✅ ยืนยัน path ผิด |
| fix | แก้ string เดียว | enhanced.js:852 `/config`→`/api/config` + bump index.html `?v=20260617-home`→`-cfgfix` | grep ไม่เหลือ `/config` ผิด, จุดอื่นไม่โดนแตะ | ✅ |
| deploy | push + DSM pull (off-LAN) | — | commit `02ac0c7` · verified prod ผ่าน Cloudflare Tunnel: enhanced.js:852 = `/api/config`, index เสิร์ฟ `?v=...-cfgfix` | ✅ end-to-end |

- **Root cause:** overlay เก่าเขียน path ขาด prefix `/api` (backend router mount ที่ `/api`) — กระทบเฉพาะ FAB Vault visibility เส้นนี้ ไม่กระทบ React (ใช้ `/api/config` ถูกอยู่แล้ว)
- **surgical:** แตะ 2 บรรทัด (enhanced.js:852 + index.html cache-bust) เท่านั้น
