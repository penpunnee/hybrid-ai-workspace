"""`LMSTUDIO_API_KEY=` (ตั้งเป็นค่าว่าง) ต้องไม่ทำให้แอปล้ม (2026-09-23)

**หลักฐาน** — ยืนยันในคอนเทนเนอร์ prod (openai 2.44.0 · ไม่มี `OPENAI_API_KEY`):
ไม่ตั้ง = import ได้ · ตั้งเป็นค่าว่าง = `OpenAIError: Missing credentials` ตั้งแต่ import
`utils/llm.py` (ทั้งโค้ดก่อนและหลังก้อน 4 — พฤติกรรมเดิม) ⇒ server ไม่ขึ้น ·
`backend-watchdog` จะพาเข้า crashloop · `utils/embed.py` ก็สร้าง client ตอน import เหมือนกัน

**กติกาที่เลือก: ค่าว่าง = ไม่ได้ตั้ง** — ตรงกับ `reasoning/router.py` ที่ใช้ `if key:` อยู่แล้ว
(ค่าว่างไม่แนบ Authorization) · client ของ OpenAI SDK ต้องมีคีย์ไม่ว่าง ⇒ ใช้ placeholder
`"lmstudio"` แบบเดียวกับตอนไม่ตั้ง (LM Studio ที่ปิด auth รับได้ · ที่เปิด auth ค่าว่างก็ไม่ผ่านอยู่แล้ว)

เทสรันใน subprocess เพราะต้องเห็นพฤติกรรม *ตอน import* จริง — ใน process นี้โมดูลถูก
import ไปแล้วด้วยค่าจาก `.env` ของเครื่อง
"""
from __future__ import annotations

import ast
import os
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent

_PROBE = """
import core.config as c
import utils.llm, utils.embed, utils.summarize, utils.ocr, memory.correction  # noqa
import agents.orchestrator as o
from utils import summarize
client, _ = summarize._get_client()
print("CFG=" + repr(c.LMSTUDIO_API_KEY))
print("ORCH=" + repr(o.LMSTUDIO_API_KEY))
print("SUMMARIZE_CLIENT_KEY=" + repr(client.api_key))
print("EMBED_CLIENT_KEY=" + repr(utils.embed._client.api_key))
print("LLM_CLIENT_KEY=" + repr(utils.llm.lmstudio_client.api_key))
"""


def _probe(key_value: str | None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in ("OPENAI_API_KEY", "LMSTUDIO_API_KEY")}
    env.update(LOG_FILE="/tmp/test_lmstudio_key.log", UI_PASSWORD="",
               LMSTUDIO_BASE_URL="http://lms.invalid:1234/v1")
    if key_value is not None:
        env["LMSTUDIO_API_KEY"] = key_value
    # ทุกเคสตั้งค่าไว้ชัด — load_dotenv ไม่ทับ env ที่ตั้งแล้ว ⇒ `.env` ของเครื่องไม่ปน
    # (จึงไม่ทดสอบเคส "ไม่ตั้ง" ที่นี่ — `.env` จะเติมให้ · เคสนั้นไม่เคยพังอยู่แล้ว)
    r = subprocess.run([sys.executable, "-c", _PROBE], cwd=REPO, env=env,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, f"import ล้ม (key={key_value!r}):\n{r.stderr[-1500:]}"
    return dict(line.split("=", 1) for line in r.stdout.splitlines() if "=" in line and
                line.split("=", 1)[0].isupper())


def test_ค่าว่าง_import_ได้_และทุก_client_ได้คีย์ที่ไม่ว่าง():
    out = _probe("")
    for name in ("CFG", "ORCH", "SUMMARIZE_CLIENT_KEY", "EMBED_CLIENT_KEY", "LLM_CLIENT_KEY"):
        assert out[name] == repr("lmstudio"), f"{name} = {out[name]}"


def test_คีย์ที่ตั้งไว้จริงต้องถูกใช้ตามเดิม():
    """กลุ่มควบคุม — ตัวแก้ต้องไม่ไปทับคีย์จริงของผู้ใช้"""
    out = _probe("sk-real-123")
    for name in ("CFG", "ORCH", "SUMMARIZE_CLIENT_KEY", "EMBED_CLIENT_KEY", "LLM_CLIENT_KEY"):
        assert out[name] == repr("sk-real-123"), f"{name} = {out[name]}"


# ── ต้นเหตุเชิงโครงสร้าง: อ่านคีย์ดิบกระจาย 4 ไฟล์ แต่ละที่ตีความค่าว่างเอง ─────────
_PROD_DIRS = ("core", "routers", "utils", "memory", "reasoning", "agents", "assistants")
# router ตั้งใจอ่านเอง: ต้องแยก "ไม่ตั้ง" (ไม่แนบ header) ออกจาก "ตั้ง" — ไม่สร้าง client
_ALLOWED = {"reasoning/router.py"}


def _raw_key_reads(src: str) -> list[int]:
    lines = []
    for node in ast.walk(ast.parse(src)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("getenv", "get") and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "LMSTUDIO_API_KEY"):
            lines.append(node.lineno)
    return lines


def test_คีย์_LM_Studio_อ่านจาก_config_ที่เดียว():
    offenders = {}
    for d in _PROD_DIRS:
        for p in (REPO / d).rglob("*.py"):
            rel = str(p.relative_to(REPO))
            if rel in _ALLOWED:
                continue
            hits = _raw_key_reads(p.read_text())
            if hits:
                offenders[rel] = hits
    assert offenders == {}, (
        "อ่าน LMSTUDIO_API_KEY เองโดยไม่ผ่าน core.config (ค่าว่างจะหลุดไปถึง OpenAI client "
        f"แล้วล้ม): {offenders}")


def test_สแกนเนอร์มีตา():
    assert _raw_key_reads('import os\nk = os.getenv("LMSTUDIO_API_KEY", "lmstudio")\n') == [2]
    assert _raw_key_reads('import os\nk = os.environ.get("LMSTUDIO_API_KEY")\n') == [2]


@pytest.mark.parametrize("value", ["", None])
def test_router_ยังไม่แนบ_Authorization_เมื่อว่างหรือไม่ตั้ง(monkeypatch, value):
    """กลุ่มควบคุมของ router — ต้องไม่ถูกลากไปใช้ placeholder"""
    import reasoning.router as router

    if value is None:
        monkeypatch.delenv("LMSTUDIO_API_KEY", raising=False)
    else:
        monkeypatch.setenv("LMSTUDIO_API_KEY", value)
    assert "Authorization" not in router._lmstudio_headers()
