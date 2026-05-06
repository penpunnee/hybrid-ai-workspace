# Hybrid AI Workspace - Project Summary

## ภาพรวมโปรเจกต์

โปรเจกต์ Hybrid AI Workspace เป็นระบบ AI Assistant ที่รองรับทั้ง Local LLM (Ollama) และ Cloud LLM (Gemini) พร้อมระบบ Memory, Dream Cycle, และ Obsidian Vault Integration

---

## สถาปัตยกรรมระบบ

### Core Components

1. **Frontend**
   - `app.py` - Streamlit UI สำหรับการแชทและจัดการ
   - `static/` - React build output สำหรับ Web UI

2. **Backend**
   - `server.py` - FastAPI server ให้บริการ API endpoints
   - WebSocket สำหรับ Voice Mode

3. **AI Integration** (`utils/llm.py`)
   - **Ollama (Local)**: เชื่อมต่อผ่าน OpenAI SDK
     - Retry mechanism: 2 ครั้ง พร้อม exponential backoff (2s, 4s)
     - Timeout: 120 วินาที
     - Health check: ตรวจสอบ service และ model availability พร้อม caching 30 วินาที
   - **Gemini (Cloud)**: เชื่อมต่อผ่าน google-genai SDK
     - รองรับ Agent Mode (Google Search + Code Execution)
     - รองรับ Image Analysis

4. **Memory System** (`utils/memory.py`)
   - **ChromaDB**: Vector database สำหรับเก็บความจำ
   - **Collections**:
     - `memory_{assistant}`: Short-term memory สำหรับแต่ละ assistant
     - `lessons`: บทเรียนที่ AI เรียนรู้
     - `preferences`: ความชอบของผู้ใช้
     - `long_term_memory`: ความจำระยะยาวจาก Dream Cycle
   - Auto-detect ChromaDB host: chromadb, 192.168.51.49, chroma.pawinhome.com

5. **Dream Cycle** (`utils/dream.py`)
   - **Phase 1 - Light Sleep**: ดึง memory ดิบจาก ChromaDB (ย้อนหลัง 24 ชั่วโมง)
   - **Phase 2 - REM Sleep**: ใช้ AI วิเคราะห์ pattern และสรุปเป็น themes
   - **Phase 3 - Deep Sleep**: Promote ข้อมูลสำคัญไป skills_db.json และ long_term_memory
   - รันทุกคืน 2 ครั้งผ่าน cron job

6. **Obsidian Vault Integration** (`utils/obsidian_sync.py`)
   - Sync ไฟล์ .md จาก Obsidian Vault ไป ChromaDB
   - Semantic search สำหรับดึง context ในการแชท
   - Auto-sync เมื่อมีการเปลี่ยนแปลง (ตรวจสอบ mtime)

---

## Data Flow

### การแชท (Chat Flow)
```
User Input → app.py/server.py 
           → stream_response(utils/llm.py)
           → Ollama/Gemini
           → Stream Response
           → save_memory(utils/memory.py)
           → Auto-learn (save_lesson, save_preference)
```

### Dream Cycle Flow
```
Trigger → run_dream_cycle()
        → light_sleep() (ดึง memory จาก ChromaDB)
        → rem_sleep() (วิเคราะห์ผ่าน stream_response)
        → deep_sleep() (promote ไป long-term memory)
        → save_report() (บันทึก dream_reports/)
```

### Obsidian Context Flow
```
Chat Request → obsidian_inject=True
             → search_vault() (ค้นหา notes)
             → Inject context ลง messages
             → AI Response พร้อม context
```

---

## Configuration (`.env`)

```env
# Ollama (Local LLM)
OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_MODEL=llama3
OLLAMA_TIMEOUT=120
OLLAMA_MAX_RETRIES=2
OLLAMA_RETRY_DELAY=2

# Gemini (Cloud LLM)
GEMINI_API_KEY=your_key_here
GEMINI_MODEL=gemini-2.0-flash

# ChromaDB (Long-term Memory)
CHROMA_HOST=localhost
CHROMA_PORT=8000

# Obsidian Vault
OBSIDIAN_VAULT_PATH=/path/to/vault
```

