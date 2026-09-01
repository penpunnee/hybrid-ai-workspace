import os
from dotenv import load_dotenv

load_dotenv()

# ── Ollama (Local LLM) ───────────────────────────────────────────────────────
OLLAMA_BASE_URL    = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL       = os.getenv("OLLAMA_MODEL", "llama3")
OLLAMA_TIMEOUT     = int(os.getenv("OLLAMA_TIMEOUT", "120"))
OLLAMA_MAX_RETRIES = int(os.getenv("OLLAMA_MAX_RETRIES", "2"))
OLLAMA_RETRY_DELAY = int(os.getenv("OLLAMA_RETRY_DELAY", "2"))
OLLAMA_TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", "0.7"))
OLLAMA_TOP_P       = float(os.getenv("OLLAMA_TOP_P", "0.85"))
OLLAMA_NUM_CTX     = int(os.getenv("OLLAMA_NUM_CTX", "4096"))
OLLAMA_REPEAT_PENALTY = float(os.getenv("OLLAMA_REPEAT_PENALTY", "1.1"))

# ── Gemini (Cloud LLM) ───────────────────────────────────────────────────────
GEMINI_API_KEY   = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL     = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
# Live API (bidiGenerateContent) — ⚠️ ชื่อต้องเป๊ะ ไม่งั้น bidiGenerateContent → 1008 not found
# **default ย้ายไปอยู่ที่ `utils/voice.py` แล้ว** (2026-08-04) เพราะเคยมี default 2 ที่ที่
# ไม่ตรงกันเงียบๆ ตั้งแต่ `369f18e` (2026-06-19): ที่นี่เป็น 3.1-flash-live ส่วน
# `utils/voice.py` ค้างที่ 2.5-native-audio-latest พร้อมคอมเมนต์ที่เขียนว่า "ตรงกับ
# core/config.py" — คอมเมนต์บอกเจตนา ไม่ได้บอกพฤติกรรม
from utils.voice import GEMINI_LIVE_MODEL_DEFAULT

GEMINI_LIVE_MODEL = os.getenv("GEMINI_LIVE_MODEL", GEMINI_LIVE_MODEL_DEFAULT)

# ── Database ─────────────────────────────────────────────────────────────────
DB_PATH      = os.getenv("DB_PATH", "./chat_history.db")
CHROMA_HOST  = os.getenv("CHROMA_HOST", "")
CHROMA_PORT  = int(os.getenv("CHROMA_PORT", "8000"))
CHROMA_PATH  = os.getenv("CHROMA_PATH", "./data/chroma")

# ── App ──────────────────────────────────────────────────────────────────────
UI_PASSWORD  = os.getenv("UI_PASSWORD", "")
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "")
RELOAD       = os.getenv("RELOAD", "false").lower() == "true"

# ── Paths ────────────────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS_DIR = os.path.join(PROJECT_ROOT, "skills")
# ⚠️ path เดียวแต่คนละไฟล์ระหว่าง prod กับ dev — เคยทำให้เข้าใจผิดมาแล้ว:
#   prod (container): /app/skills_db.json = bind mount จาก ${NAS_DATA_PATH}/skills_db.json
#                     (ดู docker-compose.yml) = ไฟล์จริงที่มีข้อมูลใช้งาน
#   dev  (บนเครื่อง): <repo>/skills_db.json — **ไม่ถูก track ใน git แล้ว** (2026-08-02)
#                     เพราะสำเนาที่ track ไว้เดิมค้างตั้งแต่ มิ.ย. และเนื้อหาซ้ำกับ
#                     skills/*.md ทุกหัวข้อ → แก้ไฟล์นั้นไม่มีผลกับ prod แต่ดูเหมือนมี
# ไม่มีไฟล์ = `_load_skills_db()` คืน {} เฉยๆ ไม่ crash (skills/*.md ยังโหลดปกติ
# ผ่าน load_skills_relevant) — ถ้าอยากเทส semantic search บน dev ให้ copy ตัวจริงมา
SKILLS_DB_PATH = os.path.join(PROJECT_ROOT, "skills_db.json")

OBSIDIAN_VAULT_PATH = os.getenv("OBSIDIAN_VAULT_PATH", "")
NAS_DATA_PATH       = os.getenv("NAS_DATA_PATH", os.path.join(PROJECT_ROOT, "data"))

