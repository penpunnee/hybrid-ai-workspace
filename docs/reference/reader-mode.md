# โหมดขวัญอ่านนิยาย (`/ws/reader` + ปุ่ม 📖)

> ยกมาจาก memory `project_khim_reader.md` เมื่อ 2026-08-17 · **เนื้อไม่ถูกแก้**
> (ตัดเฉพาะ YAML frontmatter)
> 🔒 ข้อห้ามเรื่องค่าเสียง/จังหวะอ่านยังมีผล — ดู `CLAUDE.md` หัวข้อ ▶️ และ `MEMORY.md`


**ระบบขวัญอ่านนิยายเสร็จและ user ใช้จริงแล้ว (2026-08-11)** — ปุ่ม 📖 ในหน้าเสียง ·
เส้นทาง: PDF → ซ่อม PUA → `data/reader.db` → `/ws/reader` (Gemini Live เสียง Aoede) →
`bookreader.ts` · กติกาที่สัญญากับ user: **"ฟังซ้ำได้ ไม่มีวันข้ามเนื้อหา"**
(ที่คั่นเลื่อนเมื่ออ่านจบท่อนเท่านั้น)

ทำไมไม่ใช้ Gemini TTS: เพดาน **10 req/วัน** (อ่าน 363 ชม. = ~9.7 ปี) · Live API เสียง
เดียวกัน ไม่ชนโควตา และ**อ่านคำต่อคำได้ 100%** เมื่อ prompt เข้มพอ · `READER_PROMPT`
จูน 4 รอบกับ user แล้ว — **แก้เมื่อไหร่ต้องวัดใหม่ทั้งชุด** (คำว่า "นักพากย์" คำเดียวช้าลง 56%)

🔒 **2026-08-17 user สั่งปิดคดี: "เสียงอ่านนิยายลงตัวแล้ว ไม่ต้องไปปรับแก้"**
ห้ามแตะ: `READER_PROMPT` · `READER_FEED_PREFIX` · Aoede/`seed=20260804`/`temperature=0.6`/
`affective_dialog=False` · `tools=None` ของโหมดอ่าน · `READ_BLOCK_CHARS=600`/`_BACKTRACK=120` ·
กฎเลื่อนที่คั่นเมื่อจบท่อน · jitter prime 0.8s
⇒ **ข้อเสนอ "ถอด `temperature` แก้บั๊ก Google เสียงเบาลง" พักถาวร ห้ามเสนอซ้ำ** เพราะ
`build_reader_config()` สืบ `build_live_config()` ทั้งก้อนแก้แค่ `tools` ⇒ `VOICE_TEMPERATURE`
เป็นค่าเดียวกันทั้งสองโหมด · จะทดลองได้ต้องแยก config สองโหมดออกจากกันก่อน

**โหมดอ่านนิยายกับโหมดเสียงสดทำงานพร้อมกันเสมอ** — UI ปุ่ม 📖 อยู่ใน `{voiceMode && (`
⇒ เข้าโหมดอ่านโดยไม่มี `/ws/voice` ไม่ได้เลย · จุดเชื่อมเดียวคือ `stopVoice()` เรียก `bookStop()`
⇒ **สอง Gemini Live session เปิดพร้อมกันตลอดที่ฟังนิยาย** (กิน quota สองเท่า + session แชท
idle ตาย 1008 ทุก ~151 วิ ตลอดทั้งเล่ม — ค้างอยู่)

✅ **แก้ครบ + deployed 2026-08-17** (`5f190d4` server+bundle · `a627f3f` React source ·
bundle `index-DD3rJ0CH.js`) — ยืนยันด้วย log prod ไม่ใช่แค่เทส:
· **ตัวอ่านซ้อน** → `bookToggleAction()` คลุมครบ 4 ค่า + `disconnect()` ก่อนสร้างใหม่เสมอ
· **ขวัญตอบทับเสียงอ่าน** → `HalfDuplexGate` มี timeline ที่สอง `extUntil` (เสียงนิยายชนะสวิตช์
  พูดแทรก) — วัดจริง: อ่าน 5:41 นาที ขวัญเงียบสนิท
