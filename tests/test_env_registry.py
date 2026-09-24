"""`core/config.py` ต้องรู้ตัวเองว่าอ่าน env อะไรบ้าง — ผ่าน registry

**ทำไม** — ตอนนี้ `.env.example` / `CLAUDE.md` / `docker-compose.yml` เขียนด้วยมือทั้งหมด
แล้วดริฟต์จากโค้ดเงียบๆ (วัด 2026-09-23: โค้ดอ่าน env **122 ชื่อ** แต่มี **38 ตัว
ที่ไม่ได้ถูกจดไว้ในเอกสารไหนเลย**) · `test_env_docs_ratchet.py` จับได้เฉพาะทิศ
*เอกสาร → โค้ด* ⇒ ทิศกลับเปิดโล่ง

registry นี้คือ**ฐาน**ของก้อนถัดไป (generate `.env.example` จากโค้ด) — ตัวมันเอง
ยังไม่ปิดช่องนั้น แต่ทำให้ "ถามโค้ดว่ามี env อะไรบ้าง" เป็นไปได้เป็นครั้งแรก

🔑 **ข้อบังคับที่ทำให้ registry ไม่กลายเป็นของประดับ:** ทุกรายการต้องมีคำอธิบาย
ไม่ว่าง — เพราะปลายทางคือบรรทัดคอมเมนต์ใน `.env.example` ที่คนต้องอ่านรู้เรื่อง
"""

from __future__ import annotations

import ast

import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _คืน_registry_หลังเทส():
    """เทส helper ลงทะเบียนชื่อปลอม (`TEST_STR` ฯลฯ) ลง REGISTRY ซึ่งเป็น global
    ⇒ ถ้าไม่คืนค่า `test_env_example_generated.py` ที่รันทีหลังในโปรเซสเดียวกันจะแดง
    (ชุดเต็มเขียวได้เพราะชื่อไฟล์เรียงให้ไฟล์นั้นรันก่อน — เจอ 2026-09-23 ตอนรันชุดย่อย
    เป็น baseline ของ mutation)"""
    from core.env_registry import REGISTRY, load_all

    # 🔴 เติมชื่อจริงก่อน snapshot — ไม่งั้นเทสแรกที่ import core.config จะลงทะเบียน
    #    ชื่อจริงระหว่างเทส แล้ว fixture ลบทิ้งเพราะนับเป็น "ชื่อใหม่" (import ถูก cache
    #    ⇒ ไม่มีใครเติมกลับ = REGISTRY ว่างทั้งโปรเซส · พลาดมาแล้วรอบแรก)
    load_all()
    before = dict(REGISTRY)
    yield
    for name in set(REGISTRY) - set(before):
        del REGISTRY[name]


# ── 1) core/config.py ต้องอ่าน env ผ่าน helper เท่านั้น ────────────────────────

def _raw_env_reads(path: pathlib.Path) -> list[str]:
    """หา os.getenv / os.environ.get / os.environ[...] ที่เหลืออยู่ในไฟล์"""
    tree = ast.parse(path.read_text())
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            f = node.func
            if f.attr == "getenv" and isinstance(f.value, ast.Name) and f.value.id == "os":
                hits.append(f"os.getenv บรรทัด {node.lineno}")
            elif (f.attr == "get" and isinstance(f.value, ast.Attribute)
                  and f.value.attr == "environ"):
                hits.append(f"os.environ.get บรรทัด {node.lineno}")
        elif (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute)
              and node.value.attr == "environ"):
            hits.append(f"os.environ[...] บรรทัด {node.lineno}")
    return hits


def test_config_อ่าน_env_ผ่าน_registry_เท่านั้น():
    leftovers = _raw_env_reads(REPO / "core" / "config.py")
    assert leftovers == [], (
        "core/config.py ยังอ่าน env ดิบอยู่ — ต้องผ่าน env_str/env_int/env_float/env_bool "
        f"เพื่อให้ registry เห็น: {leftovers}"
    )


def test_เครื่องมือวัดมีตาจริง(tmp_path):
    """กลุ่มควบคุม: ถ้าสแกนเนอร์ตาบอด เทสข้างบนจะเขียวฟรี"""
    fake = tmp_path / "fake.py"
    fake.write_text("import os\nX = os.getenv('A')\nY = os.environ.get('B')\nZ = os.environ['C']\n")
    assert len(_raw_env_reads(fake)) == 3


# ── 2) ตัว registry ──────────────────────────────────────────────────────────

def test_ทุกรายการมีคำอธิบายที่ไม่ว่าง():
    # 🔴 ต้อง import core.config ก่อน ไม่งั้น REGISTRY ยังว่าง แล้วเทส "ผ่าน" แบบไม่มีเนื้อหา
    #    (mutation N2 จับได้ 2026-09-23: ลบคำอธิบายทิ้งแล้วเทสยังเขียว เพราะลำดับการรัน
    #     ทำให้ไฟล์นี้ถูกเรียกก่อนเทสตัวอื่นที่ import config)
    import core.config  # noqa: F401
    from core.env_registry import REGISTRY

    assert REGISTRY, "REGISTRY ว่าง — เทสนี้กำลังจะผ่านโดยไม่ได้ตรวจอะไรเลย"
    ไม่มีคำอธิบาย = [name for name, spec in REGISTRY.items() if not spec.doc.strip()]
    assert ไม่มีคำอธิบาย == [], (
        f"env เหล่านี้ยังไม่มีคำอธิบาย (ปลายทางคือคอมเมนต์ใน .env.example): {ไม่มีคำอธิบาย}"
    )


def test_registry_เห็น_env_ของ_config_ครบ():
    import core.config  # noqa: F401  — import เพื่อให้ registry ถูกเติม
    from core.env_registry import REGISTRY

    # sentinel จากทุกกลุ่มใน core/config.py — ถ้าใครลบ helper ทิ้งกลับไปใช้ os.getenv
    # เทสนี้จะแดงคู่กับ test_config_อ่าน_env_ผ่าน_registry_เท่านั้น
    for name in ("OLLAMA_BASE_URL", "OLLAMA_TIMEOUT", "GEMINI_API_KEY", "GEMINI_LIVE_MODEL",
                 "DB_PATH", "CHROMA_PORT", "UI_PASSWORD", "RELOAD",
                 "OBSIDIAN_VAULT_PATH", "NAS_DATA_PATH", "READER_DB_PATH",
                 "LMSTUDIO_BASE_URL", "LMSTUDIO_TIMEOUT", "SHOW_THINKING"):
        assert name in REGISTRY, f"{name} หายไปจาก registry"
    assert len(REGISTRY) >= 20, f"registry มีแค่ {len(REGISTRY)} ชื่อ — น่าจะไม่ได้ถูกเติมจริง"


def test_ชนิดของค่าถูกบันทึกไว้():
    import core.config  # noqa: F401
    from core.env_registry import REGISTRY

    assert REGISTRY["OLLAMA_TIMEOUT"].kind == "int"
    assert REGISTRY["OLLAMA_TEMPERATURE"].kind == "float"
    assert REGISTRY["RELOAD"].kind == "bool"
    assert REGISTRY["OLLAMA_MODEL"].kind == "str"


# ── 3) helper ต้องแปลงค่าเหมือนโค้ดเดิมเป๊ะ ──────────────────────────────────

