"""Tool Registry — รวบรวมเครื่องมือทั้งหมดที่ agent ใช้ได้

แต่ละ tool ต้องมี:
  - description: บอก model ว่าเครื่องมือนี้ทำอะไร
  - parameters: JSON schema สำหรับ arguments
  - fn: ฟังก์ชัน Python ที่รันจริง (รับ **kwargs คืน string)
"""
import logging
import re
from datetime import datetime
from typing import Any

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
    results = _enrich_with_fetch(results)  # default _FETCH_TOP_N = 3 หน้า (2026-06-11)
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


def _t_run_python(code: str, timeout: int = 10) -> str:
    """รัน Python code ใน sandbox"""
    from utils.code_sandbox import run_python
    try:
        timeout = int(timeout)
    except (TypeError, ValueError):
        timeout = 10
    r = run_python(code, timeout=timeout)
    if not r.ok:
        err_block = (r.stderr or r.error or "unknown error").strip()
        return f"❌ exit_code={r.exit_code} ({r.mode}, {r.runtime_ms}ms)\n{err_block}"
    out = (r.stdout or "(no output)").rstrip()
    return f"✅ ran in {r.mode} ({r.runtime_ms}ms)\n```\n{out}\n```"


def _t_fs_list(path: str = "") -> str:
    """รายชื่อไฟล์/โฟลเดอร์ในตำแหน่ง path"""
    from utils.fs_tools import list_dir
    r = list_dir(path)
    if not r.get("ok"):
        return f"❌ {r.get('error', 'unknown')}"
    lines = [f"📁 {r['path']} ({r['count']} entries):"]
    for e in r["entries"][:50]:
        mark = "📂" if e["type"] == "dir" else "📄"
        size = f" ({e['size']}b)" if "size" in e else ""
        lines.append(f"  {mark} {e['name']}{size}")
    if r["count"] > 50:
        lines.append(f"  ...({r['count'] - 50} more)")
    return "\n".join(lines)


def _t_fs_read(path: str, max_bytes: int = 0) -> str:
    """อ่านไฟล์ในตำแหน่ง path"""
    from utils.fs_tools import read_file
    try:
        max_bytes = int(max_bytes) if max_bytes else 0
    except (TypeError, ValueError):
        max_bytes = 0
    r = read_file(path, max_bytes=max_bytes or None)
    if not r.get("ok"):
        return f"❌ {r.get('error', 'unknown')}"
    suffix = "\n[...TRUNCATED]" if r.get("truncated") else ""
    return f"📄 {r['path']} ({r['size']}b)\n```\n{r['content']}{suffix}\n```"


def _t_fs_write(path: str, content: str, overwrite: bool = False) -> str:
    """เขียนไฟล์ — overwrite=true เพื่อทับของเดิม"""
    from utils.fs_tools import write_file
    if isinstance(overwrite, str):
        overwrite = overwrite.lower() in ("true", "1", "yes")
    r = write_file(path, content, overwrite=bool(overwrite))
    if not r.get("ok"):
        return f"❌ {r.get('error', 'unknown')}"
    return f"✅ wrote {r['bytes_written']}b → {r['path']}"


def _t_fs_search(pattern: str, path: str = "", file_glob: str = "*") -> str:
    """grep-like — หา pattern ในไฟล์ใต้ path"""
    from utils.fs_tools import search_files
    r = search_files(pattern, path=path, file_glob=file_glob)
    if not r.get("ok"):
        return f"❌ {r.get('error', 'unknown')}"
    if not r["matches"]:
        return f"🔍 no matches for {pattern!r} ใน {r['files_scanned']} files"
    lines = [f"🔍 {r['count']} matches for {pattern!r}:"]
    for m in r["matches"][:30]:
        lines.append(f"  {m['file']}:{m['line']}: {m['text']}")
    return "\n".join(lines)


def _t_nas_disk() -> str:
    """พื้นที่ดิสก์ NAS จริง (Synology API)"""
    from utils.home_tools import nas_disk_usage
    r = nas_disk_usage()
    if r.get("error"):
        return f"❌ {r['error']}"
    vols = r.get("volumes", [])
    if not vols:
        return f"NAS {r.get('nas_ip', '')} ตอบ แต่ไม่มีข้อมูล volume"
    lines = [f"NAS Disk ({r.get('nas_ip', '')}):"]
    for v in vols:
        lines.append(
            f"• {v['path']}: ใช้ {v['used_gb']}/{v['total_gb']}GB "
            f"({v['percent']}%) | เหลือ {v['free_gb']}GB | {v['status']}"
        )
    return "\n".join(lines)


