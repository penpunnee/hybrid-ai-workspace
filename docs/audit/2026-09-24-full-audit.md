# 🩺 ตรวจทั้งระบบ 2026-09-24 (บ่าย) — "ห้ามข้าม ห้ามเว้น หาข้อผิดพลาด"

วิธี: 6 สายตรวจโค้ดคู่ขนาน (core/infra · routers · LLM/agent · memory/RAG · เสียง/reader · frontend) อ่านไฟล์เต็มทุกไฟล์ในขอบเขต
+ repro read-only ใน `/tmp/uivenv` · ผมตรวจ runtime บน prod เองผ่าน `nas-cf` และยืนยันข้อ CRITICAL/HIGH ซ้ำด้วยการอ่านโค้ดจริง
ลำดับที่แนะนำอยู่ท้ายไฟล์ · การแก้แต่ละข้อต้องมี failing test ก่อน (Iron Law)
**สถานะ:** ✅ ก้อน 1 ปิดแล้ว 09-24 ค่ำ (`ff1ce17` · HIGH 1, 2, 7 + share token 40-bit ใน LOW) — devlog [ต่อ 10]
· ✅ **ก้อน 2 ปิดแล้ว 09-24 ดึก (`e5223ef` · HIGH 3, 4)** — devlog [ต่อ 11] · ข้อ 4 ร้ายแรงกว่าที่ประเมิน: prod 24/30 memory created_at เป็นของคนอื่น
(กู้จาก id แล้ว 28 รายการ · confidence/access_count กู้ไม่ได้ → รีเซ็ตตัวนับ)
· ✅ **ก้อน 3 ปิดแล้ว 09-24 ดึก (`82681d9` · HIGH 5, 6, 8)** — devlog [ต่อ 12] · ข้อ 5 พิสูจน์บน prod ว่าอ่าน `/proc/self/environ` ได้จริง ·
มี 2 ทางเข้า (agent tool + `POST /api/fs/search`) ปิดที่ `search_files` จุดเดียว
· ✅ **ก้อน 4 ปิดแล้ว 09-24 ดึก (`fdc269a` · HIGH 9, 10, 11, 12)** — devlog [ต่อ 13] · ข้อ 12 ยืนยัน image มี `.env`+`data` 605 MB จริง ·
ข้อ 10 วัด prod = 0 hit (ประเมินแรงไป) · ✅ rebuild+prune image แล้ว (devlog [ต่อ 14] · image เก่าที่มี `.env` หายหมด) · ที่เหลือยังไม่แก้ (HIGH 13-14 + MEDIUM/LOW)

## 0. runtime บน prod — สะอาด (ยืนยันของจริง)
- NAS HEAD = main · CI เขียว · `ai-backend-1` healthy restarts=0 · watchdog/cloudflared up 4 สัปดาห์ · ERROR 24 ชม. = 0
- sqlite ทุกไฟล์ `integrity_check ok` · **backup กู้ได้จริง** (แตก tar ล่าสุด → DB 4 ใบ integrity ok) · chroma backup รายคืน
- บริการภายนอกตอบครบ (ChromaDB · LM Studio · Ollama · HA · Gemini `gemini_ok`) · skills 22=22=22 · bundle git=dist=served
- ประตู WS: loopback → 101 (LAN bypass) · ปลอม CF header → 403 · `chromadb` "Up 13 ชม." = DSM task `chroma-backup` stop/start ทุกคืน (ยืนยันแล้ว ไม่ใช่ crash)
- ขยะ: `data/reader.db.bak-*` 4 ไฟล์ × 130 MB (08-13/15) · `data/YYYY-MM-DD-dream.md` เก่า (05-07→07-06) ที่ root ของ data
- 🔴 **ถอนข้อสรุป [ต่อ 8]**: 1007 "token เกิน 8192" (09-22 06:10) เกิดบนสายเสียงที่**เปิดสด** #367 หลังเงียบ 10 ชม. (37 วิหลัง connect ·
  ในช่วง 19:30→06:15 มี `go_away` **0** ครั้ง) ⇒ ทั้ง "resume_handle พาบริบทข้าม 1008-reconnect" (ของผม — ผิด: handle เป็น local ต่อ handler)
  และ "โซ่ go_away regen" (สายเสียงเสนอ — ผิด: ไม่มีใน log) **ไม่ใช่สาเหตุ** · ต้นเหตุยังไม่รู้ · สายเสียงไม่ log `usage=` (reader มี) จึงวัดไม่ได้
  · ที่ยืนยันได้จริง: 1008-loop = client reconnect วน (`voicelive.ts:638` error→`scheduleRetry`, cap 3 นับเฉพาะล้มติดกัน) ไม่มี idle cutoff ทั้งสองฝั่ง

