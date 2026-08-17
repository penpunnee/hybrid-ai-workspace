# Infrastructure — NAS / LMStudio / ChromaDB / deploy channels

> ยกมาจาก memory `hybrid_ai_infra.md` เมื่อ 2026-08-17 · **เนื้อไม่ถูกแก้**
> (ตัดเฉพาะ YAML frontmatter) · เครือข่ายบ้านส่วนกลางอยู่ memory `project_home_network.md`
> 🔴 อ่านก่อน deploy/probe production ทุกครั้ง

## SSH access to NAS — กลับมาใช้ได้แล้ว (user ปลด 2FA ออก, แจ้ง 2026-06-12)
`ssh pawin@192.168.51.49` ด้วย password ควรใช้ได้ปกติแล้ว — **อย่าอ้างบันทึกเก่าว่า SSH ตัน**
✅ **key auth ก็ผ่านแล้ว (verified 2026-06-12):** `ssh -o BatchMode=yes pawin@192.168.51.49` ไม่ต้องรหัส + `sudo -n /usr/local/bin/docker ...` ใช้ได้ → deploy ตรงจาก Mac: `git fetch origin main && git reset --hard origin/main && sudo -n docker restart ai-backend-1` (โค้ด volume mount แค่ restart ไม่ต้อง recreate/build)
ประวัติ (เผื่อเจออาการเดิมซ้ำ): ช่วงที่ 2FA เปิดอยู่ (พ.ค. 2026) password auth โดนบล็อก, key auth ติด PAM `Permission denied`, และลองซ้ำหลายครั้งโดน DSM Auto Block แบน IP — ถ้า SSH ไม่ติดให้เช็ก Auto Block list ใน DSM ก่อน
- (id_ed25519 เป็น deploy key ของ repo "Rat" บน GitHub เท่านั้น)

### ✅ วิธี deploy ที่ใช้ได้จริง = DSM Task Scheduler (ไม่ผ่าน SSH เลย)
1. สร้าง git bundle ของ commit: `git bundle create /tmp/x.bundle <base>..main`
2. base64 bundle → ฝังใน script (heredoc) → ให้ user สร้าง **Task Scheduler → User-defined script (User: `pawin`)** → paste → Run
3. script: decode bundle → `git fetch <bundle> main && git checkout FETCH_HEAD -- core utils routers agents` → เติม .env → `sudo -n /usr/local/bin/docker compose up -d hybrid-ai --force-recreate`
4. pbcopy script ขึ้น clipboard ให้ user paste ง่าย. Task Scheduler รันเป็น root/pawin local — ไม่ติด 2FA/AutoBlock

### ✅ verify deploy เอง = ยิง API ตรงทาง LAN (bypass auth)
Mac อยู่วง LAN 192.168.51.x → ยิง `http://192.168.51.49:8080/api/chat` ตรง (LAN IP bypass auth ไม่ต้อง token!)
- distinguish backend: ถาม "base model name" → Ollama=`Llama/Meta`, LM Studio=`Gemma 4/Google DeepMind`
- ⚠️ self-ID มี hallucinate ("Gemini") บ้าง — ใช้ร่วมกับ error signature (provider=lmstudio เด้ง model-not-found, ollama ไม่เด้ง = redirect หาย)

## Sudo nopw for docker
NAS sudoers อนุญาตให้ `pawin` รัน `docker` ผ่าน sudo โดยไม่ต้องรหัสผ่าน — แต่ต้องใช้ flag `-n` (non-interactive):
```bash
ssh pawin@192.168.51.49 "sudo -n /usr/local/bin/docker compose -f /var/services/homes/pawin/ui/docker-compose.yml up -d hybrid-ai --force-recreate"
```
**Note:** `which docker` ไม่เจอ ตอน non-interactive shell — ต้องใช้ full path `/usr/local/bin/docker`

## Ports & Hosts
- **FastAPI app**: `192.168.51.49:8080` (mapped จาก container `:8000`) — NOT 8000!
- **ChromaDB**: `192.168.51.49:8000` — ใช้ `/api/v2/heartbeat` (v1 → 410 Gone)
- **Ollama**: `192.168.51.235:11434` (PC) — model `llama3`. ⚠️ port 11434 ไม่ใช่ 1234
- **LMStudio**: `192.168.51.235:1234` (PC เดียวกับ Ollama) — เปิด LMStudio app + Start Server. มี gemma-4-e4b, llama-3.2-11b-vision ฯลฯ
- ⚠️ PC `.235` ต้องเปิดเครื่อง local LLM ถึงจะใช้ได้ — ถ้า PC ปิด → ollama+lmstudio ล่มหมด → ตกไป Gemini → quota หมดง่าย
- **DSM Web**: `https://192.168.51.49:5001` (auto cert) หรือ `http://:5000`
- **Cloudflare tunnel**: `https://ai.pawinhome.com` → routes ไป `localhost:8080` ใน NAS