def _t_nas_docker() -> str:
    """รายการ container บน NAS จริง (Synology Docker API / docker ps)"""
    from utils.home_tools import nas_docker_status
    r = nas_docker_status()
    if r.get("error"):
        return f"❌ {r['error']}"
    cs = r.get("containers", [])
    if not cs:
        return f"NAS {r.get('nas_ip', '')} ตอบ แต่ไม่พบ container"
    lines = [f"Docker บน NAS ({r.get('nas_ip', '')}):"]
    for c in cs:
        icon = "🟢" if c["running"] else "🔴"
        lines.append(f"• {icon} {c['name']} ({c['status']})")
    return "\n".join(lines)


def _t_ping_network() -> str:
    """ping Router+NAS+PC จริง (TCP check) — คืนผลดิบ ไม่ให้โมเดลเดา"""
    from utils.home_tools import ping_network, _format_ping_results
    return _format_ping_results(ping_network())


def _t_ping_device(ip: str) -> str:
    """ping device ตาม IP จริง (TCP check)"""
    from utils.home_tools import ping_device
    r = ping_device(ip)
    if r.get("online"):
        lat = f" ({r['latency_ms']}ms, port {r.get('port')})" if r.get("latency_ms") is not None else ""
        return f"🟢 {ip} online{lat}"
    return f"🔴 {ip} ไม่ตอบสนอง (offline หรือ block port)"


def _t_wol_pc() -> str:
    """ส่ง Wake-on-LAN ปลุก PC"""
    from utils.home_tools import wol_pc
    r = wol_pc()
    if r.get("error"):
        return f"❌ {r['error']}"
    return f"✅ {r.get('message', 'ส่ง WoL แล้ว')}"


def _t_ha_search_entities(query: str, max_results: int = 10) -> str:
    """ค้น HA entity จาก friendly_name หรือ entity_id"""
    from utils.ha_client import search_entities
    try:
        max_results = int(max_results)
    except (TypeError, ValueError):
        max_results = 10
    results = search_entities(query, max_results=max_results)
    if not results:
        return f"ไม่พบ entity ที่ตรงกับ '{query}'"
    if results[0].get("error"):
        return f"❌ {results[0]['error']}"
    lines = [f"พบ {len(results)} entity สำหรับ '{query}':"]
    for r in results:
        lines.append(
            f"• {r['entity_id']} ({r['friendly_name']}) — state: {r['state']}"
        )
    return "\n".join(lines)


def _t_ha_get_state(entity_id: str) -> str:
    """ดึงสถานะ + attributes ของ HA entity"""
    from utils.ha_client import get_state
    r = get_state(entity_id)
    if r.get("error"):
        return f"❌ {r['error']}"
    attrs = r.get("attributes", {})
    friendly = attrs.pop("friendly_name", entity_id)
    attr_str = ", ".join(f"{k}={v}" for k, v in list(attrs.items())[:8])
    return (
        f"{friendly} ({entity_id})\n"
        f"state: {r['state']}\n"
        f"attributes: {attr_str or '-'}\n"
        f"last_changed: {r.get('last_changed', '-')}"
    )


def _t_ha_call_service(
    domain: str,
    service: str,
    entity_id: str = "",
    data: dict | None = None,
) -> str:
    """เรียก HA service — สั่งเปิด/ปิด/ตั้งค่าอุปกรณ์ใดๆ"""
    from utils.ha_client import call_service
    if isinstance(data, str):
        import json
        try:
            data = json.loads(data)
        except Exception:
            data = {}
    r = call_service(domain, service, entity_id=entity_id, data=data or {})
    if r.get("error"):
        return f"❌ {r['error']}"
    label = f"{entity_id} " if entity_id else ""
    if r.get("warning"):
        return f"⚠️ {label}{domain}.{service} ส่งคำสั่งแล้วแต่ไม่ยืนยันได้ว่าสำเร็จ — {r['warning']}"
    return f"✅ {label}{domain}.{service} สำเร็จ"




def _t_generate_image(prompt: str) -> str:
    """สร้างรูปด้วย Gemini Image — คืน markdown รูปสำหรับแสดงใน chat"""
    from utils.image_gen import generate_image
    result = generate_image(prompt)
    if result.get("ok"):
        caption = result.get("text") or "วาดเสร็จแล้ว"
        return f"{caption}\n\n![generated image]({result['url']})"
    return f"สร้างรูปไม่สำเร็จ: {result.get('error', 'unknown')}"

# ── Registry ─────────────────────────────────────────────────────────────────