· **กดพักไม่หยุด** → `reader_stream_action()` ลูปสตรีมดูธง `paused` ทุก chunk
· **ประโยคเดิมซ้ำ** → regen ส่ง `{"type":"flush"}` ก่อนอ่านท่อนซ้ำ
· **ปุ่ม 🔁 อ่านท่อนนี้ใหม่** (เพราะไมค์ปิดตอนอ่าน สั่งด้วยเสียงไม่ได้)

🔑 **ที่คั่นเดิน 13.8 ตัวอักษร/วินาที** (เทียบตอนพัง 08-14 = 185.9) **ทั้งที่ไม่มี pacing**
⇒ ปิดคดี: "ที่คั่นวิ่งหนี" เกิดจากตัวอ่านซ้อน **ไม่ใช่ป้อนเร็วเกิน** — `reader_pacing_wait`
ของ `55b8594` เป็นการรักษาปลายเหตุ **ไม่ต้องเอากลับ** (`stash@{0}` ที่ผูกกับมันทิ้งได้)

**ทางเข้า PC GPU (.235):** `ssh penpu@192.168.51.235` — key ต้องอยู่
`C:\ProgramData\ssh\administrators_authorized_keys` (บัญชี admin — `~/.ssh` ถูกเมิน) ·
JaiTTS ที่ `C:\Users\penpu\JaiTTS-Easy` ใช้งานได้ RTF 3.4-4.1x เมื่อโหลดโมเดลครั้งเดียว ·
`ping` .235 ไม่ตอบเสมอ (Windows บล็อก ICMP) เช็คพอร์ตบริการแทน

**gotcha แมคเครื่องนี้:** Tailscale network extension **บล็อก TCP ในวง LAN ทั้งหมด**
(ICMP ผ่าน) — ใช้ `nas-cf` แทน · token Cloudflare Access หมดอายุเป็นระยะ ให้ user
เปิด browser login

**Windows + ไทย:** stdout เป็น cp1252 → `sys.stdout.reconfigure(encoding="utf-8")`
**ในสคริปต์** เท่านั้น (ตั้งจากภายนอกพังทุกแบบ) · cmd จำกัด 8,191 ตัวอักษร ·
ไฟล์ .ps1 ไม่มี BOM ต้องรันด้วย `pwsh`

งานค้าง + รายละเอียดเต็ม: `~/Desktop/ui/CLAUDE.md` หัวข้อ "▶️ เซสชันหน้าเริ่มตรงนี้"
(Perfect World ซ่อมช่องว่าง 200k จุด · เส้นอ่านไฟล์จากดิสก์ · อัป Xian Ni เต็มเล่ม)

related: [[hybrid_ai_status]] · [[feedback-voice-bargein-off]]



## 📦 บรรทัดดัชนีฉบับเต็มก่อนย่อ (ย้ายมา 2026-08-18)

/ws/reader + ปุ่ม 📖 · Live API อ่านคำต่อคำ 100% (TTS ติดเพดาน 10/วัน) · 🔒 **08-17 user สั่ง "เสียง/จังหวะอ่านลงตัวแล้ว ห้ามแก้"** (รวม temperature — ค่าเดียวกับโหมดคุย ห้ามเสนอถอดซ้ำ) · ✅ **08-17 ปิด 4 อาการแล้ว + deployed** (ตัวอ่านซ้อน · ขวัญตอบทับ · กดพักไม่หยุด · ประโยคซ้ำ) + ปุ่ม 🔁 อ่านท่อนนี้ใหม่ · **ห้ามเอา pacing กลับ** · ทางเข้า PC .235 (`penpu@` key ใน administrators_authorized_keys) · Tailscale บล็อก LAN TCP บนแมค → ใช้ nas-cf · งานค้างใน ~/Desktop/ui/CLAUDE.md

---

## 📦 archive — YAML frontmatter ของ memory ก่อนย่อ (2026-08-17)
```
---
name: project-khim-reader
description: Khim AI — ระบบขวัญอ่านนิยาย (เสร็จ ใช้จริงแล้ว) + ข้อจำกัด/ทางเข้าเครื่องที่ต้องรู้
metadata: 
  node_type: memory
  type: project
  originSessionId: 7c7f8e51-9122-4b73-945c-afafd11b9ef8
  modified: 2026-08-17T06:32:36.310Z
---
```
