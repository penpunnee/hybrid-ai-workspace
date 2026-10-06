# แผนที่ UI — ส่วนบนจอ → ใครเป็นเจ้าของ

จุดเริ่มของ subagent `ui-investigator` (`.claude/agents/ui-investigator.md`) · สร้าง 2026-10-05
· แหล่งกฎของ subagent `ui-reviewer` (`.claude/agents/ui-reviewer.md` · ตรวจ diff ก่อน commit) ด้วย — สถานะ gate/จุดชนในไฟล์นี้ผิด = ผู้ตรวจตัดสินผิดตาม

**อ่านก่อนใช้**
- **React** = `~/appscript.ui` (แก้ → `npm run build` + `bash scripts/sync_static.sh`) · ทั้งแอปอยู่ในคอมโพเนนต์เดียว
  `InteractiveLiquidGlass` ใน `app.tsx` · logic ย่อยอยู่ `utils/*.ts` (มี vitest) · ⛔ `src/app.tsx` = สำเนาเก่า ไม่ได้ใช้
- **overlay** = `static/enhanced.js` (vanilla · แก้แล้ว bump `?v=` ใน `~/appscript.ui/index.html`) + `chat_intercept.js` + `dream_stats.js`
- `app.tsx` ตั้ง `window.__hwReactChatBox = true` ⇒ section ของ overlay ที่ **gate** ด้วยธงนี้ = ตาย (เหลือไว้เป็น fallback ของ bundle เก่า)
- ตัวยึด = backtick ครอบ "path ไฟล์ » ข้อความ" · path ขึ้นต้น `a.ui/` (= `~/appscript.ui/`) หรือ `static/` —
  **grep ข้อความนั้นเจอในไฟล์จริงเสมอ** (ตรึงด้วย `tests/test_ui_map_anchors.py` + `~/appscript.ui/utils/uimap.test.ts`)
  · ไม่ใช้เลขบรรทัดเพราะเลื่อนทุกครั้งที่แก้

## 1. React — ส่วนบนจอ

