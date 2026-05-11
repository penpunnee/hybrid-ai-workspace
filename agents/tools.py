"""Tool Registry — รวบรวมเครื่องมือทั้งหมดที่ agent ใช้ได้

แต่ละ tool ต้องมี:
  - description: บอก model ว่าเครื่องมือนี้ทำอะไร
  - parameters: JSON schema สำหรับ arguments
  - fn: ฟังก์ชัน Python ที่รันจริง (รับ **kwargs คืน string)
"""
import json
import logging
import re
from datetime import datetime
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ── Tool implementations ─────────────────────────────────────────────────────

def _t_web_search(query: str, max_results=5) -> str:
    """ค้น DDG + fetch top URLs + embedding rerank → คืน top 3"""
    from utils.websearch import search_web, _enrich_with_fetch, format_for_context
    try:
        max_results = int(max_results)
    except (TypeError, ValueError):
        max_results = 5
    # ดึง 2x แล้ว rerank เพื่อให้ได้ผลลัพธ์ที่ตรงประเด็นที่สุด
    initial_n = max(max_results, 6)
    results = search_web(query, max_results=initial_n)
    results = _enrich_with_fetch(results, top_n=2)
    try:
        from utils.embed import rerank_by_similarity
        reranked = rerank_by_similarity(
            query, results,
            text_keys=("title", "fetched_text", "body"),
            top_k=min(max_results, 3),
        )
        if reranked:
            results = reranked
    except Exception as e:
        logger.warning(f"[Tool web_search] rerank failed: {e}")
        results = results[:max_results]
    return format_for_context(results, query)


def _t_weather(city: str = "Bangkok") -> str:
    """ดึงพยากรณ์อากาศจาก wttr.in"""
    from utils.websearch import fetch_weather_by_city
    result = fetch_weather_by_city(city)
    return result or f"ไม่พบข้อมูลอากาศของ {city}"


def _t_wikipedia(topic: str) -> str:
    """ค้น Wikipedia (ไทยก่อน → อังกฤษ)"""
    from utils.websearch import fetch_wikipedia
    result = fetch_wikipedia(topic)
    return result or f"ไม่พบบทความเกี่ยวกับ '{topic}' ใน Wikipedia"


def _t_memory_recall(query: str, assistant: str = "kwan") -> str:
    """ค้นหาความทรงจำเก่า"""
    try:
        from memory.operations import recall
        result = recall(assistant, query, n_results=5)
        return result or "ไม่พบความทรงจำที่เกี่ยวข้อง"
    except Exception as e:
        return f"Memory error: {e}"


def _t_current_time(timezone: str = "Asia/Bangkok") -> str:
    """เวลาปัจจุบันในเขตเวลาที่ระบุ"""
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo(timezone))
        return now.strftime("%Y-%m-%d %H:%M:%S %Z (%A)")
    except Exception:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _t_calculator(expression: str) -> str:
    """คำนวณนิพจน์ทางคณิตศาสตร์ (เฉพาะตัวเลข + - * / % ** ฯลฯ)"""
    if not re.match(r"^[\d\s\+\-\*\/\(\)\.\%\,\s]+$", expression.replace("**", "")):
        return "❌ นิพจน์ไม่ปลอดภัย (อนุญาตเฉพาะตัวเลขและเครื่องหมายพื้นฐาน)"
    try:
        result = eval(expression, {"__builtins__": {}}, {})
        return f"{expression} = {result}"
    except Exception as e:
        return f"❌ คำนวณไม่ได้: {e}"


def _t_skill_search(query: str, n_results=3) -> str:
    """ค้น skills จาก vector DB"""
    try:
        try:
            n_results = int(n_results)
        except (TypeError, ValueError):
            n_results = 3
        from utils.skills import search_skills
        return search_skills(query, n_results=n_results) or "ไม่พบ skill ที่เกี่ยวข้อง"
    except Exception as e:
        return f"Skills error: {e}"


def _t_obsidian_search(query: str, n=3) -> str:
    """ค้น Obsidian vault notes"""
    try:
        try:
            n = int(n)
        except (TypeError, ValueError):
            n = 3
        from utils.obsidian_sync import search_vault
        results = search_vault(query, n=n)
        if not results:
            return "ไม่พบโน้ตที่เกี่ยวข้องใน vault"
        return "\n\n".join([f"📝 **{r['title']}**\n{r['content'][:500]}" for r in results])
    except Exception as e:
        return f"Vault error: {e}"


# ── Registry ─────────────────────────────────────────────────────────────────