## Volume mount gotcha (สำคัญ!)
`docker-compose.yml` ของ hybrid-ai mount:
```yaml
${NAS_DATA_PATH:-./data}/skills:/app/skills
```
- Container อ่าน .md จาก `/var/services/homes/pawin/ui/data/skills/`
- **NOT** จาก `/var/services/homes/pawin/ui/skills/` (git repo path)
- หลัง `git pull` ใหม่ ต้อง `cp skills/*.md data/skills/` เพื่อให้ container เห็น

## LLM provider routing (session 2026-05-26 fix)
- **ปุ่มแยกชัด ไม่ cross-redirect**: ปุ่ม Ollama→Ollama, LM Studio→LM Studio, Gemini→Gemini, auto→router. เดิม `utils/llm.py` มี bug redirect `provider=="ollama"` ไป LM Studio (ลบออกแล้ว)
- Gemini quota หมด → fallback local (LM Studio ถ้าตั้ง `LMSTUDIO_BASE_URL`, ไม่งั้น Ollama) — `routers/chat.py`
- ค่า address มาจาก `.env` ทั้งหมด (เลิก hardcode IP ใน source). `LMSTUDIO_BASE_URL` default = `""`
- ⚠️⚠️ **`.env` ถูก gitignore → ไม่ sync ขึ้น git**. แก้ `.env` บน Mac ไม่ไปถึง NAS — ต้องแก้ `.env` บน NAS แยก (`/var/services/homes/pawin/ui/.env`) ด้วยมือ แล้ว docker recreate
- embeddings/reflection/query_rewrite/skill_discovery ใช้ LM Studio (อ่าน `LMSTUDIO_BASE_URL` จาก .env) — ต้องตั้งค่าไม่งั้น memory/RAG/cache เพี้ยน

## GitHub repo
`https://github.com/penpunnee/hybrid-ai-workspace` (main branch)
- ✅ **(แก้แล้ว 2026-05-27)** remote เปลี่ยนเป็น SSH `git@github.com:penpunnee/hybrid-ai-workspace.git` — **ไม่มี PAT ฝังใน URL อีกแล้ว** (ของเก่า `ghp_O3BB1pL...` HTTPS หายไป)
- ✅ **push จาก Mac ได้แล้ว** (SSH auth ผ่าน) — ต่างจากบันทึกเก่าที่ว่า id_ed25519 push hybrid-ai ไม่ได้. verified: push `fix/llm-cascade-parser` สำเร็จ 2026-05-27
- ✅ **deploy จากนอกบ้านได้แล้ว!** (verified 2026-05-27) ผ่าน **QuickConnect (id `Pawinh`, เปิดตลอด) → DSM Task Scheduler → สร้าง User-defined script (user `pawin`) → paste → Run**. ไม่ต้องอยู่วง LAN — เฉพาะ probe/curl API ตรงเท่านั้นที่ต้องอยู่วง 192.168.51.x
- ✅ **NAS `git fetch origin main` จาก GitHub ได้แล้ว** → deploy script ใช้ `git fetch origin main` + `git checkout origin/main -- utils/llm.py reasoning/parser.py` + `sudo -n /usr/local/bin/docker compose up -d --force-recreate hybrid-ai`. **เลิกใช้ base64 bundle ได้** (โค้ด mount เป็น volume → recreate พอ ไม่ต้อง build). script เก็บที่ `/tmp/nas_deploy.sh` (git-fetch flavor)
- ⚠️ paste script เข้า DSM **ห้าม copy จาก markdown/แชต** (โดน HTML-encode `>`→`&gt;`, `&`→`&amp;`, ครอบ URL ด้วย `<>`) → ใช้ `pbcopy` clipboard หรือไฟล์ดิบเท่านั้น
- ✅✅ **SMB = deploy ไฟล์ตรงได้! (verified 2026-05-27)** ตอน Mac อยู่วง LAN `.51.x`: `mkdir -p /tmp/mnt; mount_smbfs '//pawin:<pass-urlenc>@192.168.51.49/home' /tmp/mnt` → home share = `/var/services/homes/pawin/` → แก้ไฟล์ที่ `/tmp/mnt/ui/...` ตรง. **SMB ไม่ติด 2FA** (2FA แค่ DSM web/SSH). รหัส url-encode `@`→`%40`
  - **static file** (`static/enhanced.js` — เสิร์ฟจาก disk per-request) → SMB copy แล้ว **live ทันที ไม่ต้อง restart** (แค่ browser hard-refresh กัน cache). แก้ UI/CSS เร็วมาก
  - **code file** (`utils/*.py` volume mount) → SMB copy ได้ แต่ Python process ต้อง restart (docker recreate = ต้อง shell/Task Scheduler) ถึง reload → SMB ช่วยเต็มๆ แค่ static
  - (อัปเดต 2026-06-12: 2FA ปลดแล้ว → SSH password ใช้ได้ — SMB/Task Scheduler ยังเป็นทางเลือกสำรอง)
