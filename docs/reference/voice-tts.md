# เสียง — Voice WS · เสียงคนเดิม · `/api/tts` · AudioLevelMeter (อ้างอิง)

> ยกทั้งดุ้นจาก `CLAUDE.md` เมื่อ 2026-10-01 (ไฟล์นั้นโต 103 KB และถูกฉีดทุกเซสชัน) — **ไม่ได้แก้เนื้อหา**
> หัวข้อ ▶️ / กติกาที่ยังมีผล ยังอยู่ใน `CLAUDE.md` · ประวัติอยู่ใน `docs/session-log/devlog.md`

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