_ALL_TOOLS: dict[str, dict[str, Any]] = {
    "generate_image": {
        "description": (
            "สร้าง/วาดรูปภาพจากคำบรรยายด้วย Gemini Image "
            "ใช้เมื่อ user ขอให้วาดรูป สร้างภาพ ออกแบบโลโก้/โปสเตอร์ "
            "ผลลัพธ์เป็น markdown รูป ให้ใส่ไว้ในคำตอบตรงๆ ห้ามแก้ URL"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "คำบรรยายรูปที่ต้องการ (ละเอียด = ผลดีกว่า)"},
            },
            "required": ["prompt"],
        },
        "fn": _t_generate_image,
    },

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
    "run_python": {
        "description": (
            "รัน Python code ใน sandbox (Docker ถ้ามี, fallback subprocess) "
            "ใช้สำหรับ: คำนวณซับซ้อน, จัดการข้อมูล, demo code, parse JSON/CSV "
            "ห้าม: network call, file I/O นอก /work, sleep ยาว"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python source code"},
                "timeout": {"type": "integer", "description": "วินาที (1-60)", "default": 10},
            },
            "required": ["code"],
        },
        "fn": _t_run_python,
    },
    "fs_list": {
        "description": "รายชื่อไฟล์/โฟลเดอร์ในตำแหน่ง path (จำกัดอยู่ใน sandbox root)",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "relative หรือ absolute path", "default": ""},
            },
            "required": [],
        },
        "fn": _t_fs_list,
    },
    "fs_read": {
        "description": "อ่านเนื้อหาไฟล์ (text, max 1MB)",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "max_bytes": {"type": "integer", "description": "limit bytes (default 1MB)", "default": 0},
            },
            "required": ["path"],
        },
        "fn": _t_fs_read,
    },
    "fs_write": {
        "description": "เขียนไฟล์ใหม่ (ปฏิเสธถ้ามีอยู่แล้ว ใส่ overwrite=true เพื่อทับ)",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
                "overwrite": {"type": "boolean", "default": False},
            },
            "required": ["path", "content"],
        },
        "fn": _t_fs_write,
    },
    "fs_search": {
        "description": "grep-like — หา pattern ในไฟล์ใต้ path (regex หรือ literal substring)",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "regex หรือ string"},
                "path": {"type": "string", "default": ""},
                "file_glob": {"type": "string", "description": "เช่น '*.py'", "default": "*"},
            },
            "required": ["pattern"],
        },
        "fn": _t_fs_search,
    },
    "nas_disk": {
        "description": (
            "ดึงพื้นที่ดิสก์ NAS Synology จริง (used/total/free/percent ต่อ volume) "
            "ใช้เมื่อถามพื้นที่/ดิสก์/storage เต็ม-เหลือ ของ NAS — คืนตัวเลขจริง"
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
        "fn": _t_nas_disk,
    },
    "nas_docker": {
        "description": (
            "ดึงรายการ Docker container บน NAS จริง (ชื่อ + สถานะ running/stopped) "
            "ใช้เมื่อถามว่า container/service ตัวไหนรันอยู่บน NAS"
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
        "fn": _t_nas_docker,
    },
    "ping_network": {
        "description": (
            "ping Router + NAS + PC จริงพร้อมกัน (TCP check) คืนสถานะ online/offline + latency จริง "
            "ใช้เมื่อถามว่าเครือข่าย/router/อุปกรณ์ในบ้าน online ไหม — อย่าเดาเอง เรียกอันนี้"
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
        "fn": _t_ping_network,
    },
    "ping_device": {
        "description": (
            "ping device ตาม IP ที่ระบุจริง (TCP check) คืน online/offline + latency "
            "ใช้เมื่อถามว่าเครื่องที่ IP หนึ่งๆ ออนไลน์ไหม"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "ip": {"type": "string", "description": "IP address เช่น 192.168.51.49"},
            },
            "required": ["ip"],
        },
        "fn": _t_ping_device,
    },
    "wol_pc": {
        "description": "ส่ง Wake-on-LAN ปลุก PC ให้เปิดเครื่อง (ต้องตั้ง PC_MAC ใน .env)",
        "parameters": {"type": "object", "properties": {}, "required": []},
        "fn": _t_wol_pc,
    },
    "ha_search_entities": {
        "description": (
            "ค้นหา Home Assistant entity จากชื่อ (ภาษาไทยหรืออังกฤษ) "
            "คืน entity_id + state ที่ตรงกัน "
            "ใช้ก่อน ha_call_service เสมอเมื่อไม่รู้ entity_id"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "ชื่อหรือคีย์เวิร์ด เช่น 'ไฟห้องนั่งเล่น', 'แอร์', 'ปลั๊ก'"},
                "max_results": {"type": "integer", "description": "จำนวนผลลัพธ์สูงสุด (default 10)", "default": 10},
            },
            "required": ["query"],
        },
        "fn": _t_ha_search_entities,
    },
    "ha_get_state": {
        "description": (
            "ดึงสถานะปัจจุบัน + attributes ของ HA entity (ไฟ/แอร์/สวิตช์/sensor ฯลฯ) "
            "ใช้เมื่อต้องการรู้ว่าอุปกรณ์เปิด/ปิด อุณหภูมิเท่าไหร่ ฯลฯ"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string", "description": "เช่น 'light.living_room', 'climate.bedroom_ac'"},
            },
            "required": ["entity_id"],
        },
        "fn": _t_ha_get_state,
    },
    "ha_call_service": {
        "description": (
            "สั่ง Home Assistant service — เปิด/ปิด/ตั้งค่าอุปกรณ์ใดๆ ในบ้าน "
            "domain เช่น 'light','switch','climate','automation','script' "
            "service เช่น 'turn_on','turn_off','toggle','set_temperature' "
            "ควรเรียก ha_search_entities ก่อนเพื่อให้ได้ entity_id ที่ถูกต้อง"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "เช่น 'light', 'switch', 'climate'"},
                "service": {"type": "string", "description": "เช่น 'turn_on', 'turn_off', 'set_temperature'"},
                "entity_id": {"type": "string", "description": "entity ที่จะสั่ง (ปล่อยว่างถ้า service ไม่ต้อง)"},
                "data": {
                    "type": "object",
                    "description": "extra payload เช่น {\"temperature\": 25} สำหรับ climate",
                },
            },
            "required": ["domain", "service"],
        },
        "fn": _t_ha_call_service,
    },
}