## 1. 🔴 CRITICAL / HIGH (ความปลอดภัย + ข้อมูลเสียหาย)
| # | ที่ | ข้อผิดพลาด | ผล | ยืนยัน |
|---|---|---|---|---|
| 1 | `server.py:183` `/shared/{token}` | ใส่ path param ดิบลง JS ใน HTML (`fetch('/api/shared/{token}')`) · `/shared` เป็น open prefix | XSS จากลิงก์เดียว → อ่าน `localStorage.hw_auth_token` = **`UI_PASSWORD` ตัวจริง** (`routers/auth.py:24` คืนรหัสเป็น token) | repro จริง (TestClient) + อ่านโค้ด |
| 2 | `routers/auth.py:24` + `enhanced.js:467` + `voicelive.ts:256` `bookreader.ts:91` + `server.py:938` | token = รหัสผ่านดิบ เก็บ localStorage และแนบ `?token=` ใน URL ของ WS → uvicorn access_log (default on) พิมพ์ URL เต็มทุก handshake (1008-loop = ซ้ำทุก 152 วิ) · Cloudflare เห็นด้วย | รหัสอยู่ใน `docker logs` / CF analytics / history | อ่านโค้ด 2 ฝั่ง + config |
| 3 | `utils/history.py:231` ← `routers/sessions.py:71` `DELETE /api/truncate/{id}` | `DELETE FROM messages WHERE id >= ?` ไม่กรอง assistant/session · UI ใช้ตอน "แก้ข้อความแล้วส่งใหม่" (`app.tsx:772`) | แก้ข้อความใน session เก่า = ลบทุกแชทที่คุยหลังจากนั้นทุก session ทุกผู้ช่วย · ไม่มีเทส | รัน repro (temp DB) + อ่านโค้ด |
| 4 | `memory/store.py:189-207` `bump_access_count` | `col.get(ids=doc_ids)` คืนตาม insertion order แต่โค้ด zip กับ `doc_ids` ตามลำดับที่ขอ (หลัง rank) แล้ว `update(ids=doc_ids, …)` | **metadata สลับข้าม memory ทุกเทิร์น**ที่ recall ≥2 (verified/confidence/timestamp/source สลับกัน) → prune/decay ลบผิดตัว · ขยะได้ป้าย ✅ | รันจริง EphemeralClient 1.5.9 + อ่านโค้ด |
| 5 | `utils/fs_tools.py:221` `search_files` | `root.rglob(file_glob)` รับ `..` ได้ + ไฟล์ที่ match ไม่ถูก `_resolve_safe` (ตาม symlink ด้วย) | tool `fs_search(file_glob="../../../proc/self/environ")` → `GEMINI_API_KEY`/`NAS_PASS`/`HA_TOKEN` เข้า context โมเดล (trigger ได้จาก prompt injection) | รันจริง + อ่านโค้ด |
| 6 | `agents/tools.py:98` `_t_calculator` | regex ตรวจบน `expression.replace("**","")` แต่ `eval` ของเดิม | `9**9**9` → thread ค้าง 100% CPU ถาวร (threadpool 40 slot) | รันจริง |
| 7 | `routers/auth.py:10-17` `/api/auth/check` · `core/auth.py:64-76` WS | `/auth/check` ตอบ 200 `ok:false` (ไม่ใช่ 401) + เป็น open path ⇒ ไม่เข้า lockout · WS ไม่ผ่าน rate-limit/lockout เลย (middleware http เท่านั้น) | เดารหัสได้ไม่จำกัด (HTTP เหลือ RPM 120 · WS ไม่มีเพดาน) — รหัสที่เดาได้ = รหัสจริง (ข้อ 2) | รัน repro (AUTH_FAIL_MAX=3) + อ่านโค้ด |
| 8 | `~/appscript.ui/utils/markdown.tsx:20,24` | regex กัน `//evil` แต่ไม่กัน `/\evil.com/…` (WHATWG parser ตีความ `\` = `/`) · code fence ไม่ได้ยกเว้น | รูป/ลิงก์ในคำตอบ AI ชี้โดเมนนอกได้ (tracking pixel / phishing ที่ดูเป็นลิงก์ภายใน) | รันจริง `new URL` + `renderMarkdown` |
| 9 | `utils/memory.py:494-531` `POST /api/memory/cleanup` | skip แค่ `long_term_memory`/`preferences` แล้วลบทุก collection ที่ `timestamp < cutoff` — รวม **`user_facts`** และ `lessons` | ปุ่ม "🧹 ลบ memory เก่า" ใน UI ลบข้อเท็จจริงที่ user สอนไว้เกิน 30 วัน | อ่านโค้ด + caller `app.tsx:1194` |
| 10 | `routers/chat.py:159` + `:621` · `memory/teach.py:16-27` | `teach()` ถูกเรียก 2 ครั้ง/เทิร์น → fact ซ้ำ 2 doc · regex ไม่ anchor (`แก้ไข…`, `note…`, `remember…`, `ชอบ…มากกว่า`) | "ช่วยแก้ไข bug ใน login หน่อย" → เขียน `user_facts` verified 0.95 แล้วฉีดทุก prompt | รันจริง regex + จำลอง 2 calls |
| 11 | `routers/dream.py:37` `routers/memory.py:88` `routers/system.py:369` | `except Exception: data = {}` กลืน `_BodyTooLarge` (ตั้งใจไม่สืบ HTTPException) จาก `core/body_limit.py` | body chunked > 10 MB → ตอบ 200 แล้ว**รัน dream/ลบ memory/unlock IP** ด้วย body ว่าง | repro จริง (app จิ๋ว chunked) |
| 12 | `Dockerfile:18` `COPY . .` + ไม่มี `.dockerignore` | build context บน NAS มี `.env` `data/` (reader.db 130 MB · db_backups · logs) `.git` | ทุก rebuild ยัด secrets + DB จริงเข้า image layer (`docker history`/`save` กู้ได้) | โครงสร้างยืนยัน · ยังไม่ได้วัดขนาด image บน NAS |
| 13 | `static/enhanced.js:2711-2722` ปุ่ม 🗑️ overlay | `.remove()` DOM node ที่ React เป็นเจ้าของ (ไม่ gate) | ลบข้อความที่เพิ่งส่ง → React reconcile ครั้งถัดไป `removeChild` throw → **จอขาวทั้งแอป** (ไม่มี error boundary) | อ่านโค้ด + พฤติกรรม React |
| 14 | `app.tsx:1351-1407, 737-763, 783-813, 686-707` | เส้น stream ทั้ง 4 ไม่เช็ค `res.ok` | 401/413/429/5xx → ฟองค้าง `streaming:true` ตลอด ไม่มี error · ปุ่ม regenerate หาย · Stop overlay ค้าง | อ่านโค้ด + backend ตอบ JSON ได้จริง |

## 2. 🟠 MEDIUM
**backend**
- `routers/chat.py:701-717` regenerate: ลบ assistant ล่าสุดแล้ว `load_history` (ยังมี U2) + `append(last_prompt)` อีก → LLM เห็น `U2,U2` · ถ้า turn สุดท้ายเป็น orphan (ไม่มีคำตอบ) จะลบ **A1** ทิ้ง (repro จริง)
- `routers/chat.py:324, 458-461` client หลุดกลาง stream → `GeneratorExit` ไม่เข้า `except Exception` → user msg orphan ไม่มี assistant คู่ (ไม่มี try/finally) → เหยื่อของข้อบน
- Dream ซ้อน 2 ทาง: `core/scheduler.py:22` job กลางคืนเรียก `run_dream_cycle` ตรง ไม่ผ่าน `dream_lock` (asyncio.Lock ใช้จาก thread ไม่ได้อยู่แล้ว) · `routers/dream.py:49-59` timeout ปล่อย lock ทั้งที่ thread ยังวิ่ง · `scheduler.py:18` provider = `gemini`/`ollama` ไม่ใช่ `auto` (ขัด CLAUDE.md "single source of truth")
- `core/ratelimit.py:66-67` `_cap()` `popitem()` = ไล่ key **ใหม่สุด** ออก → dict เต็ม = IP ใหม่ไม่ถูกจำกัด/ไม่ถูกนับ (ต้อง ≥50k key/60s — ต่ำแต่ตรรกะกลับด้าน · ทดลองแล้ว)
- async def เรียก sync บน event loop (ขัดกติกาโปรเจกต์): `routers/reader.py` ทุก route (`_ingest` regex 3 pass + sqlite บนไฟล์ถึง 200 MB · วัด 0.35 s/4.2M chars) · `server.py:613` `_books.text()` ทั้งเล่ม 56.8 MB ใน WS handler · `server.py:724,740,879` `_marks` sqlite (timeout 10 s) ใน feed_loop · `:518,522` `_save_msg` ใน voice send_loop · `routers/sessions.py:37,56,98` · `routers/system.py:376-396` admin memory (ChromaDB ตรง) · `test_*_concurrency` ครอบเฉพาะ chat
- `routers/system.py:319-320, 346-347` `/api/tts*` กลืน exception เป็น `{"error"}` 200 **ไม่ log** = "พังเงียบ" แบบ 08-06 ยังอยู่
- `server.py:769-834` reader regen 3 เส้น (stall watchdog / receive จบไม่มี turn_complete / go_away) `regen.set(); return` ไม่มี cap/backoff (เส้นท่อนไม่ครบมี cap 3) → Gemini ตายเงียบทุกท่อน = Live session ใหม่ทุก 45 วิ ไม่รู้จบ เผาโควตาจน 1011 · โซ่ go_away ของ voice `559-561` ก็ไม่มี cap
- `agents/orchestrator.py:635-651` Ollama ReAct: guard `ok_observations==0` ทำงานเฉพาะครบ max_steps · `Answer:` ที่ step ใดก็ yield ตรง · tool ที่คืน "ไม่พบ…"/"Memory error" นับเป็นได้ข้อมูล (repro จริง: user เห็นราคาทองที่แต่ง)
- `agents/orchestrator.py:233-287, 316-321` Gemini adapter: tool result ของ step สุดท้ายค้างใน `_pending` ไม่ถูกส่ง · history = function_call ตามด้วย user text → 400/สรุปโดยไม่มีข้อมูล (repro fake chat)
- `routers/agent.py:53` `max_steps` จาก body ไม่มีเพดาน/ไม่ validate (500 รอบ LLM · `"abc"` → 500)
- `utils/websearch.py:262-291` CSE key ใน query string → `str(e)` ของ requests มี URL เต็ม → `GOOGLE_SEARCH_API_KEY` ลง `server.log` (log WARNING ทั้งที่ควร ERROR) — ยืนยันด้วย requests จริง
- `utils/llm.py:365-366, 692-701` จัดประเภท error ด้วย substring `"model"` → OOM/"insufficient resources" กลายเป็น "❌ Model ไม่พบ ollama pull" ไม่ retry · `:945,1111` `"401"/"invalid" in err` เช่นกัน
- `utils/response_cache.py:137-243` + `routers/chat.py:131,162` key = (assistant, prompt) lookup **ก่อน** context → คำตอบ 👍 ของ "สรุปให้หน่อย" ในเอกสาร A เสิร์ฟให้ session อื่น · `feedback.py:138` เก็บคำตอบ agent-mode (real-time) ด้วย
- `utils/embed.py:265-278` `@lru_cache` แคช `tuple()` ตอนล้ม → Ollama ดับชั่วคราว = ข้อความนั้น embed ไม่ได้ตลอดอายุโปรเซส (cache/rerank/dedup เป็น no-op เงียบ)
- `utils/skills.py:327-347` `sync_skills_to_search(db)` นอก transaction ด้วย snapshot เก่า → ผู้เขียนพร้อมกัน (auto_extract/dream/router) ลบ skill ออกจาก `skills_collection` ทั้งที่ไฟล์มี
- `memory/store.py:112-131` + `dualvec.merge_max:84-92` ฝั่ง `__keys` ข้าม `min_confidence`/`verified_only` → memory ที่ถูกลดเป็น 0.3 โผล่กลับเป็น "🟡 probable" ด้วย content = key text
- `utils/memory.py:136-155` `_get_client()` ถือ `_lock` ระหว่างต่อ ChromaDB ที่ `httpx timeout=None` → host unreachable (SYN หาย) = threadpool 40 ช่องต่อคิวหลัง lock · "ChromaDB optional" จริงเฉพาะ connection refused
**frontend**
- ปุ่ม ⏹ Stop overlay: abort กลาง stream → `app.tsx:1408` แทนที่คำตอบบางส่วนด้วย "❌ เชื่อมต่อ server ไม่ได้" · abort ก่อน headers → ฟองค้าง · React ไม่มี AbortController · debate N request ทับ `_abortCtrl` ตัวเดียว
- `enhanced.js:114-129, 1974-1981` `_parseChatSSE` ไม่ gate → citations/reflection/cache_hit/active_learning **ซ้ำสอง** ในฟอง React (+ ยัดผิดฟองตอน debate)
- `app.tsx:1526, 2144` fallback `AI_PALETTE.khim` = undefined → เพิ่มผู้ช่วยตัวที่ 2 = จอขาว (latent)
- `app.tsx:1322-1334` shortcut "จำไว้ว่า…" `await fetch` นอก try → เน็ตล้มครั้งเดียว composer ล็อกถาวร + ข้อความหาย
- `enhanced.js:1085-1091` prompt history ↑/↓ ตั้ง `ta.value` ตรง → React ไม่เห็น → Enter ส่งเงียบไม่ได้ · ยึด ArrowUp ทุกครั้ง
- `enhanced.js:1103-1133` paste รูป → เขียน `hw_pending_image` ที่ไม่มีใครอ่าน → toast "✅ รูปพร้อม" แต่ไม่ส่ง
- `voicelive.ts:262-279` `onclose` ของ socket เก่าไม่เช็ค `ws === this.ws` → close ที่มาช้าฆ่า socket ใหม่ระหว่าง retry (plausible)
- `bookreader.ts:96, 196-200` server ปิดสาย/`done_book` ไม่ `disconnect()` → ticker 250 ms + listener + AudioContext + `audioSession.type='playback'` ค้าง → แตะ 🎤 ต่อ = `getUserMedia` ใต้ playback-only (เข้าข่ายอาการไมค์ `zeros`)
- Ctrl+E ผูกซ้ำ 2 ชั้น (`app.tsx:1270` + `enhanced.js:666`) → export 2 ไฟล์ · สลับ session/ผู้ช่วยระหว่าง stream ไม่มี latest-request guard (`app.tsx:453-481, 1205-1230, 1459`)
- input ที่ทำ 500 แทน 400: `int()` ดิบ (`agent.py:53` `sandbox.py:95` `documents.py:148`) · `.strip()` บน non-str (`sessions.py:34` `memory.py:47` `system.py:310,328` `skills.py:86`) · `skills_delete` `delete_file=true`+`skill_id=""` → `os.remove(dir)`

## 3. 🟡 LOW / doc-vs-code
- doc เท็จ: `core/config.py:78` + `.env.example` อ้าง "UI_PASSWORD ว่าง middleware ยังกัน" — จริงคือเปิดหมดรวม `/api/admin/*` · `scripts/gen_env_example.py:7` บอก scripts ไม่ mount (mount แล้ว) · CLAUDE.md open paths ขาด `/gen` `/api/files` `/assets` · `core/auth.py:27` อ้าง `/gen` 128-bit (จริง 24-bit + timestamp · share token 40-bit ไม่หมดอายุ)
- `reasoning/router.py:53` `rstrip('/v1')` เป็น char-set → `…:1231/v1` → `…:123` (prod `:1234` รอดบังเอิญ) · `utils/llm.py:72-79` `basicConfig(FileHandler('server.log'))` ตอน import = ตัวสร้าง `/app/server.log` หลอกตา · `utils/ocr.py:119-127` หน้าเปล่าหน้าเดียว → raise ทั้งไฟล์เมื่อไม่มี LM Studio · `utils/code_sandbox.py:100-112` ไม่มี `--pids-limit/--cap-drop/no-new-privileges` · `utils/llm.py:237-268` สาขา `auto` ไม่ส่ง sink/override และกลืน quota → Ollama เงียบ (ถึงได้จาก regenerate/lesson/dream)
- `server.py:55-58` `x-request-id` จาก client ไม่จำกัดความยาว · access log พิมพ์ path ที่มี token (`/api/shared/…` `/api/files/…`) · compose bind-mount ไฟล์เดี่ยว (ไฟล์ไม่มี = Docker สร้าง dir) · `/api/health` open path เปิดเผย disk/RAM/DB · `chromadb` `8000:8000` ใน LAN ไม่มี auth · `routers/tools.py:36` `/ping/{ip}` port-scan อ่อนๆ
- memory: `teach.py:120` `update_confidence(prev[:200])` nearest-1 ไม่มีพื้น · `dream.py:380-407` decay bulk update ทับ lost-update · `dream.py:117,545` count เป็น str → TypeError ล้มก่อน prune · `skills.py:238` JSON เสีย → `{}` แล้วผู้เขียน**แทนที่คลังทั้งไฟล์** · `working.py:50` ไล่ session ทุก push เมื่อครบ 50 · `skill_discovery.py:113,149` zip ผิดคู่ + key hardcode · `skills_search.py:29` ไม่ใช้ `_detect_chroma_host` · `reconcile_keys.py:44` race กับ `save_entry` · `documents.py:83-113` delete ก่อน upsert
- `history.py:59-62` ไม่ตั้ง timeout/finally close · `search_messages:186` ไม่ escape `%`/`_` · `system.py:262-292` เปิด sqlite เอง
- frontend: §16 MutationObserver ทั้ง body หา "🦙 Llama" ที่ไม่มี (scan ทุก token) · token bar §9 เลขมั่ว · `_esc`/`esc` ไม่ escape `"` ใน attribute (`enhanced.js:1852, 787`) · blob URL revoke ทันที · `provider` ไม่ persist → dream ส่ง `ollama` · `showToast` ไม่ clear timer · fonts.googleapis render-blocking · `CitationList` href ไม่เช็ค scheme · dead code (`engineLabel`, `hw_provider`)
- memory note "มี dep ไม่ประกาศใน package.json อยู่แค่ lock" — เทียบ lock↔package.json แล้ว **ตรงกัน** (ตกรุ่น)

## 4. ✅ ที่ตรวจแล้วสะอาด (ย่อ)
middleware order ตรง doc · `_BodyTooLarge` ถึง middleware (ยกเว้น 3 handler ข้อ 11) · `_under_open_prefix` ทั้ง segment · `is_local_request` ปฏิเสธเมื่อมี `cf-connecting-ip` · `token_matches` constant-time · WS gate ก่อน accept ทั้ง 2 เส้น · `/api/files` token regex+sanitize+realpath · `fs_tools._resolve_safe` (ยกเว้น glob) · `fetch_url_safe` SSRF ครบ (redirect/rebinding/IPv4-mapped) · code sandbox gate/timeout/kill · web search แยก ERROR≠0 ผล + min score 2 pipeline + Brave lock · `_stream_gemini` retry/fallback · `_MarkerFilter` · lock/atomic ของ skills_db · `skills_search` singleton/space · retrieval/response cache TTL/evict · `db_backup` verify+retention · `obsidian_sync` lock/halted · `run_until_both_done` · reader ไม่ใช้ handle + pause ปล่อย session · TTS chunk/threadpool · SSE parser ทั้ง 4 เส้น · overlay gating ตามเทส · cache-bust · vitest 501 / tsc 0 / node --test 29 · requirements↔lock 22/22 · CI ในอิมเมจ prod · scheduler timezone

## 4.5 ค้นเน็ต/ซอร์สที่ติดตั้งจริงเสริม (user สั่ง 09-24: "ถ้าไม่ชัวร์ค้นข้อมูลในเน็ตเสริมก่อน") — ผลต่อข้อที่เคยติดป้าย plausible
| ข้อ | ผลค้น | สถานะใหม่ |
|---|---|---|
| HIGH 2 uvicorn log รหัสใน WS URL | ซอร์สที่ติดตั้ง `uvicorn/protocols/websockets/websockets_impl.py:281` log `"WebSocket %s" [accepted]` ด้วย `get_path_with_query_string` (`utils.py:58-62` ต่อ query string) · **docker logs ของ prod 48 ชม. มีบรรทัด `WebSocket /ws/voice/kwan?token=…` จริง** | confirmed (prod) |
| HIGH 4 Chroma `get(ids=)` ไม่คืนตามลำดับที่ขอ | Chroma Cookbook: 0.4.x–0.5.10 เรียงตาม document ID · ≥0.5.11 เรียงตาม internal ID — ไม่มีรุ่นไหนคืนตามลำดับ `ids` ที่ขอ ([cookbook](https://cookbook.chromadb.dev/core/collections/)) | confirmed |
| MEDIUM `_get_client` ไม่มี timeout | `chromadb/api/fastapi.py:87,92` `httpx.Client(timeout=None)` ในเวอร์ชันที่ติดตั้ง | confirmed |
| MEDIUM Gemini agent history ผิดรูป → 400 | Google forum/issue หลายเธรดยืนยัน 400 "function response turn must come immediately after a function call turn" ([forum 46213](https://discuss.ai.google.dev/t/about-the-gemini-api-400-please-ensure-that-function-call-turns-come-immediately-after-a-user-turn-or-after-a-function-response-turn-error/46213) · [litellm 26755](https://github.com/BerriAI/litellm/issues/26755)) | confirmed |
| MEDIUM bookreader ค้าง `audioSession.type='playback'` → ไมค์เงียบ | สเปก W3C/MDN **ไม่ได้บอก**ว่า playback ปิด capture · แต่ซอร์ส WebKit `AudioSessionIOS.mm` `setCategory`: `if (categoryOverride() != None && categoryOverride() != newCategory) { "override set, NOT changing"; return; }` = override ชนะ ไม่มี logic บังคับ PlayAndRecord ตอน capture · `AVAudioSessionCategoryPlayback` ไม่มี input ⇒ **เป็นไปได้จริงเชิงซอร์ส** แต่ยังไม่ได้วัดบนเครื่อง · ⚠️ ค่านี้เพิ่งใส่ 09-21 (`4263cf0`) — อาการ `zeros` ของเดือน ส.ค. จึง**ไม่ใช่**จากตัวนี้ · เป็นความเสี่ยงใหม่หลัง 09-21 เฉพาะเส้น "server ปิดสายอ่าน → กดไมค์" | plausible → รองรับด้วยซอร์ส WebKit · รอวัดจริง |
| 1007 "input token count exceeds 8192" | เอกสาร Live API ([ai.google.dev live-guide](https://ai.google.dev/gemini-api/docs/live-guide) · [Firebase limits](https://firebase.google.com/docs/ai-logic/live-api/limits-and-specs)) ระบุ context 128k (native audio)/32k (อื่น) · 25 token/วิ audio · session 15 นาที — **ไม่มีเลข 8192 ที่ไหนเลย** · เธรด 1007 ใน forum/issue ([83206](https://discuss.ai.google.dev/t/received-1007-invalid-payload-using-gemini-live-api/83206) · [js-genai #1212](https://github.com/googleapis/js-genai/issues/1212)) เป็นเรื่อง modality config ไม่ใช่ token | **ยังไม่รู้** — ต้อง log `usage=` ฝั่ง voice + จับ frame สุดท้ายที่ client ส่งก่อน 1007 |
| audioSession playback = ไมค์ zeros ของเดือน ส.ค. | บทความ Sam Eddy (iOS Safari audio sessions): WebKit อนุมาน category จาก API ที่ใช้ (AudioContext=playback · getUserMedia=play-and-record) และแนะนำตั้ง play-and-record ครั้งเดียวตอนเปิด ห้ามสลับกลางเซสชัน ([บทความ](https://samueleddy.com/writing/ios-safari-audio-sessions/)) — ไม่พูดถึงเคส override เป็น playback | ไม่ใช่สาเหตุของอาการเดือน ส.ค. (ค่ายังไม่มีตอนนั้น) |

## 5. ลำดับที่แนะนำ (ยังไม่แก้ — รอ user เคาะ)
1. XSS `/shared` + token=รหัสดิบ/WS URL/access log (ข้อ 1-2) — ปิดด้วย escape/validate token + session token สุ่มหมดอายุ + `access_log=False` หรือกรอง query
2. ✅ ~~truncate ข้าม session (3) + `bump_access_count` สลับ metadata (4)~~ ปิดแล้ว `e5223ef` (devlog [ต่อ 11])
3. ✅ ~~fs glob (5) + calculator (6) + markdown backslash (8)~~ ปิดแล้ว `82681d9` (devlog [ต่อ 12]) · (7) ปิดไปกับก้อน 1
4. ✅ ~~memory cleanup ลบ user_facts (9) + teach ซ้ำ/regex (10) + body-cap กลืน (11) + `.dockerignore` (12)~~ ปิดแล้ว `fdc269a` (devlog [ต่อ 13]) · ค้าง rebuild+prune image
5. overlay 🗑️ จอขาว (13) + `res.ok` (14) → MEDIUM ตามลำดับในหัวข้อ 2
