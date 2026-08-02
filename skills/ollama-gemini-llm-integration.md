# LLM Integration — Ollama / LMStudio / Gemini

`utils/llm.py` รวม 3 providers ผ่าน function เดียว: `stream_response(messages, provider, image_b64, image_mime, agent_mode, model_override)`

## 🔀 Provider Routing

```
stream_response(provider=...)
├── "gemini_agent"  → Gemini + tools (Google Search + Code Execution)
├── "gemini"        → Gemini (or force ถ้ามี image_b64)
├── "lmstudio"      → LM Studio OpenAI-compatible API
├── "lmstudio_web"  → LM Studio + DDG web context injection
├── "ollama"        → Ollama (redirect ไป LMStudio ถ้า LMSTUDIO_BASE_URL ตั้ง)
└── "auto"          → reasoning/router.py ตัดสินใจตาม complexity classifier
```

## 🦙 Ollama (Local)

**Config (`core/config.py`):**
```env
OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_MODEL=llama3
OLLAMA_TIMEOUT=120
OLLAMA_MAX_RETRIES=2
OLLAMA_RETRY_DELAY=2
OLLAMA_TEMPERATURE=0.7
OLLAMA_TOP_P=0.85
OLLAMA_NUM_CTX=4096
OLLAMA_REPEAT_PENALTY=1.1
```

**ใช้ OpenAI SDK** เรียกตรง (Ollama รองรับ OpenAI-compatible endpoint)

**Retry logic:** 2 ครั้ง พร้อม exponential backoff (2s → 4s)
- Connection error / Timeout → retry
- Model not found → ไม่ retry, แสดงคำแนะนำ `ollama pull <model>`

**Health check:** `check_ollama_health()` cache 30s

## 💎 Gemini (Cloud)

**SDK:** `google-genai` (ใหม่ ไม่ใช่ google-generativeai เก่า)

**Config:**
```env
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.5-flash      # default ไว
GEMINI_LIVE_MODEL=gemini-2.5-flash-native-audio-latest   # สำหรับ voice WebSocket
# ⚠️ gemini-2.0-flash-exp / gemini-live-2.0-flash-001 ถูกถอดจาก Live API แล้ว (คืน 1008 not found)
```

**Features:**
- Vision: ใส่ image_b64 ลง `Part(inline_data=Blob(...))` ใน user message สุดท้าย
- Agent mode: เปิด `tools = [GoogleSearch, ToolCodeExecution]` → AI ใช้ web search + code exec ได้เอง
- Streaming: `generate_content_stream()`

**Error classes:**
- `GeminiQuotaExhausted` — quota หมด → fallback LMStudio + web search อัตโนมัติ
- `GeminiUnavailable` — key ผิด / network → fallback LMStudio

## 🎨 LM Studio (Local)

**Config:**
```env
LMSTUDIO_BASE_URL=http://192.168.51.235:1234/v1
LMSTUDIO_CHAT_MODEL=qwen/qwen3.5-9b
LMSTUDIO_REASON_MODEL=qwen/qwen3.5-9b
LMSTUDIO_VISION_MODEL=qwen/qwen3.5-9b
LMSTUDIO_TIMEOUT=180
SHOW_THINKING=false   # toggle เพื่อแสดง <think>...</think> block
```

**OpenAI-compatible** — ใช้ `OpenAI()` client เหมือน Ollama

**Vision:** ใช้ `LMSTUDIO_VISION_MODEL` (qwen/qwen3.5-9b) ถ้ามี `image_b64`

**Reasoning model:** `qwen/qwen3.5-9b` (ตั้งแต่ 2026-07-05) — ถ้าโมเดลส่ง `<think>...</think>` มา `reasoning/parser.py:stream_with_thinking()` กรองออกก่อนแสดง (เว้น SHOW_THINKING=true)

## 🌐 Web Search Augmentation (`lmstudio_web`)

ใช้เมื่อต้องการ real-time data:
1. `utils/websearch.py:web_search_with_results(query)` ค้น DuckDuckGo
2. Wikipedia/Weather routing สำหรับ definitional/weather queries
3. Fetch HTML จริงของ top 2 results
4. Rerank ด้วย embedding (`utils/embed.py:rerank_by_similarity`)
5. Format → inject เข้า system prompt ก่อน LMStudio
6. AI ตอบโดย ground บนเนื้อหาที่ดึงมา

## 🔁 Fallback Chain (เมื่อ Gemini quota หมด)

```
Gemini quota exhausted
   ↓ (in routers/chat.py)
needs_internet(prompt)? 
   ├── YES → web_search_with_results + LMStudio
   └── NO  → LMStudio direct
```

## ⏱️ Timing Markers (Phase E observability)

ทุก call บันทึก:
- `context_assembly` ms
- `retrieval` ms (memory + skills + docs)
- `llm_stream` ms (จริงๆ จาก LLM)

ดู `done` SSE event field `timings`