def test_env_str_อ่าน_env_ทับ_default(monkeypatch):
    from core.env_registry import env_str

    monkeypatch.setenv("TEST_STR", "จากenv")
    assert env_str("TEST_STR", "ค่าตั้งต้น", doc="ทดสอบ") == "จากenv"
    monkeypatch.delenv("TEST_STR")
    assert env_str("TEST_STR", "ค่าตั้งต้น", doc="ทดสอบ") == "ค่าตั้งต้น"


def test_env_bool_ใช้กติกาเดิม_lower_equals_true(monkeypatch):
    """ของเดิมคือ `os.getenv(X, "false").lower() == "true"` — ห้ามเปลี่ยนกติกา
    เช่น ห้ามไปรับ "1"/"yes" เพิ่ม เพราะ .env ที่มีอยู่เขียนตามกติกาเดิม"""
    from core.env_registry import env_bool

    for raw, expected in (("true", True), ("TRUE", True), ("True", True),
                          ("false", False), ("1", False), ("yes", False), ("", False)):
        monkeypatch.setenv("TEST_BOOL", raw)
        assert env_bool("TEST_BOOL", False, doc="ทดสอบ") is expected, f"ค่า {raw!r} แปลผิด"


def test_env_int_และ_float(monkeypatch):
    from core.env_registry import env_float, env_int

    monkeypatch.setenv("TEST_INT", "42")
    assert env_int("TEST_INT", 7, doc="ทดสอบ") == 42
    monkeypatch.delenv("TEST_INT")
    assert env_int("TEST_INT", 7, doc="ทดสอบ") == 7

    monkeypatch.setenv("TEST_FLOAT", "0.25")
    assert env_float("TEST_FLOAT", 1.0, doc="ทดสอบ") == 0.25


def test_ค่าพังต้องดังไม่ใช่เงียบ(monkeypatch):
    """ของเดิม `int(os.getenv(...))` โยน ValueError — คงพฤติกรรมนั้นไว้
    (ค่า config ที่พิมพ์ผิดแล้วเงียบ = ระบบรันด้วยค่าที่ไม่มีใครตั้งใจ)"""
    from core.env_registry import env_int

    monkeypatch.setenv("TEST_BAD", "ไม่ใช่ตัวเลข")
    with pytest.raises(ValueError):
        env_int("TEST_BAD", 1, doc="ทดสอบ")


def test_ลงทะเบียนชื่อซ้ำด้วย_default_คนละค่า_ต้องดัง(monkeypatch):
    """กันไม่ให้ registry กลายเป็นที่เกิดของปัญหาเดิม (default 2 ที่ไม่ตรงกัน)
    — ลงซ้ำด้วยค่าเดิมต้องได้ (importlib.reload ทำแบบนั้น)"""
    from core.env_registry import env_str

    env_str("TEST_DUP", "ก", doc="ทดสอบ")
    env_str("TEST_DUP", "ก", doc="ทดสอบ")  # ซ้ำแบบเหมือนเดิม = ผ่าน
    with pytest.raises(ValueError, match="TEST_DUP"):
        env_str("TEST_DUP", "ข", doc="ทดสอบ")


# ── 4) ค่าที่ core/config.py ให้ออกมา ต้องไม่เปลี่ยนจากของเดิม ────────────────

