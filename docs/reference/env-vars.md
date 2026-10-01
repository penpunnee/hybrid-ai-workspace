# Environment Variables (อ้างอิง)

> ยกทั้งดุ้นจาก `CLAUDE.md` เมื่อ 2026-10-01 (ไฟล์นั้นโต 103 KB และถูกฉีดทุกเซสชัน) — **ไม่ได้แก้เนื้อหา**
> หัวข้อ ▶️ / กติกาที่ยังมีผล ยังอยู่ใน `CLAUDE.md` · ประวัติอยู่ใน `docs/session-log/devlog.md`

### Environment Variables
```env
# AI
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.5-flash-lite   # ค่าที่ prod ตั้ง · default ในโค้ด = `utils/llm.py:GEMINI_MODEL_DEFAULT` (gemini-3.5-flash) · ⚠️ gemini-2.5-flash ปิด 2026-10-16 (`GEMINI_MODEL_SUNSET`) · ห้ามใช้ gemini-2.5-pro บน free tier (quota limit=0 → 429 ทุก request, เจอจริง 2026-06-11)
GEMINI_FALLBACK_MODEL=gemini-3.1-flash-lite   # สำรองเมื่อตัวหลัก transient-fail · ว่าง = ไม่สลับโมเดล
GEMINI_SEARCH_MODEL=            # โมเดลเฉพาะ gemini_web_search() (grounding ให้ local/Claude/Kimi) — ว่าง = ใช้ GEMINI_MODEL; precedence: arg > env นี้ > GEMINI_MODEL (มีตั้งแต่ 7087f88, test ใน test_gemini_web_search.py)
GEMINI_WEB_SEARCH_ENABLED=true    # false = ข้าม gemini_web_search ไปเส้น Brave ตรง — free tier grounding = 429 limit: 0 · prod ตั้ง false (2026-10-01)
GEMINI_LIVE_MODEL=gemini-3.1-flash-live-preview   # default อยู่ที่ `utils/voice.py:GEMINI_LIVE_MODEL_DEFAULT` ที่เดียว (ดูหัวข้อ "เสียงต้องเป็นคนเดิม") ⚠️ ห้ามสลับไปสาย native-audio โดยไม่ถอด `VOICE_TEMPERATURE` — วัดแล้วเสียงหายเงียบๆ 0 ไบต์ · gemini-2.0-flash-exp/gemini-live-2.0-flash-001 ถูกถอดจาก Live API แล้ว (1008 not found). เช็ค model ที่ใช้ได้: ListModels filter supportedGenerationMethods มี bidiGenerateContent
GEMINI_TTS_MODEL=gemini-2.5-flash-preview-tts   # ⚠️ ต้องเป็นสาย `*-tts` เท่านั้น (`utils/tts.py` เรียก generateContent ไม่ใช่ bidi) · ห้ามใส่สาย native-audio เด็ดขาด = 404 ทุก request · free tier 10 req/วัน/โมเดล · ทางเลือกที่วัดแล้วใช้ได้: gemini-3.1-flash-tts-preview · ดูหัวข้อ "🔊 /api/tts"
# Claude (Anthropic) — provider "claude"; ปล่อยว่าง=ปิด
ANTHROPIC_API_KEY=
CLAUDE_MODEL=claude-sonnet-4-6   # default คุ้ม; claude-opus-4-8 = ฉลาดสุด/แพงสุด, claude-haiku-4-5 = ถูกสุด
CLAUDE_MAX_TOKENS=4096           # เพดานคำตอบ = คุม cost
CLAUDE_THINKING=off            # off | adaptive (adaptive=คิดลึกขึ้น แต่ช้าลง)
CLAUDE_EFFORT=high             # low|medium|high|xhigh|max (ใช้คู่ adaptive)
CLAUDE_AUTO=off                # off | reasoning | all — ให้ provider=auto เลือก Claude (ต้องมี key)
# Kimi K2.6 (Moonshot AI) — provider "kimi"; ปล่อยว่าง=ปิด (โชว์ใน Model picker แบบ disabled)
MOONSHOT_API_KEY=
KIMI_BASE_URL=https://api.moonshot.ai/v1   # .cn สำหรับ endpoint จีน
KIMI_MODEL=kimi-k2.6
KIMI_TIMEOUT=180
OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_MODEL=llama3
OLLAMA_TIMEOUT=120
OLLAMA_NUM_CTX=4096
LMSTUDIO_BASE_URL=          # opt-in: ปล่อยว่าง=ปิด (local หลักคือ Ollama). ใส่ค่าเฉพาะเมื่อรัน LM Studio จริง
LMSTUDIO_API_KEY=lmstudio   # ⚠️ LM Studio รุ่นใหม่บังคับ token — ใส่ให้ตรง (หรือปิด "Require API key" ใน LM Studio)
LMSTUDIO_CHAT_MODEL=qwen/qwen3.5-9b
LMSTUDIO_REASON_MODEL=qwen/qwen3.5-9b
LMSTUDIO_VISION_MODEL=qwen/qwen3.5-9b
LMSTUDIO_TIMEOUT=180
SHOW_THINKING=false
# Embeddings — **env ตัวเดียวคุมทั้ง Ollama (ตัวหลัก) และ LM Studio (fallback)**
EMBEDDING_MODEL=paraphrase-multilingual   # ⛔ ห้ามใช้ `nomic-embed-text` เป็นตัวหลัก — พิสูจน์บน prod 2026-08-02 ว่าแมปประโยคไทยทุกประโยคเป็น vector เดียวกันหมด (cosine 1.0000) · ปล่อยว่างใน `utils/memory.py` = ปิด embedding_function ของ ChromaDB
EMBED_FALLBACK_LMSTUDIO=true              # false = Ollama ล่มแล้วโยน error ไปเลย ไม่ลอง LM Studio

# Home Assistant
HA_URL=https://ha.pawinhome.com   # หรือ http://192.168.51.x:8123 ถ้าใช้ LAN เท่านั้น
HA_TOKEN=                          # Long-Lived Access Token (HA → Profile → Security)
HA_TIMEOUT=10                      # วินาที

# Auth + Network
UI_PASSWORD=
CORS_ORIGINS=
# Rate limiting (public exposure) — LAN/loopback bypass; ปิดด้วย false
RATE_LIMIT_ENABLED=true
RATE_LIMIT_RPM=120            # req/นาที/IP
AUTH_FAIL_MAX=8              # 401 กี่ครั้งใน window ก่อน lock IP
AUTH_FAIL_WINDOW=300        # วินาที
NAS_IP=192.168.51.49
NAS_USER=
NAS_PASS=
PC_IP=192.168.51.235
PC_MAC=

# Storage
DB_PATH=/app/data/chat_history.db  # (ย้ายจาก mount ไฟล์เดี่ยว 09-29 · WAL ต้องการโฟลเดอร์) ⛔ docker-compose `environment:` ทับ `env_file:` — ตั้งใน .env **ไม่มีผลในคอนเทนเนอร์** (มีผลเฉพาะรัน local ตรงๆ)
OBSIDIAN_VAULT_PATH=/vault  # ⛔ docker-compose `environment:` ทับ `env_file:` — ตั้งใน .env **ไม่มีผลในคอนเทนเนอร์** (มีผลเฉพาะรัน local ตรงๆ)
CHROMA_HOST=
NAS_DATA_PATH=./data

# Phase B-E feature toggles
SKILLS_SEARCH_MIN_SCORE=0.38          # พื้นคะแนนของ search_skills() (ปิด =off) — ดูหัวข้อท้ายไฟล์
QUERY_REWRITE_ENABLED=true
QUERY_REWRITE_TIMEOUT=8
REFLECTION_MODEL=
REFLECTION_THRESHOLD=0.7
EMBED_CACHE_ENABLED=true
EMBED_CACHE_DB=./data/embed_cache.db
RESPONSE_CACHE_ENABLED=true
RESPONSE_CACHE_THRESHOLD=0.92
RESPONSE_CACHE_TTL_DAYS=30
RESPONSE_CACHE_MAX=1000

# Phase D sandbox
CODE_SANDBOX_IMAGE=python:3.11-slim
CODE_SANDBOX_TIMEOUT=10
CODE_SANDBOX_MAX_TIMEOUT=60
CODE_SANDBOX_MEM=256m
CODE_SANDBOX_CPU=0.5
CODE_SANDBOX_ALLOW_LOCAL=false        # ⚠️ true = run on host without Docker
FS_TOOLS_ROOTS=                       # colon-separated; default ~/Desktop/ui/sandbox

# Phase F observability
LOG_LEVEL=INFO
LOG_FORMAT=plain                      # plain | json
LOG_FILE=/app/logs/server.log  # ⛔ docker-compose `environment:` ทับ `env_file:` — ตั้งใน .env **ไม่มีผลในคอนเทนเนอร์** (มีผลเฉพาะรัน local ตรงๆ)
```
