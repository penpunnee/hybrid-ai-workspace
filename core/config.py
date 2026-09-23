"""ค่าคอนฟิกของระบบ — อ่าน env ผ่าน `core/env_registry.py` เท่านั้น

ห้ามเรียก `os.getenv` ตรงๆ ในไฟล์นี้ (มีเทสตรึง `tests/test_env_registry.py`)
เพราะค่าที่ registry มองไม่เห็น = ค่าที่ `.env.example` ที่ generate จากโค้ดไม่มีทางรู้จัก
"""

import os

from dotenv import load_dotenv

from core.env_registry import env_bool, env_float, env_int, env_str

load_dotenv()

# ── Ollama (Local LLM) ───────────────────────────────────────────────────────
_G = "Ollama"
OLLAMA_BASE_URL    = env_str("OLLAMA_BASE_URL", "http://localhost:11434/v1", group=_G,
                             doc="ที่อยู่ Ollama (OpenAI-compatible) — ⚠️ พอร์ต 11434 ไม่ใช่ 1234\n"
                                 "บน Docker: http://host.docker.internal:11434/v1\n"
                                 "บน NAS ที่ Ollama รันบน PC แยกตัว: http://[PC-IP]:11434/v1\n"
                                 "เป็นตัวหลักของ embeddings (ทิศตรงข้ามกับงานแชทที่ LM Studio เป็นหลัก)")
OLLAMA_MODEL       = env_str("OLLAMA_MODEL", "llama3", group=_G,
                             doc="โมเดลแชทของ Ollama (บทบาท fallback ตั้งแต่ 2026-06-15)")
OLLAMA_TIMEOUT     = env_int("OLLAMA_TIMEOUT", 120, group=_G, doc="วินาที")
OLLAMA_MAX_RETRIES = env_int("OLLAMA_MAX_RETRIES", 2, group=_G, doc="จำนวนครั้งที่ลองซ้ำ")
OLLAMA_RETRY_DELAY = env_int("OLLAMA_RETRY_DELAY", 2, group=_G, doc="วินาทีระหว่างการลองซ้ำ")
OLLAMA_TEMPERATURE = env_float("OLLAMA_TEMPERATURE", 0.7, group=_G, doc="ความสร้างสรรค์ 0-1")
OLLAMA_TOP_P       = env_float("OLLAMA_TOP_P", 0.85, group=_G, doc="nucleus sampling")
OLLAMA_NUM_CTX     = env_int("OLLAMA_NUM_CTX", 4096, group=_G, doc="ขนาด context window")
OLLAMA_REPEAT_PENALTY = env_float("OLLAMA_REPEAT_PENALTY", 1.1, group=_G,
                                  doc="โทษการพูดซ้ำ")
# มี 2 ผู้อ่านคนละความหมายกับค่าว่าง (utils/memory.py: ว่าง = ปิด embedding_function ของ ChromaDB
# · utils/embed.py: ว่าง = ถอยไป paraphrase-multilingual) ⇒ เจ้าของอยู่ที่นี่ default "" ทั้งสองไฟล์
# ตีความค่าว่างเองต่อ (ก้อน 4 · 2026-09-23)
EMBEDDING_MODEL    = env_str("EMBEDDING_MODEL", "", group=_G,
                             doc="Embedding function ของ ChromaDB — ปล่อยว่าง (default) = MiniLM เดิม (ใช้กับ\n"
                                 "ภาษาไทยไม่ได้เลย ทุกประโยคได้ vector เดียวกัน semantic recall เป็น noise ล้วน\n"
                                 "ดู wiki concepts/thai-embedding-chromadb.md). ตั้งเป็น paraphrase-multilingual\n"
                                 "เพื่อเปิดใช้จริง — ⚠️ ต้องรัน scripts/migrate_thai_embeddings.py ก่อน/หลังตั้งค่านี้\n"
                                 "(เปลี่ยน embedder = dimension เปลี่ยน ของเก่า query ไม่ได้ ต้อง re-embed ทุก collection)\n"
                                 "และต้อง `ollama pull paraphrase-multilingual` บน Ollama ที่ OLLAMA_BASE_URL ชี้ไปด้วย\n"
                                 "⛔ ห้ามใช้ nomic-embed-text เป็นตัวหลัก (พิสูจน์บน prod 2026-08-02: ไทยทุกประโยค cosine 1.0)")

# ── Gemini (Cloud LLM) ───────────────────────────────────────────────────────
_G = "Gemini"
GEMINI_API_KEY   = env_str("GEMINI_API_KEY", "", group=_G,
                           doc="คีย์ Gemini (ขอฟรีที่ https://aistudio.google.com/)\n"
                               "ว่าง = ปิดเส้นคลาวด์ทั้งหมด")
