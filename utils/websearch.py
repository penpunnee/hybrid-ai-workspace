"""Web Search — ค้นหาข้อมูลจาก DuckDuckGo แล้ว inject เป็น context ให้ local model

Flow:
  User ถามเรื่อง real-time
  → backend ค้น DuckDuckGo (ไม่ต้อง API key)
  → เอาผล 5 อันแรกมา format เป็น context
  → inject เข้า system prompt
  → local model (Gemma 4) อ่านข้อมูลจริงแล้วตอบ
"""
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def search_web(query: str, max_results: int = 5, region: str = "th-th") -> list[dict]:
    """ค้น DuckDuckGo คืนค่า list of {title, body, href}"""
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(
                query,
                region=region,
                safesearch="moderate",
                max_results=max_results,
            ))
        logger.info(f"[WebSearch] '{query}' → {len(results)} results")
        return results
    except Exception as e:
        logger.warning(f"[WebSearch] DuckDuckGo failed: {e}")
        return _fallback_search(query, max_results)


def _fallback_search(query: str, max_results: int = 3) -> list[dict]:
    """Fallback: ใช้ DuckDuckGo Instant Answer API"""
    try:
        import requests
        resp = requests.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
            timeout=8,
            headers={"User-Agent": "Mozilla/5.0 HybridAI/1.0"},
        )
        data = resp.json()
        results = []
        if data.get("AbstractText"):
            results.append({
                "title": data.get("Heading", query),
                "body": data["AbstractText"],
                "href": data.get("AbstractURL", ""),
            })
        for rt in data.get("RelatedTopics", [])[:max_results - 1]:
            if isinstance(rt, dict) and rt.get("Text"):
                results.append({
                    "title": rt.get("Text", "")[:80],
                    "body": rt.get("Text", ""),
                    "href": rt.get("FirstURL", ""),
                })
        return results
    except Exception as e:
        logger.warning(f"[WebSearch] Fallback also failed: {e}")
        return []


def format_for_context(results: list[dict], query: str) -> str:
    """แปลงผล search เป็น context string สำหรับ inject ใน system prompt"""
    if not results:
        return ""

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "🌐 **ข้อมูลล่าสุดจากอินเตอร์เน็ต** (ระบบดึงให้แล้ว ณ เวลานี้)",
        f"คำค้น: \"{query}\" | เวลา: {now}",
        "",
        "**คำสั่งสำคัญ:** ห้ามบอกว่า \"ไม่มี internet\" หรือ \"ไม่มีข้อมูล real-time\" "
        "เพราะระบบดึงข้อมูลด้านล่างให้แล้ว ตอบโดยใช้ข้อมูลด้านล่างนี้เท่านั้น "
        "และอ้างอิงแหล่งที่มาทุกครั้ง:",
        "",
    ]
    for i, r in enumerate(results, 1):
        title = r.get("title", "").strip()
        body  = r.get("body", "").strip()[:500]
        href  = r.get("href", "").strip()
        if not body:
            continue
        lines.append(f"[{i}] **{title}**")
        lines.append(f"    {body}")
        if href:
            lines.append(f"    🔗 {href}")
        lines.append("")

    return "\n".join(lines)


def web_search_context(query: str, max_results: int = 5) -> str:
    """API เดียวที่ router/chat ใช้ — คืน context string พร้อม inject"""
    results = search_web(query, max_results=max_results)
    return format_for_context(results, query)