---

## API Endpoints (สำคัญ)

| Method | Path | การทำงาน |
|---|---|---|
| POST | `/api/chat` | แชท streaming SSE |
| GET | `/api/status` | สถานะ Ollama/Gemini/Memory |
| POST | `/api/dream` | รัน Dream Cycle |
| GET | `/api/vault/sync` | Sync Obsidian Vault |
| GET | `/api/vault/search` | ค้นหา Obsidian notes |

---

## Error Handling & Logging

### Logging Configuration
- **File**: `server.log`
- **Format**: `%(asctime)s - %(name)s - %(levelname)s - %(message)s`
- **Level**: INFO

### Logging Points
- **utils/llm.py**: Ollama connection errors, timeout, model not found
- **utils/memory.py**: ChromaDB connection errors, save/search failures
- **utils/dream.py**: Dream cycle errors, parse errors
- **utils/obsidian_sync.py**: Vault sync/search errors

### Error Classification (Ollama)
- **Connection Error**: Retry 2 ครั้ง พร้อม exponential backoff
- **Model Not Found**: ไม่ retry แสดงคำแนะนำการ pull model
- **Timeout**: Retry 2 ครั้ง พร้อม exponential backoff

---

## Integration Points (Verified ✅)

1. **GBRAIN Memory Integration**
   - ✅ `save_memory()` บันทึกทุกการสนทนาหลัง AI ตอบ
   - ✅ Auto-learn background thread สรุปบทเรียนและความชอบ
   - ใช้ใน: `app.py`, `server.py`

2. **Dream Cycle Integration**
   - ✅ Light Sleep: ดึง memory จาก ChromaDB
   - ✅ REM Sleep: ใช้ `stream_response()` จาก llm.py
   - ✅ Deep Sleep: บันทึกกลับ ChromaDB (skills + long-term memory)

3. **Obsidian Vault Integration**
   - ✅ `obsidian_inject=True` ค้นหา notes ที่เกี่ยวข้อง
   - ✅ Inject context ลง `full_context` ก่อนส่งให้ AI
   - ✅ API endpoints: `/api/vault/sync`, `/api/vault/search`

---

## การปรับปรุงที่ทำล่าสุด

1. ✅ **Retry Mechanism**: ลดจาก 3 เป็น 2 ครั้ง
2. ✅ **Logging**: เปลี่ยนจาก `ollama_errors.log` เป็น `server.log`
3. ✅ **Memory Logging**: เพิ่ม logging ใน `utils/memory.py`
4. ✅ **Obsidian Logging**: เพิ่ม logging ใน `utils/obsidian_sync.py`
5. ✅ **Documentation**: เพิ่ม docstring อธิบาย Logic ใน `utils/llm.py` และ `utils/dream.py`

---

## ไฟล์หลักที่แก้ไข

- `utils/llm.py` - Ollama/Gemini integration, retry mechanism, logging
- `utils/dream.py` - Dream cycle logic, logging
- `utils/memory.py` - ChromaDB operations, logging
- `utils/obsidian_sync.py` - Vault sync/search, logging
- `app.py` - Streamlit UI, memory integration
- `server.py` - FastAPI backend, memory integration
- `.env.example` - Configuration template

---

## สถานะปัจจุบัน

✅ ระบบ Integration ทั้งหมดทำงานได้ถูกต้อง  
✅ Error handling ครอบคลุม พร้อม logging  
✅ Retry mechanism ลดโอกาสการ fail  
✅ Documentation ชัดเจน อ่านทวนได้ง่าย

**เสร็จสิ้นการปรับปรุง Ollama Integration และ Error Handling**