| ส่วนบนจอ | ตัวยึด (React) | API | overlay ที่แตะส่วนเดียวกัน |
|---|---|---|---|
| Sidebar: สลับผู้ช่วย · แชทใหม่ · รายการ session | `a.ui/app.tsx » {/* AI Switcher */}` · `a.ui/app.tsx » {/* Session list */}` · `a.ui/app.tsx » const loadSessions =` | `/api/sessions/{ai}` (GET/POST/DELETE) · `/api/history/{ai}/{sid}` | — |
| Sidebar: ช่องค้นหา | `a.ui/app.tsx » {/* Search box */}` | `/api/search` | — |
| Sidebar: Obsidian Sync | `a.ui/app.tsx » {/* Obsidian Sync */}` | `/api/vault/stats` · `/api/vault/sync` | — |
| Sidebar: Dream Cycle (คลื่น Light/REM/Deep) | `a.ui/app.tsx » {/* Dream Cycle - Wave UI */}` · `a.ui/utils/dreamstats.ts » export` | `/api/dream` · `/api/dream/report` | §1.5 + `dream_stats.js` (gate แล้ว) |
| Sidebar: Skills · Memory stats | `a.ui/app.tsx » {/* Skills Panel */}` · `a.ui/app.tsx » {/* Memory Stats */}` | `/api/skills` · `/api/memory/stats` · `/api/memory/cleanup` | — |
| Header: ปุ่ม Share/Pinned/Home/Dashboard/Export/ล้างแชท (จอ < md: 🧩 🔗 📊 💾 🏠 อยู่ใน **เมนู ⋯** ขวาสุด (10-06 · ปุ่มเดิม `hidden md:flex`) · 🧩 เป็น*สวิตช์* `debateMode` ไม่ใช่ปุ่มเปิดหน้าต่าง · ชื่อผู้ช่วย 1 บรรทัดตัดด้วย … · พื้นที่แตะขยายด้วย `::before` (⛔ ห้าม `::after` — tooltip `:hover::after` ของ overlay ทับ): ⋯ 36×44 · 🌙 🤖 📌 🗑️ 26×44 (หน้าตา 24×24 · ชนกันกลางช่อง 2px) · badge 📌 `pointer-events-none` · **ห้ามปุ่มข้างเคียงล้ำเข้าพื้นที่แตะของ 🗑️ ทั้งตอนปกติและตอน hover** (ปอยเคาะ 10-06 รอบ 10 · แทนข้อ "ยอมรับ ⋯ ล้ำ 1–2px" เดิม) ⇒ overlay §13 ปิด `scale(1.15)` ของปุ่มแถบหัวใน `@media (hover: none)` (เดสก์ท็อปยังขยาย) · e2e ㊴ ㊺ ㊻ · 🗑️ แสดงตั้งแต่ 10-05 · disabled ระหว่าง stream และระหว่างมีการล้างแชทค้าง (ทั้งแอป) · ช่องพิมพ์/ปุ่มส่งล็อกเฉพาะแชทที่กำลังลบ · **ล้างแล้วได้แชทใหม่ว่าง** ทางเดียวกับปุ่มเริ่มแชทใหม่ (ไม่เด้งไปแชทที่เหลือ · หมุดถูกล้าง) · ระหว่างรอยังสลับแชท/ผู้ช่วย/เริ่มแชทใหม่ได้ — แตะจอเฉพาะเมื่อ (ผู้ช่วย, session) ยังเป็นตัวที่ลบ ทั้งตอน DELETE ตอบและตอนได้ id แชทใหม่) | `a.ui/app.tsx » {/* Header */}` · `a.ui/app.tsx » title="Pinned"` · `a.ui/app.tsx » title="Export"` · `a.ui/app.tsx » title="เมนูเพิ่มเติม"` · `a.ui/app.tsx » {/* More menu ⋯ (มือถือ)` · `a.ui/utils/moremenu.ts » export function shouldCloseOnViewportChange` | `/api/share` · `/api/pinned/…` · `/api/export/…` · `/api/stats` | §3 Export (gate แล้ว) · FAB 🏠/🔍 ถูกลบเมื่อมีธง |
| ฟองข้อความ (render markdown) | `a.ui/app.tsx » {/* Messages */}` · `a.ui/utils/markdown.tsx » md-pre` | — | ⚠️ §15 ฉีดเข้าฟอง (ดูข้อ 3) |
| ปุ่ม **Copy บนกล่องโค้ด** (ใน `.md-pre-wrap` · เห็นตลอด · toast ของ React) | `a.ui/utils/markdown.tsx » data-md-copy` · `a.ui/utils/markdown.tsx » export function codeFromCopyClick` · `a.ui/app.tsx » const copyCode =` | — (clipboard) | §6 COPY CODE BUTTON (gate แล้ว) |
| ปุ่ม 📋 คัดลอกทั้งข้อความ (ใต้ฟอง) | `a.ui/app.tsx » const copyMsg =` | — (clipboard) | §19 COPY MESSAGE (gate แล้ว) |
| ปุ่ม ✏️ แก้ · ลบคู่ · 🔄 ตอบใหม่ | `a.ui/app.tsx » const deletePair =` · `a.ui/app.tsx » const regenerate =` | `/api/message/{id}` · `/api/truncate/{id}` · `/api/regenerate` | §19 EDIT/§20 DELETE PAIR (gate แล้ว) |
| ปุ่ม 🔊 อ่านออกเสียง · 👍👎 · 📌 · บันทึกเป็น Skill | `a.ui/app.tsx » const speakMessage =` · `a.ui/app.tsx » title="ตอบดี (เก็บไว้เทรนโมเดล)"` · `a.ui/app.tsx » const togglePin =` · `a.ui/app.tsx » const saveAsSkill =` | `/api/tts` · `/api/feedback` · `/api/pin/{id}` · `/api/skills/extract` | §4 PIN (gate แล้ว) |
| Agent timeline · citations · reflection ในฟอง | `a.ui/app.tsx » function AgentTimeline` · `a.ui/app.tsx » function CitationList` · `a.ui/app.tsx » function ReflectionPanel` | SSE ของ `/api/chat` | §17/F2 ตาย (tee ถูก gate) |
| ChatBox: pill โหมด/โมเดล/Agent/Skills + จุดสถานะ | `a.ui/app.tsx » {/* Mode pill */}` · `a.ui/app.tsx » {/* Model pill` · `a.ui/app.tsx » {/* Agent pill */}` · `a.ui/app.tsx » {/* Skills pill */}` · `a.ui/utils/chatflags.ts » export function buildChatFlags` | `/api/chat` (body `tool_agent`/`plan_mode`/`obsidian_inject`) · `/api/status` · `/api/models` | §22 ตาย (gate แล้ว) |
| ChatBox: ช่องพิมพ์ · ส่ง · แนบไฟล์/รูป/กล้อง · วางรูป | `a.ui/app.tsx » const handleSend =` · `a.ui/app.tsx » title="แนบไฟล์"` · `a.ui/utils/paste.ts » export` · `a.ui/utils/filemanager.ts » export` | `/api/chat` · `/api/upload` · `/api/documents/upload` | ⚠️ §5 @vault · §13 · §21 ยังทำงาน · §11/§18 gate แล้ว |
| ChatBox: เมนู `/` · ตัวนับ token · draft | `a.ui/app.tsx » {/* Slash quick-prompts menu` · `a.ui/app.tsx » {/* Token/char counter pill` · `a.ui/utils/draft.ts » export` | — | SLASH/TOKEN/DRAFT ของ overlay (gate แล้ว) |
| แถบ Context (ตัวเลขใต้ช่องพิมพ์) | `a.ui/app.tsx » {/* แถบ Context` · `a.ui/utils/contextbar.ts » export` | `done.usage` ใน SSE | §9 (gate แล้ว) |
| **Toast (React)** — ข้อความลอยกลางล่าง | `a.ui/app.tsx » {/* Toast */}` · `a.ui/app.tsx » const [toast, setToast]` | — | ⚠️ overlay มี toast ของตัวเองแยก (ดูข้อ 3) |
| Modal: Dream report · Stats · Global Search · Pinned · Daily Digest · Debate · Dream alert | `a.ui/app.tsx » {/* Dream Report Modal */}` · `a.ui/app.tsx » {/* Global Search modal` · `a.ui/app.tsx » {/* Pinned Messages Panel */}` · `a.ui/app.tsx » {/* Daily Digest Modal */}` · `a.ui/app.tsx » {/* Multi-AI Debate Overlay */}` | `/api/dream/history` · `/api/search` · `/api/digest` · `/api/chat` (debate: **3 ฟ้องขนาน** ใต้ session `debate_<sid>` · ระหว่าง Debate `streaming=false` ⇒ 🗑️/ส่ง ไม่ disabled · หน้าต่าง z85 บังด้วยตา แต่ **textarea ยังโฟกัส คีย์บอร์ดส่งรอบใหม่ได้** = รอบใหม่ abort รอบเดิม (e2e ㊿)) | §2 Ctrl+Shift+F (gate แล้ว) · ฟ้อง Debate ส่ง `signal` เอง ⇒ fetch override ไม่ยุ่ง (ไม่ทับ signal · ไม่โชว์ ⏹ · ไม่กลืน `AbortError`) |
| Home Panel (NAS/Docker/PC/WoL) | `a.ui/app.tsx » {/* Home Panel` · `a.ui/utils/homepanel.ts » export` | `/api/health` · `/api/tools/home/*` | §14 (gate แล้ว) |
| โหมดเสียง (หน้าจอ Voice) 🔒 | `a.ui/app.tsx » {/* ===== Voice Mode Overlay ===== */}` · `a.ui/app.tsx » const startVoice =` · `a.ui/utils/voicelive.ts » /ws/voice/` | WS `/ws/voice/{slug}` | — · 🔒 ห้ามแตะค่าเสียง (CLAUDE.md) |
| 📖 ขวัญอ่านหนังสือ 🔒 | `a.ui/app.tsx » const loadBooks =` · `a.ui/utils/bookreader.ts » /ws/reader` | `/api/reader/books` · WS `/ws/reader` | — · 🔒 |
| อุ่นเครื่อง local model ตอนเปิดหน้า | `a.ui/utils/warmup.ts » export` | `/api/warmup` · `/api/config` | §16 (ไม่มีผลแล้ว ดูข้อ 2) |

