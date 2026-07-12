# ROADMAP — Hybrid AI Workspace (Khim AI)

> จัดทำจากการ audit ทั้งโปรเจกต์ 2026-07-12 · สถานะ ณ วันตรวจ: backend 690 tests ผ่านหมด ·
> frontend (appscript.ui) 111 vitest ผ่านหมด, git clean, backup 2 remotes ✅ ·
> โครงหลักแข็งแรง — งานที่เหลือส่วนใหญ่เป็น "ปิด loose ends" ไม่ใช่สร้างใหม่
> ⚠️ สถานะฝั่ง NAS prod ในเอกสารนี้อ้างจากบันทึกล่าสุด (2026-06-18/07-05) — session นี้ตรวจสดไม่ได้ ให้ verify ตอนลงมือ

---

## P0 — ปัญหาที่เจอจริงวันนี้ / เสี่ยงข้อมูล-เสถียรภาพ

### 1. Icon\r recur รอบ 5 (เจอ+ลบแล้ว 2,668 ไฟล์ 2026-07-12) — ต้องแก้ที่ต้นตอ
- อาการรอบนี้: ลามเข้า `.venv/` ทำ **pytest collection พังทั้ง suite** (NotADirectoryError)
- ลบแล้วรอบที่ 5 — การลบซ้ำไม่ใช่ทางแก้ ต้องปิดที่ต้นตอ:
  - [ ] เช็คว่า iCloud Desktop & Documents sync ถูกปิดจริง (`System Settings → iCloud → Drive → Desktop & Documents`) — เคย "ปิดแล้ว" แต่ recur แสดงว่ายังมีตัวเขียนอยู่
  - [ ] ถ้าปิดไม่ได้/ไม่อยากปิด: ทำ launchd job หรือ cron ลบ `Icon\r` รายวัน + เพิ่มบรรทัด `Icon?` ใน `.gitignore` ทุก repo ที่โดน
  - [ ] ระยะยาว: พิจารณาย้ายโปรเจกต์ dev ออกจาก `~/Desktop` (โฟลเดอร์ที่ iCloud จับ) ไป `~/dev/` — ตัดปัญหาถาวร

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
- [ ] เทส upload PDF scan จริง 1 ไฟล์ผ่าน UI (ยังไม่ได้ทำ — ต้องมีไฟล์ scan จริง)

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

### 9. Admin API ลบ episodic memory (แก้ pain "memory ปนเปื้อนจากการเทส")
- ทุกวันนี้เทส `/api/chat` บน prod แล้วต้องต่อ ChromaDB ตรงเพื่อลบขยะ (Known Quirks) — ทำผิดพลาดง่ายและเคยเกิด contamination จริง (2026-06-11)
- [ ] `GET /api/admin/memory/{assistant}?q=...` (list+preview) + `DELETE /api/admin/memory/{assistant}/{id}` — จำกัด LAN-only เหมือน `/api/admin/unlock`
- [ ] ตัวเลือกเสริม: header/flag `X-Test-Request` ให้ chat ข้าม remember/teach ตอน smoke test — ตัดปัญหาที่ต้นทาง

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

### 12. Web-search grounding classifier (#34 ค้างตั้งแต่ 2026-06-11)
- [ ] เขียน test ที่ค้างให้จบ + ตัดสินว่าจะขยาย `needs_internet()` ตามบริบท หรือเปิด grounding ทุก call ของ Gemini
- [ ] วัดผลด้วยชุดคำถาม real-time (ราคาทอง/อากาศ/ข่าว) ก่อน-หลัง

### 13. สะสม 👍 → fine-tune ขวัญ (pipeline พร้อมทั้งเส้นแล้ว)
- [ ] เช็คยอดปัจจุบัน: `GET /api/feedback/stats` (เป้า ~200-500)
- [ ] ระหว่างรอ: รัน `scripts/auto_score.py` (RLAIF) สะสมคู่ auto-scored แยกไว้
- [ ] ครบเป้า → `scripts/improve_loop.sh` บน PC GPU (.235) — **ห้าม deploy ถ้า eval gate FAIL**

### 14. Verify ด้วยตาที่ค้าง (งานเปิด browser 15 นาที)
- [ ] File Manager: drag&drop / กล้อง 📷 / index toast บน prod จริง
- [ ] Dream cycle บน prod ยังผลิต report รายคืนไหม (local มี report เดียว 2026-05-08 — ปกติเพราะ dev ไม่ได้เปิดค้าง แต่ prod ควรมีทุกคืน) → `ls dream_reports/` บน NAS + ดู Sleep card

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