def get_gemini_tools() -> list:
    """แปลง TOOL_REGISTRY → format ของ Gemini function calling (google.genai SDK)"""
    from google.genai import types as genai_types
    declarations = []
    for name, spec in TOOL_REGISTRY.items():
        params = spec["parameters"]
        props = params.get("properties", {})
        required = params.get("required", [])
        gemini_props = {}
        for prop_name, prop_schema in props.items():
            ptype = prop_schema.get("type", "string").upper()
            type_map = {
                "STRING": genai_types.Type.STRING,
                "INTEGER": genai_types.Type.INTEGER,
                "NUMBER": genai_types.Type.NUMBER,
                "BOOLEAN": genai_types.Type.BOOLEAN,
            }
            gemini_props[prop_name] = genai_types.Schema(
                type=type_map.get(ptype, genai_types.Type.STRING),
                description=prop_schema.get("description", ""),
            )
        func_decl = genai_types.FunctionDeclaration(
            name=name,
            description=spec["description"],
            parameters=genai_types.Schema(
                type=genai_types.Type.OBJECT,
                properties=gemini_props,
                required=required,
            ) if gemini_props else None,
        )
        declarations.append(func_decl)
    return declarations


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


# ── Capability gate ──────────────────────────────────────────────────────────
# ทะเบียน tool คือ "สัญญาว่าทำได้" ไม่ใช่รายการความหวัง — tool ที่รันไม่ได้ในสภาพแวดล้อม
# นี้ต้องไม่โผล่ให้โมเดลเลือก ไม่งั้นมันจะเสียเทิร์นไปกับการเรียกแล้วได้ error
# (เจอจริงบน prod 2026-08-03: `run_python` blocked ทุกครั้งเพราะ container ไม่มี
# /var/run/docker.sock แต่ยังอยู่ในทะเบียนมาตลอด — backlog ข้อ 6)


def _sandbox_available() -> bool:
    """รัน Python ได้จริงไหม — มี Docker หรือเปิด local ไว้"""
    from utils import code_sandbox
    return bool(code_sandbox._has_docker() or code_sandbox._ALLOW_LOCAL)


# lambda เพื่อให้ lookup `_sandbox_available` เกิดตอน "เรียก" ไม่ใช่ตอน import
# (ผูก reference ตรงๆ จะ patch ในเทสไม่ได้ และ gate จะค้างค่าที่อ่านตอน boot ตลอดอายุ process)
_GATED = {"run_python": lambda: _sandbox_available()}


def build_registry() -> dict[str, dict[str, Any]]:
    """ทะเบียนเฉพาะ tool ที่ใช้ได้จริงตอนนี้"""
    return {
        name: spec
        for name, spec in _ALL_TOOLS.items()
        if name not in _GATED or _GATED[name]()
    }


TOOL_REGISTRY: dict[str, dict[str, Any]] = build_registry()


def execute_tool(name: str, args: dict) -> str:
    """รัน tool แล้วคืน string result (clamp ความยาว)"""
    if name not in TOOL_REGISTRY:
        if name in _ALL_TOOLS:
            return (
                f"❌ tool '{name}' ใช้ไม่ได้ในสภาพแวดล้อมนี้ "
                "(run_python ต้องมี Docker หรือตั้ง CODE_SANDBOX_ALLOW_LOCAL=true)"
            )
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