## 2. overlay ที่ยังทำงาน (ไม่ gate) — ของพวกนี้ React **ไม่มี**

| ส่วนบนจอ | ตัวยึด (overlay) | API | หมายเหตุ |
|---|---|---|---|
| หน้า Login (เมื่อตั้ง `UI_PASSWORD`) | `static/enhanced.js » 0. AUTH` | `/api/auth/login` · `/api/auth/check` | แนบ token ทุก `/api/*` ผ่าน fetch override |
| fetch override กลาง (auth · stop · history · typing) | `static/enhanced.js » Single unified fetch override` · `static/chat_intercept.js » applyChatBodyMutations` | ทุก `/api/*` | แก้ body `/api/chat` ได้ — เช็คก่อนแก้ flag ใน React |
| @vault ในช่องพิมพ์ | `static/enhanced.js » 5. @vault SEARCH` | `/api/vault/search` | ฟัง `input` บน `document` (ทุก INPUT/TEXTAREA รวมช่องพิมพ์ของ React) · คลิกผลลัพธ์ = คัดลอก + toast ของ overlay |
| ปุ่มหยุด stream ⏹ (แชทปกติ) | `static/enhanced.js » 7. STOP GENERATION` | — (abort fetch) | React ไม่มีปุ่มหยุดของแชทปกติ · ฟ้องที่ผู้เรียกส่ง `signal` มาเอง overlay ไม่แตะ |
| ปุ่ม ⏹ หยุด ของ Debate (React · 10-06) | `a.ui/app.tsx » const stopDebate` · `a.ui/app.tsx » const closeDebate` | — (`AbortController` ต่อผู้ร่วม · id รอบใน `debateRunRef`) | ✕ / Escape = หยุดทั้งหมด + ปิด (ปอยเคาะ) · ⏹ แตะได้สูง 44 (`::before`) · คอลัมน์ที่จบ/error แล้วไม่ถูกทับ · **ข้อจำกัดที่ยอมรับ:** ผู้ร่วม A จบแล้ว → B/C ที่ถูกหยุดทีหลัง *ไม่ถูกบันทึกลง DB* (`has_reply_after` ใน session `debate_<sid>` เดียวกัน · จอเห็นครบ) · กดหยุดตอน server ส่ง `done` แล้วแต่ยังไม่อ่าน = จอ "หยุดแล้ว" แต่ DB เก็บคำตอบเต็ม · e2e ㊼–㊾ |
| ปุ่มเลื่อนลงล่างสุด | `static/enhanced.js » 8. SCROLL TO BOTTOM BUTTON` | — | ปุ่มลอยบน `body` |
| ของลอยเกาะเหนือกรอบช่องพิมพ์ (↓ · toolbar 🌿/⏹ · "กำลังคิด…") | `static/enhanced.js » function _placeFloaters` · อ่านตำแหน่งของ `a.ui/app.tsx » id="hw-chatbox"` | — | อ่านอย่างเดียว ไม่แตะ DOM ของ React → ส่งระยะผ่าน CSS variable `--enh-*-bottom` · rename id = ของลอยกลับไปใช้ระยะตายตัว (ทับกรอบ) |
| "กำลังคิด…" ก่อน chunk แรก | `static/enhanced.js » 12. TYPING INDICATOR` | — | ลอยบน `body` |
| ปรับแต่งช่องพิมพ์/ปุ่ม (CSS) | `static/enhanced.js » 13. CHAT INPUT + BUTTON IMPROVEMENTS` | — | CSS ทับคลาสของ React |
| badge ชื่อโมเดลใต้ฟอง AI | `static/enhanced.js » 15. MODEL INDICATOR` · `static/enhanced.js » function _injectModelBadge` | header `X-Model-Used` ของ `/api/chat` | ⚠️ ฉีดเข้าฟองของ React |
| ป้าย "🦙 Llama" → ชื่อโมเดล | `static/enhanced.js » 16. แทน` | `/api/config` | แก้ text node ของ React · ตอนนี้ไม่มีผล (`app.tsx` ไม่มีคำว่า Llama แล้ว) |
| เลื่อนช่องพิมพ์พ้นคีย์บอร์ด iOS | `static/enhanced.js » 21. MOBILE KEYBOARD SCROLL` | — | `visualViewport` |
| FAB 🌿 Vault (ซ่อนจนกว่า `/api/config` ตอบ `has_vault` · prod = true ⇒ แสดง) | `static/enhanced.js » id="fab-vault"` | `/api/config` | 🏠/🔍 ถูก `.remove()` เมื่อมีธง |
| **Toast (overlay)** `#enh-toast` | `static/enhanced.js » function showToast(msg, ms = 2500)` | — | caller ทุกตัวยกเว้น §5 อยู่ใน section ที่ gate แล้ว (§3 Export · §4 Pin · §11 Paste · §18 File Manager · §19/§20 แก้/ลบข้อความ · §22) ⇒ ที่ยังขึ้นจริงคือ §5 @vault จุดเดียว ("📋 คัดลอกแล้ว — วางใน chat ได้เลย") · เห็นข้อความอื่นของ overlay = bundle เก่าค้าง cache |

