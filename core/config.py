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
GEMINI_LIVE_MODEL = os.getenv("GEMINI_LIVE_MODEL", "gemini-2.0-flash-exp")

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
SKILLS_DB_PATH = os.path.join(PROJECT_ROOT, "skills_db.json")

OBSIDIAN_VAULT_PATH = os.getenv("OBSIDIAN_VAULT_PATH", "")
NAS_DATA_PATH       = os.getenv("NAS_DATA_PATH", os.path.join(PROJECT_ROOT, "data"))

# Cache databases (under NAS_DATA_PATH for persistence)
RESPONSE_CACHE_DB = os.path.join(NAS_DATA_PATH, "response_cache.db")
EMBED_CACHE_DB = os.path.join(NAS_DATA_PATH, "embed_cache.db")

# ── LM Studio (Local LLM — OpenAI compatible) ────────────────────────────────
LMSTUDIO_BASE_URL     = os.getenv("LMSTUDIO_BASE_URL", "http://192.168.51.235:1234/v1")
LMSTUDIO_CHAT_MODEL   = os.getenv("LMSTUDIO_CHAT_MODEL", "google/gemma-4-e4b")
LMSTUDIO_REASON_MODEL = os.getenv("LMSTUDIO_REASON_MODEL", "deepseek/deepseek-r1-0528-qwen3-8b")
LMSTUDIO_VISION_MODEL = os.getenv("LMSTUDIO_VISION_MODEL", "llama-3.2-11b-vision-instruct")
LMSTUDIO_TIMEOUT      = int(os.getenv("LMSTUDIO_TIMEOUT", "180"))
SHOW_THINKING         = os.getenv("SHOW_THINKING", "false").lower() == "true"

# ── CORS list ────────────────────────────────────────────────────────────────
CORS_ORIGINS_LIST = (
    [o.strip() for o in CORS_ORIGINS.split(",") if o.strip()]
    or ["http://localhost:8000", "http://localhost:5173", "http://192.168.51.49:8080"]
)
