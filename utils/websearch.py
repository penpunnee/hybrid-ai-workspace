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
_FETCH_TOP_N = 3  # ดึง HTML 3 ผลแรก ที่เหลือใช้ snippet
# เพดานเนื้อหาต่อหน้า — 2,500 ตัวอักษร/หน้า × 3 หน้า ≈ 2.5k tokens
# (สมดุล: ตอบละเอียดขึ้น แต่ไม่ชน n_ctx local agent ที่แบก system prompt ~8.5k อยู่แล้ว)
_FETCH_MAX_CHARS = 2500
_SNIPPET_MAX_CHARS = 500

# ── Domain credibility scoring ───────────────────────────────────────────────
_HIGH_CREDIBILITY = re.compile(
    r"\.go\.th|\.gov\.|\.edu\.|\.ac\.th|\.ac\.|wikipedia\.org"
    r"|who\.int|un\.org|moph\.go\.th|bbc\.com|reuters\.com|ap\.org",
    re.IGNORECASE,
)
_LOW_CREDIBILITY = re.compile(
    r"blogspot\.|wordpress\.com|pantip\.com|reddit\.com|twitter\.com"
    r"|facebook\.com|tiktok\.com|youtube\.com",
    re.IGNORECASE,
)


def _domain_score(url: str) -> tuple[float, str]:
    """คืน (score, label) ตาม domain — high=1.2, normal=1.0, low=0.7"""
    if not url:
        return 1.0, "🔵 ทั่วไป"
    if _HIGH_CREDIBILITY.search(url):
        return 1.2, "🟢 แหล่งทางการ"
    if _LOW_CREDIBILITY.search(url):
        return 0.7, "🟡 ระวัง (บล็อก/ฟอรัม)"
    return 1.0, "🔵 ทั่วไป"


def _extract_text(html: str, max_chars: int = _FETCH_MAX_CHARS) -> str:
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


def _google_search(query: str, max_results: int = 5) -> list[dict]:
    """ค้นผ่าน Google Custom Search API"""
    import os, requests
    api_key = os.getenv("GOOGLE_SEARCH_API_KEY", "")
    cx = os.getenv("GOOGLE_SEARCH_CX", "")
    if not api_key or not cx:
        return []
    try:
        resp = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={"key": api_key, "cx": cx, "q": query, "num": min(max_results, 10)},
            timeout=8,
        )
        items = resp.json().get("items", [])
        results = [{"title": i.get("title", ""), "body": i.get("snippet", ""), "href": i.get("link", "")} for i in items]
        logger.info(f"[Google] '{query}' → {len(results)} results")
        return results
    except Exception as e:
        logger.warning(f"[Google] search failed: {e}")
        return []


def search_web(query: str, max_results: int = 5, region: str = "th-th") -> list[dict]:
    """ค้นหา — ลอง Google ก่อน fallback DDG"""
    # ลอง Google Custom Search ก่อน
    results = _google_search(query, max_results)
    if results:
        return results

    # fallback → DuckDuckGo
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
        logger.info(f"[WebSearch] '{query}' → {len(results)} results (DDG)")
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

    # แยก high/low credibility เพื่อแจ้งโมเดล
    has_low = any(_LOW_CREDIBILITY.search(r.get("href", "")) for r in results)
    conflict_hint = " ข้อมูลบางแหล่งอาจขัดแย้งกัน ให้ระบุความไม่แน่นอนและแนะนำค้นเพิ่ม" if has_low else ""

    lines = [
        "🌐 **ข้อมูลล่าสุดจากอินเตอร์เน็ต** (ระบบดึงให้แล้ว ณ เวลานี้)",
        f"คำค้น: \"{query}\" | เวลา: {now}",
        "",
        "**คำสั่งสำคัญ:**",
        "- ห้ามบอกว่า \"ไม่มี internet\" เพราะระบบดึงข้อมูลด้านล่างให้แล้ว",
        "- **เรียบเรียงด้วยภาษาของตัวเอง** ห้ามคัดลอกข้อความยาวๆ โดยตรง",
        "- 🟢 แหล่งทางการ = น้ำหนักสูง | 🔵 ทั่วไป = ใช้ประกอบ | 🟡 บล็อก/ฟอรัม = ระวัง ใช้ประกอบเท่านั้น",
        f"- อ้างอิงแหล่งที่มาทุกครั้ง{conflict_hint}",
        "",
    ]
    for i, r in enumerate(results, 1):
        title = r.get("title", "").strip()
        snippet = r.get("body", "").strip()[:_SNIPPET_MAX_CHARS]
        fetched = r.get("fetched_text", "").strip()
        href = r.get("href", "").strip()
        score = r.get("_rerank_score")
        if not (snippet or fetched):
            continue
        _, cred_label = _domain_score(href)
        score_tag = f" _(relevance: {score:.2f})_" if score is not None else ""
        lines.append(f"[{i}] **{title}** {cred_label}{score_tag}")
        if fetched:
            lines.append(f"    {fetched[:_FETCH_MAX_CHARS]}")
        elif snippet:
            lines.append(f"    {snippet}")
        if href:
            lines.append(f"    🔗 {href}")
        lines.append("")

    return "\n".join(lines)