@pytest.mark.parametrize("name,expected", [
    ("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
    ("OLLAMA_MODEL", "llama3"),
    ("OLLAMA_TIMEOUT", 120),
    ("OLLAMA_MAX_RETRIES", 2),
    ("OLLAMA_RETRY_DELAY", 2),
    ("OLLAMA_TEMPERATURE", 0.7),
    ("OLLAMA_TOP_P", 0.85),
    ("OLLAMA_NUM_CTX", 4096),
    ("OLLAMA_REPEAT_PENALTY", 1.1),
    ("GEMINI_API_KEY", ""),
    ("DB_PATH", "./chat_history.db"),
    ("CHROMA_HOST", ""),
    ("CHROMA_PORT", 8000),
    ("CHROMA_PATH", "./data/chroma"),
    ("UI_PASSWORD", ""),
    ("CORS_ORIGINS", ""),
    ("RELOAD", False),
    ("OBSIDIAN_VAULT_PATH", ""),
    ("LMSTUDIO_BASE_URL", ""),
    ("LMSTUDIO_CHAT_MODEL", "google/gemma-4-e4b"),
    ("LMSTUDIO_REASON_MODEL", "qwen/qwen3.5-9b"),
    ("LMSTUDIO_VISION_MODEL", "llama-3.2-11b-vision-instruct"),
    ("LMSTUDIO_TIMEOUT", 180),
    ("SHOW_THINKING", False),
])
def test_default_ต้องเท่าของเดิมทุกตัว(name, expected):
    """ตรึง default ทั้งชุดไว้ — ก้อนนี้เป็นการ 'ย้ายท่อ' ห้ามค่าเปลี่ยนแม้ตัวเดียว

    🔑 อ่าน default จาก **registry** ไม่ใช่จากค่าที่ `core/config.py` ให้ออกมา:
    เครื่อง dev มี `.env` จริงอยู่ และ `load_dotenv()` จะยัดค่ากลับเข้า env ทุกครั้งที่
    reload ⇒ วัดจากค่าที่ resolve แล้วจะได้ค่าของ `.env` ไม่ใช่ default (เทสจะ "แดง"
    บนเครื่องที่ตั้ง env ไว้ และ "เขียว" บน CI = ตัววัดที่เชื่อไม่ได้)
    """
    from core import config  # noqa: F401  — เติม registry
    from core.env_registry import REGISTRY

    spec = REGISTRY[name]
    assert spec.default == expected and type(spec.default) is type(expected), (
        f"{name}: default เป็น {spec.default!r} ({type(spec.default).__name__}) "
        f"ควรเป็น {expected!r} ({type(expected).__name__})"
    )


def test_ค่าที่คำนวณเองยังทำงานเหมือนเดิม():
    """`CORS_ORIGINS_LIST` และ path ต่างๆ ไม่ใช่ env — ต้องไม่หายไปตอนย้ายท่อ"""
    import core.config as cfg

    assert cfg.CORS_ORIGINS_LIST, "CORS_ORIGINS_LIST ต้องมี fallback เสมอ"
    assert cfg.SKILLS_DB_PATH.endswith("skills_db.json")
    assert cfg.READER_DB_DEFAULT.endswith("reader.db")
    assert cfg.EMBED_CACHE_DB.endswith("embed_cache.db")


# ── 5) ก้อน 4: โมดูลอื่นที่ย้ายเข้า registry แล้ว (เริ่มที่ utils/llm.py 2026-09-23) ──
# 🔑 ทุกเทสข้างล่างเรียก `load_all()` ไม่ใช่ `import core.config` — ชื่อที่ลงทะเบียน
#    ใน `utils/llm.py` จะไม่อยู่ใน REGISTRY ถ้าไม่มีใคร import โมดูลนั้น
#    (บทเรียน mutation N2 เดิม: registry ว่าง = เทสผ่านฟรี)

def test_ไฟล์ที่ย้ายแล้วต้องไม่มีการอ่าน_env_ดิบเหลือ():
    from core.env_registry import MODULES

    assert "utils.llm" in MODULES
    for mod in MODULES:
        path = REPO / (mod.replace(".", "/") + ".py")
        leftovers = _raw_env_reads(path)
        assert leftovers == [], f"{path.relative_to(REPO)} ยังอ่าน env ดิบอยู่: {leftovers}"


def test_load_all_เติมชื่อของ_llm_เข้า_registry():
    from core.env_registry import REGISTRY, load_all

    load_all()
    for name in ("GEMINI_MODEL", "GEMINI_FALLBACK_MODEL", "GEMINI_SEARCH_MODEL",
                 "LMSTUDIO_API_KEY", "ANTHROPIC_API_KEY", "CLAUDE_MODEL",
                 "CLAUDE_MAX_TOKENS", "CLAUDE_THINKING", "CLAUDE_EFFORT",
                 "MOONSHOT_API_KEY", "KIMI_BASE_URL", "KIMI_MODEL", "KIMI_TIMEOUT"):
        assert name in REGISTRY, f"{name} หายไปจาก registry"
        assert REGISTRY[name].doc.strip(), f"{name} ไม่มีคำอธิบาย"


@pytest.mark.parametrize("name,expected", [
    ("GEMINI_FALLBACK_MODEL", ""),
    ("GEMINI_SEARCH_MODEL", ""),
    ("LMSTUDIO_API_KEY", "lmstudio"),
    ("ANTHROPIC_API_KEY", ""),
    ("CLAUDE_MODEL", "claude-sonnet-4-6"),
    ("CLAUDE_MAX_TOKENS", 4096),
    ("CLAUDE_THINKING", "off"),
    ("CLAUDE_EFFORT", "high"),
    ("MOONSHOT_API_KEY", ""),
    ("KIMI_BASE_URL", "https://api.moonshot.ai/v1"),
    ("KIMI_MODEL", "kimi-k2.6"),
    ("KIMI_TIMEOUT", 180),
])
def test_default_ของ_llm_เท่าของเดิมทุกตัว(name, expected):
    """ย้ายท่อล้วน — ค่าที่เคยอยู่ใน `os.getenv(...)` ของ `utils/llm.py` ห้ามเปลี่ยน"""
    from core.env_registry import REGISTRY, load_all

    load_all()
    spec = REGISTRY[name]
    assert spec.default == expected and type(spec.default) is type(expected), (
        f"{name}: default เป็น {spec.default!r} ควรเป็น {expected!r}"
    )


def test_GEMINI_MODEL_default_มาจากค่าคงที่ของ_llm():
    """default ต้องเป็น `GEMINI_MODEL_DEFAULT` ตัวเดียวกับที่ `test_gemini_health.py` ตรวจ
    ว่าไม่ใช่รุ่นที่ Google ปิดแล้ว — ไม่ใช่สตริงก๊อปมาอีกชุด"""
    from core.env_registry import REGISTRY, load_all

    load_all()
    import utils.llm as llm

    assert REGISTRY["GEMINI_MODEL"].default == llm.GEMINI_MODEL_DEFAULT


_HELPERS = {"env_str", "env_int", "env_float", "env_bool"}


def _helper_names(src: str) -> set[str]:
    """ชื่อ env ที่ไฟล์นี้ลงทะเบียนผ่าน helper"""
    names = set()
    for node in ast.walk(ast.parse(src)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in _HELPERS and node.args
                and isinstance(node.args[0], ast.Constant)):
            names.add(node.args[0].value)
    return names


def test_env_หนึ่งชื่อลงทะเบียนจากโมดูลเดียว():
    """ชื่อที่ `core/config.py` ลงทะเบียนไว้แล้ว โมดูลอื่นต้อง *import ค่า* ไม่ใช่ลงซ้ำ

    ลงซ้ำด้วย default เดียวกัน registry ยอม (reload ทำแบบนั้น) แต่ doc/group ของตัวหลัง
    จะทับตัวแรกตามลำดับ import ⇒ `.env.example` เปลี่ยนตามว่าใคร import ก่อน
    และ default สองที่ก็คือของที่ก้อน 1 เพิ่งไล่ปิดไป
    """
    from core.env_registry import MODULES

    owners: dict[str, list[str]] = {}
    for mod in MODULES:
        src = (REPO / (mod.replace(".", "/") + ".py")).read_text()
        for name in _helper_names(src):
            owners.setdefault(name, []).append(mod)
    assert owners, "สแกนไม่เจอ helper สักตัว — เครื่องมือวัดตาบอด"
    ซ้ำ = {n: m for n, m in owners.items() if len(m) > 1}
    assert ซ้ำ == {}, f"ลงทะเบียนซ้ำหลายโมดูล (ให้ import จากเจ้าของแทน): {ซ้ำ}"


def test_สแกน_helper_มีตาจริง():
    assert _helper_names('X = env_str("A", "", doc="d")\nY = env_int("B", 1, doc="d")\n') == {"A", "B"}


# ── 6) ก้อน 4 ไฟล์ที่สอง: agents/orchestrator.py (2026-09-23) ──────────────────

def test_orchestrator_อยู่ใน_MODULES():
    """ไม่อยู่ในลิสต์ = `test_ไฟล์ที่ย้ายแล้วต้องไม่มีการอ่าน_env_ดิบเหลือ` ไม่ตรวจไฟล์นี้"""
    from core.env_registry import MODULES

    assert "agents.orchestrator" in MODULES


def test_LMSTUDIO_API_KEY_เจ้าของคือ_config():
    """ถูกใช้ 6 ไฟล์ (llm/orchestrator/embed/ocr/summarize/router) — เจ้าของต้องเป็นที่กลาง
    ไม่ใช่ `utils/llm.py` (ไม่งั้นไฟล์อื่นต้อง import ตัวแปร private ของ llm)"""
    src = (REPO / "core" / "config.py").read_text()
    assert "LMSTUDIO_API_KEY" in _helper_names(src)


# ── 7) ก้อน 4 ไฟล์ที่สาม: utils/summarize.py (2026-09-23) ──────────────────────

def test_summarize_อยู่ใน_MODULES():
    from core.env_registry import MODULES

    assert "utils.summarize" in MODULES


# ── 8) ก้อน 4 ไฟล์ที่สี่: utils/home_tools.py (2026-09-23) — เจ้าของชื่อใหม่ 7 ตัว ──────

def test_home_tools_อยู่ใน_MODULES():
    from core.env_registry import MODULES

    assert "utils.home_tools" in MODULES


@pytest.mark.parametrize("name,expected", [
    ("NAS_IP", "192.168.51.49"),
    ("NAS_PORT", 5000),
    ("NAS_USER", ""),
    ("NAS_PASS", ""),
    ("PC_IP", "192.168.51.235"),
    ("PC_MAC", ""),
    # 🔑 ไม่ใช่ค่าที่คำนวณจาก NAS_IP — ไม่งั้น .env.example เปลี่ยนตาม env ของเครื่องที่ generate
    ("ROUTER_IP", ""),
])
def test_default_ของ_home_tools_เท่าของเดิม(name, expected):
    from core.env_registry import REGISTRY, load_all

    load_all()
    spec = REGISTRY[name]
    assert spec.default == expected and type(spec.default) is type(expected), (
        f"{name}: default เป็น {spec.default!r} ควรเป็น {expected!r}")
    assert spec.doc.strip()


@pytest.mark.parametrize("env,expected", [
    ({"NAS_IP": "10.0.0.5"}, "10.0.0.1"),                          # ไม่ตั้ง = เดาจาก NAS_IP (เดิม)
    ({"NAS_IP": "10.0.0.5", "ROUTER_IP": "10.9.9.9"}, "10.9.9.9"),  # ตั้งไว้ = ใช้ตามนั้น (เดิม)
    ({"NAS_IP": "10.0.0.5", "ROUTER_IP": ""}, "10.0.0.1"),          # ว่าง = เดา (เดิมได้ "" แล้ว ping ไม่ได้)
])
def test_ROUTER_IP_ยังเดาจาก_NAS_IP_เมื่อไม่ตั้ง(monkeypatch, env, expected):
    import importlib

    import utils.home_tools as ht

    monkeypatch.delenv("ROUTER_IP", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    try:
        assert importlib.reload(ht).ROUTER_IP == expected
    finally:
        monkeypatch.undo()
        importlib.reload(ht)


# ── 9) ก้อน 4 ไฟล์ที่ห้า: utils/voice.py (2026-09-23) — ลบ 1 (dead) + ย้าย 5 ──────────
# 🔑 ตรวจบน prod ก่อนเขียน: 6 ชื่อไม่ได้ตั้งสักตัวใน .env/compose/container env ⇒ default ล้วน
#    · `voice.GEMINI_LIVE_MODEL` ไม่มีใครใช้ (grep ทั้ง /app ในคอนเทนเนอร์ = none) — server.py
#    import จาก core.config · 5 ชื่อที่เหลือไม่เคยถูกจดที่ไหนเลย

def test_voice_อยู่ใน_MODULES():
    from core.env_registry import MODULES

    assert "utils.voice" in MODULES


@pytest.mark.parametrize("name,expected", [
    # 🔴 เป็น str "on" ไม่ใช่ bool — parser เดิมรับ off/0/false = ปิด (CLAUDE.md สอนให้ปิดด้วย =off)
    #    ส่วน env_bool รับแค่ "true" ⇒ ใครตั้ง =on/=1 เพื่อ "เปิดชัดๆ" จะถูกปิดเงียบ
    ("VOICE_LEVEL_LOG", "on"),
    ("VOICE_LEVEL_WINDOW_SEC", 10.0),
    ("VOICE_RECONNECT_SUSPECT_SEC", 30.0),
    ("READER_STALL_TIMEOUT", 45.0),
    ("VOICE_LOOP_EXIT_GRACE_SEC", 1.5),   # ชื่อ env ≠ ชื่อตัวแปร (LOOP_EXIT_GRACE_SEC)
])
def test_default_ของ_voice_เท่าของเดิม(name, expected):
    from core.env_registry import REGISTRY, load_all

    load_all()
    spec = REGISTRY[name]
    assert spec.default == expected and type(spec.default) is type(expected), (
        f"{name}: default เป็น {spec.default!r} ควรเป็น {expected!r}")
    assert spec.doc.strip()


@pytest.mark.parametrize("raw,expected", [
    (None, True),          # ไม่ตั้ง = เปิด (prod วันนี้)
    ("on", True), ("ON", True), ("1", True), ("yes", True), ("", True), (" true ", True),
    ("off", False), ("OFF", False), (" off ", False), ("0", False), ("false", False), ("False", False),
])
def test_VOICE_LEVEL_LOG_ยังตีความแบบเดิม(monkeypatch, raw, expected):
    """kill switch ของ AudioLevelMeter (คดีเสียงเบา) — ห้ามเปลี่ยนสัญญาตอนย้ายท่อ
    ตรวจที่ *ค่าที่โมดูล resolve จริง* ไม่ใช่ helper แยก (helper ถูกแต่ไม่มีใครเรียก = ผ่านฟรี)"""
    import importlib

    import utils.voice as v

    if raw is None:
        monkeypatch.delenv("VOICE_LEVEL_LOG", raising=False)
    else:
        monkeypatch.setenv("VOICE_LEVEL_LOG", raw)
    try:
        assert importlib.reload(v).VOICE_LEVEL_LOG is expected
    finally:
        monkeypatch.undo()
        importlib.reload(v)


def test_voice_ไม่นิยาม_GEMINI_LIVE_MODEL_ซ้ำกับ_config():
    """`utils/voice.py:63` เคยอ่าน GEMINI_LIVE_MODEL เองอีกชุด — ไม่มีใครใช้ (server.py import จาก
    core.config) · เจ้าของชื่อนี้คือ config ⇒ voice ต้องเหลือแค่ค่าคงที่ GEMINI_LIVE_MODEL_DEFAULT
    เดินด้วย ast ไม่ใช่ `in src` — ไม่งั้นคอมเมนต์ที่เล่าเรื่องนี้ทำให้เทสแดงเอง"""
    tree = ast.parse((REPO / "utils" / "voice.py").read_text())
    assigned = {t.id for node in ast.walk(tree) if isinstance(node, ast.Assign)
                for t in node.targets if isinstance(t, ast.Name)}
    assert "GEMINI_LIVE_MODEL_DEFAULT" in assigned, "ค่าคงที่ที่ config import ต้องยังอยู่"
    assert "GEMINI_LIVE_MODEL" not in assigned, "voice.py ยังอ่าน GEMINI_LIVE_MODEL เอง (dead code ซ้ำกับ config)"


# ── 10) ก้อน 4 ไฟล์ที่ 6-8: utils/fs_tools.py · utils/embed.py · utils/code_sandbox.py (2026-09-23) ──
# 🔑 ตรวจบน prod ก่อนเขียน: ตั้งจริงแค่ EMBEDDING_MODEL=paraphrase-multilingual + FS_TOOLS_ROOTS=/app/sandbox
#    ที่เหลือ default ล้วน · embed อ่าน OLLAMA_BASE_URL ซ้ำกับ config (ค่าเท่ากัน) · EMBEDDING_MODEL
#    มี 2 ผู้อ่าน (embed: `or "paraphrase-multilingual"` · memory.py: default "") ⇒ เจ้าของ = config

@pytest.mark.parametrize("mod", ["utils.fs_tools", "utils.embed", "utils.code_sandbox"])
def test_fs_embed_sandbox_อยู่ใน_MODULES(mod):
    from core.env_registry import MODULES

    assert mod in MODULES


@pytest.mark.parametrize("name,expected", [
    # fs_tools — 🔑 FS_TOOLS_ROOTS ลงทะเบียน "" ไม่ใช่ ~/Desktop/ui/sandbox ที่คำนวณจาก home ของเครื่อง
    #   ที่ generate (แบบเดียวกับ ROUTER_IP) · ว่าง/ไม่ตั้ง = default เดิม
    ("FS_TOOLS_ROOTS", ""),
    ("FS_TOOLS_MAX_READ", 1024 * 1024),
    ("FS_TOOLS_MAX_WRITE", 256 * 1024),
    ("FS_TOOLS_MAX_LIST", 500),
    ("FS_TOOLS_MAX_PATTERN", 200),
    ("FS_TOOLS_SEARCH_DEADLINE", 5.0),
    # embed
    ("LMSTUDIO_EMBED_TIMEOUT", 30),
    ("EMBEDDING_MODEL", ""),                 # เจ้าของ config · "" = memory.py ปิด EF · embed ถอยไป multilingual
    ("EMBED_FALLBACK_LMSTUDIO", True),
    ("EMBED_CACHE_DB", ""),                  # ว่าง = <NAS_DATA_PATH>/embed_cache.db (คำนวณ ห้ามลงเป็น default)
    ("EMBED_CACHE_ENABLED", True),
    # code_sandbox — MEM/CPU เป็น str เพราะส่งต่อให้ docker CLI ตรงๆ
    ("CODE_SANDBOX_IMAGE", "python:3.11-slim"),
    ("CODE_SANDBOX_TIMEOUT", 10),
    ("CODE_SANDBOX_MAX_TIMEOUT", 60),
    ("CODE_SANDBOX_MEM", "256m"),
    ("CODE_SANDBOX_CPU", "0.5"),
    ("CODE_SANDBOX_ALLOW_LOCAL", False),
])
def test_default_ของ_fs_embed_sandbox_เท่าของเดิม(name, expected):
    from core.env_registry import REGISTRY, load_all

    load_all()
    spec = REGISTRY[name]
    assert spec.default == expected and type(spec.default) is type(expected), (
        f"{name}: default เป็น {spec.default!r} ควรเป็น {expected!r}")
    assert spec.doc.strip()


def test_embed_ไม่ลงทะเบียนชื่อที่_config_เป็นเจ้าของ():
    """OLLAMA_BASE_URL / EMBEDDING_MODEL ต้อง import จาก core.config — ไม่ใช่ env_str ซ้ำใน embed"""
    embed_names = _helper_names((REPO / "utils" / "embed.py").read_text())
    config_names = _helper_names((REPO / "core" / "config.py").read_text())
    assert not embed_names & {"OLLAMA_BASE_URL", "EMBEDDING_MODEL"}, embed_names
    assert "EMBEDDING_MODEL" in config_names


def _fresh_module(modname: str):
    """รันไฟล์ของโมดูลทั้งไฟล์เข้า namespace ใหม่ **โดยไม่แตะ `sys.modules`**

    🔴 ห้าม `importlib.reload` โมดูลที่มีคลาส exception — reload สร้าง `FSError` ตัวใหม่ ส่วน
    `tests/test_fs_tools.py` ผูกตัวเก่าไว้ตั้งแต่ collect ⇒ `pytest.raises(FSError)` ไม่จับ
    (เจอจริง 2026-09-23: รันเดี่ยว 25/25 · รันหลังไฟล์นี้แดง 4) · exec ใหม่ยังเป็น "โค้ดจริงทั้งไฟล์"
    ไม่ใช่ helper แยกที่ไม่มีใครเรียก
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(modname, REPO / (modname.replace(".", "/") + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _reload_with(monkeypatch, modname, env: dict[str, str | None]):
    """ประเมิน `modname` ใหม่ภายใต้ env ที่กำหนด — `core.config` ถูกประเมินใหม่ด้วย (สลับใน
    `sys.modules` ชั่วคราว) เพราะโมดูลเป้าหมาย import ค่าจาก config ตอน import"""
    import sys

    for k, v in env.items():
        (monkeypatch.delenv(k, raising=False) if v is None else monkeypatch.setenv(k, v))
    monkeypatch.setitem(sys.modules, "core.config", _fresh_module("core.config"))
    return _fresh_module(modname)


@pytest.mark.parametrize("raw,expected", [
    (None, "paraphrase-multilingual"),   # ไม่ตั้ง = ตัวหลัก (เดิม `or`)
    ("", "paraphrase-multilingual"),     # ว่าง (conftest ตั้งแบบนี้เพื่อปิด EF ของ ChromaDB) = ยังเป็นตัวหลัก
    ("nomic-embed-text", "nomic-embed-text"),
])
def test_EMBEDDING_MODEL_ของ_embed_ยังถอยไป_multilingual_เมื่อว่าง(monkeypatch, raw, expected):
    e = _reload_with(monkeypatch, "utils.embed", {"EMBEDDING_MODEL": raw})
    assert e._EMBED_MODEL == expected


def test_embed_ใช้_OLLAMA_BASE_URL_ตัวเดียวกับ_config(monkeypatch):
    import sys

    e = _reload_with(monkeypatch, "utils.embed", {"OLLAMA_BASE_URL": "http://10.1.1.1:11434/v1"})
    # 🔴 `import core.config as cfg` คืนตัว *เก่า* ผ่าน attribute ของแพ็กเกจ `core` — ต้องดูที่
    #    sys.modules ซึ่งเป็นตัวที่ `from core.config import ...` ใน embed มองเห็นจริง
    cfg = sys.modules["core.config"]
    assert e._OLLAMA_BASE_URL == cfg.OLLAMA_BASE_URL == "http://10.1.1.1:11434/v1"


@pytest.mark.parametrize("raw,use_default", [(None, True), ("", True), ("/tmp/x.db", False)])
def test_EMBED_CACHE_DB_ว่างหรือไม่ตั้ง_ใช้_path_ใต้_NAS_DATA_PATH(monkeypatch, raw, use_default):
    import sys

    e = _reload_with(monkeypatch, "utils.embed", {"EMBED_CACHE_DB": raw})
    cfg = sys.modules["core.config"]  # ตัวที่ประเมินใหม่ (ดูเทส OLLAMA_BASE_URL)
    assert e._CACHE_DB == (cfg.EMBED_CACHE_DB if use_default else raw)


@pytest.mark.parametrize("raw,expected_roots", [
    (None, ["~/Desktop/ui/sandbox"]),
    ("", ["~/Desktop/ui/sandbox"]),      # ⚠️ เดิม "" = ไม่มี root เลย (ปฏิเสธทุก path) — เปลี่ยนตาม ROUTER_IP
    ("/tmp/a:/tmp/b", ["/tmp/a", "/tmp/b"]),
    ("/tmp/a::  :", ["/tmp/a"]),          # ช่องว่าง/ว่างระหว่าง : ถูกทิ้ง (เดิม)
])
def test_FS_TOOLS_ROOTS_แยกด้วย_colon_และว่างถอยไป_default(monkeypatch, raw, expected_roots):
    from pathlib import Path

    f = _reload_with(monkeypatch, "utils.fs_tools", {"FS_TOOLS_ROOTS": raw})
    assert f._ROOTS == [Path(p).expanduser().resolve() for p in expected_roots]


def test_code_sandbox_ค่า_docker_ยังเป็น_str():
    """`--memory 256m` / `--cpus 0.5` ต่อเข้า argv ของ docker — float("0.5") จะกลายเป็น "0.5" ก็จริง
    แต่ "1" จะกลายเป็น "1.0" และ "256m" แปลงไม่ได้เลย ⇒ ห้ามแปลงชนิด"""
    import utils.code_sandbox as c

    assert isinstance(c._MEM_LIMIT, str) and isinstance(c._CPU_LIMIT, str)
    assert isinstance(c._DEFAULT_TIMEOUT, int) and isinstance(c._MAX_TIMEOUT, int)


# ── 11) ก้อน 4 ไฟล์ที่ 9-11: utils/websearch.py · utils/response_cache.py · utils/memory.py (2026-09-24) ──
# 🔑 ตรวจบน prod ก่อนเขียน: ตั้งจริง BRAVE/GOOGLE key+cx · BRAVE_MIN_INTERVAL=1.1 · CHROMA_HOST/PORT ·
#    EMBEDDING_MODEL — ที่เหลือ default · 4 จุดเคยอ่าน env *ในฟังก์ชัน* (key ×3 · CHROMA · OLLAMA ใน memory)
#    ⇒ ย้ายเป็นระดับโมดูล (env ใน prod นิ่ง = พฤติกรรมเท่าเดิม) · เทสที่เคย setenv ตอนรัน → patch ค่าในโมดูล

@pytest.mark.parametrize("mod", ["utils.websearch", "utils.response_cache", "utils.memory"])
def test_websearch_cache_memory_อยู่ใน_MODULES(mod):
    from core.env_registry import MODULES

    assert mod in MODULES


@pytest.mark.parametrize("name,expected", [
    # websearch — MIN_SCORE/MIN_INTERVAL เป็น str เพราะมี parser เดิม ("off"/ค่าไม่ถูกต้อง → default + warning)
    ("WEB_SEARCH_MIN_SCORE", "0.35"),
    ("BRAVE_MIN_INTERVAL", "1.1"),
    ("BRAVE_SEARCH_API_KEY", ""),
    ("GOOGLE_SEARCH_API_KEY", ""),
    ("GOOGLE_SEARCH_CX", ""),
    # response_cache — DB ลง "" (default จริงคำนวณจาก NAS_DATA_PATH)
    ("RESPONSE_CACHE_DB", ""),
    ("RESPONSE_CACHE_ENABLED", True),
    ("RESPONSE_CACHE_THRESHOLD", 0.92),
    ("RESPONSE_CACHE_TTL_DAYS", 30),
    ("RESPONSE_CACHE_MAX", 1000),
    # memory
    ("RECALL_MIN_SCORE", 0.55),
])
def test_default_ของ_websearch_cache_memory_เท่าของเดิม(name, expected):
    from core.env_registry import REGISTRY, load_all

    load_all()
    spec = REGISTRY[name]
    assert spec.default == expected and type(spec.default) is type(expected), (
        f"{name}: default เป็น {spec.default!r} ควรเป็น {expected!r}")
    assert spec.doc.strip()


def test_memory_ไม่ลงทะเบียนชื่อที่_config_เป็นเจ้าของ():
    """CHROMA_HOST/CHROMA_PORT/EMBEDDING_MODEL/OLLAMA_BASE_URL ต้อง import จาก core.config"""
    names = _helper_names((REPO / "utils" / "memory.py").read_text())
    assert not names & {"CHROMA_HOST", "CHROMA_PORT", "EMBEDDING_MODEL", "OLLAMA_BASE_URL"}, names
    assert "RECALL_MIN_SCORE" in names


@pytest.mark.parametrize("raw,expected", [
    (None, 0.35), ("0.5", 0.5), ("off", None), ("", None), ("0", None), ("abc", 0.35),
])
def test_WEB_SEARCH_MIN_SCORE_ยัง_parse_แบบเดิม(monkeypatch, raw, expected):
    w = _reload_with(monkeypatch, "utils.websearch", {"WEB_SEARCH_MIN_SCORE": raw})
    assert w.WEB_SEARCH_MIN_SCORE == expected


@pytest.mark.parametrize("raw,expected", [
    (None, 1.1), ("2.5", 2.5), ("0", 1.1), ("-1", 1.1), ("abc", 1.1),
])
def test_BRAVE_MIN_INTERVAL_ยังกันค่าไม่บวกแบบเดิม(monkeypatch, raw, expected):
    """0/ติดลบ/พิมพ์ผิด → 1.1 พร้อม warning (บทเรียน TTS_MAX_CHARS=0 — ตัวหน่วงหายเงียบ = 429 ทุกตัวที่ 2)"""
    w = _reload_with(monkeypatch, "utils.websearch", {"BRAVE_MIN_INTERVAL": raw})
    assert w._brave_min_interval() == expected


def test_BRAVE_key_ว่าง_ไม่ยิงเน็ต(monkeypatch):
    import requests

    calls = []
    monkeypatch.setattr(requests, "get", lambda *a, **k: calls.append(a) or (_ for _ in ()).throw(AssertionError("ต้องไม่ถูกเรียก")))
    w = _reload_with(monkeypatch, "utils.websearch", {"BRAVE_SEARCH_API_KEY": ""})
    assert w._brave_search("x") == [] and calls == []


@pytest.mark.parametrize("raw,use_default", [(None, True), ("", True), ("/tmp/r.db", False)])
def test_RESPONSE_CACHE_DB_ว่างหรือไม่ตั้ง_ใช้_path_ใต้_NAS_DATA_PATH(monkeypatch, raw, use_default):
    import sys

    rc = _reload_with(monkeypatch, "utils.response_cache", {"RESPONSE_CACHE_DB": raw})
    cfg = sys.modules["core.config"]
    assert rc._DB_PATH == (cfg.RESPONSE_CACHE_DB if use_default else raw)


def test_memory_detect_chroma_ใช้ค่าจาก_config(monkeypatch):
    m = _reload_with(monkeypatch, "utils.memory", {"CHROMA_HOST": "10.0.0.9", "CHROMA_PORT": "9001"})
    assert m._detect_chroma_host() == ("10.0.0.9", 9001)


@pytest.mark.parametrize("raw,expected", [
    ("http://x:11434/v1", "http://x:11434"), ("http://x:11434", "http://x:11434"),
])
def test_memory_ollama_native_url_ใช้ค่าจาก_config(monkeypatch, raw, expected):
    m = _reload_with(monkeypatch, "utils.memory", {"OLLAMA_BASE_URL": raw})
    assert m._ollama_native_url() == expected


@pytest.mark.parametrize("raw,expected", [(None, ""), ("", ""), ("paraphrase-multilingual", "paraphrase-multilingual")])
def test_memory_EMBEDDING_MODEL_ว่าง_ยังคือปิด_EF(monkeypatch, raw, expected):
    """คนละความหมายกับ embed (ที่ถอยไป multilingual) — ที่นี่ว่างต้องคงว่าง"""
    m = _reload_with(monkeypatch, "utils.memory", {"EMBEDDING_MODEL": raw})
    assert m.EMBEDDING_MODEL == expected


# ── 12) ก้อน 4 ชั้น core: core/ratelimit.py · core/observability.py · core/scheduler.py (2026-09-24) ──
# 🔑 ตรวจบน prod ก่อนเขียน: ไม่มีชื่อไหนตั้งใน .env · LOG_FILE=/app/logs/server.log มาจาก compose
#    `environment:` (ทับ .env) · observability/scheduler อ่าน env *ในฟังก์ชัน* → import ค่าจาก config
#    (server.py import core.config ก่อน observability ⇒ load_dotenv วิ่งก่อนเสมอ)

@pytest.mark.parametrize("mod", ["core.ratelimit", "core.observability", "core.scheduler"])
def test_core_layer_อยู่ใน_MODULES(mod):
    from core.env_registry import MODULES

    assert mod in MODULES


@pytest.mark.parametrize("name,expected", [
    ("RATE_LIMIT_ENABLED", True),
    ("RATE_LIMIT_RPM", 120),
    ("AUTH_FAIL_MAX", 8),
    ("AUTH_FAIL_WINDOW", 300.0),
    ("RATE_LIMIT_MAX_KEYS", 50000),
    ("LOG_LEVEL", "INFO"),
    ("LOG_FORMAT", "plain"),
    ("LOG_FILE", "server.log"),
])
def test_default_ของ_core_layer_เท่าของเดิม(name, expected):
    from core.env_registry import REGISTRY, load_all

    load_all()
    spec = REGISTRY[name]
    assert spec.default == expected and type(spec.default) is type(expected), (
        f"{name}: default เป็น {spec.default!r} ควรเป็น {expected!r}")
    assert spec.doc.strip()


def test_LOG_เจ้าของคือ_config_และ_observability_scheduler_ไม่ลงทะเบียนเอง():
    """LOG_* เป็น config ระดับแอป (ประกาศคู่ DB_PATH ใน docs) — และ observability ถูก import หลัง
    config เสมอ ⇒ import ค่าจาก config ปลอดภัยเรื่อง load_dotenv · scheduler ใช้ GEMINI_API_KEY ของ config"""
    cfg = _helper_names((REPO / "core" / "config.py").read_text())
    assert {"LOG_LEVEL", "LOG_FORMAT", "LOG_FILE"} <= cfg
    assert _helper_names((REPO / "core" / "observability.py").read_text()) == set()
    assert _helper_names((REPO / "core" / "scheduler.py").read_text()) == set()
    assert {"RATE_LIMIT_ENABLED", "RATE_LIMIT_RPM", "AUTH_FAIL_MAX", "AUTH_FAIL_WINDOW",
            "RATE_LIMIT_MAX_KEYS"} <= _helper_names((REPO / "core" / "ratelimit.py").read_text())


@pytest.mark.parametrize("env,attr,expected", [
    ({"RATE_LIMIT_ENABLED": "false"}, "_ENABLED", False),
    ({"RATE_LIMIT_ENABLED": "true"}, "_ENABLED", True),
    ({"RATE_LIMIT_ENABLED": None}, "_ENABLED", True),
    ({"RATE_LIMIT_RPM": "5"}, "_RPM", 5),
    ({"AUTH_FAIL_WINDOW": "30"}, "_AUTH_FAIL_WINDOW", 30.0),
])
def test_ratelimit_ค่าที่_resolve_จริง(monkeypatch, env, attr, expected):
    rl = _reload_with(monkeypatch, "core.ratelimit", env)
    assert getattr(rl, attr) == expected


def test_install_logging_ใช้_LOG_env_จาก_config(monkeypatch, tmp_path):
    """LOG_LEVEL/LOG_FORMAT/LOG_FILE เคยอ่านในฟังก์ชัน — ตรวจที่ *ผล* บน root logger ไม่ใช่ที่ค่าคงที่
    ⚠️ install_logging แทนที่ handler ของ root ทั้งหมด ⇒ snapshot แล้วคืนสภาพเสมอ"""
    import logging

    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    log_file = tmp_path / "x.log"
    try:
        obs = _reload_with(monkeypatch, "core.observability",
                           {"LOG_LEVEL": "debug", "LOG_FORMAT": "json", "LOG_FILE": str(log_file)})
        obs.install_logging()
        assert root.level == logging.DEBUG
        files = [h for h in root.handlers if getattr(h, "baseFilename", None)]
        assert files and files[0].baseFilename == str(log_file)
        assert type(files[0].formatter).__name__ == "_JsonFormatter"
        # argument ชนะ env (สัญญาเดิม)
        obs.install_logging(level="WARNING")
        assert root.level == logging.WARNING
    finally:
        for h in list(root.handlers):
            root.removeHandler(h)
            try:
                h.close()
            except Exception:
                pass
        for h in saved_handlers:
            root.addHandler(h)
        root.setLevel(saved_level)


@pytest.mark.parametrize("key,expected", [("", "ollama"), ("k", "gemini")])
def test_scheduled_dream_เลือก_provider_จาก_GEMINI_API_KEY_ของ_config(monkeypatch, key, expected):
    import utils.dream as dream
    import utils.notify as notify

    seen = {}
    monkeypatch.setattr(dream, "run_dream_cycle", lambda **kw: seen.update(kw))
    monkeypatch.setattr(notify, "send_line_notify", lambda *a, **k: None)
    sched = _reload_with(monkeypatch, "core.scheduler", {"GEMINI_API_KEY": key})
    sched._scheduled_dream()
    assert seen.get("provider") == expected


# ── 13) ก้อน 4 ไฟล์ที่ 15-17: utils/reflection.py · utils/query_rewrite.py · utils/ocr.py (2026-09-24) ──
# 🔑 ตรวจบน prod ก่อนเขียน: REFLECTION_*/QUERY_REWRITE_* ไม่ได้ตั้งสักตัว · LMSTUDIO_*/GEMINI_API_KEY ตั้ง
#    (เจ้าของ config) · *_MODEL เดิม default เป็น `os.getenv("LMSTUDIO_..._MODEL", ...)` ซ้อน ⇒ ลงทะเบียน ""
#    แล้ว `or <ค่าจาก config>` (ตัวเลข default ซ้อนลงทะเบียนไม่ได้) · ocr อ่าน 4 ชื่อของ config ซ้ำ → import

@pytest.mark.parametrize("mod", ["utils.reflection", "utils.query_rewrite", "utils.ocr"])
def test_reflection_rewrite_ocr_อยู่ใน_MODULES(mod):
    from core.env_registry import MODULES

    assert mod in MODULES


@pytest.mark.parametrize("name,expected", [
    ("REFLECTION_MODEL", ""),          # ว่าง = LMSTUDIO_REASON_MODEL
    ("REFLECTION_TIMEOUT", 30),
    ("REFLECTION_THRESHOLD", 0.7),
    ("QUERY_REWRITE_MODEL", ""),       # ว่าง = LMSTUDIO_CHAT_MODEL
    ("QUERY_REWRITE_TIMEOUT", 8),
    ("QUERY_REWRITE_ENABLED", True),
])
def test_default_ของ_reflection_rewrite_เท่าของเดิม(name, expected):
    from core.env_registry import REGISTRY, load_all

    load_all()
    spec = REGISTRY[name]
    assert spec.default == expected and type(spec.default) is type(expected), (
        f"{name}: default เป็น {spec.default!r} ควรเป็น {expected!r}")
    assert spec.doc.strip()


def test_ocr_ไม่ลงทะเบียนอะไร_และ_reflection_rewrite_ไม่ลงชื่อของ_config():
    assert _helper_names((REPO / "utils" / "ocr.py").read_text()) == set()
    for f in ("reflection", "query_rewrite"):
        names = _helper_names((REPO / "utils" / f"{f}.py").read_text())
        assert not names & {"LMSTUDIO_BASE_URL", "LMSTUDIO_REASON_MODEL", "LMSTUDIO_CHAT_MODEL",
                            "GEMINI_API_KEY"}, (f, names)


@pytest.mark.parametrize("raw,expected", [(None, "r-model"), ("", "r-model"), ("my-critic", "my-critic")])
def test_REFLECTION_MODEL_ว่างถอยไป_LMSTUDIO_REASON_MODEL(monkeypatch, raw, expected):
    rf = _reload_with(monkeypatch, "utils.reflection",
                      {"REFLECTION_MODEL": raw, "LMSTUDIO_REASON_MODEL": "r-model"})
    assert rf._REFLECT_MODEL == expected


@pytest.mark.parametrize("raw,expected", [(None, "c-model"), ("", "c-model"), ("my-rw", "my-rw")])
def test_QUERY_REWRITE_MODEL_ว่างถอยไป_LMSTUDIO_CHAT_MODEL(monkeypatch, raw, expected):
    qr = _reload_with(monkeypatch, "utils.query_rewrite",
                      {"QUERY_REWRITE_MODEL": raw, "LMSTUDIO_CHAT_MODEL": "c-model"})
    assert qr._REWRITE_MODEL == expected


def test_ocr_ใช้ค่า_LMSTUDIO_และ_GEMINI_KEY_จาก_config(monkeypatch):
    ocr = _reload_with(monkeypatch, "utils.ocr", {
        "LMSTUDIO_BASE_URL": "http://h:1/v1", "LMSTUDIO_VISION_MODEL": "v-model",
        "LMSTUDIO_TIMEOUT": "7", "GEMINI_API_KEY": "g-key"})
    assert (ocr._LMSTUDIO_BASE_URL, ocr._LMSTUDIO_VISION_MODEL, ocr._LMSTUDIO_TIMEOUT, ocr.GEMINI_API_KEY) \
        == ("http://h:1/v1", "v-model", 7, "g-key")


def test_ลงทะเบียนชื่อเดียวกันจากคนละโมดูลต้องดัง_แม้_default_เท่ากัน():
    """ปิดช่องที่ mutation จับได้ (2026-09-24): ลงซ้ำผ่าน `env_registry.env_str(...)` แบบ attribute
    รอดสแกน AST ของ `_helper_names` และ default เท่ากันจึงผ่าน `_register` เงียบๆ
    ⇒ บังคับที่ตัว registry: เจ้าของโมดูลเดียว · โมดูลเดิมลงซ้ำได้ (reload)"""
    from core.env_registry import REGISTRY, env_str

    name = "ZZ_OWNER_TEST"
    REGISTRY.pop(name, None)
    try:
        exec('env_str(NAME, "", doc="d")', {"__name__": "mod_a", "env_str": env_str, "NAME": name})
        exec('env_str(NAME, "", doc="d")', {"__name__": "mod_a", "env_str": env_str, "NAME": name})  # reload = ok
        with pytest.raises(ValueError, match="สองโมดูล"):
            exec('env_str(NAME, "", doc="d")', {"__name__": "mod_b", "env_str": env_str, "NAME": name})
    finally:
        REGISTRY.pop(name, None)


# ── 14) ก้อน 4 ไฟล์ที่ 18-21: utils/dream.py · routers/dream.py · utils/heartbeat.py · utils/notify.py (2026-09-24) ──
# 🔑 หลักฐาน prod ที่มี: DREAM_* ไม่ได้ตั้ง (probe ชั้น core) · OBSIDIAN_VAULT_PATH=/vault จาก compose ·
#    HEARTBEAT_*/MEMORY_EPISODIC_CAP/LINE_NOTIFY_TOKEN ยังไม่ได้ probe (NAS เข้าไม่ถึงตอนเขียน) — default
#    ทุกตัวไม่เปลี่ยน · runtime read 3 จุด (MEMORY_EPISODIC_CAP · OBSIDIAN_VAULT_PATH · HEARTBEAT_URL) → ระดับโมดูล

@pytest.mark.parametrize("mod", ["utils.dream", "routers.dream", "utils.heartbeat", "utils.notify"])
def test_dream_heartbeat_notify_อยู่ใน_MODULES(mod):
    from core.env_registry import MODULES

    assert mod in MODULES


@pytest.mark.parametrize("name,expected", [
    ("DREAM_PROMOTE_MIN_HITS", 2),
    ("DREAM_PROMOTE_SKILLS", False),
    ("MEMORY_EPISODIC_CAP", 500),
    ("DREAM_TIMEOUT", 600),
    ("HEARTBEAT_URL", ""),
    ("HEARTBEAT_TIMEOUT", 10.0),
    ("HEARTBEAT_ATTEMPTS", 3),
    ("HEARTBEAT_RETRY_WAIT", 10.0),
    ("LINE_NOTIFY_TOKEN", ""),
])
def test_default_ของ_dream_heartbeat_notify_เท่าของเดิม(name, expected):
    from core.env_registry import REGISTRY, load_all

    load_all()
    spec = REGISTRY[name]
    assert spec.default == expected and type(spec.default) is type(expected), (
        f"{name}: default เป็น {spec.default!r} ควรเป็น {expected!r}")
    assert spec.doc.strip()


def _fn_names(src: str, fn: str) -> set[str]:
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == fn:
            return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
    raise AssertionError(f"ไม่พบฟังก์ชัน {fn}")


def test_dream_ใช้_OBSIDIAN_VAULT_PATH_ของ_config_และ_cap_ระดับโมดูล(monkeypatch, tmp_path):
    """เดิม `_save_report` อ่าน OBSIDIAN_VAULT_PATH ตอนเรียก และ cap อ่าน MEMORY_EPISODIC_CAP ตอนเรียก
    (env ใน prod นิ่ง) — ตรวจว่าค่ามาจาก config/registry จริง + ฟังก์ชันอ้างชื่อนั้น (เดินด้วย ast)"""
    src = (REPO / "utils" / "dream.py").read_text()
    assert "OBSIDIAN_VAULT_PATH" not in _helper_names(src), "dream ต้อง import จาก config ไม่ลงซ้ำ"
    d = _reload_with(monkeypatch, "utils.dream",
                     {"OBSIDIAN_VAULT_PATH": str(tmp_path), "MEMORY_EPISODIC_CAP": "7"})
    assert d._CFG_OBSIDIAN_VAULT_PATH == str(tmp_path) and d._EPISODIC_CAP == 7
    assert "_CFG_OBSIDIAN_VAULT_PATH" in _fn_names(src, "_save_report")
    cap_users = [n.name for n in ast.walk(ast.parse(src))
                 if isinstance(n, ast.FunctionDef) and "_EPISODIC_CAP" in {x.id for x in ast.walk(n) if isinstance(x, ast.Name)}]
    assert cap_users, "ไม่มีฟังก์ชันไหนใช้ _EPISODIC_CAP"


@pytest.mark.parametrize("url,expect_post", [("", False), ("https://hc-ping.com/from-env", True)])
def test_heartbeat_ping_ใช้_HEARTBEAT_URL_ระดับโมดูล(monkeypatch, url, expect_post):
    import requests

    class _R:
        status_code, text = 200, "OK"

    posts = []
    monkeypatch.setattr(requests, "post", lambda u, **k: posts.append(u) or _R())
    monkeypatch.setattr("time.sleep", lambda *_: None)
    hb = _reload_with(monkeypatch, "utils.heartbeat", {"HEARTBEAT_URL": url})
    assert hb.ping() is expect_post
    assert posts == ([url] if expect_post else [])


def test_notify_token_มาจาก_registry(monkeypatch):
    n = _reload_with(monkeypatch, "utils.notify", {"LINE_NOTIFY_TOKEN": "tok-x"})
    assert n.LINE_NOTIFY_TOKEN == "tok-x"
