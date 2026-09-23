"""utils/summarize.py ต้องใช้ค่าจาก config ถึง client/การเรียกจริง (ก้อน 4 · 2026-09-23)

เดิมอ่าน env เอง 7 จุด — ทุกชื่อมีเจ้าของที่ `core/config.py` แล้ว จึงเปลี่ยนเป็น import ค่า
เทสใช้ค่าที่ต่างจาก default ทุกตัว ⇒ hardcode/อ่าน env ดิบกลับมาจะแดง
"""
import ast
import pathlib

import utils.summarize as sm

SRC = pathlib.Path(sm.__file__).read_text()


def test_lmstudio_ตั้งไว้_ใช้_client_และโมเดลจาก_config(monkeypatch):
    monkeypatch.setattr(sm, "_LMSTUDIO_BASE_URL", "http://fake-lms:9/v1")
    monkeypatch.setattr(sm, "_LMSTUDIO_API_KEY", "sk-sum")
    monkeypatch.setattr(sm, "_LMSTUDIO_TIMEOUT", 77)
    monkeypatch.setattr(sm, "_LMSTUDIO_REASON_MODEL", "reason-x")
    client, model = sm._get_client()
    assert str(client.base_url).startswith("http://fake-lms:9/v1")
    assert client.api_key == "sk-sum" and client.timeout == 77 and model == "reason-x"


def test_lmstudio_ไม่ตั้ง_ถอยไป_ollama_จาก_config(monkeypatch):
    monkeypatch.setattr(sm, "_LMSTUDIO_BASE_URL", "")
    monkeypatch.setattr(sm, "_OLLAMA_BASE_URL", "http://fake-ollama:8/v1")
    monkeypatch.setattr(sm, "_OLLAMA_MODEL", "llama-x")
    client, model = sm._get_client()
    assert str(client.base_url).startswith("http://fake-ollama:8/v1") and model == "llama-x"


def test_gemini_ไม่มีคีย์_ไม่สร้าง_client(monkeypatch):
    """คีย์ต้องมาจากตัวแปรของโมดูล (= config) ไม่ใช่ os.getenv ตอนเรียก

    ⚠️ ตรวจที่ "สร้าง client ไหม" ไม่ใช่ที่ค่าคืน — `_call_gemini` กลืน exception แล้วคืน ""
    เหมือนกันทั้งสองทาง (mutation S1 รอดเพราะ assert แค่ค่าคืน)"""
    from google import genai

    made = []
    monkeypatch.setattr(genai, "Client", lambda **kw: made.append(kw) or (_ for _ in ()).throw(RuntimeError("stop")))
    monkeypatch.setattr(sm, "_GEMINI_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "มีใน-env-แต่ต้องไม่ถูกใช้")
    assert sm._call_gemini("s", "u") == ""
    assert made == [], f"สร้าง genai client ด้วยคีย์จาก env: {made}"


def test_gemini_มีคีย์ใน_config_ใช้คีย์นั้น(monkeypatch):
    """กลุ่มควบคุม — ตัวแปรของโมดูลมีคีย์ ต้องถูกส่งถึง client จริง"""
    from google import genai

    made = []
    monkeypatch.setattr(genai, "Client", lambda **kw: made.append(kw) or (_ for _ in ()).throw(RuntimeError("stop")))
    monkeypatch.setattr(sm, "_GEMINI_API_KEY", "k-from-config")
    sm._call_gemini("s", "u")
    assert made == [{"api_key": "k-from-config"}]


def test_ทุกค่า_import_จาก_core_config():
    imported = {a.name for n in ast.walk(ast.parse(SRC))
                if isinstance(n, ast.ImportFrom) and n.module == "core.config" for a in n.names}
    for name in ("GEMINI_API_KEY", "LMSTUDIO_API_KEY", "LMSTUDIO_BASE_URL", "LMSTUDIO_REASON_MODEL",
                 "LMSTUDIO_TIMEOUT", "OLLAMA_BASE_URL", "OLLAMA_MODEL"):
        assert name in imported, f"{name} ไม่ได้ import จาก core.config"