TOOL_REGISTRY: dict[str, dict[str, Any]] = {
    "web_search": {
        "description": (
            "ค้นหาข้อมูลจากอินเตอร์เน็ตด้วย DuckDuckGo + ดึงเนื้อหาหน้าเว็บจริง "
            "ใช้สำหรับ: ข่าวล่าสุด, ราคา, ข้อมูลทั่วไป, เหตุการณ์ปัจจุบัน"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "คำค้น (ภาษาไทยหรืออังกฤษ)"},
                "max_results": {"type": "integer", "description": "จำนวนผลลัพธ์ (default 5)", "default": 5},
            },
            "required": ["query"],
        },
        "fn": _t_web_search,
    },
    "weather": {
        "description": (
            "ดึงพยากรณ์อากาศจริงจาก wttr.in มีอุณหภูมิ ความชื้น ลม ฝน "
            "+ พยากรณ์ 3 วัน ใช้กับคำถามอากาศ/อุณหภูมิ/ฝน"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "ชื่อเมืองภาษาอังกฤษ เช่น Bangkok, Chiang Mai, Phuket",
                    "default": "Bangkok",
                },
            },
            "required": [],
        },
        "fn": _t_weather,
    },
    "wikipedia": {
        "description": (
            "ค้น Wikipedia (ภาษาไทยก่อน → fallback อังกฤษ) "
            "ใช้สำหรับ: นิยาม, ประวัติบุคคล, ข้อเท็จจริงทั่วไป, ความหมายของคำ"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "หัวข้อหรือชื่อที่จะค้น"},
            },
            "required": ["topic"],
        },
        "fn": _t_wikipedia,
    },
    "memory_recall": {
        "description": (
            "ค้นหาความทรงจำเก่าจาก ChromaDB ของ assistant "
            "ใช้เมื่อต้องดูว่าผู้ใช้เคยพูดอะไรไว้ หรือมีข้อมูลที่เคยจำไว้"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "คำค้นในความทรงจำ"},
                "assistant": {"type": "string", "description": "slug ของ assistant (kwan, fah, khim)"},
            },
            "required": ["query"],
        },
        "fn": _t_memory_recall,
    },
    "current_time": {
        "description": "เวลาปัจจุบัน + วันในสัปดาห์ ตาม timezone ที่ระบุ",
        "parameters": {
            "type": "object",
            "properties": {
                "timezone": {"type": "string", "default": "Asia/Bangkok"},
            },
            "required": [],
        },
        "fn": _t_current_time,
    },
    "calculator": {
        "description": "คำนวณนิพจน์ทางคณิตศาสตร์ (เลข + - * / % ** เท่านั้น)",
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "เช่น '(2+3)*4' หรือ '15**2'"},
            },
            "required": ["expression"],
        },
        "fn": _t_calculator,
    },
    "skill_search": {
        "description": "ค้น skills/ความรู้ที่เก็บไว้ในระบบ (ChromaDB skills collection)",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "n_results": {"type": "integer", "default": 3},
            },
            "required": ["query"],
        },
        "fn": _t_skill_search,
    },
    "obsidian_search": {
        "description": "ค้นโน้ตใน Obsidian vault (โน้ตส่วนตัวของผู้ใช้)",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "n": {"type": "integer", "default": 3},
            },
            "required": ["query"],
        },
        "fn": _t_obsidian_search,
    },
}


def get_openai_tools() -> list[dict]:
    """แปลง TOOL_REGISTRY → format ของ OpenAI function calling"""
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": spec["description"],
                "parameters": spec["parameters"],
            },
        }
        for name, spec in TOOL_REGISTRY.items()
    ]


def execute_tool(name: str, args: dict) -> str:
    """รัน tool แล้วคืน string result (clamp ความยาว)"""
    if name not in TOOL_REGISTRY:
        return f"❌ ไม่รู้จัก tool ชื่อ '{name}'"
    fn = TOOL_REGISTRY[name]["fn"]
    try:
        logger.info(f"[Tool] {name}({args})")
        result = fn(**args) if args else fn()
        result_str = str(result) if not isinstance(result, str) else result
        return result_str[:5000]  # clamp 5KB per tool result
    except TypeError as e:
        return f"❌ argument ผิด: {e}"
    except Exception as e:
        logger.exception(f"[Tool] {name} failed")
        return f"❌ tool error: {e}"


def list_tools() -> list[str]:
    """รายชื่อ tools ทั้งหมด"""
    return list(TOOL_REGISTRY.keys())
