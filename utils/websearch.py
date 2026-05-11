"""Web Search — ค้นหาข้อมูลจาก DuckDuckGo + ดึง HTML จริงของ top result

Flow:
  User ถามเรื่อง real-time
  → backend ค้น DuckDuckGo (ไม่ต้อง API key)
  → ดึง HTML 2 อันแรกมา extract text จริง (200-2000 chars)
  → inject เข้า system prompt
  → local model อ่านข้อมูลจริงแล้วตอบ
"""
import logging
import re
import html as html_lib
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
_FETCH_TIMEOUT = 6
_FETCH_TOP_N = 2  # ดึง HTML แค่ 2 ผลแรก ที่เหลือใช้ snippet


def _extract_text(html: str, max_chars: int = 1500) -> str:
    """ดึง text จาก HTML แบบเร็ว (ไม่ใช้ BeautifulSoup)"""
    html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<nav[^>]*>.*?</nav>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<header[^>]*>.*?</header>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<footer[^>]*>.*?</footer>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", html)
    # decode &#xE01; &amp; &nbsp; etc. → ภาษาไทยจริง
    text = html_lib.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


def _fetch_url(url: str) -> str:
    """ดึง HTML จาก URL แล้ว extract text — best effort"""
    try:
        import requests
        resp = requests.get(url, timeout=_FETCH_TIMEOUT,
                            headers={"User-Agent": _UA, "Accept-Language": "th,en;q=0.9"})
        if resp.status_code != 200:
            return ""
        ct = resp.headers.get("content-type", "").lower()
        if "html" not in ct and "text" not in ct:
            return ""
        return _extract_text(resp.text)
    except Exception as e:
        logger.debug(f"[WebSearch] fetch {url} failed: {e}")
        return ""


def _enrich_with_fetch(results: list[dict], top_n: int = _FETCH_TOP_N) -> list[dict]:
    """ดึง HTML ของ top results ขนานกัน — เติม field 'fetched_text'"""
    if not results:
        return results
    targets = results[:top_n]
    with ThreadPoolExecutor(max_workers=top_n) as ex:
        futures = {ex.submit(_fetch_url, r.get("href", "")): r for r in targets if r.get("href")}
        for fut in as_completed(futures, timeout=_FETCH_TIMEOUT + 2):
            r = futures[fut]
            try:
                r["fetched_text"] = fut.result() or ""
            except Exception:
                r["fetched_text"] = ""
    return results


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
        "สรุปข้อมูลที่เกี่ยวข้องและอ้างอิงแหล่งที่มา:",
        "",
    ]
    for i, r in enumerate(results, 1):
        title = r.get("title", "").strip()
        snippet = r.get("body", "").strip()[:300]
        fetched = r.get("fetched_text", "").strip()
        href = r.get("href", "").strip()
        if not (snippet or fetched):
            continue
        lines.append(f"[{i}] **{title}**")
        if fetched:
            # ใช้ fetched text เป็นหลักเพราะมีเนื้อหาจริง
            lines.append(f"    {fetched[:1500]}")
        elif snippet:
            lines.append(f"    {snippet}")
        if href:
            lines.append(f"    🔗 {href}")
        lines.append("")

    return "\n".join(lines)


def web_search_context(query: str, max_results: int = 5) -> str:
    """API เดียวที่ router/chat ใช้ — คืน context string พร้อม inject"""
    results = search_web(query, max_results=max_results)
    results = _enrich_with_fetch(results, top_n=_FETCH_TOP_N)
    return format_for_context(results, query)
