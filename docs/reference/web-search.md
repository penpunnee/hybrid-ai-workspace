# Web Search + พื้นคะแนน (อ้างอิง)

> ยกทั้งดุ้นจาก `CLAUDE.md` เมื่อ 2026-10-01 (ไฟล์นั้นโต 103 KB และถูกฉีดทุกเซสชัน) — **ไม่ได้แก้เนื้อหา**
> หัวข้อ ▶️ / กติกาที่ยังมีผล ยังอยู่ใน `CLAUDE.md` · ประวัติอยู่ใน `docs/session-log/devlog.md`

## Web Search (2026-06-04)
`utils/websearch.py` อัปเดต:
- **ลำดับ provider (2026-10-01): Brave → DDG** (`search_web`) — เดิม 08-31 เป็น Brave → Google CSE → DDG
  · **Brave = ตัวหลัก** (`BRAVE_SEARCH_API_KEY`) เลือกเพราะ **ไม่ผูกกับ Google Cloud project**
  · ⚠️ free tier = **1 คำขอ/วินาที** แต่ `_web_search_impl` ยิง sub-query ติดกันในลูปเดียว
    → มีตัวหน่วง `BRAVE_MIN_INTERVAL` (default 1.1s, มี lock เพราะ enrich ใช้ threadpool)
    **ไม่หน่วง = ตัวที่ 2 ได้ 429 ทุกครั้ง แล้วจะสรุปผิดว่า "Brave ใช้ไม่ได้"**
  · ⛔ **Google CSE ถอดออกแล้ว 2026-10-01** — Google ปิดรับลูกค้าใหม่ + ปิดถาวร 2027-01-01 · project เรา 403 ทุกครั้ง
    (probe prod 10-01) · ตั้งแต่ Brave ขึ้น สำเร็จ 34/34 จึงไม่เคยถึงชั้น CSE · **อย่าเอากลับมา** (vault `google-custom-search-api-shutdown.md`)
    · ด่าน `_redact_secrets` (audit 09-24 ข้อ 3) ย้ายมาครอบ log exception ของ Brave แทน
- **Domain credibility scoring** — `_domain_score(url)` คืน (score, label):
  - 🟢 แหล่งทางการ (1.2x): `.go.th`, `.gov.`, `.edu.`, `wikipedia.org`, `bbc.com`, `reuters.com` ฯลฯ
  - 🔵 ทั่วไป (1.0x): เว็บทั่วไป
  - 🟡 ระวัง (0.7x): `blogspot`, `pantip.com`, `reddit.com`, `facebook.com` ฯลฯ
- คูณ `_rerank_score × domain_score` ก่อน inject → แหล่งทางการขึ้นก่อน
- inject คำสั่งสังเคราะห์ใน prompt: "เรียบเรียงด้วยภาษาของตัวเอง ห้ามคัดลอก"
- แจ้ง hint "ข้อมูลอาจขัดแย้ง" อัตโนมัติเมื่อมีแหล่ง low credibility

**ENV ที่ต้องตั้งบน NAS:**
```env
BRAVE_SEARCH_API_KEY=       # ตัวหลัก · ปล่อยว่าง = ปิด (ไม่ยิงเน็ตเลย ไม่บ่น)
BRAVE_MIN_INTERVAL=1.1      # วินาที · <=0 ถอยไปใช้ default พร้อม warning
WEB_SEARCH_MIN_SCORE=0.35   # พื้นคะแนนสัมบูรณ์ — ต่ำกว่านี้ไม่ฉีด/ไม่ cite (ปิดด้วย =off)
```

### 🔴 บทเรียน 2026-08-31 — ชั้นค้นเว็บตาย 2 ชั้นพร้อมกันโดยไม่มีใครรู้ 8 วัน
user รายงานว่า "ขวัญตอบไม่ดี" — ไล่ log แล้วพบว่าไม่ใช่เรื่องคุณภาพโมเดล:
- **Gemini grounding 429 ทุกครั้ง** — วัดแยกตัวแปรแล้ว: โมเดลเดียวกันเรียกได้ปกติ
  แต่พอใส่ `google_search` = 429 ทันที ⇒ **free tier ไม่เปิด grounding เลย**
  (ลายเซ็น `limit: 0` เดิม) **เปลี่ยนโมเดล/รอวันใหม่ไม่ช่วย ต้องเปิด billing เท่านั้น**
- **Google CSE 403 ทุกครั้ง 48/48** — `This project does not have the access to
  Custom Search JSON API` เพราะคีย์อยู่คนละ Cloud project กับที่เปิด API ไว้
  (ผลพวงจากย้ายโปรเจกต์ 08-26) · **ยืนยันด้วยการยิงด้วย 2 คีย์เทียบกัน**:
  คีย์ Gemini ได้ `...are blocked` (= project เปิดแล้ว ติดที่ key restriction)
  ส่วนคีย์ search ได้ `does not have the access` (= project ยังไม่เปิด) — **ข้อความ
  error 2 แบบนี้แยก "ผิดที่คีย์" ออกจาก "ผิดที่โปรเจกต์" ได้ ใช้เป็นเครื่องมือวินิจฉัยได้**
- 🔑 **ต้นเหตุที่รอดสายตา: `_google_search` อ่าน `resp.json().get("items", [])`
  โดยไม่เคยดู `status_code`** ⇒ 403 กลายเป็น `INFO … → 0 results` ซึ่งอ่านแล้วเหมือน
  "ค้นแล้วไม่เจอ" ทั้งที่คือ "ค้นไม่ได้เลย" · แก้แล้ว (`436f22b`) — **ทุก provider ต้องแยก
  สองอย่างนี้ออกจากกันเสมอ** และ log ระดับ ERROR พร้อมสาเหตุจริง
- ⚠️ ผลลัพธ์ปลายทาง: เหลือ DDG ตัวเดียว → ถามราคาเกมแล้ว **ได้เว็บโป๊มาเป็นผลค้น**
  (พื้นคะแนน 0.35 ตัดทิ้งถูกต้อง แต่เหลือ 0 ตัวอักษร = ขวัญตอบโดยไม่มีข้อมูล)

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
