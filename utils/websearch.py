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


_WEATHER_KEYWORDS = re.compile(
    r"อากาศ|พยากรณ์|อุณหภูมิ|ฝนตก|ความชื้น|พรุ่งนี้|วันนี้|weather|forecast|temperature",
    re.IGNORECASE,
)

_WIKI_KEYWORDS = re.compile(
    r"คืออะไร|คือใคร|ใครคือ|อะไรคือ|ประวัติของ|ประวัติ\s|ความหมายของ"
    r"|นิยามของ|หมายถึงอะไร|what is|who is|history of|definition of"
    r"|เกิดเมื่อไหร่|เกิดอะไรขึ้น|มาจากไหน",
    re.IGNORECASE,
)


def _wiki_search_title(query: str, lang: str = "th") -> str:
    """ค้นชื่อบทความที่ตรงที่สุดใน Wikipedia"""
    try:
        import requests
        resp = requests.get(
            f"https://{lang}.wikipedia.org/w/api.php",
            params={"action": "query", "list": "search", "srsearch": query,
                    "format": "json", "srlimit": 1},
            timeout=6,
            headers={"User-Agent": _UA},
        )
        data = resp.json()
        hits = data.get("query", {}).get("search", [])
        return hits[0]["title"] if hits else ""
    except Exception as e:
        logger.debug(f"[Wiki] search failed ({lang}): {e}")
        return ""


def _wiki_extract(title: str, lang: str = "th", max_chars: int = 3000) -> str:
    """ดึง extract เต็มหน้าจาก MediaWiki API"""
    try:
        import requests
        resp = requests.get(
            f"https://{lang}.wikipedia.org/w/api.php",
            params={
                "action": "query", "prop": "extracts",
                "titles": title, "explaintext": "true",
                "exsectionformat": "plain",
                "format": "json", "redirects": "1",
            },
            timeout=8,
            headers={"User-Agent": _UA},
        )
        pages = resp.json().get("query", {}).get("pages", {})
        for _, p in pages.items():
            extract = (p.get("extract") or "").strip()
            if extract:
                return extract[:max_chars]
        return ""
    except Exception as e:
        logger.debug(f"[Wiki] extract failed ({lang}): {e}")
        return ""


def fetch_wikipedia(query: str) -> str:
    """ดึงเนื้อหาจาก Wikipedia ภาษาไทยก่อน → fallback English"""
    try:
        for lang in ("th", "en"):
            title = _wiki_search_title(query, lang=lang)
            if not title:
                continue
            extract = _wiki_extract(title, lang=lang)
            if not extract:
                continue
            page_url = f"https://{lang}.wikipedia.org/wiki/{title.replace(' ', '_')}"
            lang_label = "ภาษาไทย" if lang == "th" else "ภาษาอังกฤษ"
            lines = [
                f"📚 **Wikipedia ({lang_label}) — {title}**",
                "",
                "**คำสั่งสำคัญ**: ใช้ข้อมูลด้านล่างนี้เท่านั้นในการตอบ "
                "ห้ามเพิ่มข้อมูลจากความจำของตัวเอง ห้ามคาดเดา "
                "ถ้าข้อมูลไม่มีในนี้ ให้บอกว่า \"ไม่พบในข้อมูลที่มี\"",
                "",
                "--- เนื้อหาจาก Wikipedia ---",
                extract,
                "--- จบเนื้อหา ---",
                f"\n🔗 {page_url}",
            ]
            return "\n".join(lines)
        return ""
    except Exception as e:
        logger.warning(f"[Wiki] fetch failed: {e}")
        return ""


def _extract_city(query: str) -> str:
    """หาเมืองจากคำถาม — default Bangkok"""
    cities = {
        "กรุงเทพ": "Bangkok", "เชียงใหม่": "Chiang Mai", "ภูเก็ต": "Phuket",
        "พัทยา": "Pattaya", "ขอนแก่น": "Khon Kaen", "หาดใหญ่": "Hat Yai",
        "นครราชสีมา": "Nakhon Ratchasima", "ชลบุรี": "Chonburi",
    }
    for th, en in cities.items():
        if th in query:
            return en
    return "Bangkok"


def fetch_weather(query: str) -> str:
    """ดึงข้อมูลอากาศจาก wttr.in — คืน text plain พร้อมตัวเลขจริง"""
    try:
        import requests
        city = _extract_city(query)
        url = f"https://wttr.in/{city}?lang=th&format=j1"
        resp = requests.get(url, timeout=8, headers={"User-Agent": _UA})
        if resp.status_code != 200:
            return ""
        import json as _json
        d = _json.loads(resp.text)
        cur = d.get("current_condition", [{}])[0]
        forecast = d.get("weather", [])

        lines = [f"📍 **สภาพอากาศจริงของ {city}** (จาก wttr.in)\n"]
        lines.append(f"**ปัจจุบัน** ({cur.get('localObsDateTime','')})")
        lines.append(f"- อุณหภูมิ: {cur.get('temp_C','-')}°C (รู้สึกเหมือน {cur.get('FeelsLikeC','-')}°C)")
        lines.append(f"- สภาพ: {cur.get('lang_th',[{}])[0].get('value', cur.get('weatherDesc',[{}])[0].get('value',''))}")
        lines.append(f"- ความชื้น: {cur.get('humidity','-')}% | ลม: {cur.get('windspeedKmph','-')} km/h")
        lines.append(f"- ฝน: {cur.get('precipMM','-')} mm | เมฆ: {cur.get('cloudcover','-')}%")
        lines.append("")

        for day in forecast[:3]:
            date = day.get("date", "")
            avg = day.get("avgtempC", "-")
            mx = day.get("maxtempC", "-")
            mn = day.get("mintempC", "-")
            sun = day.get("sunHour", "-")
            noon = day.get("hourly", [{}])[4] if len(day.get("hourly", [])) > 4 else {}
            desc = noon.get("lang_th", [{}])[0].get("value", "") if noon else ""
            lines.append(f"**{date}**: {mn}-{mx}°C เฉลี่ย {avg}°C | {desc} | แดด {sun} ชม.")

        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"[Weather] wttr.in failed: {e}")
        return ""


def web_search_context(query: str, max_results: int = 5) -> str:
    """API เดียวที่ router/chat ใช้ — คืน context string พร้อม inject

    Pipeline routing:
      - weather query → wttr.in (ตัวเลขจริง)
      - definitional/factual → Wikipedia summary
      - อื่นๆ → DuckDuckGo + URL fetch
    """
    if _WEATHER_KEYWORDS.search(query):
        weather = fetch_weather(query)
        if weather:
            logger.info(f"[WebSearch] weather → wttr.in ({len(weather)} chars)")
            return weather

    if _WIKI_KEYWORDS.search(query):
        wiki = fetch_wikipedia(query)
        if wiki:
            logger.info(f"[WebSearch] wiki → Wikipedia ({len(wiki)} chars)")
            return wiki

    results = search_web(query, max_results=max_results)
    results = _enrich_with_fetch(results, top_n=_FETCH_TOP_N)
    return format_for_context(results, query)
