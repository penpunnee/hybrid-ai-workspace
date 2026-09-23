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