# GEMINI_MODEL ไม่ได้อยู่ที่นี่ — **ที่เดียวคือ `utils/llm.py`** (`GEMINI_MODEL_DEFAULT`
# + `RETIRED_GEMINI_MODELS` + เทส `test_gemini_health.py` ที่ตรึงว่า default ต้องไม่ใช่รุ่นที่ปิดแล้ว)
# เดิมบรรทัดนี้ประกาศ `gemini-2.0-flash` ค้างไว้โดยไม่มีใคร import ไปใช้เลยสักที่ (2026-09-23)
# Live API (bidiGenerateContent) — ⚠️ ชื่อต้องเป๊ะ ไม่งั้น bidiGenerateContent → 1008 not found
# **default ย้ายไปอยู่ที่ `utils/voice.py` แล้ว** (2026-08-04) เพราะเคยมี default 2 ที่ที่
# ไม่ตรงกันเงียบๆ ตั้งแต่ `369f18e` (2026-06-19): ที่นี่เป็น 3.1-flash-live ส่วน
# `utils/voice.py` ค้างที่ 2.5-native-audio-latest พร้อมคอมเมนต์ที่เขียนว่า "ตรงกับ
# core/config.py" — คอมเมนต์บอกเจตนา ไม่ได้บอกพฤติกรรม
from utils.voice import GEMINI_LIVE_MODEL_DEFAULT  # noqa: E402

GEMINI_LIVE_MODEL = env_str("GEMINI_LIVE_MODEL", GEMINI_LIVE_MODEL_DEFAULT, group=_G,
                            doc="โมเดลสายเสียงสด — ต้องเป็นสาย *-live/native-audio เท่านั้น")

# ── Database ─────────────────────────────────────────────────────────────────
_G = "Database"
DB_PATH      = env_str("DB_PATH", "./chat_history.db", group=_G,
                       doc="SQLite หลัก (แชท/เซสชัน/pins/shares/feedback 👍👎)\n"
                           "⛔ docker-compose `environment:` ทับค่านี้ — ตั้งใน .env ไม่มีผลบน prod\n"
                           "(มีผลเฉพาะตอนรัน local ตรงๆ)")
CHROMA_HOST  = env_str("CHROMA_HOST", "", group=_G,
                       doc="โฮสต์ ChromaDB (ความจำระยะยาว) — ว่าง = ให้โค้ดไล่เดาเอง\n"
                           "บน Docker: ชื่อ service เช่น chromadb · บน NAS ที่รันแยก: IP ของ NAS")
CHROMA_PORT  = env_int("CHROMA_PORT", 8000, group=_G, doc="พอร์ต ChromaDB")
CHROMA_PATH  = env_str("CHROMA_PATH", "./data/chroma", group=_G,
                       doc="⚠️ dead config — ไม่มีผู้บริโภค (ChromaDB เป็นคอนเทนเนอร์แยก)")

# ── App ──────────────────────────────────────────────────────────────────────
_G = "App"
UI_PASSWORD  = env_str("UI_PASSWORD", "", group=_G,
                       doc="รหัสผ่านเข้า UI — ว่าง = เปิดสาธารณะ (auth middleware ยังกัน endpoint\n"
                           "ที่ไม่อยู่ใน _OPEN_PATHS อยู่ แต่ไม่มีรหัสให้ผ่านด่าน)")
CORS_ORIGINS = env_str("CORS_ORIGINS", "", group=_G,
                       doc="origin ที่อนุญาต คั่นด้วย , — ว่าง = ใช้ค่าตั้งต้นใน CORS_ORIGINS_LIST\n"
                           "ตัวอย่าง: http://192.168.51.49:8080,https://ai.pawinhome.com")
RELOAD       = env_bool("RELOAD", False, group=_G,
                        doc="เปิด uvicorn auto-reload (สำหรับ dev เท่านั้น)")

# ── Observability (Phase F) ──────────────────────────────────────────────────
# เจ้าของอยู่ที่นี่ไม่ใช่ core/observability.py — server.py import core.config *ก่อน* observability
# เสมอ ⇒ load_dotenv วิ่งก่อนอ่าน · observability เคยอ่านในฟังก์ชัน install_logging (ก้อน 4 · 2026-09-24)
_G = "Observability"
LOG_LEVEL  = env_str("LOG_LEVEL", "INFO", group=_G, doc="DEBUG | INFO | WARNING | ERROR (ไม่สนตัวพิมพ์)")
LOG_FORMAT = env_str("LOG_FORMAT", "plain", group=_G, doc="plain | json (json = 1 บรรทัด/record สำหรับ log shipper)")
LOG_FILE   = env_str("LOG_FILE", "server.log", group=_G,
                     doc="ไฟล์ log (RotatingFileHandler 10 MB × 5) — prod ตั้งเป็น logs/server.log ในคอนเทนเนอร์ผ่าน compose\n"
                         "⛔ docker-compose `environment:` ทับค่านี้ — ตั้งใน .env ไม่มีผลบน prod\n"
                         "(มีผลเฉพาะตอนรัน local ตรงๆ · รัน pytest บนเครื่องให้ตั้ง LOG_FILE=/tmp/... กันทับ log จริง)")

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

