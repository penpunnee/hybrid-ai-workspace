"""pytest conftest — กัน test แตะ service จริง/remote hosts

ทำงานก่อน import test module ใดๆ → ตั้ง env ให้ชี้ localhost (กรณี .env ของ dev
ชี้ไป NAS 192.168.51.x ซึ่งจะทำให้ health check ค้างยาวตอน connect timeout).
ค่าพวกนี้ถูกอ่านเป็น module-level constant ตอน import server → ต้องตั้งก่อน import.
load_dotenv(override=False) จะไม่ทับค่าที่ตั้งไว้แล้ว
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# auth ปิดสำหรับ test
os.environ["UI_PASSWORD"] = ""
# บังคับ host เป็น localhost → connect refused เร็ว แทนการค้างต่อ NAS ที่เข้าไม่ถึง
os.environ["CHROMA_HOST"] = "localhost"
os.environ["OLLAMA_BASE_URL"] = "http://localhost:11434/v1"
os.environ["LMSTUDIO_BASE_URL"] = ""        # ปิด LM Studio ใน test
os.environ["EMBEDDING_MODEL"] = ""          # ปิด Ollama embedding_function ใน test
# (ไม่งั้น fake chroma client ใน test เดิม ที่ get_collection ไม่รับ **kwargs จะพัง
# เมื่อ wrapper พยายามส่ง embedding_function= เข้าไป)
# ปิด rate limit เป็น default — กัน state สะสมข้ามเทสต์ทำ 429 ปลอม
# (test_ratelimit.py เปิดเอง + monkeypatch limit เล็ก + reset)
os.environ["RATE_LIMIT_ENABLED"] = "false"
# temp FILE (ไม่ใช่ :memory:) — _get_conn() เปิด connection ใหม่ทุกครั้ง
# :memory: จะได้ db แยกกันทุก connection → table ไม่ share → "no such table"
_test_db = os.path.join(tempfile.gettempdir(), "hybrid_ai_test.db")
try:
    os.remove(_test_db)   # clean slate ทุก run
except FileNotFoundError:
    pass
os.environ["DB_PATH"] = _test_db