# ⚠️ ห้ามใส่คำบอกเวลาล้วน (วันนี้/พรุ่งนี้) — มันแย่งคำถามที่แค่บังเอิญมี "วันนี้"
# เช่น "ราคาทองวันนี้"/"ข่าววันนี้" ไป fetch_weather() (บั๊ก 2026-06-15)
_WEATHER_KEYWORDS = re.compile(
    r"อากาศ|พยากรณ์|อุณหภูมิ|ฝนตก|ความชื้น|weather|forecast|temperature",
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
                "=" * 60,
                "🚨 STRICT GROUNDING MODE — ห้ามใช้ความรู้จากการฝึกของคุณ",
                "=" * 60,
                "",
                f"📚 **แหล่งข้อมูลที่อนุญาตให้ใช้:** Wikipedia ({lang_label})",
                f"📑 **บทความ:** {title}",
                "",
                "**กฎเด็ดขาด 5 ข้อ:**",
                "1. ใช้ข้อมูลจาก \"เนื้อหาจาก Wikipedia\" ด้านล่างเท่านั้น",
                "2. ก่อนระบุข้อเท็จจริงใดๆ ให้ค้นในเนื้อหาก่อน — ถ้าไม่เจอ ห้ามแต่ง",
                "3. ถ้าไม่มีคำตอบใน source: ตอบ \"ไม่พบข้อมูลนี้ใน Wikipedia ค่ะ\"",
                "4. ห้ามเดา ห้ามเสริมจากความจำ ห้าม\"น่าจะ\"",
                "5. ตัวเลข/ชื่อ/วันที่ ต้องตรงกับ source 100%",
                "",
                "**ตัวอย่างคำตอบที่ถูก:**",
                "   ❌ ผิด: \"เกิดที่ลพบุรี\" (ไม่มีใน source)",
                "   ✅ ถูก: \"ตาม Wikipedia เกิดเมื่อ 17 เมษายน พ.ศ. 2277\"",
                "   ✅ ถูก: \"ไม่พบข้อมูลเรื่อง X ใน Wikipedia ค่ะ\"",
                "",
                "─── เนื้อหาจาก Wikipedia (เริ่ม) ───",
                extract,
                "─── เนื้อหาจาก Wikipedia (จบ) ───",
                "",
                "🚨 **ย้ำอีกครั้ง:** ตอบเฉพาะที่อ่านได้จากเนื้อหาด้านบน "
                "ถ้าผู้ใช้ถามสิ่งที่ไม่มี ให้บอก \"ไม่พบใน Wikipedia\" "
                "อย่าแต่งข้อมูลขึ้นมาเอง",
                "",
                f"🔗 แหล่งที่มา: {page_url}",
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


def fetch_weather_by_city(city: str) -> str:
    """ดึงข้อมูลอากาศจาก wttr.in ด้วยชื่อเมืองตรงๆ (ไม่ผ่าน text parsing)"""
    try:
        import requests
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


def fetch_weather(query: str) -> str:
    """Backward-compat wrapper — รับ text query แล้ว extract city"""
    city = _extract_city(query)
    return fetch_weather_by_city(city)


def web_search_with_results(query: str, max_results: int = 5, top_k: int = 3) -> tuple[str, list[dict]]:
    """เหมือน web_search_context แต่คืน (context_string, raw_results) สำหรับ citation tracking

    weather/wiki → ไม่มี raw_results (คืน [])
    """
    ctx, results = _web_search_impl(query, max_results, top_k)
    return ctx, results


def web_search_context(query: str, max_results: int = 5, top_k: int = 3) -> str:
    """API เดียวที่ router/chat ใช้ — คืน context string พร้อม inject

    Pipeline routing:
      - weather query → wttr.in (ตัวเลขจริง)
      - definitional/factual → Wikipedia summary
      - อื่นๆ → DuckDuckGo + URL fetch + embedding rerank → top_k

    Args:
        query: คำค้น
        max_results: ดึงผลลัพธ์ DDG ก่อน rerank (default 5)
        top_k: เก็บกี่ผลลัพธ์หลัง rerank (default 3)
    """
    ctx, _ = _web_search_impl(query, max_results, top_k)
    return ctx


def _web_search_impl(query: str, max_results: int = 5, top_k: int = 3) -> tuple[str, list[dict]]:
    """internal — รวม logic ทั้งหมดและคืน (context, raw_results สำหรับ citations)"""
    if _WEATHER_KEYWORDS.search(query):
        weather = fetch_weather(query)
        if weather:
            logger.info(f"[WebSearch] weather → wttr.in ({len(weather)} chars)")
            return weather, []

    if _WIKI_KEYWORDS.search(query):
        wiki = fetch_wikipedia(query)
        if wiki:
            logger.info(f"[WebSearch] wiki → Wikipedia ({len(wiki)} chars)")
            return wiki, []

    # ── Query rewriting ──────────────────────────────────────────────────
    # ขยาย/ปรับ query → ค้นด้วย rewritten + sub_queries แล้วรวม
    try:
        from utils.query_rewrite import rewrite_query
        rw = rewrite_query(query)
        search_queries = rw.all_queries or [query]
        if rw.used_llm and rw.rewritten != query:
            logger.info(f"[WebSearch] rewrite: {query!r} → {rw.rewritten!r} "
                        f"(+{len(rw.sub_queries)} sub)")
    except Exception as e:
        logger.warning(f"[WebSearch] rewrite failed: {e}")
        search_queries = [query]

    # ดึง 2x ก่อน rerank เพื่อให้มีตัวเลือก — search หลาย query แล้ว dedupe ตาม URL
    initial_n = max(max_results, top_k * 2)
    seen_urls: set[str] = set()
    results: list[dict] = []
    per_query = max(2, initial_n // max(1, len(search_queries)))
    for sq in search_queries:
        for r in search_web(sq, max_results=per_query):
            url = (r.get("href") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            results.append(r)
        if len(results) >= initial_n:
            break

    results = _enrich_with_fetch(results, top_n=_FETCH_TOP_N)

    # ใส่ domain score ก่อน rerank เพื่อให้ embedding score × credibility
    for r in results:
        d_score, d_label = _domain_score(r.get("href", ""))
        r["_domain_score"] = d_score
        r["_source_label"] = d_label

    # Embedding rerank × domain score
    try:
        from utils.embed import rerank_by_similarity
        reranked = rerank_by_similarity(
            query, results,
            text_keys=("title", "fetched_text", "body"),
            top_k=top_k,
        )
        if reranked:
            # คูณ _rerank_score ด้วย domain score
            for r in reranked:
                if r.get("_rerank_score") is not None:
                    r["_rerank_score"] = round(r["_rerank_score"] * r.get("_domain_score", 1.0), 4)
            results = reranked
    except Exception as e:
        logger.warning(f"[WebSearch] rerank failed, use top {top_k}: {e}")
        results = results[:top_k]

    return format_for_context(results, query), results