# Cache databases (under NAS_DATA_PATH for persistence)
RESPONSE_CACHE_DB = os.path.join(NAS_DATA_PATH, "response_cache.db")
EMBED_CACHE_DB = os.path.join(NAS_DATA_PATH, "embed_cache.db")

# เนื้อหาหนังสือ + ที่คั่นหน้าของโหมดอ่านนิยาย (routers/reader.py)
# แยกไฟล์จาก chat_history.db เพราะเล่มละหลายสิบเมกะไบต์ (ของจริงบน prod 125 MB)
# 🔴 ประกาศที่นี่ที่เดียว — routers/reader.py กับ utils/db_backup.py ต้อง import ตัวนี้
#    เดิม reader.py ประกาศ default ของตัวเอง ส่วน db_backup ไม่รู้จักไฟล์นี้เลย
#    ⇒ ซอง backup เก็บ cache ที่สร้างใหม่ได้ฟรี แต่ไม่เก็บใบที่สร้างใหม่ไม่ได้ (2026-09-01)
#    เป็นความล้มเหลวแบบเดียวกับ default 2 ที่ของ utils/voice.py
# ⚠️ ค่าที่ resolve ได้ต้องเท่าของเดิม (`os.path.join("data", "reader.db")` แบบ relative)
#    ไม่งั้น reader จะมองไม่เห็น DB เดิม: prod มี WORKDIR=/app, PROJECT_ROOT=/app และ
#    env NAS_DATA_PATH **ไม่ได้ตั้งในคอนเทนเนอร์** (docker-compose.yml บรรทัด 35)
#    ⇒ ทั้งสองสูตรได้ /app/data/reader.db ตัวเดียวกัน · ใช้ NAS_DATA_PATH เพราะย้ายตาม
#    cache DB เป็นชุดเดียวกัน แทนที่จะผูกกับ cwd ซึ่งเปลี่ยนได้โดยไม่มีใครสังเกต
# 🔴 แยกเป็น 2 ชื่อโดยตั้งใจ — "ห้าม default ซ้ำ" ไม่เท่ากับ "ห้ามอ่าน env ซ้ำ"
#    ค่า default ซ้ำ = บั๊ก utils/voice.py (สองที่ดริฟต์กันเงียบๆ) ⇒ อยู่ที่นี่ที่เดียว
#    ส่วนการ "อ่าน env" ต้องเกิดในโมดูลที่ใช้ เพราะ tests/test_reader_api.py แยก DB
#    ด้วย monkeypatch.setenv + importlib.reload(routers.reader) — ถ้า reader รับค่า
#    สำเร็จรูปจากที่นี่ reload จะไม่เห็น env ใหม่ (core.config ถูก import ไปแล้ว)
#    แล้ว **เทสจะไปเขียนทับ reader.db ตัวจริง** โดยยังขึ้นเขียว (พลาดมาแล้ว 09-01)
READER_DB_DEFAULT = os.path.join(NAS_DATA_PATH, "reader.db")
READER_DB_PATH = os.getenv("READER_DB_PATH", READER_DB_DEFAULT)

# ── LM Studio (Local LLM — OpenAI compatible) ────────────────────────────────
# LM Studio เป็น opt-in: เปิดใช้เฉพาะเมื่อ set LMSTUDIO_BASE_URL ใน .env
# (default ว่าง — local LLM หลักของระบบนี้คือ Ollama ดู OLLAMA_BASE_URL ด้านบน)
LMSTUDIO_BASE_URL     = os.getenv("LMSTUDIO_BASE_URL", "")
LMSTUDIO_CHAT_MODEL   = os.getenv("LMSTUDIO_CHAT_MODEL", "google/gemma-4-e4b")
LMSTUDIO_REASON_MODEL = os.getenv("LMSTUDIO_REASON_MODEL", "qwen/qwen3.5-9b")
LMSTUDIO_VISION_MODEL = os.getenv("LMSTUDIO_VISION_MODEL", "llama-3.2-11b-vision-instruct")
LMSTUDIO_TIMEOUT      = int(os.getenv("LMSTUDIO_TIMEOUT", "180"))
SHOW_THINKING         = os.getenv("SHOW_THINKING", "false").lower() == "true"

# ── CORS list ────────────────────────────────────────────────────────────────
CORS_ORIGINS_LIST = (
    [o.strip() for o in CORS_ORIGINS.split(",") if o.strip()]
    or ["http://localhost:8000", "http://localhost:5173", "http://192.168.51.49:8080"]
)