_G = "Paths"
OBSIDIAN_VAULT_PATH = env_str("OBSIDIAN_VAULT_PATH", "", group=_G,
                              doc="path ของ Obsidian vault ที่มองเห็นจากในคอนเทนเนอร์ (Synology: /vault)\n"
                                  "⛔ docker-compose `environment:` ทับค่านี้ — ตั้งใน .env ไม่มีผลบน prod")
NAS_DATA_PATH       = env_str("NAS_DATA_PATH", os.path.join(PROJECT_ROOT, "data"), group=_G,
                              doc="โฟลเดอร์ข้อมูลถาวรสำหรับ docker-compose volume mount\n"
                                  "(cache DB · reader.db · skills_db.json) — ตั้งเพื่อไม่ให้ข้อมูล\n"
                                  "หายเวลา restart container · Synology: /volume1/docker/hybrid-ai")

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
READER_DB_PATH = env_str("READER_DB_PATH", READER_DB_DEFAULT, group=_G,
                         doc="ไฟล์เนื้อหาหนังสือ + ที่คั่นของโหมดอ่าน (แยกจาก chat_history.db)")

# ── LM Studio (Local LLM — OpenAI compatible) ────────────────────────────────
# LM Studio เป็น opt-in: เปิดใช้เฉพาะเมื่อ set LMSTUDIO_BASE_URL ใน .env
# (default ว่าง — local LLM หลักของระบบนี้คือ Ollama ดู OLLAMA_BASE_URL ด้านบน)
_G = "LM Studio"
LMSTUDIO_BASE_URL     = env_str("LMSTUDIO_BASE_URL", "", group=_G,
                                doc="ที่อยู่ LM Studio — **ว่าง = ปิด** (opt-in)\n"
                                    "ใส่ค่าเฉพาะเมื่อรัน LM Studio จริง เช่น http://192.168.51.235:1234/v1\n"
                                    "⚠️ ห้ามใส่ IP เป็น default ในโค้ดไฟล์ใดๆ — เคยมี 4 ไฟล์ทำแบบนั้น\n"
                                    "แล้วระบบยิงหา PC เงียบๆ ทั้งที่ควรปิด (แก้ 2026-09-23)")
LMSTUDIO_CHAT_MODEL   = env_str("LMSTUDIO_CHAT_MODEL", "google/gemma-4-e4b", group=_G,
                                doc="โมเดลแชทของ LM Studio")
LMSTUDIO_REASON_MODEL = env_str("LMSTUDIO_REASON_MODEL", "qwen/qwen3.5-9b", group=_G,
                                doc="โมเดลสำหรับงานวิเคราะห์ (สรุป/สะท้อน/dream)")
LMSTUDIO_VISION_MODEL = env_str("LMSTUDIO_VISION_MODEL", "llama-3.2-11b-vision-instruct",
                                group=_G, doc="โมเดลอ่านรูปของ LM Studio")
LMSTUDIO_TIMEOUT      = env_int("LMSTUDIO_TIMEOUT", 180, group=_G, doc="วินาที")
# 🔴 ค่าว่าง = เหมือนไม่ตั้ง (2026-09-23) — เดิม `LMSTUDIO_API_KEY=` ส่ง "" ถึง OpenAI SDK
#    แล้วโยน `Missing credentials` ตั้งแต่ import utils/llm.py = server ไม่ขึ้น (ยืนยันใน prod)
#    · ตรงกับ reasoning/router.py ที่ `if key:` ถือว่าค่าว่างไม่ได้ตั้งอยู่แล้ว
#    · ทุกไฟล์ที่สร้าง client ต้อง import ค่านี้ (tests/test_lmstudio_api_key_empty.py)
_LMSTUDIO_KEY_PLACEHOLDER = "lmstudio"
LMSTUDIO_API_KEY      = env_str("LMSTUDIO_API_KEY", _LMSTUDIO_KEY_PLACEHOLDER, group=_G, doc=(
    "token ของ LM Studio รุ่นใหม่ (หรือปิด \"Require API key\" ในตัวโปรแกรม)\n"
    "ว่าง/ไม่ตั้ง = ใช้ค่า placeholder (LM Studio ที่ปิด auth รับได้) — ไม่ทำให้แอปล้ม"
)) or _LMSTUDIO_KEY_PLACEHOLDER
SHOW_THINKING         = env_bool("SHOW_THINKING", False, group=_G,
                                 doc="โชว์ <think> ของโมเดลบน UI")

# ── CORS list ────────────────────────────────────────────────────────────────
CORS_ORIGINS_LIST = (
    [o.strip() for o in CORS_ORIGINS.split(",") if o.strip()]
    or ["http://localhost:8000", "http://localhost:5173", "http://192.168.51.49:8080"]
)