- ⚠️ Task Scheduler ต้องตั้ง user = `pawin` (ไม่ใช่ root) ไม่งั้น git เด้ง "dubious ownership" เพราะ repo เป็นของ pawin

## Off-LAN deploy channels + recreate-vs-restart (session 2026-06-15, ทำผ่าน remote-control บนมือถือ)
**เมื่อ Mac อยู่นอกวง LAN** (เช่น hotspot, IP `192.168.6.x`): `ssh nas`/`ssh pawin@192.168.51.49` **timeout** (private IP route ไม่ถึง) — SSH config ถูกต้อง แต่ไม่ใช่ปัญหา config มันคือ network reachability. ช่องที่ใช้ได้ off-LAN:
- ❌ WireGuard (`sudo wg-quick up home`) — ต้องรหัส sudo; เครื่องมือ Claude พิมพ์รหัส interactive ไม่ได้ และ remote-control บนมือถือ **ไม่รองรับ `!` prefix** (มันส่งเป็นข้อความแทนที่จะรันคำสั่ง local) → ทางนี้ตันถ้า user อยู่มือถือ
- ❌ browser SSH `ssh.pawinhomelab.com` — เจอ "cannot connect to origin server" (route SSH ของ cloudflared พังแม้แอปหลักยัง 200) · `cloudflared` ก็ไม่ได้ติดตั้งบน Mac
- ✅ **DSM ผ่าน QuickConnect** `pawinh.sg3.quickconnect.to` (หรือ `nashome.pawinhome.com`) → File Station + Task Scheduler + Container Manager ทำงานได้หมด — เป็นทางหลักเมื่ออยู่นอกบ้าน
- ✅ **curl public** `https://ai.pawinhome.com` — verify ได้เฉพาะ open paths: `/api/config` (คืน `ollama_model` = `LMSTUDIO_CHAT_MODEL` ใน container ตอนนี้ → ใช้เช็คว่า recreate โหลด .env ใหม่จริงไหม!), `/api/status` (`local_ok`). `/api/models` = **401 ต้อง token** (curl เปล่าอ่านไม่ได้ = ปกติ ไม่ใช่บั๊ก)

⚠️⚠️ **deploy task `deploy-hybrid-ai` = `git pull` + `docker restart` เท่านั้น → ไม่ reload `.env`!** (`docker restart` reuse env เดิมตอน create). code เป็น volume mount → restart พอสำหรับโค้ด แต่ **เปลี่ยน `.env` ต้อง recreate**:
- สร้าง Task Scheduler task **`recreate-ai`** (User-defined script, **User: root** ok เพราะไม่มี git → ไม่ติด dubious-ownership) command:
  `cd /var/services/homes/pawin/ui && /usr/local/bin/docker compose up -d --force-recreate hybrid-ai`
  (target service `hybrid-ai` ตัวเดียว → ไม่แตะ chromadb/cloudflared) — task นี้ถูกสร้างไว้แล้ว 2026-06-15
- recreate ใช้เวลานานกว่า restart (~30-60s+) — เช็ค `/api/config` ซ้ำถ้าครั้งแรกยังเป็นค่าเก่า อย่าด่วนสรุปว่าพัง
- service/container ใน compose: `hybrid-ai`→`ai-backend-1`, `chromadb`, `cloudflared`→`ai-cloudflared`. hybrid-ai ใช้ `env_file: .env` (เช็คแล้ว) + `environment:` override 3 ตัว (DB_PATH/OBSIDIAN_VAULT_PATH/LOG_FILE)

## Probe script
`/Users/pawin/Desktop/ui/scripts/probe_live.sh` — รัน smoke test ของ production end-to-end
```bash
bash /Users/pawin/Desktop/ui/scripts/probe_live.sh
```

## **Why:** session 2026-05-12 ทดสอบ deploy ครั้งใหญ่จนเข้าใจ infrastructure ทั้งหมด เก็บไว้กัน probe ซ้ำใน session หน้า

## **How to apply:** ก่อน deploy/probe production → ดูเอกสารนี้ก่อน. Sudo nopw ใช้ได้ทันที — ไม่ต้องถามผู้ใช้ให้ login. Volume mount gotcha สำคัญที่สุด ผมเสีย .md หาย 8 ไฟล์เพราะไม่รู้

---

## 📦 archive — YAML frontmatter ของ memory ก่อนย่อ (2026-08-17)
```
---
name: Hybrid AI Workspace — Infrastructure access
description: วิธีเข้าถึง production stack (NAS, ChromaDB, LMStudio) และ gotchas ที่เจอจริง
type: reference
originSessionId: 594cec9b-b2b7-45fc-9275-05ad1e59ecf2
---
```
