
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