## 3. จุดเสี่ยงที่รู้แล้ว (งานเปิดใน CLAUDE.md ▶️)
1. **§15 badge โมเดล** — ไม่ gate · `appendChild` เข้า div ฟองที่ React จัดการลูกเอง (JSX) · เพิ่มอย่างเดียว ไม่ลบ
   ⇒ **ไม่ใช่**เงื่อนไขของจอขาวครั้งก่อน (ครั้งนั้นคือ overlay `.remove()` node ของ React · devlog [09-25 ต่อ 15]) ·
   ยังไม่เคยถูกตรวจใน e2e (mock ไม่ส่ง header `X-Model-Used`)
   · ✅ §6 Copy บนกล่องโค้ด ปิดแล้ว 10-05 (ย้ายเข้า React + gate) — ที่เคยจดว่า "ฉีดเข้า `<pre>` ที่ React เป็นเจ้าของ" ไม่ตรง:
   `<pre>` มาจากสตริงของ `renderMarkdown` ผ่าน `dangerouslySetInnerHTML` React ไม่ได้จัดการลูกชั้นนั้น · ปัญหาจริงคือปุ่ม `opacity:0` รอ hover
2. **Toast สองระบบ** — React (`{/* Toast */}` ที่ `bottom-6` กลาง · 14px · z-50) กับ overlay (`#enh-toast` ที่ `bottom:64px` กลาง · 12px · z 9999) · แยกด้วยข้อความ:
   grep ข้อความบนจอใน `app.tsx` ก่อน (`showToast('…')`) ไม่เจอค่อย grep `enhanced.js` แล้วเช็คว่า section นั้น gate หรือไม่
   · ✅ **ปิดแล้ว 10-05 โดยไม่แก้โค้ด** (devlog [ต่อ 109]): ไม่มี action ใดที่ได้ toast ทั้งสองระบบ · overlay เหลือ caller จุดเดียวที่ §5 @vault ·
   React ยังไม่มีช่องให้ overlay เรียก toast ของมัน (expose แค่ธง `__hwReactChatBox`) · จะหมดไปเองเมื่อย้าย Vault Search เข้า React (งานเปิดใน CLAUDE.md ▶️)
