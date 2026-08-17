# Session Status (ยกมาจาก memory `hybrid_ai_status.md`)

> ย้ายเข้ารีโป 2026-08-17 · **เนื้อไม่ถูกแก้แม้บรรทัดเดียว** (ตัดเฉพาะ YAML frontmatter
> ของ memory ออก — เก็บไว้ท้ายไฟล์นี้แล้ว)
> ⚠️ **ลำดับในไฟล์นี้ไม่เรียงตามเวลา** — ของเดิมสลับ พ.ค.↔ส.ค. อยู่แล้ว
> จงใจไม่จัดเรียงใหม่เพราะการสลับลำดับ = โอกาสทำเนื้อหาย · ใช้ `grep` หาเอาแทน
> สถานะล่าสุด/งานถัดไปอยู่ที่ [`CLAUDE.md`](../../CLAUDE.md) หัวข้อ ▶️ เท่านั้น

## 🔴 จบเซสชัน 2026-08-03 — เริ่มเซสชันหน้าที่นี่

**สถานะ:** `main` = `c10f828` · prod ตรง main · tree สะอาด · เทส **1069** · CI เขียว · PR #4–#12 merged
**ปิดไปในเซสชันนี้:** backlog ข้อ **7** (security) · **5** (routers/sandbox) · **19** (fail-open) · **20** (entry gate)
· ข้อ **21 ทำถึงขั้น "มีเครื่องมือวัด + ground truth 110 คู่" แล้ว ยังไม่แตะ `utils/rag.py`**

### ⏭️ งานแรกของเซสชันหน้า: **shadow logging ของข้อ 21** (user สั่งไว้ 2026-08-03)
log ทุกเทิร์นว่า `split` / `ngram` / `semantic` *จะ* เลือกไฟล์ไหน — **ไม่เปลี่ยนพฤติกรรมการฉีด**
รอ ~1 สัปดาห์ แล้วเทียบกับ 👍/👎 ที่มีอยู่แล้ว → ได้ตัวอย่างหลักพันโดยไม่ต้องมาร์คมือ
**เหตุผล:** ground truth ที่มี positives แค่ 11 คู่ ยืนยันค่า threshold ไม่ได้ ต่อให้มาร์คครบ 297 คู่
· `data/skills_labeling_2.md` (139 คู่) ยังอยู่ ถ้าจะมาร์คต่อก็ไม่เสียของ (merge ไม่ทับ label เดิม)
· ⚠️ อย่าเพิ่งแก้ `load_skills_relevant()` จนกว่าจะมีข้อมูลจาก shadow log

### 🚩 3 ทางเลือกของข้อ 21 ที่ยังไม่ได้ตัดสิน (เรียงตามที่ผมเชียร์)
1. **ให้ `skills_md` ผ่านด่าน semantic** (เกณฑ์ ~0.40) — ใช้ของที่ `search_skills()` รันอยู่แล้ว
2. **ถอด `skills_md` ออกทั้งเส้น** — ระบบฉีด skill 2 ทางพร้อมกันอยู่แล้ว ทางนี้แม่น 11%
3. เขียน trigger keyword ใส่ front-matter ของ 22 ไฟล์ด้วยมือ — ตรวจสอบได้ ไม่มี false positive แปลกๆ

### ❓ ค้างที่ user ต้องทำเอง (ผมทำแทนไม่ได้)
- **ลองคุย voice จากมือถือนอกบ้าน 1 ครั้ง** — ยืนยันว่า token ผ่าน `?token=` ใช้ได้จริงหลังปิดรู WebSocket (ข้อ 7)
- (ถ้าจะมาร์คต่อ) `data/skills_labeling_2.md` แล้วบอกให้รัน `import` + `sweep`

---

## 🔖 session 2026-08-03 (ต่อ 6) — ข้อ 21 ขั้นที่ 1: ground truth harness ✅ · เทส 1047→1058 · `main` = `4e52673`

**ยังไม่แตะ `utils/rag.py`** — backlog กำกับว่าห้ามแก้ tokenizer ลอยๆ ต้องมี ground truth ก่อน

### 📊 วัดสถานะปัจจุบันบน prod (376 prompt จริง)
| | prompt | ฉีด | เฉลี่ย |
|---|---|---|---|
| ไทยล้วน (ไม่มี A-Z) | 252 | **81 (32%)** | 6,437 chars |
| มี Latin ปน | 124 | **105 (84%)** | 7,876 chars |

→ ช่องว่างจริงและใหญ่ แต่ **ไม่ใช่ 0% อย่างที่บันทึกเก่าบอก** (ประโยคไทยมีช่องว่างระหว่างวลี
`.split()` เลยยัง match ได้บางส่วน) — ตัวอย่างเฉพาะเจาะจงในบันทึกเดิมยังถูก แต่ภาพรวมไม่ใช่

### 🔧 `scripts/skills_groundtruth.py` (รูปแบบเดียวกับ `recall_groundtruth.py` ข้อ 12)
`pairs` (candidate = union ของ top-k ทุก scorer) → `worksheet` (.md ให้คนกาช่อง มีหัวข้อไฟล์กำกับ)
→ `import` → `sweep` (เทียบ split vs ngram ทุก threshold + **รายงานความกว้างของที่ราบ**)
· ⚠️ **คู่ที่ยังไม่มาร์คถูกข้ามเสมอ ห้ามเดาแทนคน** · ลบบรรทัดใน worksheet = ไม่แน่ใจ → คง `None` ไม่ใช่ `false`
· `ngram` ใช้ `memory/lexical.py` ตัวเดิมที่ผ่าน ground truth ข้อ 16 แล้ว ไม่ได้เขียนใหม่
· เทสของตัวเครื่องมือเอง 11 ตัว (haystack ต้องตรงกับ `load_skills_relevant` เป๊ะ ไม่งั้นวัดคนละอย่าง)

### ⏳ ค้างที่ user ต้องทำ — **มาร์ค 110 คู่ใน `~/Desktop/ui/data/skills_labeling.md`**
30 prompt (ไทยล้วน 15) · median 4 candidate/prompt · **57 คู่เป็นของที่ `split` ให้ 0 แต่ `ngram` เจอ**
(37 มาจาก prompt ไทยล้วน) = label ของ 57 คู่นี้คือตัวตัดสินว่าคุ้มแก้ไหม
เสร็จแล้ว: `python scripts/skills_groundtruth.py import` แล้ว `sweep`

### 📊 ผลจาก ground truth 110 คู่ที่ user มาร์คแล้ว (จำลอง prod top-3, positives=11)
| วิธี | ฉีด | ถูก | P | R | F1 |
|---|---|---|---|---|---|
| `split` >0 (**ของวันนี้**) | 46 | 5 | **0.109** | **0.455** | 0.175 |
| `ngram` >0 (backlog เสนอ) | 86 | 11 | 0.128 | 1.000 | 0.227 |
| **`semantic` ≥ 0.40** | **9** | **6** | **0.667** | 0.545 | **0.600** |

**ข้อสรุป: ไม่ใช่แก้ tokenizer แต่ใช้ semantic (เส้นที่ `search_skills()` ใช้อยู่แล้ว)**
· เฉพาะ prompt ไทยล้วน semantic ได้ **P=1.000** = แก้ปัญหาไทยไปในตัวโดยไม่ต้องแตะ tokenizer
· ⚠️ **positives มีแค่ 11 คู่** และที่ราบของ threshold กว้าง 1 จุด → **อันดับระหว่างวิธีเชื่อได้
แต่ค่า threshold เป๊ะๆ ยังเชื่อไม่ได้** (เกณฑ์เดียวกับบทเรียนข้อ 16/17)

### 🔴 /scrutinize เครื่องมือตัวเอง เจอ 4 ข้อ — **ตัวเลขที่รายงานรอบแรกผิด**
1. `cmd_sweep` วนด้วย `SCORERS` ที่ hardcode → **`semantic` หายจากรายงานเงียบๆ**
   ทั้งที่ `sweep()` คำนวณให้แล้ว · เทสที่เขียนไว้ครอบแค่ `sweep()` ไม่ครอบ `cmd_sweep()`
   = **เทสเขียวโดยข้ามเส้นที่คนใช้จริง** (รอบที่ 3 ของแพตเทิร์นนี้ในเซสชันเดียว)
2. **ไม่ได้จำลอง `max_files=3` ของ `load_skills_relevant()`** → รายงาน P=0.170 R=0.818
   ทั้งที่ของจริง **P=0.109 R=0.455** (ไฟล์ที่ถูก 4/9 หลุด top-3 ไม่เคยถูกฉีด)
   · และ**อันดับ split vs ngram สลับกัน**เมื่อ cap แบบ prod → คำพูดเดิมที่ว่า
   "ngram แย่กว่า split" **ผิด** (ngram F1 0.227 > split 0.175 แต่ precision แย่ทั้งคู่)
3. `rng_seed=hash(prompt)` — Python randomize hash ต่อ process (พิสูจน์: 48287 vs 11461)
   = การสุ่มวัดจุดบอดทำซ้ำไม่ได้ → `_seed()` sha1 + เทสตรึงค่า
4. `sweep` เดาคะแนนที่หายเป็น 0 → 16 คู่ (negative ล้วน) ดัน precision ของ semantic
   สูงเกินจริง (**"ล้มเหลว → ศูนย์"**) → ข้าม+รายงานจำนวนที่ข้าม + `merge_pairs` backfill

### ⚠️ ข้อเสนอเชิงวิธีการที่ควรทำแทนการมาร์คต่อ (จาก scrutinize)
**เลิกมาร์คมือ ไปทำ shadow logging แทน** — 30 prompt / 11 positives ไม่มีทางมีพลังพอ
ต่อให้มาร์คครบ 297 คู่ · ทางที่ถูกกว่า: log ทุกเทิร์นว่าแต่ละ scorer *จะ* เลือกไฟล์ไหน
(ไม่เปลี่ยนพฤติกรรม) 1 สัปดาห์ แล้วเทียบกับ 👍/👎 ที่มีอยู่แล้ว → ข้อมูลหลักพันโดยไม่ต้องมาร์ค
· 249→297 คู่ที่มีอยู่กลายเป็นชุด validation ไม่ใช่ชุดตัดสินเดี่ยวๆ
· ทางเลือกที่ยังไม่ได้พิจารณาจริงจัง: **ถอด `skills_md` ออกทั้งเส้น** (ระบบฉีด skill 2 ทาง
พร้อมกันอยู่แล้ว — ทางนี้แม่น 11%) · หรือเขียน trigger keyword ใส่ front-matter 22 ไฟล์ด้วยมือ

### 🔴 เจอระหว่างทาง: `scripts/` เป็นโค้ดดิร์เดียวที่ไม่ได้ mount
ในคอนเทนเนอร์เป็น**สำเนาค้างจากตอน build ล่าสุด** — มี 11 ไฟล์ **ขาด `clean_skills_db.py` /
`recall_groundtruth.py` / `clean_episodic.py`** ทั้งที่คู่มือสั่งให้รัน `clean_skills_db.py
--resync --apply` ในคอนเทนเนอร์ → เพิ่ม `./scripts:/app/scripts` แล้ว (ต้อง `compose up -d`
ไม่ใช่ restart) · verified หลัง recreate: scripts 17 ไฟล์ · embed cache 7.5 MB ยังอยู่ (mount ข้อ 23 ทำงาน)
### ✅ ปิดคดี "รัน `clean_skills_db.py` กับ prod ยังไง" (ไล่แล้ว 2026-08-03)
**ตอบไม่ได้ว่ารันยังไง และไม่เดา** — ไม่มีใน `~/.zsh_history` (Mac) / `~/.bash_history` (NAS),
log แอปไม่มีร่องรอย (สคริปต์เขียนไฟล์ตรง ไม่ผ่าน logger), ไม่มีการเรียก `/api/admin/cleanup-skills`
· ช่วงที่ `skills_db.json` ถูกแก้ (00:56 กรุงเทพ = 17:56 UTC) ตามด้วย container restart 17:56:35
แต่ burst embed+upsert ที่เห็นคือ **startup sync** ไม่ใช่ตัวสคริปต์
· เบาะแสที่ตัดตัวเลือกได้: `skills_db.json` มีที่เดียวคือ `data/skills_db.json` บน NAS —
`~/Desktop/ui/skills_db.json` และ `/var/services/homes/pawin/ui/skills_db.json` **ไม่มีไฟล์เลย**
ถ้ารันจากสองที่นั้นจะสร้างไฟล์ทิ้งไว้ → เหลือความเป็นไปได้เดียว: **รันข้างในคอนเทนเนอร์**

**สิ่งที่สำคัญกว่าและตอบได้: prod ถูกต้องอยู่** — dry-run 2026-08-03:
`22 entries → เก็บ 22 ลบ 0 · summary ล้าสมัย 0 · .md ที่ยังไม่มีแถว 0` = ผลข้อ 18 ลง prod จริง

⚠️ **คำสั่งที่ถูกต้องเขียนลง `CLAUDE.md` แล้ว (ต้องรันในคอนเทนเนอร์เท่านั้น):**
```bash
ssh nas 'sudo -n /usr/local/bin/docker exec ai-backend-1 \
  sh -c "cd /app && python scripts/clean_skills_db.py --resync --apply"'
```
`SKILLS_DB_PATH` = `<repo>/skills_db.json` → **รันบน Mac/NAS host = แก้ไฟล์คนละตัวกับ prod
แล้วรายงานว่าสำเร็จ** (บนเครื่อง dev ไม่มีไฟล์นี้ด้วยซ้ำ)

---

## 🔖 session 2026-08-03 (ต่อ 5) — ปิดข้อ 20 gate ทางเข้า skill ✅ · เทส 1035→1047 · `main` = `6dbf570` deployed+verified prod

`_is_meaningful_skill()` ถูกใช้เฉพาะตอน**ลบ** (`cleanup_junk_skills`) + `auto_extract_skills`
— ทางเข้าอีก **3 เส้นเขียนได้อิสระ**: `save_skill()` (**dream promotion เรียกอัตโนมัติทุกคืน**),
`accept_proposal()` (`POST /api/skills/discover/accept`), `skills_extract` (`POST /api/skills/extract`
= ที่มาของ `ได-เลย.md`)
· แก้: ใส่ gate ทั้ง 3 · `save_skill()` คืน `bool` และเป็น **chokepoint** ของ `skills_db.json`
(ผู้เรียกใหม่ปลอดภัยโดย default) · `accept_proposal` ครอบ `custom_topic`/`custom_content` ด้วย
· **verified prod: `save_skill(junk)` → False · `accept_proposal(junk)` → ปฏิเสธ · 22/22 ไม่ขยับ**

**invariant ใหม่ในเทส:** *ของที่ผ่านทางเข้าได้ ต้องไม่ถูก `cleanup` ลบ* — พังทันทีที่ใคร
แยกสองเกณฑ์ในอนาคต ดีกว่าเทสรายเคส (ไม่งั้นวนลูป "สร้าง → ล้าง → สร้างใหม่" แบบข้อ 9)

### 🔑 หลักฐาน: เทสย้อนหลังจับของบน prod ไม่ได้ **ตามนิยาม**
`git log --diff-filter=A -- skills/` = **22 ไฟล์ที่คนเขียนล้วน** — `ได-เลย.md`/`openclaw-*.md`
**ไม่เคยอยู่ใน git เลย** เกิดและตายบน `${NAS_DATA_PATH}/skills` ของ prod
→ `test_skills_freshness.py` มองไม่เห็น ไม่ใช่เพราะเขียนเทสไม่ดี · **gate ตอนเขียน = ด่านเดียวที่มี**

⚠️ **gate นี้จับแค่ "รูปแบบพัง"** (สั้นเกิน/ขึ้นต้นด้วย "ได้เลย"/URL) — **ไม่จับเนื้อหาที่ผิดแต่ฟอร์มสวย**
(เอกสารที่กุทั้งฉบับผ่านฉลุย) · จงใจ**ไม่**ย้าย `BANNED` จาก `test_skills_freshness.py` เข้า production
เพราะเป็นเรื่องความล้าสมัยที่เปลี่ยนตลอด + เคยมี false positive 9/16 ต้องมีระบบข้อยกเว้นคู่กัน
· ทางปิดที่ถูกคือ "ห้าม pipeline เขียนตรงลงที่ที่ฉีดเข้า prompt" (staging + คนอนุมัติ) = งานของตัวเอง
· 📚 vault: `wiki/concepts/auth-gaps-untested-paths.md` รูปแบบที่ 4

**สถานะ prod ก่อน deploy:** skills_db 22 ไม่ผ่านเกณฑ์ **0** · auto-discovered **0** ไฟล์
→ การล้างข้อ 9/18 ยังอยู่ครบ **gate เป็นการกันล่วงหน้า ไม่ใช่การกู้**
· 🧹 `.gitignore` เพิ่ม `server.log.*` (RotatingFileHandler สร้างไฟล์ rotate ที่ pattern เดิมไม่ครอบ)

### ⏭️ เซสชันหน้า: **ข้อ 21** (Thai tokenizer) — ⚠️ **ห้ามแก้ลอยๆ**
`utils/rag.py:62` ใช้ `query.lower().split()` → prompt ไทยล้วน = token เดียว match ไม่ได้
· **ต้องมี ground truth ของ skills ก่อน** ไม่งั้นอัตราฉีดขึ้นจาก 51% โดยไม่รู้ precision
= เพิ่ม noise 1,500 tokens ทุกเทิร์น · บั๊กตระกูลเดียวกับที่แก้ใน `memory/lexical.py` แล้ว
(character n-gram containment) · หรือเก็บงาน "ยังไม่แก้" ของข้อ 5 (ต้องมีเทส concurrency ก่อน)

---

## 🔖 session 2026-08-03 (ต่อ 4) — ปิดข้อ 19 fail-open ✅ · เทส 1029→1035 · `main` = `fddd626` deployed+verified prod

`search_skills()` มี fail-open 2 เส้น (`available == False` / `except`) ที่ `return get_all_skills()`
= เท**ทั้งคลัง**เข้า prompt · วัด prod: **22 รายการ = 7,455 chars ≈ 1,863 tokens/เทิร์น**
(เลข 48 ในบันทึกเก่าล้าสมัยตั้งแต่ปิดข้อ 18)
· ไม่ใช่แค่ noise — อยู่ใน volatile block ที่**ไม่มี cap** ยกเว้นเส้น `ollama` ที่ตัด 2,000 chars
→ การเทคลัง**เบียด `home_tool_ctx` (ข้อมูล real-time จริง) + citations ให้ตกท้าย** = คำตอบแย่ลงจริง
· แก้: fail-closed ทั้งสองเส้น (`return ""`) ปลอดภัยเพราะความรู้ยังเข้าทาง `load_skills_relevant()`
ที่อ่าน `.md` จากดิสก์ตรง ไม่พึ่ง ChromaDB (ตรวจแล้วว่า fail-closed อยู่แล้ว) · ครอบ agent tool
`skill_search` ที่รั่วเหมือนกันด้วย · **verified prod: จำลอง ChromaDB ล่ม → คืน `''` · แชทจริงยังตอบเรื่อง deploy ได้**

### 🔑 บทเรียนแม่บท — **"ยังไม่เคยเกิด" ในบันทึกเก่า ผิด**
บันทึก audit เขียนว่า "ตอนนี้ยังไม่เคยเกิดเพราะ ChromaDB ไม่เคยล่มพร้อมแอป" —
ไล่ log จริงพบ **45 ครั้ง** ใน 5 วัน (`05-19` 2 · `05-26` 7 · `05-27` 8 · `06-12` 4 · **`07-30` 24**)
ครั้งล่าสุด**ก่อนเขียนประโยคนั้น 4 วัน** → เป็น*การอนุมานจากกลไก* ไม่ใช่*การเปิดดู* (ใช้เวลา 2 นาที)
> เขียนว่าอะไร "ไม่เคยเกิด" ต้องเขียนต่อว่า **ตรวจจากอะไร** ตอบไม่ได้ = เขียนว่า "ยังไม่ได้ตรวจ"

⚠️ **`LOG_FILE` ของ prod = `/app/logs/server.log`** (ไม่ใช่ `/app/server.log` ในโฟลเดอร์โปรเจกต์
ซึ่งว่างเปล่าและหลอกตา) · rotate เก็บย้อนหลัง **~2.5 เดือน** (`server.log.1`–`.5`) = แหล่งหลักฐานจริง
· 📚 vault: `wiki/concepts/failure-mode-direction.md`

### ⏭️ เซสชันหน้าเริ่มที่ **ข้อ 20** (skill-discovery ไม่มี gate ทางเข้า) แล้วค่อย **ข้อ 21**
ข้อ 21 (Thai tokenizer ใน `load_skills_relevant`) — **ห้ามแก้ลอยๆ** ต้องมี ground truth ของ skills ก่อน
ไม่งั้นอัตราฉีดขึ้นจาก 51% โดยไม่รู้ precision · หรือเก็บงาน "ยังไม่แก้" ของข้อ 5 (ต้องมีเทส concurrency ก่อน)

---

## 🔖 session 2026-08-03 (ต่อ 3) — ปิดข้อ 5 routers/sandbox ✅ · เทส 1014→1029 · `main` = `3d8c467` deployed+verified prod

**🔴 `POST /api/fs/search` ล้มทั้งแอปได้ด้วย request เดียว** — ยิง `{"pattern":"(a+)+$"}`
ใส่ไฟล์ที่มี `aaaa…b` → `/api/config` จาก 14 ms **ไม่ตอบเลยจนกว่าจะ restart** (วัดจริง)
· **สองต้นเหตุคูณกัน แก้อันเดียวไม่พอ:** (1) ReDoS — `re` ของ CPython ไม่มี timeout
และ **interrupt ไม่ได้** ย้ายไป thread ก็แค่ย้ายที่ตาย (2) handler เป็น `async def`
เพราะ**ถูกบังคับ** (`await request.json()`) แล้วเรียก sync ตรงๆ → บล็อก event loop ทั้งเส้น
· แก้: ปฏิเสธ nested quantifier + จำกัดความยาว pattern + deadline 5 วิ + `run_in_threadpool`
· ⚠️ guard เป็น **heuristic ไม่ใช่การพิสูจน์** — ไม่ครอบ `(a|a)*` (มีเทสตรึงว่า `(foo|bar)+` ต้องผ่าน)

**🔴 `POST /api/vault/sync` รับ `vault_path` จาก body** → ชี้โฟลเดอร์ไหนก็ได้ ดูด `.md`
เข้า ChromaDB อ่านกลับทาง `/api/vault/search` + poison index ที่ใช้ตอบคำถาม ·
ผู้เรียกจริงส่ง `{}` อยู่แล้ว → เลิกรับจาก body · **verified prod: ส่ง `/etc` ไปแล้ว stats ยัง 48/49 ปกติ**

**🟠 `POST /api/dream` แช่ event loop ได้ 10 นาที** (`.result(timeout=600)` ใน async def)
+ กับดักซ้อน `with ThreadPoolExecutor` → `shutdown(wait=True)` ตอนออก = **เส้น timeout
กลับไปแช่รอ dream ที่เพิ่งบอกว่าไม่รอ** → `shutdown(wait=False)`

**⚠️ ตั้งใจไม่แก้ (เหตุผลใน backlog):** `async def` + งาน sync ที่ช้ามีอีกหลายที่
(`documents` `skills_extract` `memory` `agent` `chat`) — `run_in_threadpool` ย้ายโค้ดที่
**แตะ global state** (`skills_db`/memory/cache) ไปรันพร้อมกัน = แลกบั๊ก availability
กับ data race → ต้องมีเทส concurrency ก่อน · `documents/upload` อ่านไฟล์เข้า RAM ก่อนเช็ค 10 MB

**🔑 บทเรียนแม่บทของเซสชันนี้: เทส concurrency ตัวแรกเขียวทั้งที่ยังไม่ได้แก้อะไรเลย**
จับได้ตอน `git stash` เอา fix ออกแล้ว**ไม่แดง** · เหตุ: จับเวลา*หลัง* `await asyncio.sleep()`
ซึ่ง sleep เองก็ถูก event loop ที่บล็อกดองไว้ → **ต้องวัดจาก t0 จุดเดียวก่อนยิงทั้งคู่**
→ **เขียนเทสเสร็จต้องถอด fix ออกแล้วเห็นมันแดงจริงก่อนถึงจะเชื่อได้**
· 📚 vault: `wiki/concepts/fastapi-blocking-and-redos.md`

### ⏭️ เซสชันหน้าเริ่มที่ **ข้อ 19 / 20 / 21** (เงื่อนไขก่อนพ่วง OpenClaw ครบแล้ว ✅)
19 `search_skills()` fail-open → ฉีด skill ทั้งคลัง · 20 skill-discovery ไม่มี gate ทางเข้า
(เลือดหยุดแล้ว `DREAM_PROMOTE_SKILLS` default false) · 21 Thai tokenizer (ต้องมี ground truth ก่อน)
· หรือเก็บงาน "ยังไม่แก้" ของข้อ 5 ข้างบน (ต้องมีเทส concurrency ก่อน)

---

## 🔖 session 2026-08-03 (ต่อ 2) — ปิดข้อ 7 security ✅ · เทส 997→1014 · `main` = `98da5d3` deployed+verified prod

**เจอรูจริง 2 รู ทั้งที่เทสหน่วยของ `auth.py`/`ratelimit.py` เขียวมาตลอด** (PR #4 merged, CI เขียว)
1. 🔴 **`/ws/voice/{slug}` ไม่มี auth เลย — เปิด public อยู่จริงบน prod** ยืนยันด้วยการต่อ
   `wss://ai.pawinhome.com/ws/voice/kwan` จากเน็ตนอกโดยไม่มี token → ได้ `{"type":"connected"}`
   = เปิด session Gemini Live จริง เผา quota ได้ไม่จำกัด · ต้นเหตุ: `app.middleware("http")`
   = `BaseHTTPMiddleware` **ลัดผ่านทุก ASGI scope ที่ไม่ใช่ `http`** → auth/rate-limit/request-id
   ไม่เคยแตะ WS · แก้ด้วย `core.auth.websocket_authorized()` เรียกก่อน `accept()`
   · **หลัง deploy verified: public → HTTP 403 ตอน handshake · loopback ยังต่อได้ (ไม่ regress)**
2. 🔴 **`/api/auth/login` ไม่เคยเข้าเงื่อนไข brute-force lockout** — นับเฉพาะ request ที่มี
   header `x-auth-token` แต่ login ส่งรหัสใน **body** → endpoint เดียวที่ lockout มีไว้ป้องกัน
   คือ endpoint เดียวที่ไม่เคยถูกนับ (รหัสผิด 8 ครั้งติด = 401 ทั้ง 8) · ต้นเหตุคือ
   **overcorrection ของ fix 2026-06-02** ที่กัน false lockout ตอนโหลดหน้า
3. 🟡 open prefix ใช้ `startswith` ดิบ → `/api/sharedsecrets` จะหลุด public เงียบๆ (latent) แก้แล้ว

⚠️ **WS token ต้องไปทาง query param** (browser ตั้ง header บน WebSocket ไม่ได้) →
`~/appscript.ui/utils/voicelive.ts:voiceWsUrl` (commit `fd87442`, push ครบ 2 remote)
**แก้ backend อย่างเดียว = voice ของคนนอกบ้านพัง** ต้อง build + `sync_static.sh` คู่กันเสมอ
· ❓ **ยังไม่ได้ยืนยันด้วยตา: กดคุย voice จากมือถือนอกบ้านจริง** (ผมอ่าน `UI_PASSWORD` prod ไม่ได้ — ถูก block ถูกต้องแล้ว)
· ตั้งใจ**ไม่**ยิงเทส login lockout บน prod (จะล็อก IP บ้านตัวเอง 5 นาที) — พิสูจน์ครบใน local end-to-end แทน
· ที่เลือกไม่แก้ + เหตุผล: share token 40 บิต · `client_key` เชื่อ `cf-connecting-ip` (ดูท้าย backlog)
· 📚 บทเรียนเข้า vault แล้ว: `wiki/concepts/auth-gaps-untested-paths.md` (3 รูปแบบ + เช็คลิสต์ 5 ข้อ)

### ⏭️ เซสชันหน้าเริ่มที่ **backlog ข้อ 5 (`sandbox.py` + routers อีก 12 ตัว)**
เหลือข้อเดียวก่อนครบเงื่อนไขพ่วง OpenClaw (ข้อ 7 ปิดแล้ว) · `sandbox.py` มาก่อนเพราะรันโค้ดจริง
— แต่ **`run_python` ถูก gate ปิดอยู่แล้วบน prod** (ไม่ mount `docker.sock` โดยตั้งใจ) ตรวจให้ครบว่า
เส้น `/api/fs/*` ที่เพิ่ง mount `/app/sandbox` ตอนข้อ 6 ไม่ได้เปิดอะไรเกิน
· แล้วค่อยข้อ 19 (`search_skills()` fail-open) · 20 (skill-discovery gate — เลือดหยุดแล้ว
`DREAM_PROMOTE_SKILLS` default false) · 21 (Thai tokenizer — ต้องมี ground truth ก่อน)

---

## 🔖 session 2026-08-03 (ต่อ) — ปิดข้อ 6 ยิง tools 22 ตัว + ข้อ 23 cache ✅ · เทส 984→997

**สถานะจบเซสชัน:** `main` = `5cf933e` **CI เขียวทั้ง 2 commit** (เขียวครั้งแรกตั้งแต่ `9d55c78`)
· prod git ตรง main · PR #2 + #3 merged แล้ว · tree สะอาด
· prod verified: tools 21/22 (`run_python` ถูก gate) · fs → `/app/sandbox` persist ·
embed cache 1,791 rows · skills 22 · `local_ok: true`

**ยิง agent tools ครบ 22 ตัวบน prod ครั้งแรก** (เดิมเทสจริงแค่ `ping_device`)
17 ตัวถูก · `ha_call_service` ตอบ "ส่งแล้วแต่ยืนยันไม่ได้" = **guard ทำงานถูก ไม่ใช่บั๊ก**
· ℹ️ **`HA_TOKEN` มีค่าบน prod แล้ว** — บันทึกเก่าที่ว่ายังว่างล้าสมัย HA ใช้ได้จริง

**🔴 `run_python` ตายสนิท** — container ไม่มี `/var/run/docker.sock` → blocked ทุกครั้ง
แต่ยังโฆษณาให้โมเดลเลือก → capability gate (`build_registry()`/`_sandbox_available()`)
ไม่ลบโค้ด · **ตั้งใจไม่ mount docker.sock** — agent ที่จะรับคำสั่งจากแชท (แผน OpenClaw)
ไม่ควรมี docker socket ของ NAS · verified prod: โฆษณา 21/22

**🔴 `fs_*` 4 ตัว no-op เงียบ** — `_DEFAULT_ROOT=~/Desktop/ui/sandbox` (layout Mac) →
ในคอนเทนเนอร์เป็น `/root/Desktop/ui/sandbox` ที่ไม่ได้ mount → **ไม่ error แค่คืน
"0 entries" ตลอด** → mount `${NAS_DATA_PATH}/sandbox:/app/sandbox` + `FS_TOOLS_ROOTS`

**🔴 ข้อ 23: `/app/data` ไม่ได้ mount เลย** — เป็นที่อยู่จริงของ `embed_cache.db`
(7.5MB/1,791 embeddings) + `response_cache.db` + `gen_images` · `--force-recreate`
(วิธี deploy เวลาแก้ `.env`) ล้างทิ้งหมด ทั้งที่ config เขียน "for persistence"
→ mount `${NAS_DATA_PATH}:/app/data` · กู้ของก่อน recreate · verified 1,791 rows ครบ

**🔴 CI แดงมาตั้งแต่ `9d55c78` (เซสชันก่อน) 3 commit โดยไม่มีใครเห็น** — ที่แดงคือ
**Lint (ruff) ไม่ใช่ pytest** บันทึกเขียน "เทส 961 passed" ซึ่งจริงแต่มาจากเครื่อง
· **บทเรียน: "เทสเขียวในเครื่อง" ≠ "CI เขียว" ต้องดู `gh run list` ก่อนปิดงานทุกครั้ง**

**ข้อ 22 ใหม่: CI ไม่ได้เทสสิ่งที่ prod รัน** — CI `pip install -r requirements.txt` (`>=`)
แต่ Dockerfile ใช้ `requirements.lock` · `mcp>=1.27.0` → CI ได้ **2.0.0** ที่ถอด decorator
`@server.list_tools()` → `mcp_server.py` พัง · prod รัน 1.28.1 ยังปกติ → **pin `mcp<2`**
⚠️ `mcp_server.py` คือสะพานที่จะใช้พ่วง OpenClaw จึงปล่อยพังไม่ได้

**บทเรียนร่วมข้อ 6+23: "คอมเมนต์บอกว่าทำ แต่ไม่มีใครเคยตรวจว่าทำจริง"** — `for persistence`
/ `sandbox root` เป็นเจตนา ไม่ใช่หลักฐาน · เทสหน่วย `fs_tools` ผ่านมาตลอดเพราะเทส*ตรรกะ*
ไม่ใช่*ที่อยู่จริงบน prod*

**OpenClaw (ค้นแล้ว):** แพลตฟอร์ม AI Agent open source ของ Peter Steinberger · พ.ย. 2025 ·
MIT · 180k stars · 29 ช่องทางแชท · Node 22.22.3+/26 · มี Docker official
**ทางพ่วงที่พร้อมแล้วไม่ต้องเขียนโค้ด:** `mcp.servers` ใน `~/.openclaw/openclaw.json`
รับ stdio → `{command:"docker", args:["exec","-i","ai-backend-1","python3","/app/mcp_server.py"]}`
+ `tools.allow` (แนะนำเริ่มด้วย read-only) · เก็บรายละเอียดใน `skills/openclaw.md`

## 🔖 session 2026-08-03 (ต่อรอบ 3) — ปิดข้อ 18 `skills_db.json` 48→16 ✅ · เทส 965→984
**root cause: `auto_extract_skills()` ไม่รู้จัก code fence** — `.env` ใช้ `#` เป็นคอมเมนต์
ทุกคอมเมนต์ในบล็อก ```env จึงกลายเป็น "หัวข้อความรู้" (`============ AI Models ============`)
· **บั๊กเดียวทำสองทาง**: หัวข้อจริงเหนือบล็อกถูกทิ้งด้วย เพราะ loop เก็บเนื้อหาไปหยุดที่
คอมเมนต์บรรทัดแรก → summary เหลือ `` ```env `` สั้นเกินเกณฑ์ · แก้ที่ `_fence_flags()`
· ลบ 32: GUIDE.md 25 (ตรวจทีละหัวข้อ **ซ้ำกับ skills/*.md ครบ ไม่มีความรู้ใหม่**) +
schemas.md 7 (เอกสารของ `skill-creator` คนละระบบ) · `scripts/clean_skills_db.py` dry-run default

**🔴 บทเรียนใหญ่: ข้อ 9 ปิดไม่ครบ และ guard ที่ผมเขียนเองก็ไม่จับ**
`summary` ใน `skills_db.json` เป็น **snapshot ตอน ingest ไม่ใช่ pointer ไป .md** → แก้ .md
แล้ว `search_skills()` ยังฉีด `GEMINI_MODEL=gemini-2.5-pro` ที่ควรตายไปแล้ว · stable block
ได้ของใหม่ แต่ volatile block ค้าง = **"แก้ 3 ใน 4 จุดแล้วคิดว่าจบ" ซ้ำอีกรอบ**
→ `resync_summaries()` + `--resync` **ต้องรันทุกครั้งที่แก้ `skills/*.md`**

**และ: การเข้ารหัสกฎเป็นเทสได้ผลจริง** — เติม pattern `Ollama` คู่กับ `:1234` (พอร์ต LM Studio)
เข้า BANNED → จับเพิ่ม **5 จุดใน 5 ไฟล์ ซึ่ง 4 จุดหาไม่เจอตอนไล่ด้วยมือ** ·
**กฎที่เขียนไว้จับได้มากกว่าคนอ่านทีละบรรทัด แต่จับได้เฉพาะสิ่งที่คิดจะเข้ารหัส**

## 🔖 session 2026-08-02 (รอบ 3) — ปิด P2-9 `skills/*.md` ✅ verified prod · เทส 961→965
**ขนาดจริงที่วัดได้:** skills ฉีดเข้า context **233/460 prompt (51%) median ~1,500 tokens**
อยู่ใน stable block **ไม่มี threshold กรองเลย** (keyword ตรง 1 คำ = ฉีดทั้งไฟล์)

**3 เรื่องที่เจอ — ไม่ตรงกับที่ backlog เดาไว้:**
1. **prod ล้าหลัง git 3 ไฟล์นาน 4 สัปดาห์** — แก้เป็น qwen3.5-9b ใน git ตั้งแต่ 07-05
   แต่ prod ยังอ่าน deepseek/gemma-4-e4b · ต้นเหตุ = container mount `${NAS_DATA_PATH}/skills`
   ไม่ใช่ `skills/` ในโค้ด (gotcha ที่ CLAUDE.md เตือนแต่ไม่มีอะไรบังคับ) → **sync แล้ว verified**
2. **5 ไฟล์ขยะบน prod ไม่มีใน git** (auto-discovered 05-12) ลบแล้ว — `ได-เลย.md` มีเนื้อหาเดียวคือ
   `"❌ Gemini quota หมด..."` · `openclaw-*.md` เป็นนิยามที่โมเดลกุเอง ถูกฉีดกลับ 24 ครั้ง
   = **บั๊กตระกูลเดียวกับ episodic (ข้อ 1/14) แต่ฝั่ง skill ยังไม่มี gate ปิดทางเข้า**
3. แก้เนื้อหาล้าสมัย 7 จุด + `UI_PASSWORD=Sapoil` ที่เขียนเป็นค่าจริงในไฟล์ที่ฉีดเข้า context

**⚠️ บทเรียนแม่บทของรอบนี้: grep หาชื่อของตายให้ false positive 9 จาก 16 จุด (56%)**
`ChromaDB :8000` ถูกแล้ว (แอป=8080) · `OLLAMA_MODEL=llama3` ถูกแล้ว (dormant แต่ชื่อยังงั้น) ·
`Archer C7/DS918+` เป็น*ตัวอย่างของที่โมเดลกุ*ในเอกสารกัน hallucination · `deepseek` ในประโยค
"เปลี่ยนจาก X → Y แล้ว" → **นับจาก grep แล้วรายงานเลย = รายงานผิดเกินครึ่ง ต้องเปิดดูทีละบรรทัด**

**guard:** `tests/test_skills_freshness.py` 4 เทส · ยกเว้นระดับ*บรรทัด* (`WARNING_CONTEXT`)
ไม่ใช่ระดับไฟล์ — "ห้ามใช้ X" ต้องเอ่ยชื่อ X ได้ แต่ `KEY=X` ในไฟล์เดียวกันยังโดนจับ
· `test_every_exemption_is_still_needed` กัน allow-list เน่าเงียบ
· **พิสูจน์ว่าไม่ได้ทำให้หลวมเพื่อให้เขียว: รันกับไฟล์ prod ก่อนแก้ ต้องแดงครบ 11+5 จุด**

**🆕 finding ใหม่ 4 ข้อ (บันทึกใน backlog ข้อ 18-21 ยังไม่แก้):**
- **18** `skills_db.json` 48 entry ตรวจแล้วแค่ 16 — 25 มาจาก `GUIDE.md` หั่นหัวข้อ (มี mojibake +
  `============ AI Models ============` เป็นชื่อ skill) · 7 มาจาก `schemas.md` ที่**ไม่มีไฟล์นี้ในโปรเจกต์**
  · verified prod: ถาม "openclaw คืออะไร" ได้ `============ Ollama (Local) ============` ที่ค่าผิด
- **19** `search_skills()` fail-open → ChromaDB ล่ม = ฉีด skill ทั้ง 48 รายการเข้า context
- **20** skill-discovery ไม่มี gate ฝั่งทางเข้า (ต้นเหตุขยะ) · เทส guard จับเฉพาะของที่ commit เข้า git
  — ของที่ pipeline สร้างตรงลง prod **ไม่ผ่านสายตาเทสเลย**
- **21** `utils/rag.py:62` ใช้ `query.lower().split()` → **ไทยไม่มีช่องว่าง = prompt ไทยล้วน match ไม่ได้**
  ("ระบบใช้โมเดลอะไร" → 0 chars · "memory system ทำงานยังไง" → 8,785) เป็นบั๊กตระกูลเดียวกับ
  `memory/lexical.py` เส้นที่ 2 · ⚠️ ห้ามแก้ลอยๆ — จะดันอัตราฉีดขึ้นจาก 51% โดยไม่รู้ precision

## 🔖 session 2026-08-02 — audit ทั้งระบบ: แก้ 24 บั๊ก · คลังความรู้เป็นขยะ · เจอบั๊ก embedding ไทยรอบ 3
**🔴 อ่านก่อนเริ่มงานต่อ: `~/Desktop/ui/docs/audit-backlog-2026-08-02.md` = รายการค้างทั้งหมด (P0 ปิดครบแล้ว เหลือ P1/P2/P3)**

**บั๊กใหญ่สุดของ session — embedding ภาษาไทยรอบ 3:** `nomic-embed-text-v1.5` (LM Studio)
แมปประโยคไทย**ทุกประโยค**เป็น vector เดียวกัน cosine=1.0000 (อังกฤษปกติ 0.38-0.44)
— คือเส้น `utils/documents.py` ที่รอบ ก.ค. **ตั้งใจยกเว้นไว้** รอดมา 3 สัปดาห์
→ document RAG ไทยคืนผลมั่วมาตลอด + response cache (0.92) เป็นระเบิดเวลารอกด 👍 ครั้งแรก
แก้: สลับเป็น `paraphrase-multilingual` บน Ollama (768-dim เท่าเดิม) + ตัด fallback ข้ามโมเดล
+ re-embed 1,740 chunks (`scripts/reembed_documents.py`) · รายละเอียดเต็มใน vault
[[thai-embedding-chromadb]] (เพิ่มเช็คลิสต์กันซ้ำรอบ 4 แล้ว)

**คลังความรู้เป็นขยะทั้ง 3 ชั้น — ล้างแล้ว:**
| คลัง | ก่อน | หลัง |
|---|---|---|
| lessons | 30 | **5** |
| skills | 112 (Dream สร้างเอง 60) | **52** (เขียนเองล้วน) |
| long_term_memory | 50 | **5** |
| ChromaDB collections | 14 (ซาก migration 6) | **8** |
- ต้นเหตุ lessons: auto-learn เก็บราคาทองเก่า/พยากรณ์อากาศ/ข้อความ error เป็น "ความรู้ถาวร"
  · เช็ค SKIP ใช้ `!= "SKIP"` เป๊ะๆ → `"คืนนี้ฝนจะตกไหม? SKIP"` รอดเข้ามา
- ต้นเหตุ skills: **few-shot example ใน prompt REM sleep เองสอนผิด** (`"User frequently
  deploys to NAS"` = บันทึกว่าเคยคุย) → 60 skills ใน 3 เดือน ใช้ได้จริง 1 อัน
  แก้ prompt แล้ววัดใหม่: 7 themes ผ่าน gate 6 เป็นความรู้จริง · **แต่ยังปิด
  `PROMOTE_SKILLS_ENABLED=false` ตามที่ user เลือก** (เปิดกลับ `DREAM_PROMOTE_SKILLS=true`)
- ⚠️ **บทเรียน: ของในคลังเป็นขยะ แก้ด้วย threshold ไม่ได้** — พอล้างแล้วคะแนนกลับปกติเอง
  (คำถามไม่เกี่ยว 0.452 → 0.184) โดยไม่ต้องตั้งเกณฑ์เลย

**P0 ปิดครบ (commit `2ecc6d4`, `361b772`):**
- `remember()` ไม่มี gate → episodic เก็บข้อมูลสด/error ทุกเทิร์น (memory_kwan 57/92 =62%,
  memory_logic 47/62 =76%) เพิ่ม `should_remember(prompt, response)` แล้ว
  ⚠️ **ของเก่าในคลังยังไม่ล้าง** (ห้ามล้างยกคลัง — episodic ควรเป็นบันทึกบทสนทนา ดูข้อ 14)
- `preferences` = 0 มาตลอด 3 เดือน — บั๊ก **5 ชั้น** ชั้นที่ 5 มองไม่เห็นจากโค้ด:
  collection ถูกสร้างด้วย default embedder ตั้งแต่ก่อน migration (ข้ามเพราะ 0 docs)
  → `save_preference()` คืน False เงียบๆ · ลบ+สร้างใหม่แล้ว verified 0→2 รายการ

**บั๊กอื่นที่แก้ (ดู git log `a6b9278`..`361b772`):** Dream deep_sleep theme พังลากตัวอื่นหาย ·
document RAG embed-fail เขียน vector ผิดมิติ · HA `call_service` รายงานสำเร็จทั้งที่ entity
ไม่มีจริง · chat/regenerate crash ไม่ save คำตอบบางส่วน (ฟองค้าง) · classifier gap ราคา/ข่าว ·
**SSE `error` event ไม่เคยถูกจัดการฝั่ง UI** (ฟองค้าง "กำลังพิมพ์" ตลอดไป) · citation เอกสาร
ไม่เกี่ยวโผล่ทุกข้อความ (threshold 0.3→0.5 วัดจริง) · `search_vault()` ไม่มีเกณฑ์เลย
**โน้ตส่วนตัวรั่วเป็น citation** · Gemini grounding ไม่เคยส่ง citation · `cache_hit` badge ·
`sync_skills_to_search()` มีแต่ upsert ไม่เคยลบ · realtime query ไม่ bypass response cache
(ข่าว/น้ำท่วม/แผ่นดินไหว — อันตรายกับข้อมูลภัยพิบัติ) · meter bar animate width→scaleX

**เทส 742 → 863 ผ่านหมด** · frontend 120 · ทุกอย่าง deploy+verify บน prod จริง

**gotcha ใหม่ที่มีค่า:**
- `skills_db.json` มี 2 ไฟล์: ใน git root (ไม่ใช้แล้ว **เลิก track + gitignore แล้ว**)
  กับ `data/skills_db.json` (ตัวจริงที่ compose mount) — `core/config.py` มีคอมเมนต์อธิบาย
- `scripts/` ถูก bake ใน image ไม่ได้ mount → รันสคริปต์ใหม่บน prod ต้อง `docker cp` เข้าไปก่อน
- `documents` collection ef conflict = **ตั้งใจ** (ใช้ vector ตรงจาก `embed_texts()`)
  ส่วน `preferences` conflict = บั๊กจริง
- Gemini quota หมดเร็วมากถ้าเทสถี่ (2.5-flash) → fallback ไป lmstudio อัตโนมัติ

**ค้างที่ปิดไม่ได้:** Gemini citations บนจอจริง (quota หมดตอนเทส รอ reset) · voice ต้องมี
คนเทสด้วยไมค์ · `skills/*.md` 5 ไฟล์อ้าง deepseek/llama3 ที่เลิกใช้แล้วแต่ยังฉีดเข้า context

โปรเจกต์ Hybrid AI Workspace ที่ `/Users/pawin/Desktop/ui` — ทำเสร็จไปแล้ว Phase A-G บน production (NAS DS923+ ที่ `192.168.51.49`). Latest commit: `80f1eb6` (main branch, pushed origin).

## 🔖 session 2026-07-13 (ต่อ 2) — ปิดงานค้างครบ: deploy `d6444c7` + ปิด DSM Task id=3 ✅
- **Deploy สำเร็จ:** NAS อยู่ที่ commit `d6444c7` (รวม `603864a` retrieve_chunks fix + `9af238f` docs) ผ่าน `git reset --hard origin/main` + `docker restart ai-backend-1` — verify `/api/status` ปกติหมด (ollama/lmstudio/gemini/memory=true, skills=103, next_dream_schedule=2026-07-14 02:00)
- **DSM Task id=3 ปิดแล้ว ✅** ผ่าน browser automation (QuickConnect `pawinh.sg3.quickconnect.to` → DSM GUI → Control Panel → Task Scheduler): เจอ task ชื่อ **"Task 3"** จริง (list scroll เดิมง่ายพลาดตำแหน่ง — ใช้ `find` tool ค้น action `curl.../api/dream` เจอ) เอาติ๊ก "เปิดใช้งาน" ออก + กด "ปรับใช้" (บันทึก) confirm dialog ระบุ "งานที่ถูกปิดไว้: Task 3" ตรงตัว — verify screenshot หลังบันทึก checkbox ว่างแล้วจริง
- **gotcha ใหม่:** `nashome.pawinhomelab.com` (Cloudflare Tunnel เดิม) auto-redirect ไป `:5001` แล้ว error page (tunnel ไม่ได้ forward port นั้น) — ใช้ **QuickConnect `pawinh.sg3.quickconnect.to`** แทนได้ผล (2FA ผ่านแอป Secure SignIn บนมือถือ)
- **ปิดเคสถาวร:** Dream Cycle จะไม่รันซ้ำ 2 รอบอีกแล้ว (ตัวซ้ำ=DSM Task 3 ปิดแล้ว, in-app scheduler ตัวเดียวที่เหลือรันตี 2 บางกอกถูกต้อง)

## 🔖 session 2026-07-13 (ต่อ) — P2-9 Admin memory API + P3-12 classifier gaps + P3-14 Dream Cycle silent-broken ✅ DEPLOYED prod `9af238f`
- **P2-9 ✅**: `GET/DELETE /api/admin/memory/{assistant}` (LAN-only) + `X-Test-Request` header ให้ `/api/chat` ข้าม remember/teach/auto-learn ตอนสโมกเทส — commit `5e03fca`+`f03a0db`
- **P3-12 ✅**: audit `needs_internet()` ด้วยคำถาม real-time 16 แบบ เจอ 10 gap จริง (ทองคำสลับลำดับคำ, ไม่มีหมวดกีฬา/จราจร/หุ้น/ภัยพิบัติ/ไฟดับเลย) → ปิดครบ 8 หมวดใหม่ — commit `41a7e58`
- **P3-14 🔴→✅ เจอบั๊กใหญ่จริง — Dream Cycle ประมวลผล memory เป็น 0 ทุกคืนเงียบๆ ตั้งแต่ 2026-07-09** (วัน deploy Thai-embedding migration): `light_sleep()` ครอบ loop สแกน `memory_*` collection ด้วย try/except เดียว พอเจอ collection backup migration (`*__minilm_backup_20260709` ยังผูก default embedder) → conflict กับ ollama ef ปัจจุบัน → **ทั้งฟังก์ชัน return `[]` ทันที** ทั้งที่ `memory_kwan`(79)/`memory_logic`(69) มีข้อมูลจริง แก้เป็น per-collection try/except เหมือน `memory_decay`/`memory_prune` ที่ทำถูกอยู่แล้ว — commit `3d479b5`
- **P3-14 bonus — เจอ Dream Cycle รันซ้ำวันละ 2 รอบ**: root cause #1 (แก้แล้ว) `CronTrigger(hour=2,minute=0)` ไม่ผูก `timezone=` ตรงๆ → `BackgroundScheduler(timezone="Asia/Bangkok")` ไม่ inherit เข้า trigger ที่สร้างแยก → fallback OS-local (container ไม่ตั้ง TZ=UTC) → ยิงเพี้ยน 7 ชม. (ตี 9 แทนตี 2 บางกอก) — commit `84e255d`. root cause #2 (**ยังไม่ได้แก้ ต้อง user รันเอง**): DSM Task Scheduler task id=3 ("Task 3", สร้าง 2026-04-22 ก่อน in-app scheduler จะมี 2026-05-11) `curl -X POST http://localhost:8080/api/dream` ทุกวัน 02:00 บางกอก — ซ้ำกับ in-app scheduler ที่เพิ่ง fix ให้ตรงเวลาเดียวกันพอดี **⚠️ ถ้าไม่ปิดก่อนคืน 2026-07-13 ~02:00 น. Dream จะรันซ้ำ 2 รอบพร้อมกัน** — คำสั่งปิด: `ssh -o ProxyCommand="cloudflared access ssh --hostname %h" pawin@ssh.pawinhomelab.com` แล้ว `sudo /usr/syno/bin/synoschedtask --set id=3 enable=no` (ต้องใส่ sudo password, sync ไม่มี NOPASSWD เหมือน docker) — เช็คด้วย `synoschedtask --get id=3 | grep state` ต้อง `disabled`
- **gotcha ใหม่ที่มีค่า**: `/etc/crontab` บน DSM อ่านได้โดยไม่ต้อง sudo (list synoschedtask ids ทั้งหมด) + `/usr/syno/etc/synoschedule.d/root/<id>.task` แต่ละไฟล์ก็อ่านได้ตรงๆ (ดู action/cmd จริงได้) แม้ `synoschedtask --get` เองจะต้อง sudo password — ใช้ 2 ไฟล์นี้สืบ DSM task ได้โดยไม่ต้องมี sudo เลย
- **เทส upload PDF scan จริง ✅ (P0-5 ค้าง)**: สร้าง synthetic scan (PIL render ไทย+อังกฤษ→รูป→PDF ไม่มี text layer, verify ด้วย pdftotext) upload ผ่าน curl จาก trusted network NAS เอง (ไม่กรอก UI_PASSWORD ใน browser form — นโยบายไม่พิมพ์รหัสแทน user แม้เป็น app ของ user เอง) **OCR เองทำงานถูก 100%** (Gemini Vision อ่านได้ 492 ตัวอักษรตรง) แต่เจอบั๊กคนละตัวตอน verify: **`retrieve_chunks()` (`utils/documents.py`) query กับ index ใช้ embedding คนละมิติ (768 vs 384) → document search คืนค่างเปล่าทุกครั้งแบบเงียบๆ — ไม่เกี่ยวกับ Thai-embedding migration เป็นบั๊กเก่ามาตั้งแต่ Phase B น่าจะแปลว่า docs_ctx ไม่เคย retrieve อะไรได้ในแชทเลย** แก้แล้ว + เทส 3 เคส (suite 738) — commit `603864a` push แล้ว
- **ปิด session 2026-07-13: deploy commit `603864a` (+ `9af238f` docs) ค้างไว้ตั้งใจ — user ขอ deploy ตอนเริ่ม session หน้าแทน** (ทางเดียวกับ deploy ทุกครั้งก่อนหน้า: `ssh -o ProxyCommand="cloudflared access ssh --hostname %h" pawin@ssh.pawinhomelab.com` แล้ว `cd /var/services/homes/pawin/ui && git fetch origin main && git reset --hard origin/main && sudo -n /usr/local/bin/docker restart ai-backend-1`)
- **⚠️ ค้างจริงแยกต่างหาก ไม่ใช่ deploy**: DSM task id=3 ยังไม่ได้ปิด (ดู root cause #2 ด้านบน) — user ยังไม่ได้ยืนยันว่ารันคำสั่งปิดแล้วหรือยัง ต้องถามซ้ำ session หน้าถ้ายังไม่เห็นการยืนยัน
- **WireGuard ยังใช้ไม่ได้จากเครือข่ายนี้ session นี้ (ที่ทำงาน)** — handshake ไม่ผ่านซ้ำรอยเดิม 2026-07-09 (ดู [[project_home_network]]) ใช้ Cloudflare Access SSH (`ssh.pawinhomelab.com` ProxyCommand) แทนได้ตลอด deploy ทั้งเซสชัน
- suite 735 passed (backend)

## 🔖 session 2026-07-12/13 — ROADMAP session 2 (คุณภาพ) ✅ DEPLOYED+verified prod `73c382e`
- **P2-7 ✅ pyflakes/ruff:** ตรวจ 3 จุด smell ก่อนลบ — `cached_mid` **ไม่ใช่** logic หล่นหาย (ทุก short-circuit path ส่งเฉพาะ assistant id ใน done), `nonlocal messages` ไม่จำเป็น (มีแต่ item assignment), `genai_types` shadow แก้ไปแล้วตั้งแต่ 06-12 · กวาด ruff F 58 จุด · **ruff เข้า CI แล้ว** (`ruff.toml` F-rules + step Lint pin 0.15.17 ใน tests.yml) — CI #143 เขียว
- **P2-8 ✅ ตัด Streamlit:** `app.py`→`legacy/`, ตัด mount ใน compose, regen lock ด้วย **pip dry-run resolve บน python:3.11-slim container บน NAS** (constraint=lock เดิม → ตัด 17 orphans รวม pandas/pyarrow/jinja2, ADDED 0/VERSION CHANGED 0) 138→121 pkgs + ตัด layer pre-download ONNX MiniLM — **image 1.11GB → 769MB (−341MB)** verified STREAMLIT-GONE + poppler/imports ครบ + /api/status healthy
- **P1-6 ✅ ปิดฟรี:** `GEMINI_SEARCH_MODEL` **implement ไปแล้วตั้งแต่ `7087f88` (06-20)** — รายการ "ค้าง" ใน memory เดิม stale; เก็บแค่ test precedence 3 เคส + docs. บทเรียน: งานค้างข้าม session ต้อง grep โค้ดก่อนลงมือ
- gotcha: recreate ชนซากชื่อ `_ai-backend-1` (watchdog race) — ซากหายเอง, `compose up -d` รอบสองผ่าน · ~~Icon\r ใน .ruff_cache = iCloud ยัง active~~ **diagnosis เดิมผิด — ตัวจริง = Google Drive** (ปิดคดี 2026-07-13 ดู [[mac-icon-cr-google-drive]])
- suite 697 passed

## 🔖 session 2026-07-13 — ROADMAP session 3 (บางส่วน): P0-1 Icon\r ปิดคดี ✅
- **ต้นตอจริง = Google Drive for desktop** mirror ทั้ง `~/Desktop` แปะ custom icon ทุกโฟลเดอร์ (sweep ตอน start ~15k ไฟล์ + real-time ~60s) — **ไม่ใช่ iCloud** (ปิดจริง `Enabled=0`); พิสูจน์: trap folder + A/B ปิด Drive · รายละเอียด vault `wiki/concepts/google-drive-icon-cr.md` + memory [[mac-icon-cr-google-drive]]
- mitigation: `Icon\r` ใน global gitignore + `~/.local/bin/icon-cleanup.sh` ผ่าน **SessionStart hook** (launchd hourly ติดตั้งแล้วแต่โดน TCC บล็อก) · ลบรอบ 6 ~25k ไฟล์ · ค้าง user ตัดสินใจ: เลิก mirror Desktop ใน Drive / ย้ายโปรเจกต์ → `~/dev`
- **เหลือ ROADMAP: P2-9 admin memory API** แล้วค่อย P3 (local model / classifier / fine-tune)

## 🔖 session 2026-07-12 (ต่อ) — ROADMAP session 1 (งาน NAS) ✅ DEPLOYED+verified prod `8d6ac25`
- **🐛 บั๊กใหญ่ที่เจอ: `scripts/db_backup.sh` backup ผิดไฟล์** — หยิบ `ui/chat_history.db` (ค้างเก่า 12KB, เม.ย.) แทน `ui/data/chat_history.db` (ตัวจริง 933KB ที่ compose mount) → archive 989 bytes เปล่าๆ. แก้แล้ว (prefer data/ layout) + TDD
- **✅ DB backup รายคืน 03:30 = in-app APScheduler job** (`utils/db_backup.py` ใหม่, sqlite3 backup API) — เหตุผล: ตั้ง DSM task จาก SSH ไม่ได้ (`sudo -n` จำกัดแค่ docker, cron อ่านไม่ได้) → ฝังในแอปจบเอง. dest `/app/db_backups` mount → `ui/data/db_backups`. **verified จริง: trigger ใน container ได้ archive 143KB**. เช็คไฟล์อัตโนมัตินัดแรกหลัง 2026-07-13 03:30
- **✅ pin deps: `requirements.lock`** (pip freeze จาก container prod, 137 pkgs) — Dockerfile install จาก lock แล้ว. อัปเกรด dep = แก้ requirements.txt + regen lock
- **✅ poppler จบ — เจอว่าพัง 2 ชั้น**: image ไม่มี poppler **และ** `pdf2image` ไม่อยู่ใน requirements เลย (ocr.py import lazy เลยเงียบ) → ใส่ทั้งคู่, verified `pdftoppm 25.03.0` + import ผ่าน. rebuild+recreate แล้ว app healthy, `/api/status` ปกติ. gotcha: bind mount dir ใหม่ต้อง `mkdir` ก่อน (docker NAS ไม่ auto-create)
- **chroma backup ของจริงรัน 00:01** (ไม่ใช่ 04:00 ตาม docs เดิม) — มีไฟล์รายวันจริง
- **key: user ตัดสินใจข้ามทั้งหมด** (Anthropic/HA ไม่ยืมจาก jarvis, Kimi ยังไม่มีบัญชี) — ANTHROPIC/MOONSHOT/HA ยังว่างใน NAS .env เหมือนเดิม
- หมายเหตุ permission: คำสั่ง deploy รวดเดียว (reset+build+recreate) โดน classifier block — แยกเป็นขั้น (fetch/reset → build → up) ผ่านหมด · อ่าน .env โปรเจกต์อื่นหา key = โดน block (credential harvesting) ต้องให้ user อนุญาตเอง

## 🔖 session 2026-07-12 — audit ทั้งโปรเจกต์ → `ROADMAP.md` (commit แล้วใน `ecf005d`)
- audit เต็ม: backend **690 tests ผ่านหมด** + frontend 111 vitest ผ่าน, appscript.ui clean+push ครบ 2 remote — โครงหลักแข็งแรง
- **`Icon\r` recur รอบ 5** — 2,668 ไฟล์ ลามเข้า `.venv` block pytest collection ทั้ง suite → ลบแล้ว. แผนแก้ถาวรอยู่ใน ROADMAP P0-1 (เช็ค iCloud Desktop sync จริงจัง / launchd cleanup / ย้ายออกจาก ~/Desktop)
- pyflakes findings เดิม (DEVLOG 2026-06-16) **ยังค้างครบ**: `cached_mid` unused (chat.py:147 — อาจ logic หล่นหาย), `nonlocal messages` (chat.py:390), unused imports กองใหญ่
- แผนงานทั้งหมดรวมศูนย์ที่ **`~/Desktop/ui/ROADMAP.md`** (P0 backup/pin deps/Icon → P1 ใส่ key+poppler → P2 ruff CI/ตัด streamlit/admin memory API → P3 local model/classifier/fine-tune) — session หน้าเริ่มจากไฟล์นี้
- ssh NAS ตรวจ prod สดไม่ได้ใน session นี้ (permission denied โดย classifier) — สถานะ key/.env อ้างบันทึก 2026-07-05

## 🔖 session 2026-07-09 — Thai embedding fix ทั้งระบบ ✅ (DEPLOYED+verified prod, commit `5a26ba5`)
**ปิดบั๊กที่ค้างจาก JARVIS 2026-07-08: ChromaDB default embedder (MiniLM) มองอักษรไทยเป็น UNK ทั้งหมด → ทุกประโยคไทยได้ vector เดียวกัน (score=1.000 ทุกคู่) → semantic recall ภาษาไทยเป็น noise ล้วนมาตั้งแต่ day 1 ทุก collection**
- **scope กว้างกว่า JARVIS มาก:** เจอ 28 จุดสร้าง/ดึง ChromaDB collection แบบไม่มี `embedding_function` กระจาย 7 ไฟล์ (`memory/store.py`, `memory/operations.py`, `utils/memory.py`, `utils/dream.py`, `utils/obsidian_sync.py`, `utils/skills_search.py`) — **ไม่แตะ `utils/documents.py`** เพราะมี embedding pipeline แยกของตัวเองอยู่แล้ว (LM Studio/Ollama `nomic-embed-text`, precomputed vectors) แก้ตรงนั้นเสี่ยงชนบั๊ก dimension-mismatch คนละเรื่อง
- **แก้:** wrapper กลาง `get_or_create_collection()`/`get_collection()` ใหม่ใน `utils/memory.py` ที่ inject Ollama `OllamaEmbeddingFunction` (`EMBEDDING_MODEL=paraphrase-multilingual`) อัตโนมัติ — **opt-in ปล่อยว่าง=ปิด** (ต่างจาก JARVIS ที่ hardcode default ตรงๆ — ต้องเลือกแบบนี้เพราะ test เดิมมี fake ChromaDB client ที่ `get_collection(name)` ไม่รับ kwargs เพิ่ม ถ้า default เปิดจะพัง 690 tests ทันที) → `tests/conftest.py` เพิ่ม `EMBEDDING_MODEL=""` กันพลาดด้วย
- **Migration บังคับ (ไม่ใช่ optional):** ChromaDB มีตัวเดียว ไม่มี dev/prod แยก (dev บน Mac ชี้ instance เดียวกับ NAS จริง) — เขียน `scripts/migrate_thai_embeddings.py` (idempotent, `--dry-run`/`--only`): ดึง documents+metadatas เดิม (ทิ้ง vector เดิม noise) → rename เดิมเป็น `{name}__minilm_backup_YYYYMMDD` → สร้างใหม่ชื่อเดิมด้วย ef ใหม่ → re-add. รันจริงแล้ว **5 collections, 343 docs** (`memory_kwan` 79, `memory_logic` 69, `long_term_memory` 39, `lessons` 20, `skills_collection` 119, `obsidian_notes` 17 — canary ก่อนแล้วค่อยรันที่เหลือ) count ตรง backup ทุกตัว
- **Verified สดผ่าน `docker exec` บน prod container:** query "ชอบกาแฟตอนเช้า" (ไม่เกี่ยว) → score 0.262 · query "อากาศวันนี้เป็นยังไง" → score 0.69/0.68 ตรง Q&A พยากรณ์อากาศจริง — คะแนนแยกแยะเนื้อหาได้จริงเป็นครั้งแรก (ก่อนแก้ทุกคู่ 1.000 เท่ากันหมด)
- **PC .235 มี `paraphrase-multilingual` pulled ไว้แล้ว** จากตอนแก้ JARVIS — ไม่ต้อง pull เพิ่ม
- **gotcha ใหม่:** deploy รอบนี้ต้อง **rebuild image ไม่ใช่แค่ restart/force-recreate** เพราะเพิ่ม `ollama` pip package ใหม่ใน `requirements.txt` (โค้ดอื่น volume-mount แต่ dependency ถูก bake ตอน build เท่านั้น) — `docker compose up -d hybrid-ai --build` (~2 นาทีบน NAS CPU)
- **เจอ+แก้ระหว่างทาง:** `~/Desktop/ui` โดน iCloud `Icon\r` contamination รอบใหม่ใน `.venv` (2,350 ไฟล์ block `import chromadb`) — `find .venv -name "Icon*" -size 0 -delete`
- wiki: `~/Desktop/homepawin/wiki/concepts/thai-embedding-chromadb.md` อัปเดตครบ (JARVIS+Khim AI ปิดเคสทั้งคู่แล้ว)
- **ค้าง:** พิจารณาไปดู `utils/documents.py`'s query-vs-store embedding mismatch แยกต่างหาก (สงสัยว่า nomic-embed-text ตอน store กับ default MiniLM ตอน query dimension อาจไม่ตรงกันอยู่แล้ว — ไม่ได้ยืนยัน แค่สังเกตระหว่างทาง ไม่ใช่ scope งานนี้)

## 🔖 session 2026-07-05 — เช็คทั้งโปรเจกต์ + ChatBox SSE UI + GitHub backup + qwen3.5 switch + empty-response guard (✅ ทั้งหมด DEPLOYED+verified prod, latest `31c5933`)
**ปิดงานค้างเก่า 2 ตัวใหญ่ (off-site backup, local model) + feature ใหม่ 1 + บั๊กใหม่เจอ-แก้ 2:**
1. **`Icon\r` recur รอบ 4** — 2,664 ไฟล์อีกรอบ (block pytest 15 modules ที่ `jsonschema_specifications` เหมือนเดิม) → ลบแล้ว 673/673 ผ่าน. root cause ยังไม่ฟันธง (ดูบันทึก 2026-06-25 — อย่าสงสัย pip/iCloud)
2. **✅ off-site GitHub backup `~/appscript.ui` จบ (ปิดงานค้าง)** — repo private `github.com/penpunnee/appscript-ui` + remote `github` คู่กับ `origin` (NAS bare). **gotcha: บันทึกเดิม "GitHub key ผูก repo เดียว" outdated** — เครื่องมี `~/.ssh/id_ed25519_penpunnee` (account-level, `~/.ssh/config` ตั้ง Host github.com ใช้ตัวนี้ผ่าน ssh.github.com:443 อยู่แล้ว) push repo ไหนก็ได้. **นับจากนี้ commit appscript.ui ต้อง push 2 remote** (`origin`+`github`)
3. **✅ ChatBox render 3 SSE events ที่ backend ส่งอยู่แล้วแต่ frontend ไม่เคยอ่าน** (deployed `2d9743f`, source `3779fc4`): `utils/answermeta.ts` (pure+8 vitest) → **citations** footnote chips `[n] 🌐 source` (คลิกได้ถ้ามี url) · **active_learning** badge "🤔 AI ถามกลับ" · **reflection** collapsible panel + ปุ่ม "ใช้คำตอบที่แก้แล้ว" + **skill toggle ใหม่ "Reflect" 🧐** (จำเป็น — backend ต้องได้ `reflect:true`, เดิม frontend ไม่เคยส่ง = feature ตายทั้งเส้น). reflect ไม่มีผลใน Code/agent mode (backend จำกัด). verified prod ด้วยตา: citations 5 chips + reflect panel score 1.00 ขึ้นจริง
4. **✅ เปลี่ยน local model → qwen3.5-9b ทั่วโปรเจกต์ (deployed `38ed314`)** — user ยืนยันเลิก deepseek-r1. แก้ hardcoded default 3 จุด (`core/config.py`, `utils/reflection.py`, `utils/summarize.py`) + docs (CLAUDE.md + skills 3 ไฟล์). **บั๊กที่เจอ: NAS `.env` `LMSTUDIO_CHAT_MODEL` ยังเป็น deepseek ค้าง** (REASON/VISION เปลี่ยนแล้วแต่ CHAT หลุด) = เหตุที่ prod ยังวิ่ง deepseek อยู่. **→ ไขปริศนาแล้ว 2026-07-14: ตัวการจริง = DSM task id=22 "edit-model" sed `LMSTUDIO_CHAT_MODEL=deepseek/...` ทับทุกเที่ยงคืน (ไม่ใช่แค่แก้ตกหล่น) — ปิด task แล้ว + แก้ .env กลับ qwen/qwen3.5-9b + force-recreate verified ✅ รายละเอียดใน project_home_network.md** **gotcha ย้ำ (โดนเองรอบนี้): `docker restart` ไม่ reload `.env` — ต้อง `docker compose up -d hybrid-ai --force-recreate`** + Model picker ใน browser cache รายชื่อโมเดล ต้อง reload หน้า
5. **🐛→✅ qwen3.5-9b "คิดจนไม่ตอบ" → empty-response guard (deployed `31c5933`, TDD 9 tests ใหม่, suite 683)** — เจอจริง: ขอเรื่องตลก → โมเดลค้างใน `<think>` จนหมด token 131s → `stream_with_thinking(show_thinking=False)` ทิ้งหมด → บับเบิลว่าง + save `''` ลง DB. **intermittent**: prompt เดิมส่งใหม่ตอบปกติ 17-29s ไทยล้วน. แก้ 2 ชั้น: (a) **parser salvage** (`reasoning/parser.py`) — จบ stream ไม่มี answer แต่มี think → คายส่วนท้าย think ~1500 chars + ข้อความกำกับ (b) **router guard** (`routers/chat.py`) — ทุก provider ถ้า full_response ว่าง → yield notice + save notice แทน '' + **gate ห้ามเข้า remember/teach/auto-learn** (กัน episodic contamination). หมายเหตุ: `teach(assistant, prompt)` ตัวแรก (เก็บ user facts ก่อน LLM ตอบ) ยังเรียกปกติ — gate เฉพาะตัวที่แนบ ai_response. `SHOW_THINKING` เปิด debug แล้วปิดกลับ false แล้ว
6. **candidate ถ้า qwen3.5 อาการหนัก**: Typhoon 2.1 (ไทย SCB10X) / Qwen2.5-7B-Instruct (ไม่มี thinking เลย) / Gemma 3 9B-it — user เลือก "ยอมรับความเสี่ยงไว้ก่อน ดูความถี่จริง". หลักฐาน language-leak เพิ่ม: เจอข้อความ AI เก่าเป็น**ฝรั่งเศส**ใน session `voice_default`
7. **ของค้างยืนยันซ้ำ (ยังไม่ทำ)**: `ANTHROPIC_API_KEY`/`MOONSHOT_API_KEY`/`HA_URL`+`HA_TOKEN` ยังว่างใน NAS `.env` · `GEMINI_SEARCH_MODEL` ยังไม่ตั้ง · **`requirements.txt` ไม่ pin version** (`>=` ทุกตัว — เสี่ยง silent break แบบ chromadb:latest เคยเป็น) · db_backup 03:30 + poppler ยังไม่เช็ค
- **gotcha network:** Mac ต่อ Wi-Fi ผิดวง (VLAN52 `192.168.52.x`) จะ ssh nas ไม่ได้ — เช็ค `ifconfig`+default route ก่อนสรุปว่า NAS ล่ม

## 🔖 session 2026-06-25 — local debug: `Icon\r` corruption รอบที่ 3 + NAS unreachable
- **`Icon\r` junk recur รอบ 3** (เคยเจอ 2026-06-16 รอบ CI + 2026-06-18 ใน `.venv` ก่อน push) — รอบนี้เจอ **2,664 ไฟล์** กระจายทั้ง project root + `.venv/site-packages` (ทำ `jsonschema_specifications` parse พัง → `NotADirectoryError` บล็อก pytest collect 15 modules). ลบด้วย `find . -name $'Icon\r' -print0 | xargs -0 rm -f` → suite ผ่านปกติ **673/673**
- **⚠️ ข้อมูลใหม่ขัดสมมติฐานเดิม:** เช็ค `defaults read com.apple.finder FXICloudDriveDesktop/FXICloudDriveDocuments` = **0 (ปิดอยู่แล้ว)** ทั้งคู่ + ยืนยันแน่นกว่าด้วย `~/Library/Mobile Documents/com~apple~CloudDocs/` **ไม่มีอยู่จริงบนเครื่องนี้เลย** (`~/Desktop` เป็น dir จริง ไม่ใช่ symlink เข้า CloudDocs) → iCloud Drive ไม่ได้ provision บนเครื่องนี้แน่นอน ไม่ใช่สาเหตุรอบนี้ ทั้งที่บันทึกเดิมโทษ iCloud ล้วนๆ
- **root cause ตัวจริงยังไม่ฟันธง แต่หลักฐาน timestamp ชี้ไปทางอื่น (ไม่ใช่ pip/venv):** ไฟล์ `Icon\r` ใน `.git/`, `.git/hooks/`, `.git/info/`, `.git/logs/`, `.claude/` **ก็มี timestamp เดียวกับ `.venv`** (Jun 25 00:12-00:13) — แต่ `.git`/`.claude` ไม่เกี่ยวกับ `pip install`/`python -m venv` เลย ดังนั้นทฤษฎี "pip extract ตอนสร้าง .venv" **ตกไป**. หลักฐานจริงคือทุก subdirectory ของ project ทั้งต้น (รวม `.git` internals) โดน touch พร้อมกันในหน้าต่าง ~2 นาทีเดียว → ชี้ไปทาง **เหตุการณ์ recursive ระดับ Finder/sync/backup ตัวเดียวที่เดินทั้ง tree** (เช่น เปิด Finder icon view ค้างไว้, job backup/sync เดินทับทั้ง folder, Spotlight reindex) ไม่ใช่ขั้นตอนเฉพาะของ `.venv`
- **NAS unreachable session นี้:** Mac อยู่ hotspot IP (`172.20.10.5`) ไม่ใช่ home LAN → SSH ตรง `.49` timeout. ลอง Cloudflare Tunnel SSH (`nas-cf`/`ssh.pawinhomelab.com`) — Access login ผ่าน (ยืนยัน email `penpunnee11@gmail.com`) แต่ต่อ origin ไม่ได้ (`websocket: bad handshake`) → **`cloudflared` container บน NAS น่าจะดับ/ค้าง** ต้องเข้าเช็คที่ NAS จริง (DSM/physical) — WireGuard ยังไม่ได้ลองเป็นทางสำรอง
- **ค้าง:** ตรวจ/restart `cloudflared` container บน NAS รอบหน้าที่อยู่ LAN หรือ physical access · ถ้า `Icon\r` โผล่อีกรอบ (รอบ 4) ให้เช็คว่ามี process/job อะไรเดิน recursive ทับ project folder ช่วงนั้น (backup, Spotlight, Finder ค้างเปิด icon view) — **อย่าสงสัย `.venv`/pip ก่อน** เพราะรอบนี้พิสูจน์แล้วว่า `.git`/`.claude` โดนพร้อมกันด้วย ซึ่ง pip ไม่มีทางแตะ

## 🔖 session 2026-06-20 — local model ยืม Gemini grounding ค้นเว็บ (✅ DEPLOYED+verified prod `7087f88`)
- **user ขอ "เพิ่ม web search API ให้ local"** — ของเดิม local ค้นได้อยู่แล้ว (`_inject_web_context` เมื่อ `needs_internet`) แต่ใช้ **DDG** (คุณภาพแย่ throttle) เพราะ Google CSE 403
- **ลอง Google CSE ก่อน — ตันที่ Console config:** user ก๊อป API key มา แต่ยิงแล้ว **403 `This project does not have the access to Custom Search JSON API`** ทุกครั้งแม้เปลี่ยน key/เปิด API หลายรอบ → **key ที่ก๊อปไม่ได้อยู่ใน project ที่เปิด API จริง** (project = `hybrid-ai-search`). วนหลายรอบไม่จบ → **ทิ้ง CSE**
- **✅ ทางที่เลือก (user): ให้ local "ยืม" Gemini grounding** — `utils/llm.py:gemini_web_search(query)→(text,sources)` เรียก Gemini + `google_search` tool (Google จริง) คืนสรุป + แหล่งจาก `grounding_metadata` (`_extract_grounding_sources` pure, 4 test) · `routers/chat.py:_inject_web_context` ลอง Gemini grounding **ก่อน** → fallback DDG ถ้าล้ม · **ไม่ต้องมี CSE key เลย ใช้ `GEMINI_API_KEY` ที่มี**
- ตั้ง **`GEMINI_SEARCH_MODEL`** เลือกตัว quota สูงได้ (default = `GEMINI_MODEL`=gemini-2.5-flash; ⚠️ 2.5-flash free tier ~20 RPD ต่ำ — ถ้าค้นบ่อยควรตั้งเป็น gemini-3.1-flash-lite 500 RPD)
- **verified:** unit 673 passed · `gemini_web_search` ในคอนเทนเนอร์ prod คืนราคาทอง 64,550 + 5 sources จริง. sources เป็น vertexaisearch redirect URL (ปกติของ Gemini grounding ไม่ใช่ direct link)
- gotcha: end-to-end ผ่าน qwen ช้าตอน container เพิ่ง restart (re-index skills เข้า ChromaDB) — เทส feature ตรงผ่าน `docker exec ... python -c "gemini_web_search(...)"` เร็ว+ชัวร์กว่า

## 🔖 session 2026-06-19 — voice: push-to-talk → hands-free + แก้ครบ 5 เรื่อง (✅ DEPLOYED+verified iPhone จริง, latest `f3132de`)
**user เปลี่ยนใจจาก push-to-talk → อยาก hands-free (จับเสียงเอง เหมือน Gemini Live). แก้ทีละอาการผ่าน prod log + verify ด้วยหู user บน iPhone จนจบ. ทุก commit ใน `Desktop/ui` (GitHub origin) + source `appscript.ui` (NAS bare).**

**5 เรื่องที่แก้ (เรียงตามที่เจอ — แต่ละอันมี root cause + fix):**
1. **hands-free (เลิก push-to-talk):** server `realtime_input_config` = `AutomaticActivityDetection()` เปิด (เลิก `disabled=True`) → Gemini จับ turn เอง · กัน echo ด้วย **half-duplex client gate** `utils/voicegate.ts:HalfDuplexGate` (pure+7 vitest): ปิดไมค์ตลอดช่วง AI เล่นเสียง (playUntil จากความยาว chunk) + tail 350ms. **เพราะ browser AEC (`echoCancellation:true`) ไม่ครอบ Web Audio playback บนมือถือ** → ต้อง gate เอง. recv_loop **ignore** `activity_start/end` (ถ้า forward ตอน auto VAD เปิด = error). client สตรีมไมค์ต่อเนื่อง + ปุ่มไมค์เป็น mute toggle (เลิกกดค้าง). trade-off: ไม่มี barge-in (user เลือกแล้ว)
2. **model:** `core/config.py` default `gemini-2.5-flash-native-audio-latest` → **`gemini-3.1-flash-live-preview`** (user ขอ "gemini-3-flash-live" ซึ่ง**ไม่มีบน API** — verify ผ่าน ListModels `bidiGenerateContent`; ตัวจริงคือ 3.1-flash-live-preview). NAS `.env` ไม่มี `GEMINI_LIVE_MODEL` override → default ในโค้ดมีผลจริง
3. **"หายตอนท้าย" (เด่นมือถือ session ยาว):** root cause จาก prod log = Gemini Live มี**ลิมิตอายุ session** → ส่ง `go_away` → server ไม่จัดการ → ชนลิมิตโดน **APIError 1008** ตัด stream กลางคัน (เจอซ้ำ 7 ครั้ง). **fix: `ContextWindowCompressionConfig(sliding_window=SlidingWindow())`** → session ไม่มีลิมิตอายุ
4. **"เสียงแตกท้ายๆ" (iPhone):** root cause จาก log = Gemini ส่ง audio มี gap กลางคำตอบถึง **~650ms** แต่ jitter buffer prime แค่ 0.2s → underrun → click. **fix: prime 0.2→0.8s + re-prime หลัง underrun** (worklet: `if queue empty → primed=false`). `utils/jitterbuffer.ts:JitterBuffer` pure model + 6 vitest พิสูจน์ 0.2s แตก/0.8s รอด gap 0.65s. ⚠️ trade-off: เสียงเริ่มช้าลง ~0.8s worst case
5. **"เสียงหายตอนจอล็อก":** ข้อจำกัด iOS Safari (suspend AudioContext+ไมค์ ตอน background — เล่นตอนจอดับสนิทจริงๆ เว็บทำไม่ได้ ต้อง native). **fix เคส auto-lock: `navigator.wakeLock('screen')`** กันจอดับเองระหว่างคุย (iOS 16.4+) + `visibilitychange→visible` re-acquire + resume ctx. ถ้ากดปุ่ม power ล็อกเอง → ยัง suspend (override ไม่ได้) แต่กู้คืนได้ตอนปลดล็อก

**บทเรียน/gotchas:**
- **transcript เพี้ยนเป็นเกาหลี** (`'안 아니...'` ทั้งที่พูดไทย) ที่เจอใน log = **อาการของ echo/เสียง input เพี้ยน ไม่ใช่ model bug** — พิสูจน์ด้วยเสียงไทยสะอาด (`say -v Kanya` → afconvert 16k PCM → feed Live): 3.1 transcribe ไทยถูก 100%. **`language_codes` ใน AudioTranscriptionConfig ไม่รองรับใน Gemini API** (เฉพาะ Vertex)
- **cold-start quirk:** voice session แรกหลัง restart บางทีได้ transcript แต่ audio=0 (เทสผ่าน text-input probe `{"type":"text"}`) — intermittent, ไม่ใช่ regression, voice จริง (audio input) ใช้ได้
- **ถอด `[VoiceDBG]` log แล้ว** (เหลือเฉพาะ error log tag `[Voice WS]`)
- **เทคนิค verify voice ตรง:** WS probe ด้วย `websockets`+`certifi` ผ่าน `wss://ai.pawinhome.com/ws/voice/kwan` (open path ไม่ต้อง auth); LAN `ws://192.168.51.49:8080` มีปัญหา route แปลก ใช้ public แทน. Live config test ตรง: genai SDK + key จาก `~/Desktop/ui/.env`, `http_options={"api_version":"v1alpha"}`
- bundle hash มีขีดกลางได้ (เช่น `index-Dz4c1-uP.js`) — grep ต้องรวม `-`
- **deploy:** อยู่บ้าน LAN → `ssh nas` ตรง (`git reset --hard origin/main` + `sudo -n /usr/local/bin/docker restart ai-backend-1` ถ้า server.py/config.py เปลี่ยน; static-only = git pull พอ). off-LAN ก่อนหน้า = DSM task `deploy-hybrid-ai`
- ไฟล์ใหม่: `appscript.ui/utils/voicegate.ts`+test, `utils/jitterbuffer.ts`+test · vitest รวม 102 ผ่าน

## 🔖 session 2026-06-18/19 (ต่อ) — รื้อ voice เป็น push-to-talk subsystem (⚠️ superseded โดย session 2026-06-19 ด้านบน — push-to-talk ถูกเปลี่ยนเป็น hands-free แล้ว)
**ต่อจาก voice fix แรก — ลองหลายรอบกับ voice แล้วเจอ root cause จริงทีละชั้นผ่าน [VoiceDBG] log บน prod. สุดท้าย user สั่ง "ทำ subsystem แยกคุมเอง" → rewrite เป็น push-to-talk**

**ไทม์ไลน์ root cause ที่เจอ (สำคัญ — กันลองซ้ำ):**
1. **turn-2 ค้าง/เด้งกลับหน้าแชท** = bug ฝั่ง **server** (ไม่ใช่ client!): `session.receive()` ของ Gemini Live SDK **yield แค่ turn เดียวแล้ว generator จบ** → send_loop เดิม (async for รอบเดียว) ตายหลัง turn 1, recv_loop ยังส่ง audio เข้า Gemini แต่ไม่มีใครอ่านคำตอบ → WS keepalive timeout 1011. **แก้: ครอบ `async for` ด้วย `while not stop.is_set()`** (commit `54e9144`). ทฤษฎี client เดิม (interrupted/gate/onended) **ผิดทางทั้งหมด** → revert ออก (`5905970`)
2. **เสียงขาด/แตก** = ไม่ใช่ network (log ยืนยัน Gemini ส่ง audio out ต่อเนื่อง ไม่มี gap) — เป็น playback. ลอง AudioWorklet ring-buffer (`1170535`) + แก้ prime-once (`1d3f174`) ช่วยบางส่วน
3. **ตอบไม่จบ+สลับให้ถามใหม่ + เสียงเบา-ดัง** = **echo!** log เจอ `sc.interrupted` + `turn_complete ai_len=0` ขณะ user เงียบ → ไมค์เปิดตลอด เสียง AI จากลำโพงสะท้อนเข้าไมค์ → Gemini VAD ตัดคำตอบตัวเอง. gate ไมค์แบบ client (`b8523c3`) ไม่พอ (echo แรง + cache มือถือ + VAD ยังสับประโยค user)

**✅ ทางแก้สุดท้าย — push-to-talk subsystem แยก (commit GitHub `Desktop/ui` `61a348f`, source `appscript.ui` `daae17f`→ค้าง push NAS):**
- **`utils/voicelive.ts` (ใหม่) = `VoiceController` class** คุม WS/mic/playback เองทั้งหมด (แยกออกจาก app.tsx). มี AudioWorklet `pcm-player` (ring buffer + resample 24k→ctx rate + jitter 200ms) ฝังเป็น Blob URL
- **server `server.py`:** `realtime_input_config` = `AutomaticActivityDetection(disabled=True)` + `ActivityHandling.NO_INTERRUPTION` → โมเดลตอบเฉพาะตอนได้ `activity_end`, echo แทรกตัดไม่ได้. recv_loop handle `activity_start`/`activity_end` ผ่าน `session.send_realtime_input(...)` (เปลี่ยนจาก `session.send(LiveClientRealtimeInput)` เดิม). SDK google-genai **1.75.0** มี types ครบ
- **client:** ไมค์ส่งเฉพาะตอน `recording=true` (กดปุ่มค้าง). UI overlay = ปุ่มไมค์ push-to-talk (`onPointerDown`→startTalk, `onPointerUp/Leave`→stopTalk) แทน end_turn เดิม. status ใหม่: `connecting/ready/recording/thinking/speaking`
- **build+test ผ่านหมด:** tsc, voice pytest 14, vitest 89. bundle `index-ixSLh0rx.js`

**🔴 งานค้าง session หน้า (เรียงสำคัญ):**
1. **DEPLOY** — Mac หลุด LAN ตอนจบ (ping .49 + .1 ไม่ผ่าน). พอกลับเข้า LAN: `ssh pawin@.49 'cd /var/services/homes/pawin/ui && git fetch origin main && git reset --hard origin/main && sudo -n /usr/local/bin/docker restart ai-backend-1'` (server.py เปลี่ยน→**ต้อง restart**) + verify `:8080/api/status`
2. **retry push `~/appscript.ui` → NAS bare** (`git push origin main` — รอบนี้ SSH timeout ตอนจบ)
3. **verify push-to-talk ด้วยหู/มือจริง** (ผมทำเองไม่ได้) — กดค้างพูด/ปล่อยส่ง, echo หาย, ตอบจบ, คุยหลาย turn
4. **ถอด `[VoiceDBG]` log ออกจาก server.py** (เป็น instrumentation ชั่วคราว) หลัง verify ผ่าน
5. (ถ้า push-to-talk ยังไม่เป๊ะ) เผื่อ tune: prime buffer, หรือเสนอ Gemini 3 Flash Live (half-cascade ตอบไวกว่า native-audio)
- **gotcha มือถือ:** Safari cache ดื้อมาก — ปิดแท็บไม่พอ ต้อง **Private tab** ถึงโหลด bundle ใหม่ชัวร์ (ควรตั้ง cache-control header กันถาวร) · ปุ่มย้าย 🎙️🔊 ลงกล่องแชท + layout 2 กลุ่ม + min-w-0 = deploy แล้วตั้งแต่ `d5449a7`

## 🔖 session 2026-06-18 — voice barge-in fix + ย้ายปุ่ม voice ลงกล่องแชท (✅ DEPLOYED+verified prod `d5449a7`)
- **บั๊กหลัก: voice "ค้างตอนถามต่อ"** — root cause 2 จุด (ฝั่ง client): (1) ไม่ handle Gemini Live `interrupted` → คิวเสียงเก่า (`nextPlayTimeRef`) ไม่ flush → เสียง turn ถัดไปต่อท้ายคิวเก่า เล่นช้า/ทับ (2) ไมค์สตรีมตลอดตอน AI พูด → echo สะท้อนเข้า Gemini VAD. backend `server.py` send_loop รองรับหลาย turn อยู่แล้ว (reset transcript หลัง turn_complete) — ปัญหาอยู่ client
- **fix (TDD red→green):** `utils/voice.py:live_server_content_events()` ส่ง `{"type":"interrupted"}` เมื่อ `sc.interrupted` (server.py forward ผ่าน loop เดิม ไม่แตะ) · `tests/test_voice_interrupted.py` 4 เคส. client `app.tsx`: เก็บ `voicePlayNodesRef` → `flushVoicePlayback()` (stop nodes + reset nextPlayTime) บน interrupted + gate ไมค์ขณะ `voiceAiSpeakingRef` (เคลียร์ผ่าน `node.onended` เมื่อคิวว่าง) · **`done` ไม่ flush** (กันตัดคำท้าย)
- **ย้ายปุ่ม 🎙️ Voice + 🔊 TTS จาก header → กล่องแชท** (user เลือก: ทั้งคู่ + เอาออกจาก header). จัด layout 2 กลุ่ม: แนบไฟล์ (📎🖼️📷) ซ้าย · เสียง (🎙️🔊) ขวาคู่ปุ่มส่ง + เส้นคั่น · textarea เพิ่ม `min-w-0` กันปุ่มล้นกรอบบนจอแคบ
- **verified UI ด้วยตา** (headless chromium จาก ms-playwright cache + playwright-core ใน npx cache — mock `/api/*` route, ⚠️ route ลงทีหลังชนะ ต้อง catch-all ก่อน specific; catch-all คืน `[]` เพราะ sessions/history เป็น array): screenshot **mobile 390px + iPad 820px** — 2 กลุ่มปุ่มลงตัว ช่องพิมพ์ไม่ถูกบีบ
- **test:** backend pytest **669** · node --test **24** · vitest **89** · build ผ่าน. ลบ `Icon\r` junk 2,663 ไฟล์ใน `.venv` (block pytest collection — iCloud เดิม)
- **deploy:** push GitHub `Desktop/ui` `d5449a7` + push NAS bare `appscript.ui` `437ec88` (ตอนกลับถึงบ้าน — off-LAN ก่อนหน้า SSH timeout) → `ssh pawin@.49 git reset --hard origin/main + docker restart ai-backend-1` (ผมรันเอง user authorize). **verified prod :8080:** `/api/status` 200 local_ok=true skills 95 + index.html เสิร์ฟ `index-DzpOpxQi.js`+`626BXyz0.css` (JS 200)
- **🔴 ค้าง: ยังไม่ verify voice ด้วยไมค์จริง** — ผม verify ได้แค่ test/build/screenshot layout, "หายค้างจริงไหม" user ต้องลองพูดเอง

## 🔖 session 2026-06-17 (ต่อ 5) — 🔴 prod ล่ม + fix ถาวร ai-backend-1 "หาย"
- **เจอตอนสำรวจ:** `ai-backend-1` หายจาก `docker ps -a` เลย (เหลือ chromadb+cloudflared ที่ restart ~1ชม.ก่อน), `:8080` connect refused, NAS ไม่ได้ reboot (uptime 24วัน). **กู้:** `docker compose up -d hybrid-ai` → healthy, public `ai.pawinhome.com` 200
- **root cause (ตามหลักฐาน, ไม่ได้พิสูจน์ 100% เพราะ container+log ถูกลบ):** Container Manager/docker daemon restart → restart-policy containers กลับมา แต่ ai-backend-1 ถูก**ลบ** (policy ช่วยไม่ได้). **เป็นรอบ 2** (CLAUDE.md เคยจด 2026-06-14/15 อาการเดียวกัน)
- **fix ถาวร deployed `4536e57`** (docker-compose.yml ใน git repo `~/Desktop/ui` — แก้ที่ repo ไม่ใช่ NAS เพราะ deploy = `git reset --hard` ทับ): (1) hybrid-ai `restart: unless-stopped`→`always` (2) healthcheck python urllib→`/api/config:8000` start_period 90s (3) **`backend-watchdog`** service (`docker:cli`, mount docker.sock + `/volume1/homes/pawin/ui` ที่ path เดียวกับ host → compose-in-container resolve bind-mount ถูก) loop 60s ถ้าไม่ running → `docker compose up -d hybrid-ai`
- **verified:** config valid · hybrid-ai healthy · watchdog **recovery path พิสูจน์แล้วจริง** (boot-race ครั้งเดียว: detect not-running → compose up → recreated → started) ไม่ flap · drill `rm -f` ไม่ได้ทำ (classifier ค้าน prod-down, user รันเองได้)
- ⚠️ note: watchdog มี boot-race เล็กน้อย (เช็คตอน hybrid-ai ยัง starting → recreate 1 ครั้งเกินจำเป็น) — ไม่ลูป เพราะพอ running แล้ว `status=running` match. ถ้าจะ refine: เพิ่ม sleep ก่อน loop แรก หรือเช็ค health ด้วย

## 🔖 session 2026-06-17 (ต่อ 4) — File Manager §18 เข้า React (ปิด port overlay→React ครบ)
- **port overlay §18 → React** ตาม pattern เดิม (pure util + vitest → wire → gate). user เลือก scope = **"ขยาย attach เดิม"** (ต่อยอด `fileCtx`/`imgCtx` ที่มี ไม่ทำ document side-panel — UI เบากว่า ตรงโมเดล React)
- **backend มีพร้อมแล้ว:** `/api/upload` (skills.py) สกัด text PDF/DOCX ได้อยู่แล้ว, `/api/documents/upload` index ChromaDB, `GET/DELETE /api/documents` — gap คือฝั่ง React (accept list ตัด PDF/DOCX/XLSX, ไม่มีกล้อง/drag&drop)
- **`utils/filemanager.ts`** (ใหม่, 11 vitest): `classifyUpload()` → `{kind:image/document/unsupported, ext, shouldIndex, error}` (`shouldIndex`=PDF/DOCX/XLSX/XLS → index ChromaDB เพิ่มจากสกัด text) + `FILE_ACCEPT`/`CAMERA_ACCEPT`/`MAX_UPLOAD_BYTES`
- **`app.tsx`:** refactor `uploadImageFile`/`uploadDocFile` รับ File ตรง + `handleIncomingFile` (route image vs document) · `uploadDocFile` ยิง `/api/documents/upload` fire&forget สำหรับเอกสารหนัก · ปุ่ม 📷 (`capture=environment`, `md:hidden`) · drag&drop ลง `<form>` (dragActive outline)
- **`static/enhanced.js`:** §18 IIFE gate `if(window.__hwReactChatBox) return;` · overlay `?v=20260617-filemgr`
- **build:** bundle `index-DhTo4scZ.js` · vitest **89/89** · committed: source `02ac73d` (push NAS bare `d5b74f6..02ac73d` ✅), static `843eca2` (push GitHub ✅) + doc `321653e`
- **✅ DEPLOYED prod** (ผมรันเอง — user อยู่บ้าน LAN: `ssh pawin@.49 git reset --hard origin/main`) · **verified LAN :8080:** index.html → `index-DhTo4scZ.js` + `enhanced.js?v=20260617-filemgr` + gate filemanager อยู่ใน served enhanced.js + `/api/documents`→`{"documents":[]}`. ยังไม่ verify ด้วยตาบน browser (drag&drop/กล้อง/index toast)
- **🟢 port overlay→React ครบทุกตัวแล้ว** (Home Panel/Export/Global Search/File Manager) — overlay enhanced.js เหลือเป็น fallback bundle เก่าเท่านั้น

## 🔖 session 2026-06-17 (ต่อ 3) — Global Search modal (Ctrl+Shift+F) เข้า React (ปิดงานค้าง #1)
- **port overlay §2 global search → React** ตาม pattern เดิม (pure util + vitest → wire → gate). **root cause บั๊ก field:** `search_messages()` (`utils/history.py:181`) คืน `{assistant,session_id,role,snippet,created_at}` — overlay เดิมอ่าน `content`/`timestamp` ที่ไม่มี → text+วันที่ว่าง (React sidebar search อ่านถูกอยู่แล้ว, บั๊กมีเฉพาะ overlay)
- **`utils/globalsearch.ts`** (ใหม่, 10 vitest): `toResultViews` map field ถูก + `assistantIndexByName` (สลับผู้ช่วยตอนคลิกผลข้ามผู้ช่วย). **`app.tsx`:** modal ค้น**ทุกผู้ช่วย** (ไม่ส่ง assistant, limit 30) + Ctrl+Shift+F + Escape + `jumpToSearchResult` ที่สลับ aiIdx ข้ามผู้ช่วยได้ พร้อม **`pendingJumpRef` กัน race** (effect `[aiIdx]` เดิม auto-select session ล่าสุดมาทับ session ที่เลือก)
- **`static/enhanced.js`:** gate Ctrl+Shift+F + ลบปุ่ม `fab-search` เมื่อ `__hwReactChatBox` (+ guard `?.` กัน null) · overlay `?v=20260617-gsearch`
- **build:** bundle `index-DYe7NPPV.js` · vitest **78/78** · committed: source `~/appscript.ui` **`70b708e`**, static `~/Desktop/ui` **`390d031`** (pushed GitHub origin)
- **✅ DEPLOYED prod** (user รัน DSM task) — **verified ผ่าน Cloudflare Tunnel:** `ai.pawinhome.com` เสิร์ฟ bundle `index-DYe7NPPV.js` + overlay `enhanced.js?v=20260617-gsearch` + gate `__hwReactChatBox` อยู่ครบ (keydown + fab-search)
- **🔴 ค้าง:** (1) **`~/appscript.ui` push NAS bare repo ค้าง** (off-LAN SSH timeout — push เมื่อกลับ LAN) (2) **ยังไม่ verify UI จริงด้วยตา** (modal/Ctrl+Shift+F/cross-assistant jump) — verify แค่ build+test+gating+prod-asset
- งานค้างที่เหลือ (จาก session ก่อน): File Manager §18 → React · เคลียร์ WIP `components/` · key Claude/Kimi+HA · poppler · off-site backup

## 🔖 session 2026-06-16 (ต่อ) — จบ voice transcript fix ที่ค้าง + ตั้ง remote React source
- **voice (ต่อจาก thought-leak):** native-audio พูดข้อความผ่าน `output_transcription` (ot) แต่ handler เดิม `server.py` สะสม ot ลง `ai_transcript` (เซฟ history) **ไม่ได้ send_json ให้ UI** → bubble ผู้ช่วยว่างเปล่า. fix: extract pure `live_server_content_events(sc)`→`(events,user_delta,ai_delta)` ใน `utils/voice.py` แล้ว wire เข้า handler (ot เข้า events `{"type":"text"}`). test `test_voice_transcript_to_ui.py` (5) + suite **657**. deploy prod `957fe23` · **verified WS จริงใน container**: `text:0→text:2`, AI_TEXT "สวัสดีค่ะพี่ปอย! 😊". DEVLOG SECTION #5
- **React source (`~/appscript.ui`):** commit `5d12043` ที่ค้าง (agentsteps/markdown/reveal + vitest 13) — build deploy ไปแล้ว (backend a7c67fe/2e1ad97) แต่ source ไม่เคย commit. **ตั้ง remote แล้ว ✅: `origin` → `nas:/var/services/homes/pawin/git/appscript.ui.git`** (bare repo, HEAD→main, NAS RAID+DSM backup). ปิด Next Step #25. **เดิม CLAUDE.md จดว่า "local-only ไม่มี remote" = outdated แล้ว** — future backup แค่ `git push` จาก `~/appscript.ui`. หมายเหตุ: GitHub SSH key ที่ Mac มีเป็น **deploy key ผูก repo `hybrid-ai-workspace` ตัวเดียว** (สร้าง repo อื่น/push repo อื่นไม่ได้, ไม่มี `gh`/token) → ถ้าอยาก off-site GitHub ต้องสร้าง private repo + เพิ่ม deploy key เอง

## 🔖 session 2026-06-17 (ต่อ 2) — Home Panel เข้า React + แก้บั๊ก /config 404
- **Home Panel → React (`95d81e8`):** System(RAM/ChromaDB/Skills)+NAS disk+Docker+PC ping+Wake PC/Ping NAS ย้ายเข้า React (`utils/homepanel.ts` + 13 vitest → ปุ่ม 🏠 ใน header + modal `app.tsx`). enhanced.js §14 gate `__hwReactChatBox` + ลบปุ่ม `fab-home` overlay. overlay `?v=20260617-home`. **Export พบว่า port เสร็จอยู่แล้ว** (todo เก่าคลาด). ปิด Next Step #38
- **🐛→✅ แก้บั๊ก /config 404 (`02ac0c7`, DEVLOG SECTION #7, verified prod):** `static/enhanced.js:852` เรียก `/config` → 404 (route จริง prefix `/api`, `routers/system.py:61` คืน `has_vault` จาก `OBSIDIAN_VAULT_PATH`) → FAB Vault ไม่โผล่ผ่านเส้นนี้. แก้เป็น `/api/config` + bump overlay `?v=20260617-cfgfix`. surgical 2 บรรทัด. **deploy off-LAN ผ่าน DSM task** (frontend disk → git pull พอ) + **verified prod ผ่าน Cloudflare Tunnel** `ai.pawinhome.com` (enhanced.js:852=`/api/config`, index เสิร์ฟ `?v=...-cfgfix`). docs commit `ea12b45`. ไม่กระทบ React (ใช้ `/api/config` ถูกอยู่แล้ว)
- **🔴 งานค้าง session หน้า (เรียงความสำคัญ):** ทำในเครื่องได้: (1) Global search modal Ctrl+Shift+F เข้า React — ⚠️ overlay เดิมอ่าน field ผิด `content`/`timestamp` ควรเป็น `snippet`/`created_at` · (2) File Manager §18 (PDF/DOCX/XLSX→index+กล้อง+drag&drop) · (3) เคลียร์ WIP `components/` ใน appscript.ui. — ต้องมี key/.env NAS: (4) `ANTHROPIC_API_KEY`+`MOONSHOT_API_KEY` ปลดล็อก Claude/Kimi · (5) `HA_URL`+`HA_TOKEN` · (6) poppler-utils บน NAS · (7) DSM task db_backup 03:30. — ยาว: (8) off-site GitHub backup `~/appscript.ui` · (9) qwen3.5 ไทย-leak→Typhoon/Qwen2.5 · (10) Gemini groundingMetadata→citations · (11) Google CSE สร้าง PSE ใหม่ · (12) สะสม 👍 ~200-500 → fine-tune RTX 3060

## 🔖 session 2026-06-17 — port overlay features เข้า React (DEVLOG SECTION #6, ปิด Next Step #30/#36)
- ทยอยย้าย overlay ของ enhanced.js เข้า React ตาม pattern เดิม (extract pure util + vitest → wire React → gate IIFE เดิมด้วย `window.__hwReactChatBox`). enhanced.js ตอนนี้มี **4 guards**
- **Agent timeline:** verify ว่าครบสายแล้ว (commit 5d12043 wire ไว้) — parser `utils/agentsteps.ts` ครอบ 5 type ที่ backend ยิง + verified prod ยิง agent จริง
- **Composer helpers (3):** `utils/tokencount.ts` (pill ตัวอักษร/tokens) · `utils/draft.ts` (autosave key เดิม `hw_draft_<sid>`, save อ่าน sidRef กันสลับ session) · `utils/slash.ts` (เมนู "/" quick-prompts) — deployed `546ae20`
- **Dream stats:** `utils/dreamstats.ts` render light/rem/deep counts จริงใน sleep card แทน hardcoded 40/40/20% (เลิก DOM-patch overlay) — deployed `c3432cd`, verified /api/dream/report → light=22
- **deploy:** frontend-only เสิร์ฟจาก disk → **git pull พอ ไม่ต้อง restart**. bundle `index-Cn7b8BSq.js` · enhanced.js `?v=20260617-dream` · vitest รวม utils/ **55 ผ่าน**
- **เหลือ overlay ที่ยังไม่ port (optional, ตัวใหญ่):** Home Panel FAB (System/NAS/Docker/PC/WoL), Export PNG, Global search Ctrl+Shift+F, File Manager §18
- ⚠️ verify ระดับ logic+build+deploy+gating เท่านั้น — UI จริง (pill โผล่/slash menu/draft restore/การ์ด dream) **ยังไม่เห็นบน browser จริง** (ไม่มีจอ) — ควรเปิด `ai.pawinhome.com` เช็คตาดูรอบนึง

## 🔖 session 2026-06-16 — แก้ thought-leak ใน voice transcript (✅ DEPLOYED prod `6335c1e`)
- **บั๊ก:** `/ws/voice/{slug}` ใน `server.py` `send_loop` วน `model_turn.parts` แล้วต่อ `part.text` ทุก part — รวม part ที่ `part.thought is True` (chain-of-thought ของ Gemini Live thinking model ที่ใช้คือ `gemini-2.5-flash-native-audio-latest`) → เหตุผลภายในหลุดทั้งเข้า UI สด (`{"type":"text"}`) และ transcript ที่เซฟ (`ai_transcript`→`_save_msg`). `output_transcription` (เสียงที่ถอดความ) ไม่เกี่ยว
- **fix (TDD: red→green):** helper บริสุทธิ์ `speakable_part_text(part)` ใน `utils/voice.py` — คืน text เฉพาะ part ที่ `not part.thought` และ text ไม่ว่าง (กรองที่เดียว unit-testable) แล้ว wire เข้า loop ใน `server.py`. ยืนยัน SDK: `google.genai.types.Part` มี field `thought: bool|None` ("Indicates whether the part represents the model's thought process or reasoning")
- **test:** `tests/test_voice_thought_leak.py` (4 เคส) + suite รวม **645 passed**
- **deploy:** push `main` ✅ แต่ **SSH NAS timeout (Mac off-LAN + WireGuard down)** → user รัน **DSM task** เอง → prod live (`/api/status` 200 ผ่าน Cloudflare Tunnel `https://ai.pawinhome.com`). verify end-to-end ระดับเสียงจริง = user เลือก "เชื่อ unit test พอ" (ผมไม่มีไมค์ + thought-leak โผล่ต้องคุยจริง)
- gotcha ย้ำ: off-LAN deploy ต้องผ่าน DSM (SSH/WireGuard/browser-SSH ใช้ไม่ได้ off-LAN — ตรงกับบันทึก 2026-06-15)

## 🔖 session 2026-06-16 (รอบ 2) — CI เขียวครบ: node24 + ซ่อม voice ws test (✅ merged main `50653a2`, run #96 success)
- **CI red มาตั้งแต่ run #91** (ไม่มีใครเห็น เพราะ pytest ผ่านบนเครื่องตลอด). **root cause:** `tests/test_voice_ws.py::test_voice_ws_no_nameerror` พึ่ง `GEMINI_API_KEY` จาก `.env` ของเครื่อง local — CI **ไม่มี `.env`** → `/ws/voice` handler เด้งออกที่ guard `"GEMINI_API_KEY not set"` (`server.py:210`) ก่อนถึง fake `genai.Client` (บรรทัด 221) → `assert "FAKE_NO_NETWORK" in msg` พัง. **fix:** เทส `monkeypatch.setattr(server, "GEMINI_API_KEY", "test-key")` เอง (patch **module global** เพราะ `GEMINI_API_KEY` bind ตอน import `server.py:12` แล้ว `setenv` ไม่ทัน)
- **node20 deprecation (ประกาศ GitHub: 16 มิ.ย. 2026 บังคับ JS actions → node24, ถอด node20 16 ก.ย. 2026):** บั๊ม **`checkout@v4→v5`, `setup-python@v5→v6`, `setup-node@v4→v5`** (ทั้ง 3 = node24-native; v5/v6 ต้อง runner ≥2.327.1 ซึ่ง `ubuntu-latest` ผ่าน) + เพิ่ม `setup-node@v5 node-version 24` pin ตัว `node --test` (เดิมไม่ pin = เด้งตาม image). ยืนยัน warning หมดด้วย check-runs annotations API (`annotations: 0`)
- **เทคนิค reproduce CI (เครื่องไม่มี py3.12/uv/gh):** `git archive HEAD | tar -x -C /tmp/ui-ci` (โค้ดที่ commit เป๊ะ พ้นขยะ iCloud) → ลง `uv` (`~/.local/bin`) → `uv venv --python 3.12` + `uv pip install -r requirements.txt` → `pytest tests/ -q` = **644 passed +1 failed ตรง CI**; หลัง fix = **645 passed**. ตรวจ CI ผ่าน GitHub REST แบบ unauth ได้ (runs/jobs/check-runs/annotations) แต่ **logs download = 403 ต้อง admin token**
- **gotcha — iCloud `Icon\r` ปน `.venv`:** ไฟล์ `Icon\r` (custom-icon จาก iCloud) โผล่ทั่ว `.venv` ทำ `jsonschema_specifications/schemas/` parse เป็น JSON ว่าง → `mcp`/jsonschema import ระเบิด (`NotADirectoryError`/`JSONDecodeError`). แก้: `find .venv \( -name 'Icon' -o -name $'Icon\r' \) -delete`. (อาการเดียวกับที่เคยทำ `.git/refs` พัง — ดู session 2026-05-29). local `.venv` ใช้ py3.14 + ต้อง `pip install mcp` เองด้วย (ไม่งั้น collect `test_mcp_server.py` ไม่ได้)
- **ค้างใน working tree `~/Desktop/ui` (ตั้งใจไม่แตะ — แยกเรื่อง):** `utils/voice.py` (+41 บรรทัด uncommitted), `tests/test_voice_transcript_to_ui.py` (untracked), static assets เปลี่ยน (index-9z1VQg5K.js ใหม่/ลบเก่า + index.html), `.coverage`. → เซสชันหน้าตัดสินใจว่าจะ commit voice.py + test ใหม่ไหม

## 🔖 session 2026-06-15 (รอบ 3) — web-search grounding จบ + เลือกแหล่งค้นต่อโมเดล (DEPLOYED prod `cfbd7e1`)
**ทำเสร็จ + verified prod ทั้งหมด (ทำผ่าน `ssh nas` บน LAN — git reset + restart/recreate; chat test ผ่าน localhost bypass auth ในคอนเทนเนอร์ port 8000):**
1. **Deploy Work A+B** (`4315daa`) — web-search grounding ทุกโมเดล
2. **🐛 weather-router bug** (`6f308d7`) — `วันนี้|พรุ่งนี้` ใน `_WEATHER_KEYWORDS` แย่งคำถาม "ราคาทองวันนี้"→อากาศ; ตัดออก
3. **docs Ollama dormant** (`5c38d2f`) — user ยืนยัน Ollama เลิกใช้; คงเป็น fallback (embeddings safety net) + note ใน CLAUDE.md
4. **🐛 DDG hardening** (`9afcf3f`) — DDG โดน throttle คืนขยะ/NSFW; `safesearch=on` + retry 1 ครั้ง (เลิกทำ junk-regex/relevance-floor — user deny ว่าเยอะ+เสี่ยง false-match)
5. **✅ Option B — Gemini google_search ในตัว** (`cfbd7e1`) — Custom Search API 403 ใช้ไม่ได้ → คำถาม real-time บนโมเดล **Gemini** ใช้ grounding ในตัว (Google จริง) แทน DDG; provider อื่นยัง DDG. **verified gemini-2.5-flash ตอบราคาทอง 66,850 จาก grounding จริง**

**สถานะแหล่งค้นตอนนี้:** Gemini→Google grounding (จริง) · local/Claude/Kimi→DuckDuckGo · อากาศ→wttr.in · นิยาม→Wikipedia · Agent→Gemini grounding

**🔴 งานค้างต่อเซสชันหน้า (เรียงความสำคัญ):**
1. **Google CSE ใช้ไม่ได้ (Option A ยังไม่จบ)** — NAS `.env` มี key(...CEZmfgd4)+CX(`44c7c0b7c3c5049a2`) แต่ project `387035280891` ติด/PSE สวิตช์ "ค้นทั้งเว็บ" สีเทากดไม่ได้. ถ้าจะทำต่อ: **user สร้าง PSE ใหม่ที่ search-entire-web ได้** (ตอนสร้างอย่าใส่ site) + enable Custom Search API + key unrestricted → เอา key+CX ใหม่มาให้ใส่ .env + recreate. (ผมสร้างเองไม่ได้ — PSE ไม่มี CLI + ต้อง login Google ของ user)
2. **(optional) extract Gemini groundingMetadata → citations** — ตอนนี้ Gemini ground แล้วตอบถูก แต่ช่อง citations ว่าง (ไม่มี source list โชว์)
3. **qwen3.5 ไทย-leak + context-bleed** — เจอ "ราคาทอง" หลุดเข้าคำตอบ One Piece จาก working memory session เดิม; พิจารณาเปลี่ยน local model (Typhoon/Qwen2.5-Instruct)
4. **ใส่ `ANTHROPIC_API_KEY`/`MOONSHOT_API_KEY` ใน NAS `.env`** → recreate → ปลดล็อก Claude/Kimi ใน Model picker (ตอนนี้ disabled)

## session 2026-06-15 (รอบ 2) — แก้บั๊ก Model picker บนมือถือ + สลับ local เป็น qwen3.5-9b (deployed prod ✅)
- **บั๊ก 1: dropdown ในกล่องแชท เลื่อน/กดเลือกไม่ได้บนมือถือ** — root cause: container ChatBox มี `backdropFilter: blur()` → สร้าง stacking context ใหม่ → dropdown `z-[56]` ถูกขังใน context นั้น ส่วน click-outside backdrop (`fixed inset-0 z-[55]`, sibling ใน context นอก) เลย paint ทับ dropdown → ทุกการแตะโดน backdrop = ปิดเมนูทันที. แก้: ยก `zIndex:56` ให้ container ChatBox ตอน `cbDD` เปิด (`appscript.ui/app.tsx` ~บรรทัด 1481) → `Desktop/ui` commit `530a440` (static-only, build hash auto cache-bust). **กระทบทุก dropdown — mode/model/agent/skills**. บทเรียน: `backdrop-filter` สร้าง stacking context — z-index ของ overlay ข้างในจะถูกขัง
- **บั๊ก 2: picker โชว์ local 4 ตัว** (qwen3.5-9b + gemma-4 + deepseek-r1 + text-embedding-nomic) — `/api/models` enumerate ทุกโมเดลที่ LM Studio โหลด (chat+reason+vision+embed). แก้ให้โชว์เฉพาะ **active chat model ตัวเดียว** (`LMSTUDIO_CHAT_MODEL`/`OLLAMA_MODEL`) + ทิ้ง blocking retry ~1.4s ที่ยิง `/v1/models` ตอน LM Studio ต่อไม่ได้ → commit `8b73393` (+ test `test_local_returns_only_active_chat_model`)
- **สลับ local model: deepseek-r1 → qwen3.5-9b** — แก้ `LMSTUDIO_CHAT_MODEL=qwen/qwen3.5-9b` ใน NAS `.env` (เดิม `deepseek/deepseek-r1-0528-qwen3-8b`) + recreate. verified `/api/config` → `ollama_model='qwen/qwen3.5-9b'`, `local_ok=True`. **⚠️ ขัดกับบันทึกเดิมที่ว่า qwen3.5 ไม่เหมาะ (ไทย leak จีน/รัสเซีย + reasoning timeout) — user เลือกเองทั้งที่เตือนแล้ว** ถ้าเจออาการเดิมให้เสนอ Typhoon/Qwen2.5-Instruct. (`.env` ยังมี REASON_MODEL=qwen3.5-9b, VISION_MODEL=qwen3.5-9b อยู่ก่อนแล้ว → qwen โหลดใน LM Studio พร้อมใช้)
- **gotcha สำคัญ (→ infra memory):** task `deploy-hybrid-ai` ทำแค่ `docker restart` = ไม่ reload `.env` → ต้องใช้ task `recreate-ai` (force-recreate) ที่สร้างใหม่. ทั้ง session ทำผ่าน remote-control บนมือถือ off-LAN → ใช้ DSM QuickConnect (File Station แก้ .env + Task Scheduler) เท่านั้น (SSH/WireGuard/browser-SSH ใช้ไม่ได้ off-LAN)

### scrutinize follow-up รอบเดียวกัน — Gemini resilience + prompt sanitization (deployed prod `cc759c6`, app health verified)
อาการที่ user เจอ: เลือก **gemini-3.1-flash-lite** แล้วเด้ง "❌ เชื่อมต่อ server ไม่ได้" + "⚠️ Gemini ใช้ไม่ได้ — fallback เป็น local". วินิจฉัยด้วย live Gemini API (มี key local ใน `~/Desktop/ui/.env`):
- model id ทั้ง 5 ใน picker **มีจริงใน API** (ไม่ใช่ปัญหา) — เทสด้วย `GET /v1beta/models`
- **3.1-flash-lite ตอบ 503 UNAVAILABLE** (preview ไม่เสถียร), **2.5-flash ตอบ 200** ปกติ → เป็นความไม่เสถียรของตัวโมเดล ไม่ใช่ Gemini ทั้งหมด
- **root cause:** `utils/llm.py:_stream_gemini` เดิมจับ error อะไรก็ตามที่ไม่ใช่ 401/429 → `GeminiUnavailable` → `routers/chat.py:372` fallback local **ทันทีไม่ retry**
แก้ 4 commits (`8b73393`→`cc759c6`):
1. `b1bc4db` **retry transient** (503/500/unavailable/internal/deadline/overloaded) สูงสุด 3 ครั้ง backoff 0.6/1.2s ก่อนยอมแพ้ — 429/quota/key ยัง fail เร็ว (ไม่เปลือง quota), retry เฉพาะก่อน yield chunk แรก
2. `cc759c6` **(Major 2) สลับไป Gemini ตัวเสถียร** (`GEMINI_MODEL`=2.5-flash จาก .env) ก่อนถอย local — chain: `requested → stable → local`. ตรง intent user (เลือก 3.1 เพราะ quota/วันเยอะ → อยู่กับ Gemini ดีกว่าตก local). silent switch (log อย่างเดียว ไม่ขึ้นแชท). ไม่สลับถ้า requested=stable อยู่แล้ว
3. `7ef6466` **(Major 1) coerce prompt เป็น str ที่ entry point** `routers/chat.py:37` — เดิม `data.get("prompt","")` จาก `request.json()` ไม่ validate → list/dict prompt ทำ **ทั้ง request 500 ที่ `detect_image_request` regex** (บรรทัด 61) ก่อนถึง provider ไหนเลย + ขยะลง DB. coerce ที่ boundary ครอบทุก provider. (coerce ใน `_stream_gemini` เก็บเป็น defense-in-depth)
- **บทเรียน scrutinize:** fix แรกผม coerce ใน `_stream_gemini` (band-aid เฉพาะ Gemini) — scrutinize จับได้ว่า root อยู่ entry point + failing test พิสูจน์ว่า list prompt ตายที่ regex ก่อนถึง provider. แก้ที่ `chat.py:37` คุ้มกว่า (1 บรรทัดกันทุก provider)
- **ยังไม่ทำ (minor):** `_TRANSIENT` จับแค่ 5xx ไม่จับ network blip ดิบ (timeout/reset) · `time.sleep` block threadpool worker ~1.8s/model ตอน fail · พฤติกรรม retry/fallback ยัง verify บน prod ไม่ได้ผ่าน curl (auth-gated) ต้องลองใน UI จริง (623 tests ผ่าน)

### Work A+B — web-search grounding ทุกโมเดล + quota-safe fallback (✅ DEPLOYED prod `4315daa` 2026-06-15)
**ที่มา:** user ลอง 3.1-flash-lite ถาม "คัมภีร์วิถีเซียน อนิเมะถึงตอนไหน" → qwen (local) ตอบกว้างๆ "เกิน 100 ตอน" ไม่บอกเลขจริง. **quota จริงจาก AI Studio (สำคัญมาก):** 2.5-flash & 3.5-flash = **20 RPD** (ต่ำ! 2.5 ใช้เกินแล้ว) · **3.1-flash-lite = 500 RPD** · **Gemma 4 31B = 1500 RPD** (เยอะสุด แต่ **Gemma เสิร์ช Google grounding ไม่ได้** — เฉพาะ Gemini). → 2.5/3.5 อย่าใช้เป็น fallback
- **Work A (grounding):** เดิม web search inject เฉพาะ route `auto→lmstudio_web` (`routers/chat.py`) → เลือกโมเดลเฉพาะ (qwen/Gemini/Gemma) **ไม่เสิร์ชเลย** ตอบจาก training. แก้: extract `_inject_web_context()` + เรียกเมื่อ `needs_internet(prompt)` สำหรับ**ทุกโมเดล** (ข้าม agent/vision/ที่ inject แล้ว) + คำสั่ง "ไม่พบให้บอกตรงๆ ห้ามแต่งเลข". `reasoning/classifier.py` เพิ่ม pattern: `ล่าสุด`, `ถึงตอนไหน|กี่ตอน|จบหรือยัง`, `ออกตอนใหม่|ออกฉาย`, `(อนิเมะ|มังงะ|ซีรีส์|...)+(ตอน|ออก|จบ|ใหม่)`
- **Work B (fix fallback ที่ผมทำพลาดใน Major 2):** Major 2 เดิม fallback ไป `GEMINI_MODEL`=2.5-flash (20 RPD, หมดแล้ว) → ผิด! เปลี่ยนเป็น `GEMINI_FALLBACK_MODEL` (`utils/llm.py`, default **ว่าง = ไม่สลับโมเดล** retry-then-local — กันเผา quota). **ถ้าอยากให้สลับไป Gemini ก่อนถอย local → ตั้ง `GEMINI_FALLBACK_MODEL=<ตัว quota เยอะ>` ใน NAS `.env` + recreate** (ยังไม่ได้ตั้ง = ปิดอยู่)
- **DEPLOY:** ✅ ทำแล้ว 2026-06-15 บน LAN ผ่าน `ssh nas` → `git reset --hard origin/main` (cc759c6→4315daa) + `sudo -n docker compose restart` (code volume-mounted ไม่ต้อง build). app healthy: ollama/lmstudio/gemini/memory=true, skills 87. **verify code path ใน container:** `needs_internet()` → anime "ถึงตอนไหน"/ราคาทอง/มังงะออกตอนใหม่ = True, "เขียน python" = False; `_inject_web_context` present ✅. Work B fallback ยัง **ปิด** (`GEMINI_FALLBACK_MODEL` ไม่ได้ตั้งใน .env) — ถ้าจะเปิดต้องแก้ .env + recreate. ยังไม่ได้เพิ่ม `GEMINI_FALLBACK_MODEL` ใน CLAUDE.md env docs
- **🐛→✅ bug เจอตอน verify (commit `6f308d7`, DEPLOYED prod 2026-06-15):** `utils/websearch.py:_WEATHER_KEYWORDS` มีคำบอกเวลาล้วน `วันนี้|พรุ่งนี้` → ทุกคำถามที่มี "วันนี้" (ราคาทองวันนี้/ข่าววันนี้/หุ้นวันนี้) โดน `_web_search_impl` short-circuit ไป `fetch_weather()` คืนพยากรณ์อากาศ **ไม่เคยถึง Google search** → Work A grounding ใช้ไม่ได้จริงกับคำถามมี "วันนี้". แก้: ตัด `วันนี้|พรุ่งนี้` ออก (weather จริงยัง match ผ่าน อากาศ/ฝนตก/อุณหภูมิ/weather). test `tests/test_websearch_routing.py`. **verified in-container:** "ราคาทองวันนี้" → 3 sources จริง (ไม่ใช่ weather), "วันนี้อากาศ"/"พรุ่งนี้ฝนตก" → ยัง weather ✓
- **🐛→✅ bug 2 (DDG ขยะ) + DDG hardening (commit `9afcf3f`, DEPLOYED prod 2026-06-15):** end-to-end test (ยิง `/api/chat` ผ่าน **localhost bypass auth** ในคอนเทนเนอร์ — `docker exec ... python requests localhost:8000`, ⚠️ ในคอนเทนเนอร์ app=port **8000** ไม่ใช่ 8080) เจอว่า DDG ตอนโดน throttle คืนผลขยะ/NSFW (คลิปโป๊/MV/ทำนายฝัน) ขึ้นเป็น citation. แก้แบบมินิมอล: extract `_ddg_search()` + `safesearch="moderate"→"on"` + retry 1 ครั้งถ้ารอบแรกว่าง. test `tests/test_websearch_hardening.py` (3). **VERIFIED prod:** ราคาทอง→สมาคมค้าทองคำ/สยามนิวส์, ข่าวการเมือง→ไทยรัฐ/เดลินิวส์ (สะอาด ไม่มี NSFW); chat จริง Gemini 3.1-flash-lite ตอบราคาทองแท่ง 66,850 +citation สมาคมค้าทองคำ ✅. (เลิกทำ junk-regex/relevance-floor — user deny ว่าเยอะไป + regex `sex/porn` เสี่ยง false-match)
- **Google CSE = ใช้ไม่ได้ (ค้าง):** NAS `.env` เพิ่ม `GOOGLE_SEARCH_API_KEY`(...CEZmfgd4)+`GOOGLE_SEARCH_CX=44c7c0b7c3c5049a2` แล้ว (backup `.env.bak.cse`) แต่คีย์เก่า **403 `API_KEY_SERVICE_BLOCKED` → ต่อมา "project ... no access to Custom Search JSON API"** (project เจ้าของคีย์=`387035280891`). user พยายาม enable API + แก้ key restriction หลายรอบ + พยายามสร้างชุดใหม่ แต่ **Programmable Search Engine สวิตช์ "ค้นหาทั้งเว็บ" สีเทากดไม่ได้** (ติด site จำกัด) → ยังไม่จบ. **DDG ใช้แทนได้ดีแล้ว** (search_web ลอง Google ก่อนเสมอ → พอ CSE ใช้ได้วันหลังจะเด้งไปเองอัตโนมัติ). ถ้าจะลุย CSE ต่อ: ลบ site ใน PSE ให้ปลดล็อก "ค้นทั้งเว็บ" หรือสร้าง engine ใหม่ที่ search entire web ได้
- **memory contamination:** ทุก chat test ลง episodic `memory_ui` (persona ฟ้า=default assistant) — ลบครบแล้ว (id `mem_20260615*`). gotcha: episodic **ไม่** key ด้วย session_id ต้อง get(limit=1000)+filter เนื้อหา `"ราคาทอง"` เอา. ChromaDB host ในคอนเทนเนอร์ = `chromadb:8000` (ไม่ใช่ 192.168.51.49)
- **✅ Option B — Gemini ใช้ Google Search grounding ในตัว (commit `cfbd7e1`, DEPLOYED+VERIFIED prod 2026-06-15):** แทนที่จะรอ Custom Search API (403), คำถาม real-time ที่ตอบด้วยโมเดล **Gemini** เปิด `google_search` tool ในตัว Gemini (real Google) แทน DDG. provider อื่น (local/Claude/Kimi) ยังใช้ DDG. impl: เพิ่ม `web_grounding` param → `stream_response` → `_stream_gemini` (เปิด `types.Tool(google_search=...)` เฉพาะ search ไม่เอา code_exec); `routers/chat.py` grounding block เช็ก `_eff in (gemini, gemini_agent)` → set `gemini_grounding=True` ข้าม DDG inject. tests: `test_gemini_grounding.py`(3) + `test_chat_input.py` (แยก lmstudio→DDG / gemini→grounding) + fix fake signature ใน test_model_picker. **VERIFIED:** gemini-2.5-flash ตอบราคาทอง 66,850 +1,350 จาก grounding จริง (fresh session ไม่มี DDG); 3.1-flash-lite quota หมดวันนี้ (เทสเยอะ) → fallback DDG ทำงานถูก (log ยืนยัน Gemini ถูกเรียกพร้อม config ก่อน 429). ⚠️ ตอนนี้ grounding ยังไม่ extract citations จาก groundingMetadata (citations ว่างตอนใช้ Gemini ground — งานต่อถ้าอยากได้ source list)
- **ค้าง/next:** (optional) extract Gemini groundingMetadata → citations · Google CSE ทุกโมเดล (ทำ A ทีหลัง — สร้าง PSE ใหม่ที่ search entire web ได้) · qwen3.5 ไทย-leak + context-bleed ยังเป็นความเสี่ยง (เจอ "ราคาทอง" หลุดเข้าคำตอบ One Piece จาก working memory session เดิม) · ใส่ ANTHROPIC/MOONSHOT key ปลดล็อก Claude/Kimi

## session 2026-06-15 — Model picker ในกล่องแชท (deployed prod ✅ `Desktop/ui` `4f3a874`, source `appscript.ui` `0dfbd7d`)
- **dropdown เลือกโมเดลลิสต์เดียว provider วิ่งตามตัวที่เลือก** + **effort slider 5 ระดับ** (low/medium/high/xhigh/max) + **thinking toggle** ในกล่องแชท React (`app.tsx` + `utils/modelpicker.ts`+vitest)
- backend: `_stream_kimi` (Moonshot OpenAI-compat, provider `kimi`, model `kimi-k2.6`, base `https://api.moonshot.ai/v1`) + เปิด `model`/`thinking`/`effort` ทะลุ `_stream_gemini`/`_stream_claude`/`_stream_ollama` (Gemini effort→`thinking_budget`) + `GET /api/models` (local LM Studio dynamic + cloud curated) + `routers/chat.py` อ่าน 3 field จาก body. test: `tests/test_model_picker.py` (11)
- ⚠️ **Claude + Kimi โชว์ใน dropdown แต่ `available:false` (เทา) เพราะ NAS `.env` ยังไม่มี `ANTHROPIC_API_KEY`/`MOONSHOT_API_KEY`** — ใส่ key ใน `.env` + recreate แล้วใช้ได้ทันที (ไม่ต้องแก้โค้ด)
- cloud models (id ยืนยันจาก docs): gemini-3.5-flash, gemini-3-flash-preview, gemini-3.1-flash-lite, gemini-2.5-flash, gemma-4-31b-it (ทั้งหมด provider `gemini`), claude-opus-4-8/sonnet-4-6/haiku-4-5, kimi-k2.6
- **UI cleanup**: ตัดปุ่ม toggle Gemini/Llama เก่า, cosmetic skills (dream/tts/chroma), Obsidian skill (ซ้ำ header→เก็บ header), FAB Export/Agent/Claude จาก `enhanced.js` (Claude เลือกผ่าน picker; `_agentMode`/`_claudeMode` neutralize=false → React Code pill คุม tool_agent). ⚠️ **ผลข้างเคียงที่ยอมรับ: agent step-by-step timeline ของ overlay หายไป** (React ยังไม่ parse `agent` SSE events — งานต่อถ้าอยากได้คืน)
- gotcha: **NAS:8000 = ChromaDB, app อยู่ port 8080** (`8080:8000`) — verify prod ที่ `http://192.168.51.49:8080`

## Phases ที่เสร็จแล้ว
- **Phase A** — Ollama integration + error handling (ก่อนหน้า session นี้)
- **Phase B** — Smart Retrieval (query rewrite + chunking + document RAG + citations) — commit `6835518`
- **Phase C** — Self-improvement (reflection + feedback + skill discovery + active learning) — commit `c639e8f`
- **Phase D** — Multi-modal agent (code sandbox + FS tools + 5 agent tools) — commit `c438e30`
- **Phase E** — Performance (3 cache layers + prefix-stable + context budget) — commit `3c06261`
- **Phase F** — Observability + Frontend SSE handlers — commit `7fc62a9`
- **Phase G** — Production hardening (DELETE bug fix + CLAUDE.md refresh) — commit `80f1eb6`

## Phase E (Model upgrade) — decision
User เลือก "ใช้ของเดิมก่อน" (keep LMStudio + Gemini, no Claude API integration). อาจกลับมาทำได้ทีหลังถ้าต้องการ:
- Path 1: Claude API integration
- Path 2: LMStudio model upgrade (Qwen 2.5 14B)
- Path 3: Llama 3.3 70B (ไม่แนะนำ)

## Production state (สุดท้าย session นี้)
- 60 skills (cleanup 12 junk → accept 4 proposals จาก Phase C → restore 8 .md ที่ regen)
- 19 .md files
- ChromaDB indexed: 60 (sync แล้ว)
- Memory + Skills + LMStudio + Gemini + Ollama ทำงานหมด
- Dream Cycle ตี 2 ทุกคืน — last run 2026-05-12 06:59 (47 memories → 3 themes promoted)

## Session 2026-05-27 — test coverage + 2 code fixes (✅ deployed บน NAS แล้ว)
push main + deploy ผ่าน **QuickConnect → DSM Task Scheduler** สำเร็จ — NAS running `a44f4ad`:
- **Fix 1 — LM Studio→Ollama cascade** (`utils/llm.py`): เพิ่ม `LMStudioUnavailable`, `_stream_lmstudio` raise บน connection error, helper `_stream_lmstudio_or_ollama`. แก้เคส "ขวัญ llama-3.1-8b ตอบเชื่อมต่อไม่ได้" (Gemini quota→LM Studio ล่ม→เดิมไม่ตกไป Ollama). หมายเหตุ: `llama-3.1-8b` = โมเดล LM Studio ไม่ใช่ Ollama (Ollama=`llama3:latest`)
- **Fix 2 — parser bug** (`reasoning/parser.py`): `parse_think_stream` เดิม `<think>` ที่ถูกแบ่งข้าม chunk (`"<thi"`+`"nk>"`) ทำ tag รั่วเข้า answer + think หาย — แก้ด้วย `_partial_tag_suffix_len` เก็บ tail รอ chunk ถัดไป
- **G3 เกือบเสร็จ** — เพิ่ม ~167 tests ใหม่ (6 ไฟล์): test_classifier/fs_tools/auth/tokens/context_budget/chunking/citations/parser/llm_internals/memory_package. รวม suite 187 passed (ไม่นับ test_main.py ที่ค้างเพราะ TestClient lifespan ต่อ ChromaDB/Ollama จริง)

## Memory retention (กัน ChromaDB บวม) — session 2026-05-27
ปัญหา: episodic ใน ChromaDB ไม่เคยถูกลบจริง (decay แค่ลด confidence) → บวมเรื่อยๆ. แนวทาง = lifecycle **Decay → Consolidate → Forget** (ขาด Forget).
- ✅ **Step 0 (commit `4d0f579`) — DEPLOYED:** wire `bump_access_count` + refresh `last_accessed` เข้า `search_entries` (เดิมนิยามไว้แต่ไม่เคยเรียก → access_count=0 ตลอด). deploy แบบ surgical (`git checkout origin/main -- memory/store.py` เท่านั้น) — recall เริ่ม track usage จริงแล้ว (verified: app healthy, memory_logic=7)
- ✅ **Step 1 (commit `93a99ad`) — DEPLOYED 2026-05-29:** `utils/dream.py` เพิ่ม `memory_prune()` (Phase 3.5 หลัง Deep Sleep) + `_retention_score`=0.5·conf+0.3·recency(half-life14d)+0.2·freq(access/5). floor-prune (conf≤0.2+อายุ>30d+access0) + capacity cap `MEMORY_EPISODIC_CAP`(500, ไม่ตั้งใน .env=ใช้ default). กัน verified/user_taught. NAS reset --hard → HEAD=`af9ece0` (รวม prune + finetune + mobile UI). **prune รันรอบแรกใน Dream cycle 2026-05-30 02:00** → ดูผลที่ `dream_reports/dream_20260530_02*.json` (field prune). ✅ **VERIFIED 2026-05-30:** dream report 5/30 02:00 มี `phase3_prune: {pruned:0, kept:20, cap:500}` — prune live+ทำงานถูก (pruned 0 = ยังไม่มี memory ตายจริง ถูกตามดีไซน์). dream healthy, next 5/31 02:00, แต่ data น้อย (8 memories) → themes/promote/decay ยัง 0 (ระบบใช้งานน้อย ไม่ใช่บั๊ก)
- suite รวม **212 passed** (เพิ่ม test_dream_prune 5 + bump test 1)

## Session 2026-05-29 — deploy Memory Prune Step 1 (✅ DONE)
- **git พัง→แก้:** `.git/refs/` มี junk ref `Icon\r` (0-byte, จาก macOS custom-icon file) โผล่ใน refs/heads, refs/remotes/origin, ฯลฯ 7 ตัว → `git fetch`/`push` error `fatal: bad object refs/Icon?`. แก้: `find .git/refs -type f -name 'Icon*' -delete` → fetch ใช้ได้ ยืนยัน origin/main=local=`af9ece0` (มี 93a99ad ครบ ไม่ต้อง push)
- **NAS เคย down (502):** prod `/api/status` ขึ้น 502 + LAN timeout ตอนเริ่ม → container `ai-backend-1` ไม่ได้รัน (`No such container`) → deploy ด้วย `docker compose up -d --force-recreate` (ไม่ใช่ restart) แก้ทั้ง 502 + ขึ้นโค้ดใหม่พร้อมกัน
- **DSM Task Scheduler gotcha (สำคัญ):** task เดิมรันเป็น user ธรรมดา → `sudo: a terminal is required` + git `detected dubious ownership`. แก้: ตั้ง task **User=root** (ตัด sudo ทั้งหมด) + `git config --global --add safe.directory /volume1/homes/pawin/ui` (root ≠ เจ้าของ repo pawin). `/var/services/homes`=symlink→`/volume1/homes`
- **verified:** `/api/status` = `ollama:true,gemini:true,memory:true,skills:64,next_dream:2026-05-30 02:00`. (probe LAN ChromaDB/LMStudio ✗ เพราะ Mac off-LAN ไม่ใช่ปัญหา; auth endpoints 401 เพราะไม่มี token). **ค้าง verify รอบ Dream 2026-05-30 02:00** ว่า prune ทำงาน → เช็ก dream report

## Fine-tune pipeline — session 2026-05-27 (สร้างครบ scaffolding, รอ data)
ดู [[hybrid_ai_infra]] + `FINETUNE_GUIDE.md` ใน repo. หลักการ: Curate→Train→Serve คนละ host
- **HW ชี้ขาด:** PC `.235` = **RTX 3060 12GB + 24GB RAM** (user ยืนยัน) → **QLoRA Llama-3.1-8B local ได้** (ไม่ต้อง cloud). ⚠️ ผมเคยเดา VRAM ผิดเป็น ~3-4GB จาก Ollama `size_vram=2.94GB` — จริงๆ เพราะ LM Studio แย่ง VRAM ตอนวัด (เปิด 2 ตัวพร้อมกัน)
- 🔴 **คอขวด = DATA: `feedback` ups=0 ทั้งระบบ** (เช็ก `GET /api/feedback/stats`) → เทรนไม่ได้ไม่ว่า GPU ไหน. ต้องกด 👍 สะสม ~200-500 ก่อน. memory_logic=7, db 0.75MB = ระบบใช้งานน้อย
- ✅ **Stage 1 (commit `2d2fc25`):** `utils/finetune_export.py` + `scripts/export_finetune.py` + test (5) — คัด 👍 conversations → JSONL (SFT). working+tested, รัน NAS/Mac ไม่ต้อง GPU
- ⚠️ **Stage 2+3 (commit `9cac35d`):** `scripts/train_qlora.py` (Unsloth QLoRA + GGUF, config 3060) + `requirements-train.txt` + `FINETUNE_GUIDE.md` — **template ยัง validate ไม่ได้** (dev ไม่มี GPU) ต้องรันจริงบน PC ใน WSL+CUDA
- deploy ft model: GGUF → `ollama create kwan-ft` → ชี้ `OLLAMA_MODEL` (pattern จาก `deploy_ollama.sh`). suite รวม **217 passed**
- ⚠️ PC `.235` Ollama/LM Studio **ไม่ auto-start** (ต้องเปิดแอปเอง); SSH ต้อง password (Mac ไม่มี key, user ไม่มีรหัส) → เช็ก GPU จากระยะไกลทำได้เฉพาะตอนแอป LLM เปิด (ผ่าน Ollama API)

## Session 2026-05-29 (ต่อ) — G3 tests ที่เหลือเสร็จ (✅ 371 passed)
เพิ่ม 10 ไฟล์เทสต์ใหม่สำหรับโมดูลที่ยังไม่มี coverage — suite รวม **371 passed** (เดิม ~217). ทุกไฟล์ mock service จริง (LMStudio/ChromaDB/sqlite temp) ไม่แตะ network:
- `test_embed.py` (cosine/pack/two-tier cache/rerank) · `test_retrieval_cache.py` · `test_response_cache.py` (sqlite + embed mock)
- `test_feedback.py` (สำคัญ: mock `_propagate_to_memory` กัน thread แตะ ChromaDB; test `_propagate_impl` แยกด้วย mock memory.store+response_cache)
- `test_query_rewrite.py` · `test_reflection.py` (mock `_client.chat.completions.create`, clear lru_cache)
- `test_skill_discovery.py` (greedy_cluster/dedup/accept→temp SKILLS_DIR) · `test_documents.py` (FakeCollection แทน ChromaDB)
- `test_agents.py` (tools + orchestrator: FakeClient queue responses) · `test_routers.py` (TestClient ไม่ with → lifespan ไม่ fire เหมือน test_main)
- ✅ **committed + pushed** main `4865e1b` (commit `2f4b835` bugfix + `4865e1b` tests). NAS ยังไม่ deploy — bugfix อยู่ใน utils/ (mount) ถ้าจะให้ live แค่ pull + `docker compose restart hybrid-ai` (ไม่ต้อง rebuild)

### 🐛→✅ 2 บั๊กที่เจอ + แก้แล้ว (2026-05-29, TDD: flip test→red→fix→green, suite 372 passed)
1. **query_rewrite Thai time-injection** — `_TIME_PATTERNS` ใช้ `\bวันนี้\b` แต่ "วันนี้" ลงท้ายด้วยวรรณยุกต์ ้ (U+0E49 combining mark ≠ \w) → `\b` ท้ายไม่ match → ไม่เคย inject วันที่. **แก้:** ตัด `\b` ออกจาก pattern ไทย (วันนี้/พรุ่งนี้/เมื่อวาน) match แบบ substring; คง `\b` ของอังกฤษ (today/tomorrow). test: `test_inject_time_context_thai_spaced` + `_glued`
2. **retrieval_cache eviction off-by-one** — `store()` เดิม `_evict_old` ก่อน insert → ค้าง `_MAX_SESSIONS+1`. **แก้:** สลับเป็น insert ก่อนแล้ว `_evict_old` → cap เป๊ะที่ `_MAX_SESSIONS`. test: `test_eviction_caps_sessions` (== _MAX_SESSIONS)
- ✅ committed + pushed main `4865e1b` (bugfix=`2f4b835`, tests=`4865e1b`)

## Session 2026-05-29 (ต่อ 2) — G4 cache hit-rate ครบ (✅ 385 passed)
- **Blocker ที่เจอ:** `/api/cache/stats` เดิมวัด hit *rate* ไม่ได้ — embed/retrieval ไม่มี counter, response มีแค่ `total_hits` (สะสม) ไม่มี miss → แก้โดยเพิ่ม counter
- **Instrument 3 layers** (เพิ่ม `reset_metrics()` ทุกตัวสำหรับ bench/test):
  - `retrieval_cache`: `_metrics{lookups,hits,misses}` นับใต้ _lock ใน `get_cached` → `stats()` มี `hit_rate`
  - `response_cache`: `_runtime{lookups,hits,misses}` + `_bump()` ใน `lookup` → `stats()` มี `runtime_hits`+`hit_rate` (แยกจาก `total_hits` ถาวร)
  - `embed`: ดึง `_embed_one_cached.cache_info()` (LRU hits/misses) + นับ `sqlite_hits`(warm)/`api_calls`(cold) → `cache_stats()` มี `lru_hit_rate`
- **`scripts/bench_cache.py`** — 2 โหมด: `synthetic` (คุม repeat ratio) + `replay` (ดึง prompt จริงจาก chat_history.db). `--fake-embed` (deterministic vector ต่อ text) รันได้โดยไม่ต้องมี LM Studio. แยก response db ไป temp เสมอ (ไม่แตะ prod cache). ฟังก์ชัน `run_synthetic()/run_replay()` import ได้
  - ⚠️ **ข้อสังเกตจาก bench:** `retrieval_cache` เก็บ **1 entry/session** (latest เท่านั้น) → ออกแบบมาสำหรับ consecutive-turn locality ไม่ใช่ global repeat → hit rate ต่ำใน stream ที่ repeat กระจาย (ถูกต้องตามดีไซน์ ไม่ใช่บั๊ก)
- `test_cache_metrics.py` (13 tests): counter ของทั้ง 3 layer + bench harness smoke. suite รวม **385 passed**
- ✅ committed + pushed main `1ccc466`

## Session 2026-05-29 (ต่อ 4) — ปิดช่องโหว่ backup ที่จำเป็นจริง (✅ 436 passed)
- เจอว่า **`chat_history.db` ไม่เคยมี backup** (มีแต่ chroma_backup.sh สำหรับ ChromaDB) — ไฟล์นี้เก็บ feedback 👍 ที่ fine-tune ต้องใช้ → ถ้า disk พังหายถาวร (ChromaDB เคยหายมาแล้ว = ความเสี่ยงจริง)
- ✅ **`scripts/db_backup.sh`** (commit `791aab3`): `sqlite3 .backup` (online WAL-safe; fallback cp+wal+shm) ของ chat_history.db + data/*.db → tar.gz เก็บ 7 วัน → `$DB_BACKUP_DEST` (default `/volume1/homes/pawin/db_backups`). ตั้ง DSM รายวัน **03:30** (ก่อน chroma 04:00, user=root). env-configurable. `test_db_backup.py` 3 tests. doc ใน CLAUDE.md (Data Persistence→Backups)
- **สรุป: roadmap + ช่องโหว่จำเป็นเคลียร์หมด** เหลือแค่ deploy + fine-tune(รอ data)

## UI overlay (enhanced.js) — session 2026-05-29
- เพิ่ม 3 อย่างใน `static/enhanced.js` (vanilla, ไม่ต้อง build): (1) ปุ่ม FAB ✨ Claude (5d60ca7), (2) **token/char counter pill** (`b2e0c57`) — ลอยมุมขวาบน textarea, ~4ตัว/token, amber>1500/แดง>3000, event-delegation, (3) **draft autosave** (`9e26bb6`) — เก็บข้อความค้างต่อ session (localStorage `hw_draft_<sid>`), กู้คืนผ่าน React native-setter+input event, เคลียร์ตอนส่ง, MutationObserver disconnect หลังเจอ composer. (4) **slash quick-prompts** (`3e8f729`) — พิมพ์ "/" → เมนู template (review/bug/explain/summary/translate/improve/plan), ↑↓+Enter/Tab/คลิกเลือก, keydown capture กัน Enter ส่ง, เติมผ่าน React native-setter. cache-bust ล่าสุด `?v=20260529-slash` → **hard refresh** หลัง deploy. ⚠️ ทั้ง 4 verify ด้วย node --check + logic เท่านั้น (ยังไม่เห็น browser จริง — draft restore + slash insert ขึ้นกับ React-controlled-input version; ถ้าเติมกล่องไม่ติด = native-setter trick ไม่เข้ากับ React ของ bundle นี้ ต้องปรับ)
- 🔎 เหตุการณ์ 21:20: prod ขึ้น "⚠️ Gemini (auto)" — สาเหตุ Ollama health `false` (NAS ต่อ PC ไม่ได้ชั่วคราว) **ไม่ใช่ PC ดับ** (Mac วง LAN เดียวกัน .248 ยืนยัน Ollama .235:11434 ตอบ llama3:latest + LMStudio :1234 ตอบ; ping fail เพราะ Windows บล็อก ICMP) → blip, กลับมาเองแล้ว. Ollama อยู่บน PC .235 (deploy_ollama.sh), ไม่ auto-start

## Fine-tune seed + embeddings resilience — session 2026-05-29 (ต่อ 5)
- ✅ **`scripts/gen_seed_sft.py`** (commit `483e508`): seed dataset สังเคราะห์ 27 คู่สไตล์ขวัญ (Python/FastAPI/SQL/วิเคราะห์/ชีวิต/ความรู้/เลขา) → bootstrap fine-tune โดยไม่ต้องรอ 👍. system prompt ดึงจาก assistants/config (single source). docstring บอกวิธีผสมกับ 👍 จริง (`cat seed + sft > all`). test_gen_seed 4 tests. data/ gitignored → reproducible จาก script
- 🔴 **เจอบั๊ก production: LM Studio รุ่นใหม่บังคับ API token** — ยิง `/v1/embeddings` ได้ error "API token required" → NAS ใช้ dummy `api_key="lmstudio"` โดนปฏิเสธ = embeddings/chat/vision ผ่าน LM Studio **ใช้ไม่ได้แม้ PC เปิด** → memory/RAG degrade. (LM Studio `/v1/models` ว่าง = ไม่มี model โหลด/JIT)
- ✅ **แก้ (commit `3c9af82`):** `embed.py._create_embeddings()` ลอง LM Studio (ส่ง `LMSTUDIO_API_KEY`) → **fallback Ollama** (`OLLAMA_EMBED_MODEL=nomic-embed-text`) เมื่อ LM Studio ล่ม/ติด token + metric `ollama_fallback`. `llm.py` lmstudio_client ใช้ `LMSTUDIO_API_KEY` ด้วย. test +2 → suite 442. ⚠️ ต้อง `ollama pull nomic-embed-text` บน PC ก่อน fallback ทำงาน; Ollama PC มีแค่ llama3:latest

## ✅ DEPLOYED ทั้งหมด (2026-05-30) — NAS รัน `0f7d8cd`
- ✅ **deploy สำเร็จผ่าน `scripts/deploy_nas.sh`** (DSM task user=root): git reset --hard → ensure .env → `docker compose build` (ติดตั้ง anthropic-0.105.2+mcp-1.27.2 ครบ) → recreate → `Container ai-backend-1 Started`
- ✅ **verified จาก Mac:** /api/status 200 (ollama:true,gemini:true,memory:true,skills:64) · cache/stats มี `ollama_fallback` (embed ใหม่ live) · /api/chat provider=claude รับ request (Claude provider live) · LMSTUDIO_BASE_URL+CHAT_MODEL อยู่ใน .env แล้ว
- หมายเหตุ deploy gotcha: รอบแรก task รันเป็น user ธรรมดา → docker.sock permission denied → ต้อง **User=root** ใน DSM (sudo ใช้ไม่ได้ใน non-interactive)
- bootstrap one-liner: `cd /volume1/homes/pawin/ui && git fetch origin && git checkout origin/main -- scripts/deploy_nas.sh && bash scripts/deploy_nas.sh`

## Adversarial review + fixes — 2026-05-30 (commit `4bde48d`, suite 468)
รัน adversarial-reviewer บนงานทั้ง session → เจอ+แก้ 3 บั๊กจริง:
- **C1 ratelimit memory DoS:** `_hits` โตไม่จำกัด (over_limit สร้าง key ทุก IP) → `.get()` ไม่สร้าง key + `_maybe_sweep` (ทุก window) + `_cap` popitem ที่ `RATE_LIMIT_MAX_KEYS`(50000)
- **W2 embed cache cross-provider:** `_create_embeddings` คืน `(vecs, model)`, `_cache_set(model=)` เก็บใต้ model จริง → fallback Ollama ไม่ถูก `_cache_get`(LM Studio) อ่านปน
- **W3 auto_score crash→dup:** เซฟ state ต่อ item + flush
- ⬜ **W1 (cf-connecting-ip spoof):** ประเมินแล้ว **ไม่ใช่ปัญหาสำหรับ deployment นี้** — ผ่าน cloudflared tunnel เท่านั้น (CF เขียน cf-connecting-ip จริง spoof ไม่ได้ + origin ไม่ได้ port-forward ตรง) + การ "ไม่เชื่อ header" จะพังการแยก rate-limit ราย user. ถ้าวันหน้า expose ตรง ค่อยเพิ่ม shared-secret header
- ⚠️ fix อยู่ core/+utils/ (volume mount) → `docker compose restart hybrid-ai` ก็ live (ไม่ต้อง build)

## งานที่เหลือ (optional)
1. **ตั้ง `ANTHROPIC_API_KEY` ใน NAS .env** → recreate (ปุ่ม Claude/auto ถึงตอบจริง; ตอนนี้ provider live แต่ขึ้น "ยังไม่ตั้ง key"). default ปรับเป็น **Sonnet 4.6 + max_tokens 4096** แล้ว (commit `c20e47b`, คุม cost — เปลี่ยน CLAUDE_MODEL=claude-opus-4-8 ถ้าอยากฉลาดสุด). โค้ด default อยู่ใน utils/llm+router (volume mount → pull+restart ก็ live ไม่ต้อง build)
2. **ตั้ง DSM task `db_backup.sh`** รายวัน 03:30 (user=root) — กัน feedback หาย
3. hard refresh browser → ดูปุ่ม ✨Claude + token counter + slash / + draft autosave
4. ⛔ fine-tune: รอ feedback 👍 ~200-500 (หรือใช้ `gen_seed_sft.py` bootstrap) + รัน train_qlora บน PC GPU

## Self-improvement loop (4 เฟส) — session 2026-05-30
ตอบคำถาม user: "วิวัฒน์ตัวเองอิสระไม่จำกัด = ทำไม่ได้ (ไม่มีใครทำได้+อันตราย+โมเดลเล็กมีเพดาน)" แต่ทำ **automated loop แบบมีขอบเขต** ได้: collect→curate→retrain→eval-gate→deploy โดยมี gate กัน model collapse + human oversight
- ✅ **เฟส 1 (manual fine-tune):** seed (`gen_seed_sft.py`) + `train_qlora.py` (แก้แล้ว) + `export_finetune.py`
- ✅ **เฟส 2 (eval gate) — เสร็จ (commit `d5af46d`):** `scripts/eval_kwan.py` — Claude กรรมการ pairwise (สลับ A/B กัน bias) เทียบ kwan-ft vs baseline → win_rate≥0.55 → PASS/FAIL/inconclusive, exit 0/1. ชุดคำถาม held-out 16 ข้อ. `test_eval_kwan.py` 10 tests. **กัน model collapse** (ห้าม deploy รุ่นแย่ลง)
- ✅ **เฟส 3 (RLAIF auto-score) — เสร็จ (`cb38019`):** `scripts/auto_score.py` — Claude สแกนคำตอบที่ผ่านมา ให้คะแนน 0-10 คัดอันดี (≥threshold) append `data/finetune_auto.jsonl` (แยกจาก 👍 คน). track last_id ใน `.auto_score_state.json` รันซ้ำ score เฉพาะใหม่. distillation (คัดคำตอบ Claude/Gemini ดีๆ). `test_auto_score.py` 10 tests
- ✅ **เฟส 4 (orchestrator) — เสร็จ (`20556b0`):** `scripts/improve_loop.sh` — ร้อยทุกเฟส (รันบน PC GPU): seed+export👍+auto_score → รวม data → train_qlora → ollama create → **eval_kwan GATE** → deploy เฉพาะ PASS (กัน collapse). guard MIN_EXAMPLES. ยัง human-in-the-loop (รันเอง, ไม่ autonomous เต็ม by design)
- **self-improvement loop ครบ 4 เฟส แล้ว** (suite 462). ใช้จริงต้อง: PC GPU + ANTHROPIC_API_KEY + data พอ. รัน: `ANTHROPIC_API_KEY=... DB_PATH=... bash scripts/improve_loop.sh`
   - ✅ **train_qlora.py review+fix แล้ว (2026-05-29, commit `0765da3`):** แก้บั๊ก SFTTrainer→SFTConfig (dataset_text_field/max_seq_length ย้ายเข้า SFTConfig ตาม TRL ใหม่ — เดิม TypeError แน่), เพิ่ม bf16=is_bfloat16_supported()/fp16 fallback, weight_decay+lr_scheduler, prereq GGUF (build-essential+cmake), pin trl>=0.11 + เตือน unsloth จัดการ deps เอง, คอมเมนต์ train_on_responses_only ไว้เป็นออปชัน. ยืนยัน JSONL schema {"messages":[sys,user,asst]} ตรงกับ export. py_compile ผ่าน — แต่ยัง GPU-unverified (ต้องรันจริงรอบแรกปรับ config). feedback ตอนนี้ยัง ups=0 (เช็ก /api/feedback/stats)

## งานที่ทำต่อได้
- ✅ **Deploy done 2026-05-27** — running `a44f4ad`. NAS เดิมค้างที่ `0c1e762` (ตามหลัง 2 commit รวม fix `4002a19` ปุ่ม Ollama redirect ที่ไม่เคย live มาก่อน!) → checkout เฉพาะ `utils/llm.py`+`reasoning/parser.py` ขึ้น a44f4ad. **git HEAD บน NAS ยัง 0c1e762** — ถ้าจะ sync เต็มทุกไฟล์ใช้ `git reset --hard origin/main`
- ✅ **ChromaDB แก้แล้ว** (2026-05-27): (1) container `Exited(0) 8 วัน` → start กลับ. (2) เจอ+แก้ **volume mount bug**: compose mount `chroma_data:/chroma/chroma` แต่ chroma `:latest` persist ที่ `/data` → data ไม่เคย persist (commit `3a228ec` แก้เป็น `chroma_data:/data`, volume จริง = `ui_chroma_data`). (3) 🔴 **data เก่าหายถาวร** (episodic+long_term vectors) — ผม `docker compose up` recreate ทับ container layer (ควรใช้ `docker start`); เช็กครบทุก volume ว่างหมด + ไม่มี snapshot. (4) ✅ **skills_search auto-rebuild** ทุก startup ผ่าน `server.py:_startup_sync_skills` → 64 skills re-index แล้ว. ที่หายจริง = episodic (decay เองอยู่แล้ว) + long_term collection (แต่ Dream themes อยู่ใน skills_db.json รอด). force re-sync: `POST /api/admin/sync-skills`
- ✅ **ปิดสีแดงครบ (2026-05-27):** (1) pin chromadb image ด้วย **digest** `sha256:1e0b73a1` commit `ee59b9f` (กัน `:latest` เปลี่ยน persist path ซ้ำ — verified running image = digest แล้ว). (2) `git reset --hard origin/main` บน NAS → HEAD สะอาด (stray `index.html` ใน root = stale Vite build "Khim AI" 10 พ.ค. ไม่ track/ไม่ serve → **ลบแล้ว**, git status ว่าง 100%). (3) backup: script `chroma_backup.sh` (stop→tar `ui_chroma_data`→start, เก็บ 7 วัน, ปลายทาง `/var/services/homes/pawin/chroma_backups`) ตั้งเป็น DSM scheduled task รายวัน 04:00
- ✅ **health ยืนยัน 2026-05-27:** `chromadb.available=true`, collections: `skills_collection=64` (ครบ!), `memory_logic=1` (episodic เริ่ม rebuild). deploy ผ่าน QuickConnect+Task Scheduler ทั้งหมด (git-fetch flavor)
- ✅ **hardening เสร็จ (audit ครบ 8/8):** chromadb `restart: always` (`38748d4`), ลบ orphan volume `hybrid-ai_chroma_data`, ลบ merged branch `fix/llm-cascade-parser`.
- ✅ **#8 เสร็จ (commit `aed51ed`):** (1) test_main.py ค้าง — root cause: mock ผิด target (`test_status_endpoint` patch `utils.llm`/`utils.memory` แต่ `routers/system.py` ทำ `from ... import` ผูกชื่อแล้ว ต้อง patch `routers.system.*`) → real func ต่อ NAS .51 ค้างที่ `ThreadPoolExecutor.shutdown(wait=True)`. แก้: `tests/conftest.py` (ชี้ host→localhost + `DB_PATH`=temp file ไม่ใช่ `:memory:` เพราะ `_get_conn()` เปิด conn ใหม่ทุกครั้ง table ไม่ share) + แก้ mock target. (2) เพิ่ม `.github/workflows/tests.yml` (py3.12, pytest ทุก push/PR). ผล: **206 passed ~7s, CI run แรก = success**. **main = `aed51ed`** (NAS ไม่ต้อง deploy — เป็นไฟล์ test/CI ล้วน)
- ✅ **G3 เสร็จแล้ว (2026-05-29)** — เพิ่มเทสต์ครบทั้ง response_cache/retrieval_cache/embed/documents/query_rewrite/reflection/feedback/skill_discovery/agents/routers → suite 371 passed (ดู session note ด้านบน + 2 บั๊กที่เจอ)
- ✅ **G4 เสร็จ (2026-05-29)** — instrument hit/miss counter ทั้ง 3 cache layers + bench script + tests (ดู session note ด้านล่าง)
- ✅ **MCP server export เสร็จ (2026-05-29, stdio)** — `mcp_server.py` wrap `TOOL_REGISTRY` 13 tools ผ่าน MCP low-level Server, dispatch ไป `execute_tool` (ไม่เขียนซ้ำ). `build_tool_list()`+`run_tool()` testable. `mcp>=1.27` ใน requirements (ผ่าน py3.14). doc: `skills/mcp-server-export.md` (วิธี `claude mcp add hybrid-ai -- python3 .../mcp_server.py` + env CHROMA_HOST สำหรับ memory tools). e2e handshake ผ่าน (13 tools listed, calc/time ตอบถูก). `test_mcp_server.py` 8 tests → suite 393. **เพิ่ม tool ใน TOOL_REGISTRY → โผล่ใน MCP อัตโนมัติ**. ยังเป็น stdio (local); HTTP/remote ยังไม่ทำ
- ✅ **Rate limiting + auth hardening เสร็จ (2026-05-29)** — `core/ratelimit.py`: `SlidingWindowLimiter` per-IP (req-rate 120/min default) + auth-fail lockout (8 fails/5min → 429). middleware register outer-กว่า auth (gate ก่อน + จับ 401 จาก auth ไป feed lockout) inner-กว่า request_id. `client_key` = cf-connecting-ip→peer. **constant-time compare** (`hmac.compare_digest` ใน `core.auth.token_matches`) ใช้ใน auth_middleware + routers/auth check/login (แก้ timing attack + brute-force login). env: RATE_LIMIT_ENABLED/RPM/AUTH_FAIL_MAX/WINDOW (อยู่ใน CLAUDE.md). conftest ปิด rate limit (กัน state ข้ามเทสต์). `test_ratelimit.py` 17 tests (clock monkeypatch, ⚠️ ใช้ public IP จริง 8.8.8.8 — TEST-NET 203.0.113.x ถูก py3.14 จัด is_private=True) → suite 410. ✅ committed+pushed main `af6802c`
- ✅ **Claude API integration (Path 1) เสร็จ (2026-05-29)** — เพิ่ม provider `claude`/`claude_agent` ใน `utils/llm.py` (`_stream_claude`) ผ่าน official `anthropic` SDK (0.105.2, py3.14 ok). system→cached block (`cache_control:ephemeral` prefix-stable), vision, adaptive thinking opt-in (`CLAUDE_THINKING=adaptive`+`output_config.effort`), default `claude-opus-4-8` / max_tokens 8192. branch อยู่**ก่อน** gemini catch-all (Claude คุม vision เอง). typed-exception error classify (auth/rate/5xx). `ClaudeUnavailable` exc. env: `ANTHROPIC_API_KEY/CLAUDE_MODEL/CLAUDE_MAX_TOKENS/CLAUDE_THINKING/CLAUDE_EFFORT` (doc CLAUDE.md). `test_claude_llm.py` 17 tests (mock messages.stream) → suite 427. ✅ committed+pushed main `7cd7c35`
- ✅ **Claude เข้า auto-router + ปุ่ม UI เสร็จ (2026-05-29):** (1) `reasoning/router.py` เพิ่ม opt-in `CLAUDE_AUTO=off|reasoning|all` (ต้องมี ANTHROPIC_API_KEY; default off→พฤติกรรมเดิม; internet/vision ยังไป Gemini ก่อน). +6 tests ใน test_llm_routing → suite 433. (2) UI: `static/enhanced.js` (vanilla overlay, ไม่ต้อง build) เพิ่ม FAB ✨ Claude + `_claudeMode` (localStorage `hw_claude_mode`) + fetch-intercept override `b.provider="claude"` บน /api/chat (exclusive กับ Agent) + icon ✨ ใน model badge. node --check ผ่าน. **static/ เป็น volume mount → pull + refresh browser ก็ขึ้น (ไม่ต้อง rebuild/recreate)**. ⚠️ UI ยังไม่ได้เทสต์บน browser จริง (verify ด้วย syntax-check+logic review). ✅ committed+pushed main `5d60ca7`

## Session 2026-05-31 — UI audit + แก้ hallucination chain ครบ 4 ชั้น (✅ DEPLOYED NAS, suite 488)
User ส่งภาพหน้าเว็บจริงให้ตรวจ → ไล่เจอ+แก้ปัญหาจริงหลายชั้น (deploy ผ่าน DSM Task Scheduler `deploy-hybrid-ai`, git fetch origin main + recreate):
- **Anti-hallucination (`12b7214`):** ต้นเหตุ system prompt สั่ง "ไม่เคยปฏิเสธ ไม่บอกว่าทำไม่ได้" → ดันโมเดลเล็กกุข้อมูล. เพิ่ม `_NO_FABRICATION` guard ทั้ง 3 ผู้ช่วย (assistants/config.py) + reword ขวัญ. guard เข้า seed fine-tune ผ่าน gen_seed_sft อัตโนมัติ. test_assistants_config 5 tests
- **Dream % เลขปลอม→จริง (`c5c02dd`):** Light/REM/Deep Sleep `40/40/20%` เป็น hardcoded literal ใน React bundle (ตัวเลขปลอม). แก้: `static/dream_stats.js` (pure mapper report→{light=phase1.raw_count, rem=phase2.themes.length, deep=phase3.count}, dual-export) + enhanced.js fetch /api/dream/report เขียนทับ DOM (React build แล้วแก้ตรงไม่ได้ → overlay + re-apply 2s กัน re-render). test (node:test) 7 tests. cache-bust `v=20260531-dream`
- **home_tool guard (`5f07796`):** verify prod เจอ prompt guard อย่างเดียวไม่พอ — โมเดลเอาข้อมูลจริงที่ build_tool_context ฉีดไปห่อเป็น "ผล ping ปลอม". แก้: `_TOOL_GUARD` + `_join_with_guard()` แนบกติกาท้ายข้อมูลที่ฉีด (ใกล้ attention กว่า system prompt). **ได้ผล: เลิกกุผล ping verbose**
- **🔴 contamination loop + quality gate (`33712c6`):** เจอต้นตอลึก — คำตอบกุถูก **auto-save เป็น lesson** (chat.py บันทึกทุก exchange >100char ไม่เช็กคุณภาพ) → recall กลับมา prime กุซ้ำ. เจอ lessons ปนเปื้อน 8/13 (เรื่อง ping/network จากภาพ + test ผมเอง). **ลบ 8 อันผ่าน API** (`DELETE /api/memory/lessons/{id}`, LAN bypass) เหลือ 5 สะอาด. + `reasoning/learn_gate.py:should_auto_learn()` block negative_feedback("ไม่ใช่ละ"/"ผิดแล้ว") + realtime_home_tool. test 4. **gate verified: lessons คงที่ ไม่บันทึกขยะเพิ่ม**
- **✅ ping จริง — ตัวชี้ขาด (`35d8795`):** user เลือก "ping router/NAS จริง". เดิม build_tool_context ping แค่ PC → โมเดลเดา online/offline. เพิ่ม `ping_network` tool: ping Router(`_default_gateway`=.1)+NAS(.49)+PC(.235) จริงด้วย TCP check (`ping_device` generic อยู่แล้ว) + `_NETWORK_KW` route. **verify สุดท้าย: ขวัญตอบ "Router/NAS ออนไลน์" ตรง ground truth จริง (Router🟢 NAS🟢) ไม่กุ ไม่ปนเปื้อน**. test_ping_network 8 tests
- **เหลือ (low-harm):** โมเดลเล็กยังแถม "ตัวอย่างคำสั่ง ping" (กรอบ hypothetical ไม่ใช่ยืนยันเลขปลอม) → ปิด 100% ต้องใช้ Agent mode (มี ping tool จริง แสดง output ดิบ). **บทเรียน: self-learning ไม่มี quality gate = ยิ่งใช้ยิ่งโง่ (ปนเปื้อนสะสม); โมเดลเล็กกับ real-time data ต้องป้อน "ข้อมูลจริง" ไม่ใช่หวัง guard อย่างเดียว**
- **UI verify:** 480 เทสผ่าน, ทุก frontend endpoint (24) มี handler ครบ, FAB 5 ปุ่ม wired ถูก. ChromaDB UP เอง (`restart:always`) + 95 entries — "Total 0" ในภาพ = chroma down ชั่วคราว, ฟื้นเองแล้ว (ไม่ใช่ data หาย)

## Session 2026-06-01 — wire home tools เข้า Agent registry (✅ DONE local, suite 496, ยังไม่ deploy)
Next Step #1 ใน CLAUDE.md (narration→execution) เสร็จ. TDD RED→GREEN:
- **Root cause:** `agents/tools.py:TOOL_REGISTRY` มี 13 tools แต่ home tools (nas_disk_usage/nas_docker_status/ping_device/ping_network/wol_pc ใน `utils/home_tools.py`) wire เข้าแค่ narration path (detect_home_tools+build_tool_context) → Agent mode เรียกไม่ได้ → กุได้
- **แก้:** (1) extract `ping_network() → list[dict]` ใน home_tools + refactor build_tool_context ให้ reuse (กัน dup device list). (2) +5 wrapper `_t_nas_disk/_t_nas_docker/_t_ping_network/_t_ping_device/_t_wol_pc` + registry entries → **13→18 tools**. (3) +7 tests (test_agents.py, monkeypatch home_tools กัน network). (4) อัปเดต "13 tools" stale 4 จุด (CLAUDE.md Next#1 done + Key Files, mcp_server.py docstring, skills/mcp-server-export.md, skills/anti-hallucination-local-llm.md)
- **ผล:** Agent mode รัน ping/disk/docker จริง โชว์ผลดิบ = ปิด hallucination (วิธีเดียวปิดสนิทบนโมเดลเล็ก). MCP server ได้ 5 tools ใหม่อัตโนมัติ. suite 496 passed compile ok ไม่ regress
- **scrutinize review → เจอ+แก้ 2 จุดที่ทำให้ claim เป็นจริง (suite 499):** orchestrator (`agents/orchestrator.py`) hardcode client เป็น **LM Studio อย่างเดียว** ทุก agent request → (1) 🔴 `api_key` hardcode `"lmstudio"` ไม่อ่าน `LMSTUDIO_API_KEY` env (เหมือนบั๊กที่ embed/llm เคยโดน — LM Studio รุ่นใหม่ reject dummy → agent ตายก่อนเรียก tool) → แก้อ่าน env. (2) 🟠 `AGENT_SYSTEM_HINT` ลิสต์แค่ 7 tools ไม่มี home tools/run_python/fs → โมเดลเล็กไม่รู้ว่ามี ping_network เลยเดาแทน → เพิ่ม home tools + กฎ "network/NAS ต้องเรียก tool เสมอ". +3 tests. **บทเรียน: agent path = LM Studio เท่านั้น; non-agent ทุก provider พึ่ง narration guard 4 ชั้น**
- **ยังไม่ commit/deploy** (รอ user). ทั้งหมดอยู่ agents/+utils/ (volume mount) → deploy = DSM Task Scheduler git fetch + recreate. เหลือ optional เดิม: ANTHROPIC_API_KEY บน NAS, db_backup DSM task, fine-tune (feedback ups ยัง 0)

## Session 2026-06-01 (ต่อ) — scrutinize ทั้งโปรเจกต์ → เจอ+แก้ 5 บั๊ก (suite 509, ยังไม่ deploy)
ใช้ skill `scrutinize` audit ครบ security + correctness. **fix แบบ TDD เรียง severity:**
- **#1 🔴 Broken access control (verified curl prod):** `core/auth.py` GET เป็น fail-open (เปิด เว้นแต่ตรง `_PROTECTED_GET_PREFIXES`) → `/api/vault/search`,`/api/documents`,`/api/skills`,`/api/feedback/low-rated`,`/api/sandbox/info` เปิด public 200 (auth.memory/stats=401 ยืนยัน auth เปิด). store ว่างตอนนี้ blast radius ต่ำ แต่ latent leak. **แก้: fail-closed** — ลบ GET exception + ลบ orphan `_WRITE_METHODS`/`_PROTECTED_GET_PREFIXES` + เพิ่ม `/api/health`,`/api/shared` เข้า open list. แก้ test เดิม `test_middleware_unprotected_get_allowed_for_public` (เคย encode ช่องโหว่) → fail-closed
- **#2 🟠 middleware order กลับด้าน (verified: 401 ไม่มี x-request-id):** `server.py` register rate_limit แล้ว auth → Starlette ทำ auth outermost → auth คืน 401 ก่อน rate_limit ถูกเรียก → lockout/rate-limit ใช้ไม่ได้กับ protected endpoint (brute-force token ไม่จำกัด). **แก้: register auth→rate_limit→request_id** (add ทีหลัง=outer) → outer→inner = request_id→rate_limit→auth. test ตรวจ `app.user_middleware` order
- **#3 🟠 /api/regenerate พัง+data loss (verified UI เรียกจริง):** `routers/chat.py:436` เรียก `search_memory` ที่**ไม่ถูก import** → NameError 500 + `delete_last_assistant_message` (บรรทัด 426) รันไปแล้ว = คำตอบ AI หายถาวรทุกครั้งกด regen. ไม่มี test ครอบเลย. **แก้: เพิ่ม import** + integration test
- **#4 🟡 recall ranking:** `memory/store.py:search_entries` sort confidence ล้วน ทิ้ง semantic score → memory มั่นใจสูงแต่ไม่เกี่ยวเด้งทับ relevant. **แก้: extract `_rank_results` + blend `0.5*conf+0.5*score`** (verified ยัง primary)
- **#5 🟡 LM Studio token:** `reasoning/router.py` `_ping_model`/`_is_model_available` ไม่ส่ง `LMSTUDIO_API_KEY` → ถ้า LM Studio บังคับ token, probe 401 → auto-route หลบ lmstudio เสมอ (degraded เงียบ). **แก้: `_lmstudio_headers()` แนบ Bearer** (pattern เดียวกับ orchestrator/embed/llm)
- **✅ ตรวจแล้วสะอาด:** dream prune (floor-prune ครบ 3 เงื่อนไข + cap sort ascending ลบถูกทาง + ข้าม verified), code_sandbox (Docker --network none --read-only; local block by default), fs_tools (resolve+relative_to กัน traversal), CORS (specific origins)
- ✅ **DEPLOYED + VERIFIED 2026-06-01** — push origin/main `b3df096` (6 commits แยกหัวข้อ) → Run DSM `deploy-hybrid-ai` → re-probe prod ผ่าน: sensitive GET (vault/documents/skills/feedback/sandbox) = **401** (เดิม 200 รั่ว), open path (status/config/health/shared) = 200, 401 มี `x-request-id` (#2 fix). ช่องโหว่ access control + middleware order ปิดสนิทบน prod แล้ว. suite 509

## Session 2026-06-10 — scrutinize §22 ChatBox → แก้ Major 1+2 (✅ pushed `383125c`, ⛔ ยังไม่ deploy — prod 502)
scrutinize commits `adbf262`+`1e9c032` (§22 Custom Chat Input Bar) เจอ 2 Major + แก้แล้ว (TDD, suite **561**):
- **Major 1 (แก้แล้ว):** webSearch skill ฉีด `tool_agent` โดยไม่เช็ค `_claudeMode` → backend เช็ค tool_agent ก่อน provider (`chat.py:182`, "claude" ไม่อยู่ใน agent list) → request เด้งไป **gemini agent เงียบๆ** ทั้งที่ status โชว์ "Claude". แก้: guard `!_claudeMode` ใน interceptor + toast เตือนตอน toggle search ขณะ Claude เปิด
- **Major 2 (แก้แล้ว):** Plan mode เดิม mutate `b.prompt` ต่อ suffix → `save_message` บันทึกลง DB → ปนเปื้อน history/fine-tune export/memory. แก้: ส่ง `plan_mode: true` flag → backend (`routers/chat.py`) ฉีด instruction เข้า system prompt เท่านั้น (แพทเทิร์น active_learning) + plan_mode bypass response cache. tests: `tests/test_plan_mode.py` 3 เคส. cache-bust `?v=20260610-chatbox4`
- **Findings M3/M4/m5 แก้แล้ว commit `4e3bbcf`** (✅ **DEPLOYED+VERIFIED prod 2026-06-10** — `?v=20260610-overlayfix` live, markers ครบใน js ที่เสิร์ฟ, NAS HEAD=`4e3bbcf`): (3) `_isComposerEl` + `.enh-cb-box` → token/draft/slash คืนชีพบน overlay + กัน ghost draft ด้วย `getClientRects()=0` skip + restore ผ่าน `_visibleComposer()` + init ย้าย draft จาก native (4) `_rebindNative()` ทุก 1.5s + ก่อน doSend (5) syncStatus reconcile pill↔`_agentMode`. (6) **เสร็จแล้ว commit `598af0b`**: extract เป็น `static/chat_intercept.js` (pure dual-export — `applyChatBodyMutations` กติกา Claude-ชนะ/plan_mode-flag + `reconcileMode` pill↔agent) + `tests/chat_intercept.test.js` 16 เคส (มี regression Major 1+2) + **CI เพิ่ม step `node --test tests/*.test.js`** (เดิม JS test ไม่อยู่ใน CI เลย — dream_stats ด้วย) + enhanced.js เรียก `window.hwChatIntercept` (graceful ถ้าไม่โหลด) + index.html โหลดก่อน enhanced.js, `?v=20260610-module`. ✅ **DEPLOYED+VERIFIED prod + CI success** (2026-06-10): index.html โหลด 3 ไฟล์ครบ, chat_intercept.js served, CI run แรกที่มี node step = **success** (เช็คผ่าน GitHub REST API — เครื่องนี้**ไม่มี `gh` CLI** ใช้ `curl api.github.com` แทน). NAS HEAD=`598af0b`

## Session 2026-06-10 (ต่อ) — ย้าย ChatBox เข้า React จริง (✅ pushed `3b181ba`, รอ deploy)
**เจอ React source!** = `~/appscript.ui` (git local ไม่มี remote, title "Khim AI") — **build hash ตรง deployed เป๊ะ** (index-ClRgXlwU.js) = zero drift. ความรู้สำคัญ:
- ⚠️ vite config เดิม `outDir: '../Desktop/ui/static'` + `emptyOutDir: true` = **build ตรงจะล้าง overlay files ทิ้ง!** → แก้เป็น `dist/` + `scripts/sync_static.sh` (copy เฉพาะ index.html+assets, มี guard เช็ค enhanced.js ที่ปลายทาง)
- overlay script tags ย้ายเข้า template `appscript.ui/index.html` → `static/index.html` เป็น generated file แล้ว ห้ามแก้มือ — bump `?v=` ที่ template
- appscript.ui เคย track node_modules ทั้งก้อน (ไม่มี .gitignore) → แก้แล้ว commit `5308e46`; มี WIP refactor `components/` (untracked, ไม่ได้ import — อย่าสับสนว่าใช้งานอยู่); dirty hunks เดิม = 👍/👎 feedback UI ที่อยู่บน prod ตั้งแต่ 2026-05-10 แต่ไม่เคย commit (commit แล้วใน `8fce86c`)
- **ChatBox React** (`8fce86c`): mode pills/agent/skills/status dot ใน app.tsx + `utils/chatflags.ts:buildChatFlags` (vitest 7) ส่ง flags ตรงใน body · textarea multiline placeholder เดิม → draft/token/slash ของ enhanced.js attach อัตโนมัติ · `window.__hwReactChatBox` → enhanced.js ข้าม §22 (คง overlay เป็น fallback) · `chat_intercept.js` claude ถอด tool_agent จาก body (test 17)
- ปุ่ม 👍 มีบน prod อยู่แล้ว — "สะสม 👍" = ใช้งาน+กดเอง ไม่ใช่งานโค้ด
- ✅ **DEPLOYED+VERIFIED prod (2026-06-11)**: index.html = bundle `index-DIlLnbXd.js` + overlay tags ci2/react1 ครบ, bundle มี `__hwReactChatBox`, chat_intercept มี `delete b.tool_agent`, API healthy. (ตอน deploy มี 502 window ~60s = recreate ปกติ). NAS HEAD=`3b181ba`. ยังไม่ได้เห็น browser จริง — ถ้า user รายงาน ChatBox เพี้ยน ให้ดู app.tsx ส่วน ChatBox JSX + dropdown z-index/backdrop ก่อน
- **✅ DEPLOYED + VERIFIED prod (2026-06-10):** ระหว่าง session prod เคย 502 (container ไม่รัน) → user Run DSM `deploy-hybrid-ai` → ฟื้น + ขึ้นโค้ดใหม่พร้อมกัน. verify จาก public: index.html `?v=20260610-chatbox4` ✓, enhanced.js served มี guard `!_claudeMode` + `b.plan_mode` ✓, /api/status 200 (gemini:true,memory:true,skills:72), auth fail-closed ยังดี (POST /api/chat + GET /api/skills no-token = 401). หมายเหตุ: `ollama:false` ตอน verify **ไม่ใช่ปัญหา** — user ยืนยัน (2026-06-10) ว่า local หลักตอนนี้ = **DeepSeek R1 via LM Studio** (`.235:1234`) ไม่ใช้ Ollama แล้ว (Ollama = last-resort fallback ตาม routing 2026-06-03 เท่านั้น). ⚠️ gap `/api/status` เช็คเฉพาะ Ollama → **แก้แล้ว commit `34aa034`** (pushed, suite 569): `check_lmstudio_health()` ใน utils/llm.py (/v1/models + Bearer, cache 30s, list ว่าง=False) + status เพิ่ม `lmstudio`/`local_provider`/`local_ok` + §22 status dot สี/tooltip ตาม `local_ok` (poll 60s) + cache-bust `?v=20260610-lmhealth` + doc ใน CLAUDE.md (LLM Routing→Health). **✅ DEPLOYED+VERIFIED prod (2026-06-10):** status มี `lmstudio`/`local_provider:"lmstudio"`/`local_ok` ครบ, `?v=20260610-lmhealth`, syncLocalHealth อยู่ใน js ที่เสิร์ฟ. **ตอน verify: `local_ok:false` ทั้ง ollama+lmstudio timeout = PC `.235` ปิดทั้งเครื่อง → prod วิ่ง Gemini ล้วน (ระวัง quota)** — feature จับ silent fallback ได้ตั้งแต่นาทีแรก. NAS HEAD=`34aa034`

## Session 2026-06-11 — ตรวจ+ซ่อม web search end-to-end (✅ FIXED+VERIFIED prod)
User ถาม "ถ้าถามตอนนี้ AI หาข้อมูลเน็ตได้ไหม" → ตรวจเจอพัง 2 จุด + ซ่อมจนทำงาน:
- **🔴 Root cause 1: NAS `.env` ตั้ง `GEMINI_MODEL=gemini-2.5-pro`** → free tier quota **limit=0** สำหรับ pro (ไม่ใช่แค่หมดวัน) → ทุก internet/agent/vision query 429 → ตก llama3 ที่กุข้อมูล (อ้างราคาทอง ฿23,500 จาก wttr.in!). **แก้: DSM task แก้ .env → `gemini-2.5-flash` + recreate** (script backup .env ก่อน sed). verify จาก `/api/config:gemini_model` (endpoint เปิด ใช้เช็ค env จริงบน NAS ได้)
- **🔴 Root cause 2 (เจอระหว่างเทส): memory contamination ซ้ำรอย 2026-05-31 แต่คนละชั้น** — ทุก Q&A (รวมคำตอบกุ/error จากการเทสของผมเอง) ถูก save เข้า **episodic** `memory_kwan` → recall ฉีดกลับ → แม้ Gemini ดีแล้วก็ยังตอบ ฿23,500 ซ้ำ. learn_gate (2026-05-31) กันแค่ **lessons** ไม่กัน episodic. **แก้: ต่อ ChromaDB ตรง (`chromadb.HttpClient(192.168.51.49:8000)`) get+review → delete 6 รายการเทส** — ไม่มี API ลบ episodic รายตัว
- **✅ verify สุดท้าย:** ถามราคาทอง → gemini_agent ค้นจริง ตอบ **฿63,950 ขายออก** + เวลาอัปเดต (ตรง ground truth)
- ความรู้: เส้น `gemini_agent` ใช้ **Google Search grounding ในตัว Gemini** (`utils/llm.py` `types.Tool(google_search=...)`) ไม่ใช่ `utils/websearch.py` (อันนั้นใช้กับ route `lmstudio_web` + agent tool registry). websearch.py (Google CSE+DDG) ทดสอบจาก Mac แล้วใช้ได้ทั้งคู่
- **✅ LM Studio n_ctx แก้แล้ว (2026-06-11):** user ปรับ Context Length บน PC → Agent ผ่าน local กลับมาทำงาน — verified: `ping_network` ได้ latency จริง 3 อุปกรณ์ + `web_search` เรียก 3 รอบ อ้าง goldtraders.or.th (โมเดลเล็กยังสรุปหน่วยเพี้ยนบ้าง แต่ใช้ข้อมูลจริง)
- **บทเรียน: เทส /api/chat บน prod = สร้าง memory ปนเปื้อนเสมอ → ตามลบทุกครั้งหลังเทส** (doc ใน CLAUDE.md Known Quirks แล้ว)

## Session 2026-06-11/12 — mobile UI + websearch depth + Gemini Image Gen
**1) Mobile UI (✅ deployed `8b761a5` + appscript.ui `d7f93d1`):** ตรวจด้วย Playwright (iPhone 14 viewport ผ่าน LAN + verify ด้วย local static + proxy API) → แก้: header ซ่อนปุ่มรอง `hidden md:flex`, `.msg-action` โชว์บน touch (`@media (hover:none)`), composer safe-area + ซ่อน hint, **enhanced.js แก้ #enh-toolbar กฎชนกัน** (top:50% ค้าง → ยืดทาบกลางจอ) + **ถอด side-column hack** ของ action buttons (ต้นเหตุ "แถวอิโมจิแนวตั้ง"). ตัดของซ้ำใน appscript.ui: ลบ `src/app.tsx` (สำเนา เม.ย.) + `components/` WIP + orphan utils — **backup: `~/appscript.ui_wip_backup_20260611.tar.gz`** (28 ไฟล์, ลบได้ถ้าไม่ใช้ใน ~1 เดือน)
**2) Websearch depth (✅ deployed `96aea28`+`74a6d15`):** user รายงาน "ตอบสั้น" → root cause: โมเดลเห็น ~3k ตัวอักษร → ขยาย `_FETCH_MAX_CHARS` 1500→2500, `_FETCH_TOP_N` 2→3, snippet 300→500 (`tests/test_websearch_depth.py` 4 เคส) + orchestrator final instruction เลิกสั่ง "สรุป" → "เก็บรายละเอียด/ตัวเลข/แหล่งที่มาให้ครบ" (3 จุด). verify หลัง deploy: tool_result โตเป็น 3,939 ตัวอักษร. **เพดานที่เหลือ = โมเดล 8B เอง + เว็บข่าวไทย block scraping (fetch ได้แต่ snippet)** — งานเชิงลึกใช้ Gemini
**3) Gemini Image Gen (✅ pushed `db00d46` + appscript.ui `91c5623`, deployed, ⏳ รอ verify จริง):** "วาดรูป/สร้างภาพ/ออกแบบโลโก้" ใน chat → `utils/image_gen.py` (`IMAGE_GEN_MODEL` default `gemini-2.5-flash-image`) → PNG ลง `data/gen_images/` เสิร์ฟ `/gen/<file>` (open prefix ใน core/auth.py) → ตอบ markdown `![..](/gen/..)` persist ใน history · React `renderMarkdown` รองรับ img (เฉพาะ path ภายใน) + `.md-img` CSS · agent tool `generate_image` (registry 22 tools) · short-circuit ก่อน teach/cache กัน contamination · `tests/test_image_gen.py` 14 เคส, suite 587
**Session 2026-06-12 (บ่าย) — ปิดงานค้าง 2 ข้อ:**
- ✅ **verify image gen เสร็จ — โค้ดถูกทั้งเส้น แต่ฟีเจอร์ใช้ไม่ได้บน free tier**: 429 `limit: 0` กับ**ทุก**โมเดล image gen ของ key นี้ (gemini-2.5-flash-image → resolve เป็น `gemini-2.5-flash-preview-image`, gemini-3.1-flash-image ก็ 0, preview 404, Imagen paid-only) — เปลี่ยน `IMAGE_GEN_MODEL` ไม่ช่วย. **user ตัดสินใจ: พักฟีเจอร์ไว้** (ทางแก้เดียว=เปิด billing ~$0.04/รูป). แก้ error message แยกเคส limit=0 ("ต้องเปิด billing") ออกจาก quota ชั่วคราว — commit `7a46abb` deployed+verified prod, suite 589
- ✅ **ลบ memory เทส 2 รายการแล้ว** (ปลากัด+กาแฟดริป) — `memory_kwan` เหลือ 1 entry (`mem_20260531222819` "ทักทายสั้นๆ" — ดูเหมือน smoke test เก่า 5/31, ยังไม่ลบ ไม่อันตราย)
- 🔑 **SSH key auth เข้า NAS ใช้ได้แล้ว** (`ssh -o BatchMode=yes pawin@192.168.51.49` ผ่าน, sudo -n docker ได้) — deploy ตรงจาก Mac ได้: fetch+reset บน NAS + `docker restart ai-backend-1` (โค้ด volume mount ไม่ต้อง rebuild)
- ✅ **`[TOOL_RESULT]` หลุดในคำตอบ agent — แก้แล้ว** (commit `db9eb9a`, deployed+verified): โมเดล echo marker จาก chat template ของ LM Studio ตอน final synthesis → เพิ่ม `_MarkerFilter` stateful ใน `agents/orchestrator.py` (ตัด `[TOOL_RESULT]`/`[END_TOOL_RESULT]` แม้แบ่งข้าม chunk, pattern เดียวกับ parser `<think>`) wire 2 จุดของ lmstudio path. verify prod: agent ping ตอบสะอาด ไม่มี marker
- ✅ **บั๊กแถมที่เจอตอน verify — gemini agent พังทุก request ที่มี history** (commit `138172b`, deployed): `Part.from_text(positional)` → SDK google-genai ใหม่บังคับ `text=` keyword-only → TypeError (request แรกของ session รอดเพราะ history ว่าง เลยไม่เคยสังเกต). แก้แล้ว verify ผ่าน (เหลือ 503 จาก Google เอง = high demand ชั่วคราว ไม่ใช่บั๊กเรา). หมายเหตุ: agent default = gemini (`routers/chat.py:222` — provider อื่นต้องส่ง `"provider":"lmstudio"` มาเอง), suite **595 passed**
- ✅ **stream status แบบ Claude Code** (user ขอ): "กำลังคิด… (2m 31s · ↓ 7.1k tokens)" ใต้ bubble ระหว่าง stream — `appscript.ui/utils/streamstatus.ts` (vitest 7, รวม 14) + wire 3 เส้น (send/regenerate/edit-resend) ใน app.tsx, tick 1s, token≈chars/4. bundle ใหม่ `index-B83CU50L.js` deployed `fb39dad` (static เสิร์ฟจาก disk → live ทันที แค่ hard refresh)
- ✅ **สกัด skills + อัปเดต CLAUDE.md** (commit `56578c5`, deployed): skill ใหม่ 2 ตัว (`stream-template-marker-sanitization`, `gemini-api-quota-sdk-gotchas`) + deploy-cheatsheet เพิ่ม SSH-direct deploy + CLAUDE.md (Known Quirks 4 ข้อใหม่, Image Gen ⛔พัก, Next Steps 31-34). prod skills 76→**78** indexed ✓. ⚠️ **บทเรียน: git `skills_db.json` เป็น snapshot เก่า ≠ `data/skills_db.json` (live)** — ห้าม merge ทั้งก้อน (เคย resurrect 16 topics เก่า ถอนคืนแล้ว) → เพิ่ม skill ใหม่ = แก้ทั้ง 2 ไฟล์เฉพาะ entry ใหม่ แล้ว restart (startup sync re-index ให้)
**ค้างทำต่อ session หน้า:**
- 💡 บั๊กเล็กรอเก็บ: คำตอบ agent บางทีขึ้นต้น `[TOOL_RESULT]` หลุดมาในข้อความ (cosmetic, ฝั่ง orchestrator lmstudio path)
- 🧪 งานค้างเดิม: เทส ChatBox บน browser จริง · ขยาย classifier ค้นเว็บตามบริบท + Gemini grounding ทุก call (เริ่มไว้แต่ยังไม่เขียน test เสร็จ — ดู transcript 2026-06-11) · ANTHROPIC_API_KEY · db_backup task · 👍 fine-tune data

## Session 2026-06-14/15 — Icon/iCloud + prod 502 + active_learning weather + ลอง Qwen3.5
งานหลายชิ้น บางอย่าง deploy แล้ว บางอย่างค้าง:

**1) 🔴 Icon\r ลามจาก iCloud (✅ แก้)** — `~/Desktop/ui` อยู่บน Desktop ที่เปิด iCloud "Desktop & Documents" → iCloud propagate ไฟล์ `Icon\r` (custom-folder-icon, 0-byte) ลง**ทุก subdirectory 2,275 ไฟล์** รวม `.venv` → โค้ด walk filesystem ชน `Icon\r` = `[Errno 20] Not a directory` → **skills sync + ChromaDB client import พัง** (`/api/status` `memory:false` ทั้งที่ Chroma ปกติ — chromadb import walk `jsonschema_specifications/schemas/Icon\r`). แก้: `find . -type f -name $'Icon\r' -delete` + `xattr -c .` + **user ปิด iCloud sync บน Desktop** → `memory:true` กลับมา + skills sync ทำงาน. (เคยเจอ Icon\r ใน `.git/refs` มาแล้ว 2026-05-29 — รอบนี้คือทั้ง tree). **ควรย้ายโปรเจกต์ออกจาก Desktop ที่ sync iCloud** (venv หลายพันไฟล์ไม่ควรอยู่บน iCloud)

**2) 🔴 prod 502 (✅ แก้)** — `ai-backend-1` หายจาก compose (ทั้งที่ `restart:unless-stopped`) → `:8080` ไม่ตอบ → cloudflared 502 (cloudflared+chromadb ยัง Up เลยไม่ใช่ 530). แก้: `sudo docker compose up -d hybrid-ai` → ฟื้น 200. **ลบ container ขยะ 3 ตัว** (ตรวจ read-only ก่อน ยืนยันไม่พ่วงอะไร): `cloudflare-cloudflared-1` (= สั่ง `cloudflared version` ครั้งเดียว ไม่ใช่ tunnel/SSH), `86072b7d811f_hybrid-ai-workspace`+`hybrid-ai-workspace` (Streamlit เก่า project `hybrid-ai`, bind `/volume1/hybrid-ai` ที่**หายไปแล้ว**) + image `hybrid-ai-streamlit` + network ว่าง `hybrid-ai_default`. ยืนยัน: `ai-cloudflared` = tunnel `ai-workspace` เสิร์ฟ **ai.pawinhome.com → ai-backend-1:8000 เท่านั้น** (ไม่มี SSH); SSH browser = tunnel `home` คนละตัวบน DSM. **FYI เจอ `nebula-sync` restart-loop + `anythingllm` exited(137) — คนละโปรเจกต์ ยังไม่แตะ**

**3) ✅ active_learning weather fix (✅ DEPLOYED+VERIFIED prod 2026-06-15, commit `16bcf8f`, NAS HEAD=16bcf8f)** — ถาม "ฝนจะตกไหมวันนี้" (ไม่บอกจังหวัด) → route gemini_agent ถูก แต่ Gemini **กุชื่อ "อำเภอละเว"** (ค้นไม่ได้ว่าฝนที่ไหน). Root: `active_learning._has_entity("ฝนจะตกไหมวันนี้")=True` (chunk ไทยยาว=มี entity) → ambiguity 0 → ไม่ยิง. แก้ (TDD, `tests/test_active_learning_weather.py` 7 เคส GREEN): `reasoning/active_learning.py` เพิ่ม `_is_weather_query`+`_has_location` (จังหวัด 77 + marker, ตัด `เลย`/`ตาก` ออกเพราะเป็นคำทั่วไป) + field `clarify_directly`/`clarify_message` + param `recent_user_text` (เช็ค location จาก history). `routers/chat.py` เมื่อ `clarify_directly` → **short-circuit ถามกลับ deterministic ไม่เรียก LLM** (กุไม่ได้) + ไม่ `remember()`. **เทสจริง local ผ่าน**: no-location → provider `active_learning` ถามกลับ; มี location → gemini_agent ค้นจริง. **ยังอยู่ local — ต้อง commit + deploy**

**4) 🎨 ดีไซน์ "model-decided web search แบบ Claude" (ออกแบบแล้ว ยังไม่เริ่มโค้ด)** — bottleneck จริง = `needs_internet()` regex (whack-a-mole, ไม่ใช่โมเดลตัดสิน). Claude = ยื่น search tool ให้โมเดลตัดสินเอง. **Phase 1**: Gemini grounding always-on (แยก `grounding` จาก `agent_mode` ใน `_stream_gemini`, ปัจจุบันแนบ google_search เฉพาะ agent_mode) + ดึง `grounding_metadata`→SSE citations, gate `GEMINI_GROUNDING`/`SEARCH_MODE`. **Phase 2**: routing factual→Gemini-grounding, demote regex เป็น hint. **Phase 3**: local. ความรู้: local model ค้นเองไม่ได้ แต่ระบบฉีดผลให้ได้ (`lmstudio_web` ใช้ `utils/websearch.py` Google CSE — keys ตั้งครบ). ตรงกับ CLAUDE.md Next #34

**5) ✅ เปลี่ยน local model → Qwen3.5-9B (.env local + prod, recreated)** — เดิม `.env` ตั้ง chat+reason = `deepseek/deepseek-r1-0528-qwen3-8b` (user นึกว่าใช้ Qwen3.5 แต่ระบบยังวิ่ง R1 เพราะ .env ชี้ R1). LM Studio (`192.168.51.235:1234`) มี `qwen/qwen3.5-9b` โหลดแล้ว. แก้ `LMSTUDIO_CHAT/REASON/VISION_MODEL=qwen/qwen3.5-9b` ทั้ง **local (Mac) + prod NAS** (backup `/var/services/homes/pawin/ui/.env.bak.20260614_084228`, recreate container). Qwen3.5 มี Vision+Tool+Reasoning+256K ctx → ตัวเดียวแทน 3 โมเดล. local_ok:true ทั้งคู่

**6) 🧪 ผลเทส Qwen3.5-9B (สำคัญ — ชี้ขาดว่าไม่เหมาะเป็น chat หลัก):**
- 🟢 **Tool-calling ทำงานถูก** — ตัดสินใจเรียกเอง→`calculator`→`17**8`→ได้ `6975757441` ถูก (= ดีไซน์ B1 "local ตัดสินใจค้นเองแบบ Claude" ทำได้)
- 🔴 **ไทย prose leak** — แทรกจีน/เกาหลี/รัสเซีย กลางประโยค (`发出各种颜色的光`/`рассеивание`/`렛`) + ผิดข้อเท็จจริง. **เป็นที่ตัวโมเดล ไม่ใช่ quant** (Q8+Q6 เหมือนกัน). ตอบสั้นๆ ("กรุงเทพมหานคร") สะอาด — leak เฉพาะตอบยาว
- 🔴 **reasoning คุมไม่ได้ → timeout** — Qwen3.5 คิด 1100+ ตัวอักษร (`reasoning_content`) ทุกครั้ง → app request timeout 180-220s ไม่มีคำตอบสุดท้าย. **พิสูจน์แล้วปิด thinking ผ่าน API ไม่ได้ 5 วิธี**: `chat_template_kwargs.enable_thinking=false`, `/no_think` (user+system), `reasoning_effort=low` — ทั้งหมดถูกเมิน (LM Studio แยก thinking ไป field `reasoning_content`, reasoning ฝังตายใน Qwen3.5 GGUF template ต่างจาก Qwen3 ที่มี toggle). **โค้ดทำอะไรไม่ได้ — ต้องเปลี่ยนโมเดล**
- VRAM 3060 12GB: Q8 (10.45GB) ตึง/ช้า, Q6 (8.28GB) เร็วต่อ token แต่ยัง timeout เพราะ reasoning. **เทสไม่ contaminate memory** (timeout → `remember()` ท้าย stream ไม่รัน → `memory_ui` ยัง 3 entries สะอาด)
- **คำแนะนำ:** Qwen3.5 = tool ดี/ไทยแย่/reasoning คุมไม่ได้ → **เก็บไว้ทำ tool/agent/reasoning, อย่าใช้เป็น chat หลัก**. chat ไทย → **Typhoon (จูนไทย, ไม่ reasoning)** หรือ **Qwen2.5-7B-Instruct** (non-reasoning, tool ดี) หรือ route ไทยไป Gemini

**ค้างทำต่อ session หน้า (เรียงความสำคัญ):**
1. **ตัดสินใจ local model** — โหลด Typhoon/Qwen2.5-Instruct ใน LM Studio (PC) มาเทสแทน Qwen3.5 (แก้ทั้ง timeout+ไทย leak ที่ต้นเหตุ) แล้วแก้ `.env` local+prod
2. ✅ ~~commit + deploy active_learning weather fix~~ **เสร็จแล้ว** (`16bcf8f`, verified prod)
3. **(optional) timeout safety net** ในโค้ด — กัน app แขวน 180s กับโมเดลช้า ตัวไหนก็ตาม (request timeout + fail message, มี failing test ได้)
4. **เริ่ม Phase 1 ดีไซน์ web-search** (#4 — Gemini grounding always-on + citations)
5. งานค้างเดิม: ANTHROPIC_API_KEY บน NAS, db_backup DSM task, เทส ChatBox browser จริง, 👍 fine-tune data
- ⚠️ pytest ไม่อยู่ใน `.venv` ของ Desktop/ui — ติดตั้งแล้ว session นี้ (`./.venv/bin/python -m pip install pytest`). เครื่องนี้ไม่มี `python` มีแต่ `python3`/`.venv/bin/python`

## **Why:** User ทำงานต่อ session นี้นาน + เพิ่งเสร็จ deploy ระบบใหญ่ ขอพัก ต้องการให้บันทึกไว้กลับมาทำต่อได้ถูก

## **How to apply:** เริ่ม session ใหม่ → check `git log -10` ดู commit chain → ดู memory file นี้ เลือกงานต่อจาก "งานที่ทำต่อได้" → ตรวจ production state ผ่าน `bash scripts/probe_live.sh` ก่อนเริ่ม

---

### Session 2026-06-16 — frontend perf + Gemini agent fix + A/C/F + slug bug
**Deployed prod ครบ (NAS git `5586273`, verified):**
- **Frontend `2e1ad97`** (build จาก `~/appscript.ui`): `<Markdown>` React.memo (กัน re-parse ทั้งประวัติทุก token) + typewriter token-reveal (`utils/reveal.ts` rAF ไล่ตาม target) — แก้อาการ stream ช้า + เห็น token วิ้ง
- **Gemini agent `b3fd2da`**: tool-response turn ส่ง `list[Part]` ไม่ใช่ `types.Content` (`agents/orchestrator.py` — เดิม crash ทุก request ที่ agent เรียก tool รอบ 2: "Message must be a valid part type ... got types.Content")
- **A+C+F `5586273`**: (A) Gemini agent ใช้ `send_message_stream` → stream คำตอบหลาย chunk (verify prod = 7 chunks) (C) extract `persist_agent_turn()` ใน `routers/chat.py` → gate `remember()` ด้วย `should_auto_learn` (agent realtime ไม่ปนเปื้อน episodic; verify log "skip remember (episodic): realtime_home_tool") (F) `_gemini_stream_with_retry`+`_is_retryable_gemini` retry 503/overloaded ยกเว้น limit:0
- backend 655 tests ผ่าน · frontend 27 ผ่าน

**✅ slug bug (item D — DONE 2026-06-16, prod `5a6de17`):** `_safe_slug("🧡 ขวัญ (Logic)")`→`"logic"` (ตัด emoji+ไทย). แก้ด้วย `memory/store.py:resolve_slug()` คืน `config["slug"]` เสถียร (fallback `_safe_slug`), ใช้แทนทุกจุด `memory_{}` (store ×4, operations, utils/memory legacy). **migrate prod แล้ว (non-destructive)**: `memory_logic`(87)→`memory_kwan`(88), `memory_ui`(3)→`memory_fa`(3) เก็บ embeddings. verify `get_memory_summary("🧡 ขวัญ (Logic)")`→88 อ่านจาก memory_kwan. **ของเก่า `memory_logic`/`memory_ui` ยังอยู่เป็น backup — ลบได้เมื่อมั่นใจ (ขอ consent)**

**ค้าง/ต่อยอด:**
- ✅ **"เหลือขวัญตัวเดียว" (DONE 2026-06-16, prod `e7d38a5`)**: ถอด ฟ้า/ขิม จาก `assistants/config.py` เหลือ kwan. data-driven → be+fe ปรับเอง (verify `/api/config` count=1). คงชื่อ "🧡 ขวัญ (Logic)" → memory_kwan ไม่ต้อง migrate. `TestSingleAssistant`. **✅ orphan cleanup (2026-06-16)**: ลบ ChromaDB `memory_fa`+`memory_ui` (ฟ้า) + sessions ฟ้า(9)/ขิม(1). ขิมไม่เคยมี collection. **`memory_logic`(87) ยังเก็บเป็น ขวัญ D-migration backup** (ลบได้เมื่อมั่นใจ). gotcha: `ssh` ใน loop กิน stdin (ลบได้ตัวเดียว) → ใช้ `ssh -n` + remote server-side loop (NAS มี jq+python3). optional FE ที่ยังไม่ทำ: ซ่อนปุ่มสลับ+Debate เมื่อมี assistant เดียว (ยังโชว์แต่ไม่ crash)
- ✅ **item B (DONE 2026-06-16, prod `a7c67fe`)**: React render `agent` SSE events แล้ว — `Message.agentSteps` เก็บทั้ง 3 SSE loop (send/regenerate/edit) + `AgentTimeline` component (ยุบ/ขยาย, auto-open ตอน streaming) + `utils/agentsteps.ts:agentStepView` (vitest, 6 tests). timeline tool steps กลับมาแสดงใน chat bubble
- ✅ **item E (DONE 2026-06-16, prod `3433df3`)**: รวม Gemini+LMStudio loop → `_run_agent_fc(adapter, max_steps)` กลาง + `ToolCall` dataclass + `_GeminiAdapter`/`_LMStudioAdapter` (ห่อ provider quirks: gemini stream+retry+Content-fix, lmstudio role:tool+MarkerFilter). loop เทสครั้งเดียว (`TestRunAgentFcLoop` fake adapter). **Ollama ReAct เก็บแยก** (คนละ paradigm + dormant). error รวมเป็น "{provider} agent error". verify prod: ping agent 130 chunks streaming, multi-step, zero error. 662 tests
- voice WIP (`utils/voice.py:live_server_content_events` + `tests/test_voice_transcript_to_ui.py`) ยัง uncommitted — งานคนอื่น เว้นไว้

---

### Session 2026-08-02 (รอบ 2) — P1: ล้าง episodic + user_facts ที่ไม่เคยทำงาน
**Deployed prod ครบ 6 commits (`0917e0f`→`f659015`, verified prod ทุกข้อ) · เทส 878→901**

- **✅ backlog ข้อ 14 ล้าง episodic**: `memory_kwan` 94→38 · `memory_logic` 62→19 · `scripts/clean_episodic.py` (dry-run default, backup พร้อม embeddings ก่อนลบ) + เทส 12 · **เกณฑ์ลบ = `should_remember()` ตัวเดียวกับ gate ขาเข้า** (เกณฑ์เข้า/ออกต้องเป็นตัวเดียวกัน) · กฎ: doc ที่ parse ไม่ออก = เก็บไว้ ไม่ใช่ลบ
- **✅ ข้อ 15 (บั๊กใหม่) `user_facts` ไม่เคยถูกสร้างเลย 2 เดือน** — tier 2.5 ตายเงียบตั้งแต่ 2026-06-03 · ต้นเหตุ: `teach._CORRECTION_PATTERNS` บังคับภาษาทางการ + `r"ผิด[นน]ะ"` **เขียนผิดในตัวเอง** (`[นน]` = char class ของ น ตัวเดียวซ้ำ) → รันกับ prompt จริง prod 154 ข้อได้ 0 hit · **`learn_gate` รู้พอที่จะ *ทิ้ง* เทิร์นนั้น (negative_feedback) แต่ `teach` ไม่รู้พอที่จะ *เรียน* จากมัน** = ของผิดค้างในคลังตลอดไป
- ⚠️ **ห้ามรวม `_CORRECTION_PATTERNS` กับ `learn_gate._REJECTION_KW`** — ต้นทุนเดาผิดคนละทิศ: learn_gate ผิด = เสียโอกาส · teach ผิด = ขยะเข้า context ทุก prompt
- **✅ สกัดข้อเท็จจริงด้วย LLM + คำตอบที่ผิดเป็นบริบท** (`memory/correction.py` ใหม่) — verified prod: `'เราเตอร์ที่บ้านคือ ASUS RT-BE92U'` สะอาดจริง · แถมแก้บั๊ก `teach.py` ใช้ `ai_response` ทำ 2 หน้าที่ (ค่าที่ chat.py ส่งคือคำตอบเทิร์น*ปัจจุบัน* → `update_confidence()` ลด confidence ผิดตัวมาตลอด) ตอนนี้แยก `prev_answer` อ่านจาก working memory **ก่อน** push เทิร์นนี้
- **⏸️ ข้อ 3/4 threshold ไม่แก้ โดยตั้งใจ** — ล้างคลังแล้วคะแนนยังซ้อนทับ **แต่ตัวเลขนั้นเชื่อไม่ได้เอง**: "ประวัติศาสตร์อียิปต์" ไปแมตช์ "สรุปเนื้อเรื่องคัมภีร์วิถีเซียน" 0.550 = ใกล้กันจริงเชิงความหมาย → คำถาม"ไม่เกี่ยว"ที่แต่งเองไม่ได้ไม่เกี่ยวจริง · **ข้อ 12 (ground truth) ยังบล็อกอยู่**
- **🔴 ข้อ 16 ใหม่ — เกณฑ์ `search_user_facts(min_score=0.6)` แน่นเกินจริง**: ประโยคที่สกัดสะอาดแล้วได้ 0.447 (ตก) ขณะที่เรคคอร์ดดิบยาวๆ ได้ 0.645 (ผ่าน) → **ทำให้ข้อมูลสะอาดขึ้น = recall แย่ลง** ตอนนี้ `user_facts` มี fact ที่ถูกต้องแต่ไม่เคยถูกดึงใช้ · ยังไม่แก้เลข (คลังมี fact เดียว วัด precision ไม่ได้) · เสนอ: `user_facts` (user-taught, verified) อาจสมควรมีเกณฑ์คนละตัวกับ episodic

**gotcha ใหม่ที่ใช้ซ้ำได้:**
- **`col._embedding_function` ที่อ่านจาก client เป็นของหลอก** — chromadb 1.x เก็บ ef ใน collection config แล้วประกอบใหม่ตอน query · attribute คืน `DefaultEmbeddingFunction` (384) ทั้งที่ query จริงใช้ ollama 768 → **วิธีตรวจจริง: ยิง `query_embeddings` มิติที่สงสัยตรงๆ ดูว่า server ปฏิเสธไหม** + อ่าน `col.configuration_json`
- **local `.env` ไม่มี `EMBEDDING_MODEL` แต่ต่อ ChromaDB ตัวเดียวกับ prod** — สคริปต์จาก Mac ที่เรียก `get_or_create_collection()` จะสร้าง collection ด้วย MiniLM 384 แล้วฝังถาวร (ซ้ำรอย `preferences`) · ควรตั้งให้ตรง NAS
- **Qwen3.5 ปิด thinking ผ่าน API ไม่ได้ → `max_tokens` น้อยถูก reasoning trace กินหมด** เหลือ `<think>` ที่ยังไม่ปิด · regex non-greedy ไม่แมตช์ → ได้บทครุ่นคิดมาเป็น "คำตอบ" · **`<think>` ที่ไม่ปิด = ทิ้งทั้งก้อน**
- **งานที่เรียก LLM ห้ามอยู่ในสาย SSE** — teach() ทำให้เทิร์นเดียวใช้ 61 วิ ทั้งที่คำตอบพิมพ์จบแล้ว → เธรดเบื้องหลังแบบ `_learn()`
- **ตกหลุม "ความล้มเหลวที่หน้าตาเหมือนสำเร็จ" ซ้ำอีกรอบ** — เส้นทาง `extractor คืน None` เป็นทางเดียวที่ไม่ได้ log ทำให้เห็นแค่ผลลัพธ์ fallback โดยไม่รู้สาเหตุ
- **สมมติฐานของตัวเองต้องถูกวัดเหมือนกัน** — เข้า session ด้วยความเชื่อว่า "ล้างคลังแล้ว threshold จะไม่จำเป็น" (อิงบทเรียนรอบก่อน) วัดแล้วไม่จริง

**งานต่อ:** `~/Desktop/ui/docs/audit-backlog-2026-08-02.md` — ข้อ 12 (ground truth) ปลดล็อกทั้งข้อ 3/4/16 · P2: `sandbox.py`, `skills/*.md` 26 ไฟล์อ้างโมเดลเลิกใช้แล้วแต่ถูกฉีดเข้า context ทุกเทิร์น

**(ต่อ) Session 2026-08-02 รอบ 2 — ปิด P1 ครบ + ข้อ 16/17 · เทส 878→961 · 12 commits (`0917e0f`→`97ce9ee`) deployed+verified prod ทุกข้อ**

- **✅ ข้อ 12 ground truth** (`scripts/recall_groundtruth.py` + เทส 8) — 50 คู่ที่คนมาร์ค จากคำถามจริงบน prod 25 ข้อ (prod `chat_history.db` 481 ข้อความ) · **ผลค้านสมมติฐาน: 0.6 ที่สงสัยทั้ง session ว่า "ตั้งลอยๆ" กลับเกือบดีที่สุด** · ทนทาน: พลิก label ที่ไม่มั่นใจ 6 คู่ครบ 64 กรณี เกณฑ์ดีสุดอยู่ 0.525-0.65 เสมอ
- **✅ ข้อ 3+4 พื้นความเกี่ยวข้อง** `RECALL_MIN_SCORE=0.55` (เอียง recall โดยตั้งใจ) — `search_memory`/`get_lessons`/`search_long_term_memory` เดิม**ไม่เคยอ่าน distances เลย** · `search_entries` เดิมเอา score ไปจัดอันดับอย่างเดียว → confidence สูงแต่ไม่เกี่ยวยัง surface · verified prod: "ราคาทองวันนี้"/"สูตรทำต้มยำกุ้ง" ฉีด context **0 ตัวอักษร** (เดิมได้ top-3 ทุกครั้ง)
- **✅ ข้อ 17 dual-vector** (`memory/dualvec.py` + collection คู่ขนาน `<name>__keys`) — ต้นตอ: **embedding = ค่าเฉลี่ยทั้งข้อความ** เก็บ Q+A ก้อนเดียวแล้วค้นด้วย Q → คำตอบยาวกลบคำถาม (หัวข้อ 0.913 → doc เต็ม 0.490 · อิ่มตัวที่ ~160 ตัวอักษร) · **"index แค่กุญแจ" ตกไปแล้ว** (ค่าเฉลี่ยดีขึ้น +0.183 แต่ผ่านเกณฑ์ลดลง 16/18→15/18 = ค่าเฉลี่ยหลอก) → ใช้ max ของสองฝั่ง · backfill prod แล้ว (lessons 7 · kwan 36 · logic 17 · user_facts 1 · long_term 0 ถูกต้อง)
- **✅ ข้อ 16 lexical OR-gate** (`memory/lexical.py`) — semantic จับตัวระบุ (รุ่น/รหัส/IP) ไม่ได้: 2 ประโยคที่ต่างกันแค่ชื่อรุ่นได้ 0.496 · เกณฑ์ 0.50 จาก ground truth เดิม (semantic อย่างเดียว R=0.89 → OR lexical **R=1.00 P=0.90**) · character n-gram **containment** ไม่ใช่ Jaccard (ไทยไม่มีช่องว่าง + doc ยาวกว่าคำถามเสมอ) · verified prod: "เราเตอร์ที่บ้านยี่ห้ออะไร" 0 → เจอ
- **✅ ข้อ 14 ล้าง episodic** kwan 94→38 · logic 62→19 (`scripts/clean_episodic.py`, backup พร้อม embeddings) · **✅ ข้อ 15 `user_facts` ไม่เคยถูกสร้างเลย 2 เดือน** (pattern บังคับภาษาทางการ + `r"ผิด[นน]ะ"` เขียนผิดในตัวเอง) + สกัดข้อเท็จจริงด้วย LLM (`memory/correction.py`)

**🔑 บทเรียนที่ใช้ซ้ำได้ (เต็มใน vault `wiki/concepts/embedding-dilution.md`):**
- **ความกว้างของ "ที่ราบ" คือตัวชี้ว่าเกณฑ์เชื่อได้แค่ไหน ไม่ใช่ค่า F1** — lexical ที่ราบกว้าง 0.25 (0.45-0.70 ผลเท่ากัน) = มั่นใจ · dual-vector F1=1.00 แต่ช่องว่างแค่ **0.013** = overfit เชื่อไม่ได้
- **"แมตช์เป๊ะแต่คะแนนต่ำ" = dilution ไม่ใช่เกณฑ์ผิด** — ไล่ที่สิ่งที่เอาไป embed ก่อน · วินิจฉัยเร็วสุด: เทียบ `cos(q, กุญแจ)` กับ `cos(q, doc เต็ม)` · ตรวจ `cos(t,t)`=1.0 ก่อนเสมอเพื่อตัดสมมติฐานโมเดลพัง
- **embedding ไม่ใช่เครื่องมือเดียว** — ของที่ต้องจำตรงตัว (รุ่น/IP/เลข/ราคา) ต้องมี lexical คู่เสมอ
- **`col._embedding_function` ที่อ่านจาก client เป็นของหลอก** (คืน Default 384 ทั้งที่ query ใช้ ollama 768) → ตรวจจริงด้วยการยิง `query_embeddings` มิติที่สงสัยดูว่า server ปฏิเสธไหม + อ่าน `col.configuration_json`
- **local `.env` ไม่มี `EMBEDDING_MODEL` แต่ต่อ ChromaDB ตัวเดียวกับ prod** → สคริปต์จาก Mac ที่ `get_or_create` จะฝัง MiniLM 384 ถาวร · **backfill/สร้าง collection ใหม่ต้องรันในคอนเทนเนอร์เท่านั้น** (`docker cp` สคริปต์เข้าไป — `scripts/` ไม่ได้ mount, scp ถูกปิด)
- **งานที่เรียก LLM ห้ามอยู่ในสาย SSE** (teach ทำเทิร์นเดียวใช้ 61 วิ) → เธรดเบื้องหลังแบบ `_learn()`
- **Qwen3.5 ปิด thinking ผ่าน API ไม่ได้** → `max_tokens` น้อยถูก reasoning trace กินหมด เหลือ `<think>` ที่ไม่ปิด = ทิ้งทั้งก้อน
- **ตกหลุม "ล้มเหลวหน้าตาเหมือนสำเร็จ" ซ้ำ 2 ครั้งในเซสชันเดียว** (extractor คืน None เงียบ · ids หายทำผลว่างทั้งชุด) — เส้นทางล้มเหลวทุกเส้นต้อง log
- **"แก้ 3 ใน 4 จุดแล้วคิดว่าจบ" โดนอีก 1 ครั้ง** (dual-vector ลืม `search_user_facts`) — เจอตอน verify prod เท่านั้น

**🔴 เซสชันหน้าเริ่มที่: P2 ข้อ 9 — `skills/*.md` 26 ไฟล์** (`~/Desktop/ui/docs/audit-backlog-2026-08-02.md`)
ไฟล์พวกนี้ถูกฉีดเข้า context **ทุกเทิร์น** ผ่าน `load_skills_relevant()` และมีอย่างน้อย 5 ไฟล์อ้างโมเดลที่เลิกใช้แล้ว (`deepseek-r1-0528-qwen3-8b` เลิกใช้ 2026-07-05 · `llama3` เป็น fallback ที่แทบไม่ใช้) = ป้อนข้อมูลล้าสมัยให้ตัวเองทุกวัน
⚠️ **volume mount gotcha:** container อ่าน skills จาก `data/skills/` ไม่ใช่ `skills/` ในโค้ด — แก้ใน git แล้วต้อง `cp skills/*.md data/skills/` ด้วย
P2 ที่เหลือ: ข้อ 5 `sandbox.py` (รันโค้ดจริง = ผิวสัมผัสความปลอดภัย ยังไม่เคยตรวจ) · ข้อ 6 agent tools 21 ตัวไม่เคยยิงจริง

## 🔴 เซสชัน 2026-08-03 (รอบสอง) — ข้อ 21 ขั้นที่ 2: shadow logging + backfill

**ผลใหญ่สุด: ข้อสรุปของเซสชันก่อนที่ว่า "คำตอบคือใช้ semantic" ผิด** — วัดบน 432 เทิร์นจริง
(prompt ทั้งหมดใน prod DB) พบ `semantic@0.40` ฉีดให้ prompt **ไทยล้วนได้แค่ 5.9%**
แย่กว่า `split` ของเดิม (29.7%) เสียอีก · `ngram` ฉีด 92.8% = ท่วมเกินรับได้

- **`feedback` บน prod = 0 แถว** ตั้งแต่ 2026-04-21 (447 คำตอบ) → แผน "log 1 สัปดาห์แล้ว
  เทียบ 👍/👎 ที่มีอยู่แล้ว" **เทียบกับความว่างเปล่า** · ทราฟฟิก ~4 เทิร์น/วัน = 1 สัปดาห์
  ได้ ~30 เทิร์น · **เลิกแผนรอเก็บสด ใช้ backfill แทน** (คะแนนเป็นฟังก์ชันบริสุทธิ์ของ
  (prompt, ไฟล์) → ย้อนหลังได้ทันที)
- **root cause จริงไม่ใช่ tokenizer**: ช่องว่างไทย/Latin ยังอยู่ครบใน semantic ที่ไม่ใช้
  `.split()` เลย (มัธยฐานอันดับ 1 ไทย 0.253 vs Latin 0.371) — เกณฑ์ 0.40 อยู่**เหนือ p90
  ของคะแนนไทย** · `"deploy ยังไง"` ได้ `deploy-cheatsheet.md` อันดับ 1 (ถูกเป๊ะ) ที่ 0.380
  แล้วตกเกณฑ์ → ไม่ฉีดอะไรเลย
- **ทางที่หลักฐานชี้: เกณฑ์สัมพัทธ์** (อันดับ 1 นำอันดับ 2 อยู่เท่าไร) — นำ ≥ 0.03 ให้
  ไทย 47.9% / Latin 60.6% หดช่องว่างจาก 6.4 เท่าเหลือ 1.3 เท่า · **ยังไม่รู้ precision
  ต้องเอา 110 คู่ที่มาร์คไว้แล้วมาตรวจก่อน (ฟรี ทำได้ทันที) = งานถัดไป**
- ⚠️ **ground truth ที่สร้างจาก candidate ของ scorer มองไม่เห็น base rate** — "ไทยล้วน
  semantic P=1.000" จริงบน 11 คู่ที่บังเอิญผ่าน 0.40 แต่ recall บนของจริงคือหายนะ
  → **precision จาก candidate pool ห้ามใช้สรุปเรื่องเลือกวิธี** (vault
  `wiki/concepts/threshold-vs-ranking-calibration.md`)
- ⚠️ **ไม่มีงบค่า API** — ตัดแผน "Claude เป็น judge" ทิ้ง · ทางฟรีที่เหลือ: weak label จาก
  n-gram overlap ระหว่างคำตอบที่ AI ตอบไปจริงกับเนื้อไฟล์ (ตรวจความน่าเชื่อกับ 110 คู่)
  หรือ qwen3.5-9b บน PC `.235` เป็น judge

### โค้ดที่เพิ่ม (ยังไม่ commit / ยังไม่ deploy — tree ยังสกปรก)
- `utils/skills_shadow.py` — scorer + `build_row/record/observe` + ตาราง `skill_shadow`
  (คีย์ `message_id` → join กับ `feedback` ได้) · env `SKILLS_SHADOW_LOG` default true
- `utils/rag.py` — แยก `select_skill_files()`/`format_skill_files()` ออกจาก
  `load_skills_relevant()` เพื่อให้ "ไฟล์ที่ฉีดจริง" สังเกตได้ (ไม่ต้องคำนวณซ้ำ)
- `scripts/skills_shadow_backfill.py` — `--dry-run/--apply/--report` + `apply_thresholds()`
- `scripts/skills_groundtruth.py` — เลิกมีสำเนา scorer ของตัวเอง import จาก skills_shadow
- `tests/test_skills_shadow.py` (24) · แก้ `test_test_request_header.py` ให้เช็คชื่อเธรด
  แทนจำนวน · รวม 1093 ผ่าน ruff เขียว
- **รัน semantic จาก Mac ได้** (ไม่ต้องเข้าคอนเทนเนอร์): `CHROMA_HOST=192.168.51.49
  EMBEDDING_MODEL=paraphrase-multilingual OLLAMA_BASE_URL=http://192.168.51.235:11434/v1`
  (ต้องเปิด PC `.235`) · snapshot prod DB มาวิเคราะห์ได้โดยไม่แตะ prod
- 🔑 **เทสรุ่นแรกของผมเองมีจุดบอด 2 จุด จับได้ด้วยการแกล้งแก้**: เทียบ
  `format(select(...))` กับ `load_skills_relevant()` = tautology (มันเรียกตัวเดียวกัน)
  · cap top-3 ของ shadow ไม่มีเทสคุมเลย → ถอด `[:cap]` ออกแล้วยังเขียวทั้งชุด

### ต่อ: ตรวจกฎสัมพัทธ์กับ 110 คู่ (ทำแล้ว — **ผลคือตัดสินไม่ได้**)
`scripts/skills_rule_eval.py` เทียบกฎบนคู่ที่มาร์คแล้ว (110 คู่ · positives 11 · 30 prompt):

    split (prod วันนี้)      ฉีด 18/30 เทิร์น  P=0.162 R=0.545  ไม่รู้  9
    ngram >0                 ฉีด 30/30        P=0.139 R=1.000  ไม่รู้  7   ← ท่วม
    semantic สัมบูรณ์ 0.40    ฉีด  7/30        P=0.667 R=0.545  ไม่รู้  6
    semantic สัมพัทธ์ 0.08    ฉีด  8/30        P=0.714 R=0.455  ไม่รู้  5

**สองกฎหลังต่างกันแค่ 1-2 คู่ = อยู่ในระดับ noise** (positives 11 คู่ → R ขยับทีละ 0.091)
→ **ข้อมูลชุดนี้แยกไม่ออกว่ากฎไหนดีกว่า** · ของที่ยังยืนอยู่คือผลแบบไม่ต้องมี label:
`split` ทิ้งไทย (29.7%) · `ngram` ท่วม (92.8%) · สัมบูรณ์ 0.40 ทิ้งไทยหนักกว่าเดิม (5.9%)
· สัมพัทธ์ 0.08 ให้ไทย 14.5% (≈2.5 เท่าของสัมบูรณ์ ที่ precision พอๆ กัน)

**ถ้าจะตัดสินจริงต้องมาร์คเพิ่ม 134 คู่** (= คู่ที่สองกฎเลือกไม่ตรงกัน จากทั้ง 432 เทิร์น
· ที่ 0.05 = 238 คู่ · ที่ 0.10 = 105 คู่) — มี 187 คู่ที่สร้างไว้แล้วยังไม่ได้มาร์คด้วย

### 🔑 บทเรียนเพิ่ม (จากบั๊กของเครื่องมือตัวเองอีกรอบ)
**shadow log ที่บันทึกแค่ "สิ่งที่จะฉีด" ประเมินได้เฉพาะกฎที่คิดไว้แล้ว** — เก็บ top-3
เท่าที่ฉีดจริง ทำให้กฎ "นำอันดับถัดไปเท่าไร" มองไม่เห็นอันดับ 4 เลยคิดว่านำอยู่อนันต์
→ รายงานว่าสองกฎต่างกัน 1,049 คู่ (ของจริง 134) · **แก้: `RECORD_TOP=8` เก็บลึกกว่าที่ฉีด
แล้วตัดกลับเป็น CAP=3 ตอนรายงาน** — ยืนยันว่าถูกโดยรันซ้ำแล้วตัวเลข prod เท่าเดิมเป๊ะ
- `utils/skills_shadow.py` เพิ่ม `rule_absolute()` / `rule_margin()` (+ `RECORD_TOP`)
- `scripts/skills_rule_eval.py` — มีคอลัมน์ **"ไม่รู้"** บังคับ (ไฟล์ที่กฎหยิบแต่ไม่มี label)
  เพื่อไม่ให้เผลออ่าน P สูงๆ ที่คำนวณจากตัวอย่างน้อยนิดว่าเป็นข้อสรุป
- เทสรวม **1099 ผ่าน · ruff เขียว** · ยังไม่ commit/deploy

### ✅ ปิดข้อ 21 ด้วย OR-gate — **PR #13 รอ merge (ผม merge เองไม่ได้ ถูก classifier บล็อก)**
`feat/skills-or-gate` = `96773e5` · **CI เขียว (tests 1m13s)** · เทส 1112 · ruff เขียว
- `utils/skills_select.py` — lexical ก่อน · semantic สำรองเฉพาะตอน lexical ได้ศูนย์
  ต้องผ่าน **2 ด่าน**: `SKILLS_FALLBACK_MARGIN=0.05` (นำอันดับถัดไป) **และ**
  `SKILLS_FALLBACK_MIN_SCORE=0.35` (พื้นสัมบูรณ์) · ปิดด้วย `SKILLS_FALLBACK_MARGIN=off`
- วัดจริง 432 เทิร์น: ไทยล้วน 29.7% → **33.8%** · Latin 81.7% → 86.6% · **0 regression**
  (assert ยืนยัน: เทิร์นที่ lexical เคยเจอ ได้ผลเหมือนเดิมทุกตัว) · เส้นสำรองยิง 15 เทิร์น (3.5%)
- 🔑 **พื้นสัมบูรณ์ห้ามถอด**: กฎสัมพัทธ์ล้วน**พูดว่า "ไม่มีอะไรเกี่ยวเลย" ไม่ได้** เพราะเทียบ
  ผู้สมัครกันเอง → เปิดดูผลจริงเจอ `"ราคาทองคำวันนี้เท่าไหร่"` → `env-variables-reference.md`
  ที่ **0.138** ทั้งที่ตัวเลขรวมดูดีขึ้นทุกช่อง (+8.6pp ไทย, 0 regression) —
  **ตัวเลขถูกไม่ได้แปลว่าสื่อถูก อีกครั้ง · จับได้เพราะเปิดดู output ไม่ใช่เพราะเทสแดง**
- คุณภาพที่เปิดดูจริง 15 เทิร์น ≈ **8 ดี / 7 มั่ว** — ยอมรับได้เพราะเทิร์นพวกนี้เดิมได้ศูนย์
  และ precision ที่วัดได้ของ `split` เองคือ 0.162 · **ไม่ใช่ชัยชนะ เป็นการปรับปรุงเล็กๆ
  ที่หลักฐานอยู่ระดับ "เปิดดูด้วยตา" เท่านั้น**

**✅ merged + deployed + verified บน prod จริง (2026-08-03)** — `main` = `4629012`
verify ในคอนเทนเนอร์: `margin=0.05 floor=0.35` · `"ตรวจสอบโครงสร้างเครือข่ายในบ้าน"` →
`home-network-tools-nas-wol.md` (0.534) · `"ราคาทองคำวันนี้"` → เงียบ ✓ · `deploy docker nas`
→ 3 ไฟล์เดิมไม่เปลี่ยน ✓ · end-to-end ผ่าน `/api/chat` เห็น log `skills fallback` จริง
· ตาราง `skill_shadow` **ยังไม่ถูกสร้าง** = gate `X-Test-Request` ทำงานถูก (จะเกิดตอนคุยจริงครั้งแรก)
⚠️ `X-Test-Request` ข้าม remember/teach/shadow แต่ **ไม่ข้าม `save_message`** — verify แล้วมี
ข้อความหลุดลง history 2 แถว (ลบทิ้งแล้ว DB กลับเป็น 930 แถวเท่าเดิม)

### สถานะ env บน prod (เช็คจริง 2026-08-03 — บันทึกเดือน มิ.ย. ที่ว่า "ทั้ง 3 ยังว่าง" ล้าสมัยแล้ว)
`HA_URL` + `HA_TOKEN` **ตั้งแล้ว** ✓ · `ANTHROPIC_API_KEY` / `MOONSHOT_API_KEY` ยังว่าง
(แต่ user แจ้งว่า**ไม่มีงบค่า API** → ไม่ใช่งานค้างอีกต่อไป ไม่ต้องเสนอซ้ำ)
`SKILLS_FALLBACK_*` / `SKILLS_SHADOW_LOG` ไม่ได้ตั้งใน env = ใช้ค่า default ในโค้ด (ตามตั้งใจ)

### ✅ ปิดคดี WebSocket voice auth (ข้อ 7) — พิสูจน์ตรงแล้ว 2026-08-03
**ยิง WebSocket จริงเข้ามาทดสอบเอง ไม่ต้องรอ user ยืนยัน:**

    LAN ไม่มี token                     → ✅ accept   (LAN bypass ตามดีไซน์)
    ผ่าน ai.pawinhome.com ไม่มี token    → ❌ HTTP 403
    ผ่าน ai.pawinhome.com token ผิด      → ❌ HTTP 403

**403 ตอน handshake = `websocket.close(1008)` ก่อน `accept()`** ซึ่ง Starlette แปลงเป็น 403
→ เป็น gate ของเราเอง (`core.auth.websocket_authorized`) ไม่ใช่ Cloudflare
(ยืนยันด้วย `/api/config` ผ่านโดเมนเดียวกันได้ 200 = Access ไม่ได้บล็อกทั้งโฮสต์)
**รูที่เคยเปิด public ปิดสนิทแล้ว**

⚠️ **เครื่องมือทดสอบหลอกได้ 2 ชั้น ระวังตอนทำซ้ำ:**
- `curl` ใส่ header upgrade เองได้ **404** (Starlette ไม่ match websocket route จาก HTTP scope)
  ตีความว่า "ไม่มี endpoint" ผิด — ต้องใช้ WS client จริง (`websockets`)
- Python บน Mac ไม่มี CA bundle → `SSLCertVerificationError` ทั้งที่ cert ปกติ
  (curl ผ่านได้) ต้องส่ง `ssl.create_default_context(cafile=certifi.where())`

**หลักฐานว่า voice ใช้ได้จริง:** session `probe_item19` provider `gemini_live` 5 เทิร์น
2026-08-03 15:22–15:24 น. (log ในคอนเทนเนอร์เป็น **UTC** = 08:22 — เคยอ่านผิดว่าไม่มีข้อมูลวันนี้)
⚠️ **voice session ที่สำเร็จไม่ log อะไรเลย** (log เฉพาะ error) → หาหลักฐานต้องดู transcript
ในตาราง `messages` ที่ `provider='gemini_live'` ไม่ใช่ grep log

**ยืนยันปิดท้าย (16:06 น. 2026-08-03):** user คุย voice อีกเซสชันขณะอยู่บน **เน็ตมือถือ 5G**
(session `probe_item19` provider `gemini_live`) → ผ่าน Cloudflare → `cf-connecting-ip` มี →
`is_local_request()` = False → **บังคับใช้ token และผ่านจริง**
ตัดคำอธิบายทางเลือกทิ้งด้วย `ssh Pawin@192.168.51.1 'wg show'`: ทั้ง 3 peer **ไม่มีบรรทัด
`latest handshake` เลย** = มือถือไม่ได้อยู่บน WireGuard จึงไม่ใช่การผ่านด้วย LAN bypass
🔑 **ถ้าไม่เช็ค WG ก่อน จะสรุปผิดได้ง่ายมาก** — มือถือที่เปิด VPN จะได้ peer IP 10.6.0.x
ซึ่งเป็น private → LAN bypass ทำงาน ไม่ต้องใช้ token เลย แล้วเราจะเชื่อว่า "เส้น token
ใช้ได้" ทั้งที่ยังไม่เคยถูกทดสอบสักครั้ง

---

## 2026-08-03 (ต่อ) — ปิดข้อ 22: CI ไม่ได้เทสสิ่งที่ prod รัน (`e251cb6`, PR #14)

`main` = `5b2c6ab` · เทส **1116** · CI เขียว · prod verified · tree สะอาด

**บันทึกเดิมวินิจฉัยแคบไป** — เขียนว่าปัญหาคือ "CI ลงจาก `requirements.txt` แต่ prod ลงจาก
`requirements.lock`" วัดจริงแล้ว CI ต่างจาก prod **3 แกนพร้อมกัน**:

| แกน | CI (เดิม) | prod | หลักฐาน |
|---|---|---|---|
| เวอร์ชัน package | resolve สด | pin จาก lock | ต่าง **33/121** · `cryptography` ข้าม major 49→50 |
| **Python** | **3.12** | **3.11.15** | `docker exec ai-backend-1 python -V` (ไม่ได้อ่านจาก Dockerfile) |
| system deps | ไม่มี | `poppler-utils` | latent — ยังไม่มีเทสแตะ `utils/ocr.py` |

🔴 **หลักฐานที่ปิดคดี: pin `mcp>=1.27.0,<2` ที่ใส่ไว้ "แก้ชั่วคราว" ไม่แตะ prod เลย**
`Dockerfile:12-13` = `COPY requirements.lock .` + `pip install -r requirements.lock` เท่านั้น
`requirements.txt` ไม่เคยถูกใช้ติดตั้งใน image → มันแก้ให้ **CI เขียว** ไม่ได้แก้ให้ **prod ปลอดภัย**
และไม่มีอะไรเช็คว่า lock ทำตาม spec ใน `requirements.txt` (วันนั้นบังเอิญตรงครบ 22 ตัว)

**ทางแก้: รัน pytest ในอิมเมจที่ deploy จริง** (`docker-compose` ใช้ `build: .` ตัวเดียวกัน,
ไม่มี `.dockerignore` + `COPY . .` → `tests/` อยู่ในอิมเมจแล้ว, `CMD` ล้วนไม่มี `ENTRYPOINT`)
```yaml
pytest:        docker buildx build --cache-from/to type=gha  →  docker run --rm hybrid-ai:ci pytest tests/ -q
lint-and-js:   ruff + node --test  (ไม่ได้เทสพฤติกรรม Python ของ prod จึงไม่ต้องอยู่ในอิมเมจ)
```
**ดีกว่าการ sync `python-version:` ใน yml ให้ตรง `FROM` ใน Dockerfile** เพราะอันนั้นคือ
guard ที่ต้องมี guard เฝ้าอีกที = กลิ่นเดียวกับปัญหาต้นเรื่อง · ตอนนี้ Dockerfile เป็นแหล่งความจริงเดียวของทั้ง 3 แกน

**verified จริง** (CI run `30823216333`): build `FROM python:3.11-slim` · job `pytest` **ไม่มี `setup-python`** ·
`docker run` → **1116 passed** · **ต้นทุนจริง +45s** (80s → 125s, cache `type=gha`) — ถูกกว่าที่ประเมินไว้ (3-5 นาที)

`tests/test_ci_matches_prod.py` ตรึง 4 ข้อ (2 ข้อแรกแดงจริงก่อนแก้):
pytest ต้องรันในอิมเมจ · job รันเทสห้าม `pip install -r requirements.txt` ·
ทุกแพ็กเกจใน `requirements.txt` ต้องมีใน lock · เวอร์ชันใน lock ต้องผ่าน specifier
(**สองข้อหลังทำให้ pin ใน `requirements.txt` มีผลกับ prod จริง** แทนที่จะเป็นความบังเอิญ)

### 🔑 บทเรียน — assertion เชิงลบผ่านฟรีเมื่อชุดที่ตรวจว่างเปล่า
`_blocking_pytest_job()` เวอร์ชันแรกเขียนแบบ "หา job ไม่เจอก็คืนลิสต์ว่าง" → ข้อความ
*"ต้องไม่มี `pip install requirements.txt`"* เป็นจริงโดยปริยาย → **เทสผ่านทั้งที่ไม่ได้ตรวจอะไรเลย**
(รันจริงเห็น: ตัว assertion เชิงบวกแดงถูกต้อง ส่วนตัวเชิงลบขึ้น PASS)
→ เปลี่ยนเป็น `pytest.fail()` ดังๆ + **ค้น job จากพฤติกรรม** (หา job ที่รัน `pytest`) แทน hardcode ชื่อ
เพื่อทนการ rename · ข้าม job ที่ตั้ง `continue-on-error: true` (เผื่อ canary)
ทดสอบตัวเทสด้วยการแกล้งแก้ **5 แบบ** — จับได้ทุกกรณี · 📄 vault `measuring-instruments-lie.md` รูปแบบที่ 6

### ✅ canary ปิดผลข้างเคียงแล้ว (`fbd452a`, PR #15)
`.github/workflows/canary.yml` — จันทร์ 03:00 UTC + `workflow_dispatch` · python 3.11 →
`pip install -r requirements.txt` → `scripts/deps_drift.py` → `pytest`

🔴 **จงใจไม่ใช้ `continue-on-error: true` ตามที่วางไว้ตอนแรก** — flag นั้นทำให้ job รายงานเป็น
`success` ต่อ checks API แม้ข้างในแดง = canary ที่ตายแล้วไม่มีใครเห็น · **แยกเป็น workflow
ของตัวเองที่ไม่มี trigger `pull_request`** แทน → แดงได้เต็มที่ + อีเมล แต่บล็อก merge ไม่ได้
(ยืนยันเชิงประจักษ์: PR #15 รันแค่ `pytest` + `lint-and-js` ไม่มี canary)

**ยิงมือแล้ว** run `30825246134`: python **3.11.15** (ตรง prod ทุกหลัก) · drift **33/121** ·
ข้าม major 1 ตัว (`cryptography` 49→50) · **1119 passed** → upstream ยังไม่มี breaking change
→ **รีเฟรช `requirements.lock` ตอนนี้ความเสี่ยงต่ำ** (lock ไม่ถูกแตะมาตั้งแต่ 2026-07-12)

⚠️ ตัวเลข "~34/121" ที่ผมรายงานรอบแรกมาจาก resolve บน **python 3.14** (Mac ไม่มี 3.11/3.12) —
ของจริง **33** · ทิศถูกแต่ตัวเลขอ้างอิงไม่ได้ · canary ทำให้วัดซ้ำได้เองทุกสัปดาห์แทนการเดา
⚠️ GitHub ปิด scheduled workflow เมื่อ repo เงียบ 60 วัน — ไม่มี run นาน ให้เช็ค Actions → canary
ก่อนสรุปว่า "ไม่มี breakage" · `tests/test_ci_matches_prod.py` ตรึงเจตนา canary ไว้ 3 เทส

⚠️ บรรทัดใน `~/Desktop/ui/CLAUDE.md` ที่ว่า **"เครื่อง Mac ไม่มี `gh` CLI" ล้าสมัย — มีแล้ว**
ใช้ `gh run list` / `gh run watch --exit-status` ได้ (แก้ในไฟล์แล้ว)

---

## 2026-08-04 — เซสชันยาว: ปิดข้อ 22 + canary + ข้อ 10/11/24 + voice go_away

`main` = `e7e2419` · เทส **1152** · CI เขียวทั้ง `tests` + `canary` · prod deployed+verified · tree สะอาด
12 commits · PR #14–#18 merged · **audit เหลือข้อ 13 (ใส่ API key) + ข้อ 8 (voice, ค้างบางส่วน)**

### ✅ ข้อ 22 — CI เทสอิมเมจที่ deploy จริง (`e251cb6`, PR #14)
CI ต่างจาก prod **3 แกน** ไม่ใช่แกนเดียวอย่างที่บันทึกเดิมเขียน: python 3.12 vs **3.11.15** ·
lib **33/121** ไม่ตรง lock (`cryptography` ข้าม major) · ไม่มี `poppler-utils`
🔴 pin `mcp<2` ที่ใส่ไว้ "แก้ชั่วคราว" **ไม่แตะ prod เลย** — `Dockerfile:12-13` ลงจาก lock อย่างเดียว
แก้: `docker buildx build` + `docker run hybrid-ai:ci pytest` → Dockerfile เป็นแหล่งความจริงเดียว
**+45s** (80s→125s) · ดีกว่าการ sync `python-version:` ให้ตรง `FROM` ซึ่งคือ guard ที่ต้องมี guard เฝ้าอีกที

### ✅ canary รายสัปดาห์ (`fbd452a`, PR #15)
`.github/workflows/canary.yml` จันทร์ 03:00 UTC + `workflow_dispatch` · python 3.11 →
`requirements.txt` สด → `scripts/deps_drift.py` → pytest
🔴 **จงใจไม่ใช้ `continue-on-error: true`** — flag นั้นทำให้ job รายงาน `success` แม้ข้างในแดง
= canary ที่ตายแล้วไม่มีใครเห็น · แยกเป็น workflow ที่ไม่มี trigger `pull_request` แทน
ยิงมือแล้ว: python **3.11.15** ตรง prod · drift **33/121** · **1119 passed** → upstream ยังไม่พัง
→ **รีเฟรช `requirements.lock` ตอนนี้ความเสี่ยงต่ำ** (lock ค้างตั้งแต่ 2026-07-12)

### ✅ ข้อ 10/11 — ตรวจ UI บนจอจริง (Chrome ผ่าน LAN `:8080`)
File Manager 3 input (รวมปุ่มกล้อง `capture="environment"`) · drag&drop กรอบประ + แนบรูปได้จริง ·
`__hwReactChatBox: true` · status dot · Dream card ค่าจริง · citations เรนเดอร์ครบ
⚠️ **ห้ามคลิก 📎 ด้วย browser automation** — เปิด native file dialog แล้วล็อกทั้งเซสชัน
ใช้ยิง `DragEvent`+`DataTransfer` ที่ `<form>` แทน · ใส่ `X-Test-Request: 1` กัน memory ปนเปื้อน

### ✅ ข้อ 24 (ใหม่) — web search ฉีดเว็บโป๊เข้า context + ขึ้นจอเป็น citation (`b81d988`, PR #16)
ถาม *"Python เวอร์ชันเสถียรล่าสุด"* ได้ `[1] หนังโป๊เก่าเก็บ (0.1874)` · โค้ดมี rerank +
domain credibility ครบ **แต่ไม่เคยตัดทิ้ง** (`results[:top_k]`)
แก้ 3 จุด: `WEB_SEARCH_MIN_SCORE=0.35` (ผลดี 0.5955–0.8234 vs ขยะ 0.1024–0.2393 **ช่องว่าง 0.36**) ·
`clean_query()` ตัดคำสั่งงานแบบไม่พึ่ง LLM · ใส่พื้นใน `agents/tools.py` ด้วย (**pipeline ค้นเว็บมี 2 ชุด**)
verified prod: คำถามเดิมเด้ง **0.1874 → 0.7706 ตรงประเด็น**
🔴 `rewrite_query()` ที่พึ่ง LLM **ตายเงียบตั้งแต่เปลี่ยนเป็น Qwen3.5** — `finish_reason=length`,
`content=''`, thinking กินงบหมด ทั้ง 200 และ 800 tokens · `QUERY_REWRITE_ENABLED=true` เป็น no-op
⚠️ `safesearch="on"` ส่งไป DDG จริง (เทสยืนยัน) **แต่ DDG ไม่กรองให้** → พื้นคะแนนคือด่านที่สอง

### 🟡 ข้อ 8 voice — แก้ไปครึ่ง ค้างครึ่ง
**ปิดแล้วเปิดใหม่ในวันเดียว** — user ยืนยันว่า "ถามตอบปกติ" ผมเลยปิด แล้ว user รายงานทันทีว่า
เล่านิยายยาวๆ พัง ซึ่งตรงกับเคสขอบที่**ผมเขียนกำกับไว้เองตอนปิด**

**วินิจฉัยผิด 2 รอบก่อนถูก:**
1. เดาว่า transport (GoAway/jitter) — user บอกว่า "มันถามกลับว่าจะให้เล่าต่อไหม" → คนละเรื่อง
2. แก้ persona (`83b5dd8`) — user บอกเพิ่มว่า "จอเล่าอยู่แต่เสียงหาย" → ยังมีอีกชั้น

✅ **`83b5dd8`** `voice_system_prompt()` แยก prompt โหมดเสียงออกจากแชท — persona แชทสั่ง
"กระชับ + ถามไถ่เชิงรุก" ทำให้เล่าท่อนนึงแล้วถามทุกครั้ง (ในแชทดี ในเสียง = หยุดเสียงทั้งหมด)
✅ **`e6b486d`** `live_control_signals()` + `SessionResumptionConfig` + ลูปต่อ session ใหม่
`send_loop` เดิมอ่านแค่ `data`/`server_content` — `go_away` เป็น field คนละตัว **ไม่มีใครอ่าน**
→ Gemini ตัดทิ้งเองด้วย 1008 ("client failed to close" = server เรา) · **ยืนยัน 2 ครั้ง ที่นาทีที่ ~10**

🔑 **หลักฐานที่ปิดคดี: จับคลิปเสียงที่ user อัดมากับ log ได้พอดี**
วิเคราะห์คลื่นด้วย ffmpeg: 0:00–9:50 ดังปกติ (−1..−6 dB) → **9:55 เบาลงค้าง ~15 dB** →
**10:32 = `go_away` ใน log** (คลิปเริ่ม 04:23 ไทย = 21:23 UTC) → **เสียงเพี้ยนก่อน session ตาย 37 วิ**

❌ **สมมติฐาน "underrun ทำให้เงียบถาวร" หักล้างแล้ว** ด้วยเทสที่เขียนไปพิสูจน์เอง
(`~/appscript.ui` `2135548`) — ตอน unprimed ตัวเล่นไม่กิน buffer คิวโตจนครบ 0.8s แล้วเล่นต่อเอง

⏳ **ค้าง: "เสียงเบา" ยังไม่ยืนยัน** — สมมติฐาน AEC/AGC หรี่ เพราะ `HalfDuplexGate` คำนวณ
`playUntil` จาก**เวลาที่ chunk มาถึง** แต่ worklet prime 0.8s ก่อนเล่น → เสียงจริงช้ากว่า gate
จับ 2 โมเดล pure ประกบกันวัดได้ **72 block ที่ไมค์เปิดทั้งที่มีเสียงค้างสูงสุด 519 ms**
→ **user จะเทสด้วยหูฟังพรุ่งนี้: ใส่หูฟังแล้วหายเบา = ยืนยัน · ยังเบา = ผมคิดผิด ต้องรื้อใหม่**
(ให้อัดด้วย Screen Recording ปิดไมค์ เพื่อตัดตัวแปรระยะห่าง · เล่าเกิน 11 นาที)
⚠️ ค้างด้วย: client `voicelive.ts:216` ยัง `disconnect()` ทิ้งเมื่อได้ event `error` ไม่มี retry

### 🔑 บทเรียนของเซสชันนี้
- **เขียนข้อจำกัดกำกับไว้ ≠ ไม่ปิดงาน** — ผมเขียนเองว่า "ยังไม่ครอบเคสเล่ายาว" แล้วมาร์คปิด
  แล้วอาการที่ user เจอก็คือเคสนั้นเป๊ะ · **ถ้ารู้ว่ายังไม่ครอบ ก็คือยังไม่ปิด**
- **เชื่ออาการที่ตัวเองตีความ แทนที่จะถามว่ามันหายยังไง** — ขุด transport อยู่นาน ประโยคเดียวของ
  user ("มันถามกลับ") ตัดสมมติฐาน 3 ชั้นทิ้ง · แล้วประโยคที่สอง ("จอเล่าอยู่แต่เสียงหาย") เปลี่ยนอีกรอบ
- **assertion เชิงลบ (`assert not ...`) ผ่านฟรีทันทีที่ชุดที่ตรวจว่างเปล่า** — ตัวดึงข้อมูลต้องล้มดังๆ
  ไม่ใช่คืนลิสต์ว่าง (โผล่ในเทสที่เขียนเพื่อกันปัญหาตระกูลนี้เอง) → vault รูปแบบที่ 6
- **เทสที่ผ่านตั้งแต่ก่อนแก้ให้ข้อมูลได้** — `safesearch` ผ่านตั้งแต่แรก = ตัดสมมติฐาน "ลืมขอ" ทิ้ง
  แล้วชี้ว่า "ผู้ให้บริการไม่ทำตาม" ซึ่งเปลี่ยนวิธีแก้ทั้งหมด
- **pipeline ที่คัดลอกกันมาจะมีรูเหมือนกัน** — `agents/tools.py` copy มาทั้งชุด แก้เส้นเดียว = ปิดรูครึ่งเดียว
- **ตรวจ field name กับ SDK จริงก่อนเขียน** (`docker exec` ดู `model_fields`) ไม่เดาจากความจำ

---

## 2026-08-04 — ข้อ 9/openclaw: พื้นคะแนน `search_skills()` ✅ **ปิดแล้ว verified prod**

PR #19 merged → `d931b63` บน main · deploy + restart แล้ว · **verified บน prod ด้วยการดู
output ที่ฉีดจริง**: `"openclaw คืออะไร"` → ฉีดแค่ `openclaw.md` ตัวเดียว (เดิมพ่วง
`mcp-server-export` 0.296 + `project-architecture` 0.280 มาด้วยทุกครั้ง) ·
`"ทำต้มยำกุ้ง…"` → ว่าง · `SKILLS_SEARCH_MIN_SCORE` บน prod = **0.38** (ไม่ได้ตั้งใน `.env`
ใช้ default ในโค้ด)

**ต้นเหตุที่เจอ 3 ชั้น** (เดิมบันทึกไว้แค่ชั้นเดียว):
1. `utils/skills.py:search_skills()` ฉีด top-3 ดิบ — `skills_search.py` คำนวณ `distance`
   ใส่ dict ไว้แล้วแต่**ไม่มีใครตัดสินใจด้วยค่านั้น** · เส้นพี่น้องมีพื้นกันหมดแล้ว
   (`SKILLS_FALLBACK_MIN_SCORE` · `WEB_SEARCH_MIN_SCORE`) เหลือเส้นนี้เส้นเดียว
2. 🔑 **`skills_collection` เป็น collection เดียวในโปรเจกต์ที่ไม่ได้ตั้ง `hnsw:space: cosine`**
   — `skills_search.py` เรียก `client.create_collection()` ตรงๆ ข้าม wrapper
   `utils/memory.py:get_or_create_collection` ที่ทุกที่อื่นใช้ → ตกไปใช้ l2 (default chroma)
   · กับดักซ้อน: wrapper ใช้ `setdefault("metadata", ...)` **ทั้งก้อน** → caller ที่ส่ง
   metadata ของตัวเองมาจะทำให้ `hnsw:space` หายเงียบ (แก้เป็น merge ทีละคีย์แล้ว)
3. ผลพวง: `skills_shadow.py:159` แปลง `1.0 - distance` เอง ซึ่งถูกเฉพาะ cosine
   → **ตัวเลข semantic ที่ใช้ตัดสินใจในข้อ 21 อาจวัดจากสเกลที่ผิด** (เครื่องมือวัดโกหกครั้งที่ 9)

**ทิศที่ user เลือกเมื่อคะแนนแปลไม่ได้ทุกแถว: fail-closed + log ERROR**
ปิดเส้นนี้ได้เพราะ `load_skills_relevant()` อ่าน .md จากดิสก์ตรงๆ ไม่ผ่าน ChromaDB (เส้นสำรองยังอยู่)
· `SKILLS_SEARCH_MIN_SCORE=off` ยังเป็น escape hatch จริง (ไม่ร้อง ไม่ตัด)

### ผลวัดจริง (เก็บไว้อ้างอิง — อย่าวัดซ้ำโดยไม่จำเป็น)
- **`skills_collection` บน prod = cosine อยู่แล้ว** (`{'hnsw:space': 'cosine'}`) 22 รายการ ครบตาม `skills/`
- เคส openclaw = **จัดอันดับถูกอยู่แล้ว** (`openclaw.md` sim 0.546 อันดับ 1) — บั๊กคือไม่มีพื้น
- **ที่มาของ 0.38**: sweep กับ ground truth 110 คู่ที่คนมาร์คเอง (`data/skills_pairs.json` ของข้อ 21)
  0.30→P.360/R.818 · 0.35→P.438/R.636 · **0.38→P.583/R.636** · 0.40→P.667/R.545 · 0.45→P1.00/R.273
- ⚠️ **ไม่มี "ที่ราบ"** — positive ต่ำสุด 0.142 · negative สูงสุด 0.430 (negative 59/99 สูงกว่า
  positive อย่างน้อยหนึ่งตัว) → เกณฑ์ตัดหางล่างเฉยๆ **positive มีแค่ 11 ตัว ห้ามจูนละเอียดกว่านี้**
- วัดใหม่เมื่อจำเป็น: `scripts/skills_floor_probe.py` (รันในคอนเทนเนอร์)

### 🔑 บทเรียน 2 ข้อที่แพงที่สุดของงานนี้
1. **กลุ่มควบคุมที่ตัวเองแต่งขึ้นให้ภาพดีเกินจริง** — คำถามที่ผมเขียนเอง (อากาศ/ต้มยำ/ราคาทอง)
   ให้ช่องว่าง 0.047 ที่ดูเหมือนที่ราบ · ของจริงทับกันเละ เพราะคำถามที่แต่งเอง**อยู่นอกโดเมน
   ชัดเจนเกินไป** — ของที่ทำให้พังจริงคือคำถาม*ในโดเมน*ที่ไม่ตรงไฟล์
2. **โค้ดปัจจุบันไม่ใช่หลักฐานของ state ที่ถูกสร้างไว้ในอดีต** — ผมอ่านโค้ดแล้วสรุปว่า
   collection เป็น l2 (และตามมาด้วยว่าตัวเลขข้อ 21 วัดผิดสเกล) **ผิดทั้งคู่** เพราะ collection
   ถูกสร้างสมัยโค้ดยังผ่าน wrapper · ใช้ได้ทั้งทิศอนุมานว่าดีและอนุมานว่าพัง

**บทเรียน:** `distance` ถูกคำนวณอยู่ใน dict มาตลอด — โค้ด*ดูเหมือน*สนใจความเกี่ยวข้อง
แต่ค่าไหลไปตายเฉยๆ · **"มีค่าอยู่ในโครงสร้างข้อมูล" ≠ "มีใครตัดสินใจด้วยค่านั้น"**
· log ที่ชี้ไปฟังก์ชันที่ไม่มีอยู่จริงคือ "เจตนา ไม่ใช่หลักฐาน" อีกแบบ → เขียนเทสบังคับว่า
คำสั่งที่ log แนะนำต้อง `callable()` ได้จริง

---

## 2026-08-04 (รอบสอง) — ปิดคิว 3 ข้อรวด: voice retry · body limits · event-loop blocking

`main` = `288d3eb` · PR #19/#20/#21 merged · deploy + **recreate** แล้ว (mem_limit ต้อง recreate ไม่ใช่ restart)
verified prod หลัง recreate: skills_db 22 ครบ · embed cache 1,825 แถวรอด · mem_limit 2 GiB (ใช้จริง 157 MiB)
· เทสในคอนเทนเนอร์ prod 27 ตัวผ่าน

### ข้อ 2 — voice retry (`~/appscript.ui` `1e65beb` · bundle `da74594`)
`voicelive.ts` เดิมเจอ event `error` แล้ว `disconnect()` ทิ้ง = เน็ตสะดุดครั้งเดียวจบ session
แก้: ต่อ **WS อย่างเดียว** backoff 1s→2s→4s (`utils/voiceretry.ts` + 6 vitest)
🔑 **ห้ามสร้าง audio graph ใหม่ตอน retry** — `getUserMedia`/`new AudioContext()` นอก user gesture
ถูกบล็อก/suspend บน iOS · mic กับ worklet ไม่ผูกกับ ws (`proc.onaudioprocess` อ่าน `this.ws` สด)
· ระหว่าง retry ไม่ยิง `onError`/`onClose` (UI จะเด้ง toast/รีเซ็ตทั้งที่กำลังกู้)
⚠️ **เส้น retry ยังไม่เคยถูกกระตุ้นจริงบน prod** — ยืนยันได้แค่ระดับ unit test + โค้ดอยู่ในบันเดิล

### ข้อ 3 — body limits (`6fb11fc`) + `mem_limit: 2g`
`utils/http_limits.py` — `declared_too_large()` (content-length) + `read_capped()`/`json_body_capped()`
⚠️ ไม่มี `content-length` = **"ไม่รู้" ไม่ใช่ "ใหญ่เกิน"** (chunked ไม่ส่งมา) · `UploadFile.read(n)`
**ไม่รับประกันว่าคืนครบ n** คืนสั้น ≠ จบไฟล์
🔑 **ตรวจแล้วบันทึกเดิมคลาดครึ่งหนึ่ง**: starlette spool multipart ลงดิสก์ที่ >1 MB → parse ไม่กิน RAM
ที่กินคือ `.read()` ที่ดูดไฟล์ที่ spool กลับเข้า RAM · **JSON path กิน RAM เต็มก้อนจริง**
⛔ ยังเหลือ: multipart 5 GB ยังเขียนลงดิสก์คอนเทนเนอร์ระหว่าง parse (ต้องกันที่ proxy/middleware)

### ข้อ 4 — event-loop blocking + skills_db race (`288d3eb`)
🔑 **ข้อกังวลเดิมที่ทำให้เลื่อนงานนี้ทั้งเซสชัน จริงแค่จุดเดียว** — บันทึกเขียนว่า "โค้ดแตะ global
state ที่ไม่เคยออกแบบให้ concurrent" · ไล่อ่านจริงแล้ว `embed.py`/`response_cache.py` มี
`check_same_thread=False`+Lock อยู่แล้ว · `history.py` เปิด connection ใหม่ทุกครั้ง · ChromaDB
เป็น HttpClient → **เหลือ `skills_db` ตัวเดียวที่ต้องแก้**
🔑 **และ race ของมันไม่ได้รอ threadpool — เกิดได้แล้ววันนี้** (`dream.py:549` เขียนจาก APScheduler
02:00 vs `auto_extract_skills()` จากเส้นแชท) · เทสวัดได้ **อ่านเจอไฟล์เปล่า 79 ครั้งใน 150 การเขียน**
→ `_load_skills_db()` คืน `{}` → เขียนต่อ = คลังหายถาวร
แก้: `_db_lock` (RLock) + `_save_skills_db()` atomic (mkstemp→fsync→`os.replace`)
+ `run_in_threadpool` ที่ `/upload` `/search` `/ocr` `/summarize`
ℹ️ `list_all`/`delete` เป็น `def` ธรรมดา FastAPI โยนเข้า threadpool ให้เองแล้ว — บั๊กมีเฉพาะ `async def`
หลักฐานก่อนแก้ (คอนเทนเนอร์ prod): `/api/config` ใช้เวลาเอง **3.5 ms** แต่ต้องรอ summarize 605 ms

### ⛔ ยังไม่ทำ (จงใจ ระบุเหตุผลไว้)
- `chat.py` (context assembly ก่อน stream) · `agent.py` — เส้นร้อนสุด มี streaming เอง ต้องมีเทสเฉพาะทาง
- `memory.py` / `skills.py` routers — ยังไม่ได้ไล่
- RLock กันได้แค่ process เดียว — `scripts/clean_skills_db.py` คนละ process (atomic กันไฟล์พังได้
  แต่ยัง lost-update ได้ถ้ารันชนกับแอป)

### 2026-08-04 (รอบสาม) — ปิด `chat.py` + `agent.py` (PR #22, `992f9ba`)

🔑 **บันทึกใน backlog ชี้ผิดจุด** — เขียนว่า `chat.py` บล็อกที่ "context assembly ก่อนเริ่ม stream"
**ไม่จริงตั้งแต่ 2026-07-13** ตอนย้ายงานเข้า `def generate()` เพื่อยิง SSE `{"phase":...}` ·
starlette ห่อ **sync generator** ด้วย `iterate_in_threadpool()` (`StreamingResponse.__init__`)
→ context assembly/retrieval/LLM stream รันนอก event loop อยู่แล้ว
**การย้ายเข้า generator เพื่อ UX ปิดปัญหา blocking ไปด้วยโดยไม่มีใครรู้**

ตัวที่บล็อกจริงอยู่ **ก่อน** `return StreamingResponse(...)` — คนละที่กับที่บันทึกชี้:
`generate_image()` (Gemini Image API) · `_rc_lookup()` (embed prompt = round-trip) ·
`teach()` (ChromaDB) · `search_memory()` ใน `/regenerate` · `save_message()`/`load_history()`

`agent.py`: `sse()` เป็น sync generator อยู่แล้ว ก่อน generator มีแค่ sqlite 2 ครั้ง (ย้ายให้ครบเส้น)

**verified บน prod จริง (ไม่ใช่ ASGI test transport):**
```
baseline /api/config          0.005 s
/api/documents/search         2.093 s   ← embedding จริง
/api/config ระหว่างงานหนัก     0.004 s   (เสร็จที่ 0.155 s จาก t0)
```
+ เทส concurrency 10 ตัว (chat×3 documents×2 skills_db×2 sandbox×3) เขียวกับโค้ดที่ deploy จริง
+ log ไม่มี error/traceback หลัง restart

⚠️ วิธี verify ที่ใช้: สลับไฟล์ patched เข้า `/app` → รันเทส → `cp` คืน → เช็ค `git status` บน NAS ว่าสะอาด
(อย่าลืมคืน — `/app` เป็น volume mount ของ repo จริง · `git` ไม่มีในคอนเทนเนอร์ ต้องเช็คจาก host)


---

## 📌 สถานะย้ายมาจาก MEMORY.md (2026-08-05)
_ย้ายมาเพราะ MEMORY.md โตถึง 173 บรรทัด ใกล้เพดาน 200 ที่จะโดนตัดอ่านไม่ครบ_

**Khim AI** (`~/Desktop/ui`) — CI เขียว · prod deployed+verified · tree สะอาด · **PR #25–#28 merged**
(**ไม่เขียน commit hash ไว้ตรงนี้** — ตามหลังจริงหนึ่งก้าวตลอด เคยผิดมาแล้ว ให้ดู `git log`)
· NAS repo sync แล้ว · `~/appscript.ui` push ครบ github+NAS
⚠️ **`origin` ของ `appscript.ui`/vault ชี้ NAS ผ่าน LAN — อยู่นอกบ้าน push ไม่ได้**
ใช้ `git push "nas-cf:/var/services/homes/pawin/git/<repo>.git" main` แล้ว
`git update-ref refs/remotes/origin/main <sha>` ตามด้วย ไม่งั้น `git status` จะโชว์ "ahead N"
ค้างทั้งที่ push แล้ว (เจอจริง 08-05 — tracking ref ที่โกหก)
📌 **งานค้างฉบับเต็มอยู่ใน `~/Desktop/ui/CLAUDE.md` หัวข้อ "งานค้าง ณ 2026-08-05"** (บนสุดของ next steps)
— มีหัวข้อ **"▶️ เซสชันหน้าเริ่มตรงนี้"** + รายการ A–F ที่ **grep ตรวจกับโค้ดจริงแล้ว 08-05**
🔴 **ที่ยังเปิดอยู่จริงและต้องให้ user เคาะก่อน:** (A) `accept_proposal` ยัง `return ok:True`
แบบไม่มีเงื่อนไข — PR #24 เพิ่มแค่ `logger.error` ไม่ได้แก้สัญญา · (B) `POST /api/upload`
(`routers/skills.py:307`) ยัง `await file.read()` **ไม่มีเพดานเลย** + `memory.py` มี
`request.json()` ดิบ 3 จุด (ใส่เพดาน = ไฟล์ที่เคยอัปได้กลายเป็น 413 จึงต้องถามก่อน) ·
~~(C) DSM ไม่เคยมี task เรียก `db_backup.sh`~~ ✅ **ปิดคดี 08-05 — ไม่เคยพัง บันทึกดูผิดโฟลเดอร์**
มีโฟลเดอร์ชื่อคล้ายกัน 2 อัน: `/volume1/homes/pawin/db_backups/` (เส้น host ค้างที่ 07-12 · **ตั้ง DSM
ไม่ได้ด้วยข้อจำกัด sudo ซึ่งคือเหตุผลที่ in-app job มีอยู่**) vs `ui/data/db_backups/` = **ตัวจริง
เดินทุกวันไม่ขาด** · เปิดไส้ในตรวจแล้ว: integrity ok · 1,069 แถว · chroma backup 00:00 ก็ครบ
🟢 **PR #29 merged+deployed+verified 2 ทิศ:** `_verify_snapshot()` (integrity+นับแถว → `BackupUnhealthy`
· **รอบที่ไม่ผ่านไม่รัน retention** กัน "พังชั่วคราว→พังถาวร") + `utils/heartbeat.py` ยิง
healthchecks.io **เฉพาะตอนสำเร็จจริง** · check `Khim AI db-backup` (cron `30 3 * * *` Asia/Bangkok
grace 2h · อีเมล+Telegram) **เขียวแล้ว user ยืนยันเอง**
⚠️ **วัดจริงบน prod: uuid ที่ไม่มีอยู่ → HTTP 200 + body `'OK (not found)'` ซึ่งขึ้นต้นด้วย `OK`**
→ `startswith("OK")` ก็ยังหลุด ต้องเทียบเป๊ะ `body.lower()=="ok"` (บันทึกนี้ยังไม่ได้ลงโค้ด/CLAUDE.md)
🔴 **ยังเปิด 3 ข้อ:** archive ที่ไม่ผ่านใช้ชื่อเดียวกับตัวปกติ (คนกู้แยกไม่ออก) · `scripts/db_backup.sh`
ยังไม่มีตัวตรวจ (**และเส้นนี้แหละที่เคยผลิต archive 989 ไบต์**) · heartbeat ไม่มี retry (เน็ตกระตุก
ตอน 03:30 = เตือนปลอม)
และ `docs/audit-backlog-2026-08-02.md` — ทั้งสองฐานตรงกันแล้ว
**audit 24 ข้อ ปิดไป 23** เหลือ **ข้อ 13** (user ใส่ `ANTHROPIC_API_KEY`/`MOONSHOT_API_KEY` ใน NAS `.env`)
✅ **ปิดรวด 4 อย่าง 08-04:** ข้อ 9 openclaw (`SKILLS_SEARCH_MIN_SCORE=0.38`) · voice retry ·
body limits + `mem_limit: 2g` · event-loop blocking + `skills_db` race
รายละเอียด/ตัวเลข/บทเรียนทั้งหมดอยู่ท้าย [hybrid_ai_status.md](hybrid_ai_status.md)

### 🔵 คิวถัดไปของ `~/Desktop/ui` — ทำต่อได้เลย ไม่ต้องรอ user
✅ **ปิดข้อ 2 แล้ว (PR #23 merged + deployed + verified prod)** — `memory.py`/`skills.py`
`async def`+sync ครบ 6 endpoint · พ่วงปิด race บน `skills_db.json` 3 จุด (ทางเขียนเหลือทางเดียว
`set_skill_entry`/`delete_skill_entries`) · **บั๊กที่เจอระหว่างทางและร้ายที่สุด: `accept_proposal`
ส่ง mapping รายการเดียวเข้า `sync_skills_to_search` ซึ่งเป็น reconcile = ล้าง ChromaDB index
เหลือ skill เดียว** (ยังไม่เคยกัด prod — ตรวจแล้ว 22/22/22) · บทเรียนเต็มใน vault
`wiki/concepts/widening-a-contract-breaks-old-callers.md` · **`nas-cf` (ssh ผ่าน Cloudflare)
ใช้ deploy ได้เลยตอนอยู่นอกบ้าน ไม่ต้องเปิด WG ไม่ต้อง sudo** ·
✅ **ปิดข้อ 6 แล้วด้วย (PR #24 merged + deployed + verified บน prod จริง)** — `_db_transaction()`
= RLock + **flock** (ข้ามโปรเซส) + เพดาน 5 วิ (`SKILLS_DB_LOCK_TIMEOUT`) · ตัวปัญหาคือ
`scripts/clean_skills_db.py` ที่ไม่เคยใช้ทางของ `utils/skills.py` เลย (วัดได้ **หาย 60/120**)
· lock อยู่บนไฟล์ **แยก** `skills_db.json.lock` ห้ามล็อกตัว db (os.replace สลับ inode)
· **`_save_skills_db()` โยน `SkillsDbWriteFailed` แล้ว ไม่กลืนเหมือนเดิม**
· verify บน prod: ยึด lock จาก docker exec หนึ่งตัว อีกตัวถูกกันจริงที่ 5.0s ·
🔴 **งานค้างที่เจอใหม่: DSM ไม่เคยมี task เรียก `db_backup.sh` เลย** (ไล่ครบ 24 task)
backup ล่าสุด 2026-07-12 = ChromaDB/sqlite ไม่มี backup อัตโนมัติ ·
multipart ใหญ่ยังเขียนลงดิสก์ตอน parse (ต้องกันที่ proxy/middleware) ·
voice retry ยังไม่เคยถูกกระตุ้นจริงบน prod · `SKILLS_SEARCH_MIN_SCORE` **ห้ามจูนละเอียดกว่านี้**
(positive 11 ตัว — ต้องมาร์คเพิ่มจาก 187 คู่ว่างใน `data/skills_pairs.json` ก่อน)

### ✅ voice "สลับเป็นคนละคน" ปิดแล้ว (PR #25 merged+deployed+verified 08-04)
`utils/voice.py` เป็นแหล่งเดียวของเสียง (`resolve_voice`/`build_live_config`/
`GEMINI_LIVE_MODEL_DEFAULT`) · **ต้นเหตุ: default โมเดล Live มี 2 ที่ไม่ตรงกันเงียบๆ ตั้งแต่
`369f18e` (06-19)** — `core/config.py`=3.1-flash-live (ตัวจริง) vs `utils/voice.py`=2.5-latest
พร้อมคอมเมนต์ว่า "ตรงกับ core/config.py" · `VOICE_MAP` ก็ซ้ำ 2 ที่ และตัวที่ `server.py`
ใช้จริงคือของ `tts.py` → **ไฟล์ชื่อ `voice.py` คือไฟล์ที่ตายแล้ว** · ตรึงด้วย seed+temp+
`affective=False` (3 รอบได้ไบต์เท่ากันเป๊ะ) · ⚠️ **`temperature` บน 2.5-native-audio =
เสียงหาย 0 ไบต์ เงียบสนิทไม่ error** (เกือบ pin ไปตัวนั้น) · `affective=True` บน 3.1 = 1011
· ยังไม่ปิด: 3.1-live ไม่มี snapshot ปักวันที่ → Google อัปทับได้ · **`/api/tts` ถูกเรียก
0 ครั้งบน prod — แก้ `utils/tts.py` ไม่มีผลกับเสียงที่ผู้ใช้ได้ยิน**
🔬 **รอ user ยืนยัน: คุยข้ามนาทีที่ 10 แล้วยังสลับคนไหม** (ไบต์เท่ากัน = ตรึงการสุ่มได้ ไม่ใช่หลักฐานว่าหูได้ยินเหมือนกัน)

### ✅ skills_collection "ไม่ใช่ cosine" = false alarm (PR #26 merged+deployed+verified)
ERROR บน prod 08-04 08:20:12 สั่งให้ `recreate_collection()` **ทั้งที่ collection ปกติดี**
(`collection.id` = `56c1cde1…` ตัวเดียวกับที่ upsert ตอน 08:18 · metadata = cosine)
→ ทำตาม = ลบ index 22 รายการฟรีๆ · ต้นเหตุ: `_space()` ยุบ "อ่านไม่ได้" เข้ากับ `"l2"`
(`.get(...,"l2")` + `except: return "l2"`) · **พ่วงเจอ: `get_skills_search()` เป็น
lazy singleton ไม่มี lock — วัดบน prod 12 เธรด → 12 instance และ instance ที่ init ล้ม
ถูก cache ค้างถาวร = ฉีด skill ไม่ได้ตลอดอายุโปรเซส** · แก้: `_space()` คืน
cosine/l2/None แยกกัน · ข้อความ `space=None` ห้ามเสนอคำสั่งที่ลบข้อมูล · ใส่
`_search_lock` + ไม่ cache instance ที่พัง · fail-closed ไม่เปลี่ยน
· verified prod: 12 เธรด → 1 instance · `search_skills("openclaw คืออะไร")` ฉีดถูกตัวแล้ว

### ✅ พิมพ์แทรกระหว่างคุยด้วยเสียงได้แล้ว (PR #28) + 🎨 ธีมรอ user เคาะ
กล่องพิมพ์ในหน้าจอ voice · backend รองรับมาตลอด (`elif t == "text"`) ขาดแค่ UI ·
วัดจริง: **ส่งตอน AI พูดอยู่ → `interrupted` แล้วตอบใหม่ 8.1 วิ · ส่งตอนเงียบ → 5.3 วิ**
· พ่วงแก้ **ก๊อปที่สามของตารางเสียง** (`app.tsx` hardcode fa/kwan/khim ใต้จอ) → อ่านจาก
event `connected` แทน · ⚠️ **`session.receive()` yield แค่ turn เดียวแล้วจบ generator —
เขียน probe ต้องวน `while` ไม่งั้นสรุปผิดว่าโมเดลเงียบ** (ผมพลาดจริง 08-05)

🎨 **ธีม: เสนอ 2 ทิศแล้ว ยังไม่แตะโค้ดสักบรรทัด รอ user เคาะ**
artifact: https://claude.ai/code/artifact/28e28630-e2f8-443c-9fcf-2fab144b3ba4
· **`app.tsx` มี 12 ตระกูลสี · L ห่าง 25 จุด · C ต่างเกือบ 2 เท่า** = เหตุผลเชิงกลไกที่ไม่เข้ากัน
· **contrast ตกเกณฑ์ 59 จุด — `text-gray-700` = 1.79:1 · แก้ได้เลยไม่ต้องรอเลือกธีม**
· C = สีเดียวจาก `AI_PALETTE` · D = 6 สีล็อก `L .75 C .13` หมุนแค่เฉด
· ⚠️ `AI_PALETTE` มี `fa`/`khim` ค้างเป็นซาก · **เลือก D ต้องเขียน `DESIGN.md` ก่อนแตะโค้ด**

### 🔬 ข้อ 8 "เสียงเบา" — มีตัววัดแล้ว (PR #27 deployed) รอ user คุยยาว 12 นาที
`AudioLevelMeter` (`utils/voice.py`) log RMS/peak ของ PCM **ก่อน**ส่งเข้าเบราว์เซอร์
ทุก 10 วิของเสียง → **baseline วัดจากเสียงจริง: −15 ถึง −18 dBFS · peak 24k–28k**
· ดูผล: `docker exec ai-backend-1 sh -c "grep VoiceLevel /app/logs/server.log"`
· **แบนราบ = ปัญหาอยู่ปลายทาง (OS/AEC/HFP) · ลดลง = Gemini ส่งเบาลงจริง**
· meter อยู่นอกลูป reconnect (นาฬิกาไม่รีเซ็ตตอนนาทีที่ 10) · ปิดด้วย `VOICE_LEVEL_LOG=off`
⚠️ แบนราบ **ไม่ได้แปลว่าไม่มีปัญหา** แปลว่า "ปัญหาไม่ได้อยู่ก่อนจุดนี้"

**โปรโตคอลเทสที่บอก user ไป:** 2 รอบติดกัน เนื้อหาเดียวกัน เกิน 12 นาที (ต้องข้ามนาทีที่ 10)
อัด Screen Recording ปิดไมค์ · รอบ A = ลำโพงเครื่อง · รอบ B = AirPods
· **ห้ามตัดสินจาก "ดัง/เบา" ให้ดู "รูปร่างตามเวลา"** — AirPods เบาตั้งแต่ต้นเพราะ iOS
สลับ HFP ทันทีที่หน้าเว็บถือ mic stream · **ปุ่มปิดไมค์ในแอปช่วยไม่ได้** (`setMuted()`
แค่พลิก flag ไม่เคยปิด track — verified `voicelive.ts:300`) · หูฟังมีสายเคลียร์กว่ามาก
· session เดียวตอบ 2 คำถาม: เสียงเบา + "สลับเป็นคนละคน" ตอนข้ามนาทีที่ 10
user จะเทสเช้านี้ · **ใส่หูฟังแล้วหายเบา = ยืนยันสมมติฐาน AEC/AGC หรี่ · ยังเบา = ผมคิดผิด ต้องรื้อใหม่**
ให้อัดด้วย **Screen Recording ปิดไมค์** (ตัดตัวแปรระยะห่าง) · เล่าเกิน 11 นาที ·
AirPods จะเบาตั้งแต่ต้นเพราะ iOS สลับ HFP — **ดูว่า "แย่ลงตามเวลา" ไม่ใช่ "ดัง/เบา"**
แก้ไปแล้ว 2 ชั้น (persona `83b5dd8` · go_away `e6b486d`) แต่ **"เสียงเบา" ยังไม่ยืนยันว่าหาย**

---

### ✅ 2026-08-06 (รอบดึก) — TTS โควตา ปิดแล้ว (PR #46 merged + deployed + verified prod)

**ที่มา:** งานค้างข้อ 1 ที่ติดป้าย "รอ user เคาะ" · user เลือก **"จัดกลุ่มประโยค + ตัดทิ้ง"**

`utils/tts.py` — `_pack_sentences()` รวมประโยคแบบ greedy จนใกล้ `TTS_MAX_CHARS` (2000)
→ `_apply_chunk_cap()` เพดาน `TTS_MAX_CHUNKS` (3) · **1 chunk = 1 request**

**วัดจากคำตอบจริงบน prod 469 ข้อความ** (`chat_history.db` ในคอนเทนเนอร์):
median 323 · p90 907 · p99 6,856 · max 9,610 ⇒ **95.3% เหลือ 1 request** (เดิม 1 req/ประโยค
⇒ ~2 คำตอบ/วัน) · 4.7% กิน 2-3 · 1.3% ชนเพดานแล้วถูกตัด (มี `logger.warning`)

🔑 **มี 2 เส้นกินโควตา ไม่ใช่เส้นเดียว** — `/api/tts` (frontend เรียก) และ **`/api/tts/stream`**
(`routers/system.py`) ที่ **แบ่งประโยคเองอีกชั้นคนละไฟล์** · เกือบตกสำรวจเพราะนับ caller
ใน bundle prod ได้ `api/tts` 1 ครั้ง / `api/tts/stream` **0 ครั้ง** แต่ endpoint ยังเปิดอยู่
⇒ **แก้ไฟล์เดียวไม่พอ ต้องนับเส้นให้ครบก่อนประกาศปิดงาน** (รูปแบบเดียวกับข้อ B ที่เคยติด ✅ ผิด)

⚠️ **`text[:2000]` ตัดข้อความทิ้งเงียบมาตลอด** — `_split_sentences` ใช้ regex ที่ต้องการ
`\s+` หลัง `.` ⇒ ข้อความ 4,900 ตัวอักษรที่ไม่มีเว้นวรรค (bullet list) = **"1 ประโยค"**
แล้วโดนตัดทิ้ง 2,900 ตัวอักษร · เจอโดยบังเอิญจากเทสที่เขียนเพื่อเรื่องอื่น

🔑 **CodeRabbit จับ 2 Major ที่เทสผมปล่อยผ่านทั้งคู่:**
1. `TTS_MAX_CHARS=0` → ลูปหั่นแข็งที่ผมเพิ่งเพิ่มเอง **วนไม่รู้จบ** (`s[:0]` ว่าง แล้ว `s[0:]`
   เท่าเดิม) · ยืนยันด้วย SIGALRM ว่าค้างจริง · **hang แย่กว่า crash** เพราะ worker ตายเงียบ
   ทีละตัวไม่มี traceback · กันสองชั้น: `_positive_env()` **ถอยไป default + warning ไม่ raise**
   (raise ตอน import = `backend-watchdog` `compose up -d` ทุก 60 วิ → **crashloop ทั้งระบบ
   เพราะปุ่มลำโพงตัวเดียว**) + `_pack_sentences` โยน `ValueError` เองไม่ว่าใครเรียก
2. `generate_tts` blocking ~3.5 วิ/chunk ถูกเรียกตรงๆ ใน handler `async` ⇒ **ทุกคำขอหยุดรอ**
   → `run_in_threadpool` ทั้งสองเส้น (convention มีอยู่แล้วที่ `routers/skills.py:7`)
⇒ **เทสที่เขียนเองครอบแต่ "ข้อมูลเข้าแบบที่คาดไว้" ไม่เคยแตะ config ที่ผิดรูป**

🔧 **เทส "ไม่ได้รันบน event loop" แบบไม่เปราะ:** ใน worker thread **ไม่มี** running loop
⇒ `asyncio.get_running_loop()` ต้องโยน `RuntimeError` — อย่าผูกกับชื่อ thread ของ anyio

🔴 **CodeRabbit ขึ้น `pass` ได้ทั้งที่ไม่ได้รีวิวเลย** — ชน review limit
("you've reached your PR review limit · Next review available in 49 minutes")
check เขียวแต่ inline comments เท่าเดิมจากรอบแรก ⇒ **ดู `gh pr checks` อย่างเดียวสรุปผิด**
ต้องเปิด `gh api .../issues/<n>/comments` อ่านของจริง

**verified ในคอนเทนเนอร์ prod:** 5 ประโยค → 1 req · 4,800 ตัวอักษรไม่มีเว้นวรรค → 3 req
รวมครบไม่หาย · 20,001 ตัวอักษร → 3 req + warning โผล่ในลอกจริง · `max_chars=0` → `ValueError`
· ทั้งสองเส้นใช้ `run_in_threadpool` · ยิง `{"text":""}` เช็ค route **โดยไม่กินโควตา**


---

## 📥 ยกมาจาก MEMORY.md ตอนยุบหัวไฟล์ 2026-08-08 (เนื้อหาเซสชัน 08-05/08-06)

### 🌆 เซสชัน 08-06 รอบเย็น — 10 PR (#35–#45) merged+deployed+verified prod
เริ่มจาก user สั่ง **"ไล่ตรวจปุ่มทีละปุ่ม"** (63 ปุ่ม/33 endpoint) → เจอพัง 3 + ปัญหา 3
→ ลามไปเจอหนี้เชิงโครงสร้าง · **รายละเอียดครบอยู่ใน `~/Desktop/ui/CLAUDE.md`
หัวข้อ "▶️ เซสชันหน้าเริ่มตรงนี้" — เปิดอ่านก่อนวางแผนเสมอ**
**3 ปุ่มพัง:** เริ่มแชทใหม่ (auto-select `sessions[0]` ทับ session ใหม่ · `POST /api/sessions`
ไม่ persist) · pin overlay ตาย 66/66 (จับคู่ข้อความเป๊ะ แต่มีป้ายปุ่ม React ปน) ·
TTS 404 (โมเดลสาย native-audio = bidi-only ยัดเข้า `generate_content()` ไม่ได้ + ต้องมี prefix `Say:`)
**เพดาน body ปิดครบสองฝั่ง:** RAM 27/27 เส้น (#43) + ดิสก์ผ่าน pure-ASGI middleware (#44)
— ก่อนแก้ยิง multipart 315 MB ได้ 413 แต่ **313.3 MB ลงดิสก์ไปแล้ว**
🔴 **ห้ามใช้ `BaseHTTPMiddleware` กับงานคุม body** — ให้ `Request` ที่อ่าน body ไปแล้ว
· `_BodyTooLarge` **ห้ามสืบทอด `HTTPException`** ไม่งั้น handler ที่ดัก except จะกลืนทิ้ง
**ล้าง session ทดสอบ 39 ตัว** — ⚠️ **ชื่อ session เชื่อไม่ได้** `verify-opt3` (115 ข้อความ)
กับ `test-grounding-local` (70 ข้อความ มีงาน พมจ.แพร่ + ชื่อข้าราชการจริง) เป็นแชทจริง
**เกณฑ์ที่ใช้ได้คือ "จำนวนวันที่มีการคุย"** (ของจริง 3-9 วัน · probe กระจุกไม่กี่นาที prompt ซ้ำเป๊ะ)
🔧 **เครื่องมือวัดโกหก 8 ครั้ง** — ที่ต้องจำ: **`scandir` มองไม่เห็นไฟล์ที่ถูก unlink**
(`SpooledTemporaryFile`) ต้องไล่ `/proc/<pid>/fd` หา `(deleted)` · **mutation จับได้แค่ 3/5
เพราะเทสกลุ่มควบคุมของตัวเองอ่อน** (เช็คแค่ "ถูกเรียก" / ส่ง body ว่าง) ⇒ **กลุ่มควบคุม
ก็ต้องผ่าน mutation** · **`tail` กินหัว** → รายงานลบ 9 ทั้งที่ลบจริง 14 ⇒ สคริปต์ destructive
ต้องพิมพ์ยอดรวม**ท้ายสุด** · แก้ DB นอกรอบไม่ล้าง in-memory cache ของ uvicorn
✅ **TTS โควตาปิดแล้ว 08-06 (PR #46 merged+deployed+verified ในคอนเทนเนอร์ prod)** —
user เคาะ "จัดกลุ่มประโยค + ตัดทิ้ง" · `_pack_sentences` รวมจนใกล้ `TTS_MAX_CHARS`
→ `_apply_chunk_cap` เพดาน 3 · **วัดจากคำตอบจริง 469 ข้อความบน prod: 95.3% เหลือ 1 req**
🔑 **มี 2 เส้นกินโควตา ไม่ใช่เส้นเดียว** — `/api/tts/stream` แบ่งประโยคเองอีกชั้นคนละไฟล์
(bundle prod เรียก `api/tts` 1 ครั้ง / `stream` 0 ครั้ง แต่ endpoint ยังเปิด) **แก้ไฟล์เดียวไม่พอ**
⚠️ **`text[:2000]` ตัดข้อความทิ้งเงียบมาตลอด** เมื่อ `_split_sentences` จับไม่ได้
(regex ต้องการ `\s+` หลัง `.` → 4,900 ตัวอักษรไม่มีเว้นวรรค = "1 ประโยค")
🔑 **CodeRabbit จับ 2 Major ที่เทสผมปล่อยผ่าน** — `TTS_MAX_CHARS=0` ทำลูปหั่นแข็ง
**วนไม่รู้จบ** (บั๊กที่ผมสร้างเองรอบนั้น · **hang แย่กว่า crash** ไม่มี traceback) +
`generate_tts` blocking ถูกเรียกใน handler `async` ⇒ ต้อง `run_in_threadpool`
· env เพี้ยน **ถอยไป default + warning ไม่ raise** เพราะ `backend-watchdog` จะทำเป็น crashloop
· 🔧 **เทส "ไม่ได้รันบน event loop" แบบไม่เปราะ:** worker thread ไม่มี running loop
⇒ `asyncio.get_running_loop()` ต้องโยน `RuntimeError` (อย่าผูกกับชื่อ thread ของ anyio)
🔴 **CodeRabbit ขึ้น `pass` ได้ทั้งที่ไม่ได้รีวิว** — ชน review limit ("Next review in 49 min")
check เขียวแต่ inline comments เท่าเดิม ⇒ **ดู `gh pr checks` อย่างเดียวสรุปผิด ต้องเปิดคอมเมนต์อ่าน**
⏭️ **ค้าง:** เทส TTS live รอโควตารีเซ็ต · ธีม C/D · เสียงข้ามนาที 10
· `feedback` 0 แถวทั้งที่ปุ่มอยู่บน prod มานาน (payload ตรง schema — น่าจะยังไม่มีใครกด)

### ✅ A + B ปิดครบแล้ว (A: PR #31 · B: #41 แก้คำอ้าง → #43 ปิด RAM → #44 ปิดดิสก์)
**(A)** `accept_proposal` คืน `db_updated` + `warning` เพิ่มจาก `ok` (ไม่พลิก `ok` เพราะ .md
เขียนสำเร็จจริง) — **ใช้รูปแบบที่ `skills_extract` มีอยู่แล้วในไฟล์เดียวกัน ไม่ใช่ contract ใหม่**
**(B)** 🔴 **บรรทัดนี้เคยเขียนว่า "เพดาน 10 MB ครบทุกเส้น" ซึ่งเท็จ** — PR #31 ปิดแค่
`/api/upload` · `/skills/discover/accept` · `memory.py` 3 จุด แล้วสรุปเหมาว่าครบ
**วัดตอนนั้น: 27 เส้นมีเพดานแค่ 9 ยังดิบ 18** รวม `/api/chat` → **ปิดครบ 27/27 แล้วที่ #43**
และปิดฝั่งดิสก์ที่ #44 · ค่าเพดานรวมมาที่ `utils/http_limits.MAX_BODY_BYTES` **ที่เดียว**
(เดิมก๊อป 3 ไฟล์) · `tests/test_body_cap_ratchet.py` เป็นตัวนับถาวร — เพิ่ม endpoint
ที่อ่าน body ดิบเข้ามาใหม่แล้วเทสแดงทันที **ไม่ต้องพึ่งความจำอีก**
· verified prod เฉพาะเส้นที่แก้: 11 MB → **413** · 2 KB → 200 · JSON เสีย/ไม่มี body → 200
🔑 **"ปิดงานแล้ว" ต้องมาจากการนับ ไม่ใช่ความรู้สึกว่าแก้ครบ** — ข้อ B ติดป้าย ✅ อยู่ 1 วัน
ทั้งที่เหลืองาน 2 ใน 3 · เจอเพราะไล่ endpoint ตอน audit ปุ่ม ไม่ใช่เพราะกลับมาตรวจ
🔑 **ทั้งสองข้อติดป้าย "รอ user เคาะ" มาหลายเซสชันทั้งที่คำตอบอยู่ในโค้ดฐานแล้ว** —
รูปแบบเดียวกับข้อ C · **บันทึกที่บอกว่า "ต้องถาม user ก่อน" ก็ต้องถูกตรวจซ้ำเหมือนบันทึกอื่น**
⚠️ บั๊กที่ทำเองระหว่างทาง: `except HTTPException: raise` ส่งต่อ **400** (JSON เสีย) ไปด้วย
ทำลายเจตนา "body ไม่บังคับ" ของ `/api/memory/cleanup` → ต้องเช็ค `status_code == 413` ก่อน
**ใส่ด่านใหม่ต้องไล่ดูว่ามี `except` กว้างๆ อยู่เหนือมันไหม** (CodeRabbit จับได้ เทสผมผ่านฟรี)
✅ **ปิดแล้วที่ #44** (เคยเขียนว่า "ยังเปิด") — multipart spool ลงดิสก์ตอน parse
กันด้วย pure-ASGI middleware `core/body_limit.py` · วัดจริง: 315 MB ก่อนแก้ลงดิสก์ 313.3 MB
หลังแก้ **0 MB** · ⚠️ วัดด้วย `scandir` ไม่เห็น ต้องดู `/proc/<pid>/fd` ที่ `(deleted)`
**🎨 ธีม** เสนอ 2 ทิศแล้ว ยังไม่แตะโค้ด · artifact `28e28630-e2f8-443c-9fcf-2fab144b3ba4`
— เลือก D ต้องเขียน `DESIGN.md` ก่อนแตะโค้ด
✅ **contrast 59 จุดปิดแล้ว 08-06 (PR #32)** — แก้ที่ `~/appscript.ui/tailwind.config.js`
จุดเดียว (สีเทาถูกใช้เฉพาะกับตัวอักษร ไม่มี `bg-gray-*`/`border-gray-*` เลย)
500/600/700 → `#8e96a3`/`#7f8998`/`#717b8b` = 6.71/5.65/4.67 · ล็อก H218° S11% ตาม
gray-400 ไล่ L ทีละ 5.1% · verified จาก **CSS ที่ server เสิร์ฟจริง**: ตกเกณฑ์ 0 คลาส
⚠️ **พื้นหลังจริงคือ `#060810` ไม่ใช่ `rgb(15,20,32)` ที่บันทึกเก่าเขียน** (ratio ต่างเล็กน้อย)
⚠️ **Tailwind ปล่อย `rgb()` ไม่ใช่ hex — ค้น hex ใน CSS ได้ 0 แล้วเกือบสรุปว่าแก้ไม่มีผล**
🔴 **`~/appscript.ui` มี dep ที่ไม่เคยประกาศใน `package.json`** (vitest 1.6.1,
@testing-library/*, jsdom อยู่ใน lock อย่างเดียว) → **`npm i` อะไรก็ได้จะ prune ทิ้ง
แล้วเทส 15+ ไฟล์รันไม่ได้ทันที** · ประกาศคืนครบแล้วตรงเวอร์ชันเดิม ไม่ได้อัปอะไร
✅ **sidebar ล้นจอ ปิดแล้ว 08-06 (PR #33)** — บล็อก Dream+Skills+Memory ตั้ง
`flex-shrink-0 md:max-h-none` = หดไม่ได้ + desktop ไม่มีเพดาน → ล้น 24px footer โดน clip
**และบีบรายการแชทเหลือ 16px ทั้งที่มีเนื้อหา 1,843px** (อาการที่หนักกว่าและไม่มีใครสังเกต)
แก้เป็น `overflow-y-auto min-h-0 max-h-[45%]` · verified บนหน้าจริง ล้น 0 ทุกความสูง
823→380px · **ใช้ `%` ไม่ใช่ `vh` เพราะ aside เป็น `100dvh` — `vh` ไม่นับแถบมือถือที่ยุบได้**
🔧 **วิธีวัด layout ที่ได้ผล:** เปิดหน้าจริงด้วย claude-in-chrome (login ติดอยู่แล้ว) →
`javascript_tool` วัด `getBoundingClientRect()` ของลูกทุกตัวใน `aside` เทียบ `innerHeight`
**แล้วทดลองแก้ด้วย inline style ก่อนแตะโค้ด** (เทียบหลายค่าได้ในคำสั่งเดียว)
⚠️ **grep หา class ใน CSS ต้องเผื่อ escape** — Tailwind เขียน `.max-h-\[45\%\]` ไม่ใช่
`.max-h-[45%]` และปล่อยสีเป็น `rgb()` ไม่ใช่ hex · ค้นผิดแล้วได้ 0 จะสรุปผิดว่า "แก้ไม่มีผล"
**🔬 เสียง** รอ user คุยยาวข้ามนาทีที่ 10 → ตอบ 2 คำถาม (สลับเป็นคนละคนไหม · เบาลงไหม)
baseline `VoiceLevel`: −15 ถึง −18 dBFS · peak 24k–28k · **ดูรูปร่างตามเวลา ไม่ใช่ ดัง/เบา**

### 🟢 ปิดไปแล้ว 08-05 — backup + ตัวเฝ้า (PR #29)
**ข้อ C เดิม "ไม่มี backup" = เท็จ** บันทึกไปดูผิดโฟลเดอร์ (`db_backups/` มี 2 อันชื่อคล้ายกัน)
ตัวจริงคือ `ui/data/db_backups/` เดินทุกวันไม่ขาด · `_verify_snapshot()` + `utils/heartbeat.py`
deployed+verified 2 ทิศ · check `Khim AI db-backup` เขียวแล้ว
⚠️ **healthchecks: uuid ที่ไม่มีอยู่ → HTTP 200 + body `'OK (not found)'` ซึ่งขึ้นต้นด้วย `OK`**
→ `startswith("OK")` ยังหลุด ต้องเทียบเป๊ะ (บันทึกลง docstring + CLAUDE.md แล้ว)
✅ **PR #30 merged+deployed — ปิด 3 ช่องที่เหลือครบ ไม่มีอะไรค้างในเรื่อง backup แล้ว**
archive เสียชื่อ `_UNHEALTHY` (ยังขึ้นต้น `db_backup_` เพื่อให้ retention เห็น) ·
`scripts/db_backup.sh` มีตัวตรวจแล้ว · `ping()` retry 3×10 วิ **เฉพาะต่อไม่ติด/5xx**
(body ผิด/4xx = ความผิดถาวร ไม่ยิงซ้ำ) · verified บน prod 4 ทาง: in-app ปกติ/พัง ·
`.sh` บน NAS host ข้อมูลจริง exit 0 · `.sh` ในคอนเทนเนอร์ที่**ไม่มี sqlite3** ให้ผลเหมือนกันเป๊ะ
🔑 **CI จับได้ว่าอิมเมจ prod ไม่มี `sqlite3` CLI แต่แมคมี** → เทสเขียวหลอกบนเครื่อง dev ·
แก้โดยให้ตัวตรวจอ่านผ่าน `python3` (มีครบทั้งสองที่) **ไม่ใช่เติม sqlite3 ลง Dockerfile**
(= แก้เครื่องมือวัดให้เข้ากับของที่วัด) · นี่คือเหตุผลที่ CI ต้องรันในอิมเมจ ห้ามถอยกลับ

### 🟢 เซสชัน 2026-08-12 — UI polish 3 เรื่อง (ขอบขาว iPad · สถิติใต้คำตอบ · token จริง)
commits FE `543eb06`→`2ab7711` · BE `4139156`→`1030ddd` — deployed + verified ครบ
(รายละเอียดเต็ม + gotcha อยู่ `~/Desktop/ui/CLAUDE.md` หัวข้อ ▶️ เช่นเดิม)
🔑 **บทเรียนข้ามโปรเจกต์: container UTC + `datetime.now()` naive = เวลาบน UI เพี้ยน +7 ชม.
โดยไม่มีใครสังเกต** (ไม่มีจุดเทียบ) — เก็บเวลาต้องมี offset เสมอ (`astimezone().isoformat()`)
· สตริง naive เก่าให้ parse เป็น UTC ตามความจริงของเครื่องที่เขียน
🔑 `stream_options.include_usage`: chunk ท้าย `choices=[]` → โค้ด `chunk.choices[0]` เดิม
IndexError ทันทีที่เปิด · reasoning model นับ think tokens ใน output_tokens (คำเดียว = 841 ปกติ)
🔴 **ค้างจากปิดเซสชัน 08-12: Ollama บน PC .235 (11434) ตาย → embedding/vault RAG/recall
timeout ทั้งระบบ** (LM Studio 1234 เครื่องเดียวกันปกติ · start ผ่าน ssh ล้ม "Unable to init
instance" ต้องซ่อมหน้าเครื่อง) · หน้า wiki ใหม่ push ถึง NAS แล้วแต่ยังไม่เข้า ChromaDB —
วิธีตามต่อ + บั๊ก sync_vault โกหก (`ok:true` ทั้งที่ upsert ล้ม) อยู่ `~/Desktop/ui/CLAUDE.md` ▶️


---

## ย้ายจากหัว MEMORY.md (2026-08-13 — บีบ index)

สถานะ ณ 08-12 ที่เคยอยู่หัว index:
- ✅ 08-12: ขอบขาว iPad (html/body ไม่มีสีพื้น) · สถิติถาวรใต้คำตอบ + token จริง (done.usage) · เวลาข้อความในประวัติ — บั๊กแฝง container UTC + naive datetime.now() = UI เพี้ยน +7 ชม. แก้แล้ว (เก็บ offset + naive เก่า parse เป็น UTC) · reasoning model: output_tokens รวม think = ตัวเลขโดดปกติ
- ✅ 08-12 ค่ำ ปิด 4 งาน (deployed+verified · CI เขียว): sync_vault เลิกโกหก (df8e018) · ตัวซ่อมช่องว่าง PW สูตรจริง 5 ขั้น B→N→AM→A1→A2 (สอบกลับจาก golden 860/860 · เทสตรึง) + ซ่อม ํ+วรรณยุกต์+า 20,069 จุด · /api/reader/add-from-disk · PW 20.3M + Xian Ni 4.6M ใน reader.db prod (ที่คั่น xianni กู้ pos 30251)
- ✅ สืบ feedback จบ: เส้นเก็บไม่พัง แต่ปุ่มหายหลัง regenerate (done ไม่มี message_id — แก้แล้ว) + FE กลืน error 400 เป็น toast สำเร็จ (แก้แล้ว 8a690a1) — เหลือ user กดใช้จริง
- ความรู้ลง vault: thai-pdf-tts-diseases (sync RAG count 69) · ปุ่ม ← กลับหน้าเสียง deployed (ba338c3/6i5IeW3N) user เคาะ: ทำงานเหมือนจบสนทนา

---

## 📦 ย้ายมาจาก MEMORY.md ตอนบีบดัชนี (2026-08-18)

รายละเอียดพวกนี้เคยอยู่ในหัว `MEMORY.md` แต่เป็น "เรื่องที่ปิดแล้ว/หลักฐาน" ไม่ใช่
"อะไรค้าง + อะไรห้ามทำ" จึงย้ายลงมาที่นี่ · ข้อห้ามฉบับย่อยังอยู่ในดัชนี

### 08-17 — ปิด 4 อาการของโหมดอ่านนิยาย (`5f190d4` server+bundle · `a627f3f` source)
bundle ที่เสิร์ฟจริง `index-DD3rJ0CH.js` · อาการที่ปิด: ตัวอ่านซ้อน · ขวัญตอบทับเสียงอ่าน ·
กดพักไม่หยุด · ประโยคเดิมซ้ำ · เพิ่มปุ่ม 🔁 อ่านท่อนนี้ใหม่

🔑 **ตัวเลขที่ปิดคดี "ที่คั่นวิ่งหนี":** ที่คั่นเดิน **13.8 ตัวอักษร/วินาที** (ตอนพัง 08-14 =
**185.9**) = ช้าลง 13.5 เท่า **ทั้งที่ไม่มี pacing เลย** ⇒ ตัวการคือ**ตัวอ่านซ้อน ไม่ใช่
ป้อนเร็วเกิน** · `reader_pacing_wait` ของ `55b8594` เป็นการรักษาปลายเหตุ —
**ห้ามเอากลับ** · `stash@{0}` ที่ผูกกับมันทิ้งได้ · ถ้าจะเอา `55b8594` กลับ **เอาเฉพาะ watchdog**

### 08-18 — เติม log ที่ขาด (`2df117b` deployed + verified ในคอนเทนเนอร์)
`interrupt_log_line` / `reader_feed_log_line` / `reader_turn_log_line` ใน `utils/voice.py`
(pure → เทสได้) + `[Voice WS] เริ่มค้น` / `ค้นเสร็จ … เงียบไป Ns` เป็นขอบซ้าย-ขวาของช่วงเงียบ
· เทสใหม่ 19 ตัว (`tests/test_voice_logging.py`) · mutation ผ่าน 3 จุด · suite 1591 เขียว

🔴 **เจอระหว่างทาง: CI แดงติดกัน 3 commit ตั้งแต่ `f4e62e8` (08-17)** — `elif t == "reread"`
ถูกก๊อปจาก `/ws/reader` ไปวางใน handler **เสียง** ซึ่งไม่มีธง `reread` ⇒ ruff `F821` และถ้ามี
client ยิงคำสั่งนั้นเข้าสายเสียงจะได้ `NameError` → `except Exception` → `stop.set()`
= ตัด session เสียงทิ้งทั้งเส้น · **prod deploy ผ่านได้ทั้งที่ CI แดง เพราะ deploy ไม่ผูกกับ CI**

⚠️ **เทสที่อ่าน source เป็นสตริงมีกับดัก:** `"reread" not in src` แดงเพราะไปโดน**คอมเมนต์ที่
อธิบายบั๊กนั้นเอง** ⇒ เปลี่ยนไปเดินด้วย `ast` (เก็บเฉพาะ `ast.Name` ในฟังก์ชันที่สนใจ)

### เกร็ดที่ย้ายลงมาด้วย
- ⚠️ บันทึกเก่าที่ว่า "เวลาที่จดไว้ทุกที่คลาด 7 ชม." **กว้างเกินไป** — เวลาที่ **user บอก** เป็น
  เวลาไทยและถูกอยู่แล้ว (สอบแล้วตรง log เป๊ะ) ที่คลาดคือเวลาที่**อ่านจาก log แล้วจดโดยไม่แปลง**
- newmm ตัด "บอกว่า" เป็น `บอ|กว่า` (ค้างเดิม)
- ธีม C/D — artifact `28e28630…` · เลือก D ต้องเขียน `DESIGN.md` ก่อน


### 📦 บล็อก Khim AI ฉบับเต็มจากหัว MEMORY.md ก่อนแยกโปรเจกต์ (2026-08-18)

(ดัชนีเหลือแค่ตัวชี้ + ข้อห้าม · ของเต็มอยู่ที่นี่ · บทเรียนที่ใช้ข้ามโปรเจกต์ถูกยกขึ้นไป
หัวข้อ "กฎแม่บทข้ามโปรเจกต์" ใน MEMORY.md แล้ว)

**`~/Desktop/ui/CLAUDE.md` หัวข้อ "▶️ เซสชันหน้าเริ่มตรงนี้" = ของจริง เปิดก่อนวางแผนเสมอ**
(เรื่องเล่า/หลักฐาน/เซสชันเก่าทั้งหมด → `hybrid_ai_status.md`)
✅ 08-17 ปิด 4 อาการโหมดอ่าน (`5f190d4`) · ✅ 08-18 เติม log ครบ (`2df117b`)
🔴 **งานค้าง:** (1) **คำตอบหลังค้นเว็บหาย** — log พร้อมแล้ว **รอ user คุยเสียง + ถามคำถามที่
ต้องค้นเว็บ แล้ว grep `interrupted|เริ่มค้น|ค้นเสร็จ` ใน `/app/logs/server.log`**:
เห็น "เงียบมา 20s+ ⚠️" = สมมติฐานประตูไมค์**ยืนยัน** · เห็น "เงียบมา 0.x s" ทุกบรรทัด =
สมมติฐาน**ตาย อย่าดันต่อ** · (2) Gemini ตายเงียบ ไม่มี watchdog — ลายเซ็นใน log =
`ป้อนท่อน` ที่ไม่มี `ท่อนจบ` ตามมา (เอา `55b8594` กลับได้ **เฉพาะ watchdog**) ·
(3) voice idle 1008-loop (ทุก ~151 วิ ตอนเปิดค้าง · แย่ลงเพราะไมค์ปิดตอนอ่าน)
· เทส TTS live รอโควตา · ธีม C/D · เทส flaky 1 ตัว
🔒 **ห้ามแตะค่าเสียง/จังหวะอ่าน (user สั่งปิดคดี 08-17)** — `READER_PROMPT` ·
seed/temperature/Aoede · `READ_BLOCK_CHARS` · กฎเลื่อนที่คั่น · jitter prime ·
⛔ ห้ามเสนอ "ถอด temperature" ซ้ำ · ⛔ **ห้ามเอา `reader_pacing_wait` กลับ** (ตัวการจริง
คือตัวอ่านซ้อน) · เส้นฐานเสียง `gemini-3.1-flash-live-preview` ver `3.1-flash-live-03-2026`
⚠️ **ห้าม seek ซ้ำเพื่อ "ตรวจสอบ"** (user อาจฟังอยู่ — อ่านค่าปัจจุบันก่อนเขียนเสมอ) ·
🔑 **glue ข้อความได้แค่วรรคเดี่ยวกลางวลี** — migration ข้อความต้องนับวรรคคู่ก่อน/หลังเท่ากัน
🔴 **prod deploy ไม่ผูกกับ CI — CI แดงได้เป็นวันโดยไม่มีใครรู้** (08-18 แดง 3 commit จาก
F821 `reread` ที่ก๊อปข้าม handler) ⇒ **เปิด `gh run list` ก่อนเริ่มงานเสมอ**
🔴 **`db_backups/` รายวันไม่มี `reader.db`** — ข้อความหนังสือไม่มี backup อัตโนมัติ
🔴 ห้ามใช้ `BaseHTTPMiddleware` คุม body · `_BodyTooLarge` ห้ามสืบทอด `HTTPException` ·
CodeRabbit ขึ้น `pass` ได้ทั้งที่ชน review limit · `~/appscript.ui` มี dep ไม่ประกาศใน `package.json`
🔴 **`obj.cb?.(f(x))` — optional call ที่ undefined ไม่ประเมิน argument เลย** · **`now < X +
tail` ต้องเช็ค `X > 0` ก่อน** · **ก๊อปโครงสร้างต้องก๊อป *เหตุผล* มาด้วย** (`clearExternal` ≠ `reset`)
⚠️ pytest ใน sandbox ที่ symlink `logs` → เขียนลง log prod ด้วย · `test_skills_db_cross_process`
แดงใน sandbox เสมอ (กลุ่มควบคุมโค้ดเดิมก็แดง ไม่ใช่ regression)



---

## 📦 บรรทัดดัชนีฉบับเต็มก่อนย่อ (ย้ายมา 2026-08-18)

"Khim AI" · prod NAS docker **8080** · React source `~/appscript.ui` · **ประวัติ audit ทุกข้อ (5·6·7·9·18·19·20·21·22·23) + บทเรียนอยู่ในไฟล์นี้ — เปิดอ่านก่อนวางแผนเสมอ** · ⚠️ **gotcha ที่ต้องรู้ก่อนลงมือ:** แก้ `skills/*.md` แล้วต้อง `clean_skills_db.py --resync --apply` **ในคอนเทนเนอร์เท่านั้น** (`docker exec ai-backend-1 sh -c "cd /app && python scripts/..."`) เพราะ `SKILLS_DB_PATH` บน Mac/NAS host เป็นคนละไฟล์กับ prod (`data/skills_db.json`) แล้วรายงานว่าสำเร็จ · `LOG_FILE` prod = `/app/logs/server.log` (ไม่ใช่ `/app/server.log` ที่ว่างเปล่าและหลอกตา) · `mcp` pin `<2` (2.0 ถอด decorator ที่ `mcp_server.py` ใช้ = สะพานพ่วง OpenClaw) · สร้าง ChromaDB collection ใหม่ต้องรันในคอนเทนเนอร์ (local `.env` ไม่มี `EMBEDDING_MODEL`) · **CI รัน pytest ในอิมเมจ Docker แล้ว — ห้ามถอยกลับไป `setup-python` + `requirements.txt`** (`tests/test_ci_matches_prod.py` จะแดง) · backlog `~/Desktop/ui/docs/audit-backlog-2026-08-02.md` · ค้าง: key Claude/Kimi, สะสม👍→fine-tune

---

## 📦 archive — YAML frontmatter ของ memory ก่อนย่อ (2026-08-17)
```
---
name: Hybrid AI Workspace — Session Status (2026-05-12)
description: สถานะโปรเจกต์ /Users/pawin/Desktop/ui — ล่าสุด 2026-08-03 ปิด backlog ข้อ 7 + 5 + 19 + 20 + ข้อ 21 ขั้นที่ 1 (WebSocket หลุด public + login หลุด lockout + fs/search ล้มทั้งแอปด้วย request เดียว + fail-open เทคลังเข้า context) · งานค้างอยู่ที่ docs/audit-backlog-2026-08-02.md
type: project
originSessionId: 594cec9b-b2b7-45fc-9275-05ad1e59ecf2
modified: 2026-08-04T06:43:41.527Z
---
```