3. **ชั้น z ของของลอย** (แก้ 10-05 · devlog [ต่อ 122] · e2e ㉚–㉞ ตัดสินด้วย `elementFromPoint`) — ของลอยใหม่ต้องเลือกเลขจากลำดับนี้:
   `<main>` 10 < แถบ Context 12 < "กำลังคิด…" 14 < ปุ่ม ↓ 15 < toolbar 🌿/⏹ 16 < ฉากหลังแถบข้างมือถือ 20 < แถบข้าง 30 < เมนู ⋯ มือถือ 40/41 (portal ไป body) < toast ของ React 50 < หน้าต่างของ React 60–85 < Vault overlay 9100 < toast ของ overlay 9999
   · `<main>` เป็น stacking context ของตัวเอง ⇒ แถบหัว (100) และ dropdown ของ ChatBox (55/56) ที่อยู่ข้างใน **เทียบเลขกับของข้างนอกไม่ได้** (ทั้งก้อนนับเป็น 10)
   · ⏹ Stop อยู่ใต้หน้าต่างเมื่อมีหน้าต่างเปิด (รวม Debate เต็มจอ — Debate มี ⏹ หยุด ในแถบหัวหน้าต่างของตัวเองแล้ว 10-06)
   · **ตำแหน่งแนวตั้ง** (devlog [ต่อ 123] · e2e ㉟ ㊱): "กำลังคิด…" เกาะเหนือขอบบนของ `#hw-chatbox` ทุกความกว้าง · ↓ และ toolbar เกาะเมื่อกรอบกว้างมาถึงใต้มัน (จอ ≤ ~1024 · จอกว้างกว่านั้นอยู่มุมขวาล่างตามเดิม) — ⛔ ห้ามใส่ `bottom` ตายตัวให้ของลอยใหม่
   · e2e ของของลอยใช้ชื่อผู้ช่วย/โมเดลยาวเท่า prod (ค่าเริ่มต้นของ `e2e/mocks.ts` ใน `~/appscript.ui` ตั้งแต่ 10-06) — ชื่อสั้นทำให้กรอบช่องพิมพ์เตี้ยกว่าจริงและมองไม่เห็นการทับ

## 4. ตายแล้ว (gate ด้วย `__hwReactChatBox` · อย่าแก้ที่นี่ แก้ที่ React)
§1.5 DREAM STATS · §2 GLOBAL SEARCH · §3 EXPORT · §4 PIN · §6 COPY CODE BUTTON (`static/enhanced.js » function _wireCopyButtons`) · §9 TOKEN USAGE BAR · §10 PROMPT HISTORY · §11 PASTE ·
§14 HOME PANEL · §17 AGENT + F2 SSE (tee ที่ fetch override ถูก gate) · TOKEN COUNTER · DRAFT · SLASH · §18 FILE MANAGER ·
§19 COPY/EDIT · §20 DELETE PAIR · §22 CHAT INPUT BAR
