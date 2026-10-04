"""Web Search — ค้นหาข้อมูลจาก DuckDuckGo + ดึง HTML จริงของ top result

Flow:
  User ถามเรื่อง real-time
  → backend ค้น DuckDuckGo (ไม่ต้อง API key)
  → ดึง HTML 2 อันแรกมา extract text จริง (200-2000 chars)
  → inject เข้า system prompt
  → local model อ่านข้อมูลจริงแล้วตอบ
"""
import asyncio
import logging
import math
import re
import threading
import time
import html as html_lib
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeout

from core.env_registry import env_float, env_str

logger = logging.getLogger(__name__)


# ── พื้นคะแนนสัมบูรณ์ ────────────────────────────────────────────────────────
# จัดอันดับอย่างเดียวไม่พอ — "อันดับ 1 ของผลที่ห่วยทั้งหมด" ก็ยังห่วย
# (prod 2026-08-03: ถาม Python เวอร์ชันล่าสุด แล้วได้เว็บโป๊เป็น citation [1]
#  เพราะโค้ดตัด `results[:top_k]` ตรงๆ ไม่เคยดูว่าคะแนนต่ำแค่ไหน)
#
# วัดจริงในคอนเทนเนอร์ prod 4 query:
#   ผลถูกต้อง  0.5955 – 0.8234   |   ขยะทั้งหมด  0.1024 – 0.2393
# ช่องว่าง 0.36 = ที่ราบกว้าง → เชื่อเกณฑ์ได้ · 0.35 เหนือขยะสูงสุด 0.11
# และต่ำกว่าผลดีที่แย่สุด 0.245 (เลขเดียวกับ SKILLS_FALLBACK_MIN_SCORE)
#
# ปิดด้วย WEB_SEARCH_MIN_SCORE=off (เผื่อ embed ล่มยาวจนต้องยอมรับผลที่ไม่ได้ตรวจ)
def _parse_min_score(raw: str) -> float | None:
    if raw.strip().lower() in {"off", "none", "", "0"}:
        return None
    try:
        return float(raw)
    except ValueError:
        logger.warning(f"[WebSearch] WEB_SEARCH_MIN_SCORE={raw!r} ไม่ใช่ตัวเลข — ใช้ค่า default 0.35")
        return 0.35


# env ของค้นเว็บ — ไฟล์นี้เป็นเจ้าของ 5 ชื่อ (ก้อน 4 · 2026-09-24 · ตัวกัน: tests/test_env_registry.py)
# MIN_SCORE/MIN_INTERVAL ลงเป็น str เพราะมี parser เดิม ("off" · ค่าไม่ถูกต้อง → default + warning) ห้ามใช้ env_float
# key ×3 เคยอ่านในฟังก์ชันทุกครั้งที่เรียก — ย้ายเป็นระดับโมดูล (env ใน prod นิ่ง) · เทส patch ค่าในโมดูลแทน setenv
_G = "Web Search"
WEB_SEARCH_MIN_SCORE = _parse_min_score(env_str("WEB_SEARCH_MIN_SCORE", "0.35", group=_G, doc=(
    "พื้นคะแนนสัมบูรณ์ของผลค้นเว็บ (rerank × credibility) — ต่ำกว่านี้ไม่ฉีด/ไม่ cite\n"
    "วัดบน prod: ผลถูกต้อง 0.60-0.82 · ขยะ 0.10-0.24 ⇒ 0.35 อยู่กลางที่ราบ · ปิดด้วย =off")))
BRAVE_SEARCH_API_KEY = env_str("BRAVE_SEARCH_API_KEY", "", group=_G,
                               doc="ตัวหลัก (ไม่ผูกกับ Google Cloud project) · ว่าง = ปิด ไม่ยิงเน็ตเลย ไม่บ่น")
BRAVE_MIN_INTERVAL = env_str("BRAVE_MIN_INTERVAL", "1.1", group=_G, doc=(
    "วินาทีหน่วงระหว่างคำขอ Brave · free tier = 1 คำขอ/วิ (sub-query ยิงติดกันในลูปเดียว)\n"
    "ค่า <=0 หรือพิมพ์ผิด ถอยไป 1.1 พร้อม warning — ไม่หน่วง = ตัวที่ 2 ได้ 429 ทุกครั้ง"))

_UNSET = object()


def _drop_below_min_score(results: list[dict], min_score=_UNSET) -> list[dict]:
    """ตัดผลที่พิสูจน์ความเกี่ยวข้องไม่ได้ออก ก่อนฉีด context / สร้าง citation

    `min_score=None` = ปิดพื้น · ไม่ส่ง = ใช้ `WEB_SEARCH_MIN_SCORE`

    **ผลที่ไม่มี `_rerank_score` ถูกตัดทิ้งด้วย** (fail-closed) — เกิดตอน rerank ล้ม
    แล้วโค้ดตกไปทาง `results[:top_k]` · หน้าที่ของพื้นคือ "พิสูจน์ก่อนฉีด" ผลที่ไม่มี
    คะแนนคือผลที่ยังไม่ถูกพิสูจน์ ถ้าปล่อยผ่าน รูเดิมจะเปิดอยู่ทั้งดุ้นทันทีที่ embed ล่ม
    """
    floor = WEB_SEARCH_MIN_SCORE if min_score is _UNSET else min_score
    if floor is None:
        return results

    kept, dropped = [], []
    for r in results:
        score = r.get("_rerank_score")
        (kept if isinstance(score, (int, float)) and score >= floor else dropped).append(r)

    if dropped:
        logger.info(
            f"[WebSearch] ตัด {len(dropped)} ผลที่คะแนนต่ำกว่า {floor}: "
            + ", ".join(f"{(r.get('title') or '?')[:40]!r}={r.get('_rerank_score')}" for r in dropped[:3])
        )
    return kept

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


# เนื้อหาหลักใน <main> ต้องยาวพอถึงจะเชื่อ (เว็บ SPA มี <main> เปล่ารอ JS เติม)
_MAIN_MIN_CHARS = 500
# เนื้อหาสั้นกว่านี้ = หน้าอ่านไม่ได้ (เว็บ JS) — เติมคำอธิบายหน้าจาก meta แทน
_THIN_TEXT_CHARS = 200
_META_DESC = re.compile(
    r'<meta[^>]+(?:property|name)=["\'](?:og:)?description["\'][^>]*content=["\']([^"\']*)', re.I)


def _strip_html(html: str) -> str:
    html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<nav[^>]*>.*?</nav>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<header[^>]*>.*?</header>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<footer[^>]*>.*?</footer>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", html)
    # decode &#xE01; &amp; &nbsp; etc. → ภาษาไทยจริง
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_text(html: str, max_chars: int = _FETCH_MAX_CHARS) -> str:
    """ดึง text จาก HTML แบบเร็ว (ไม่ใช้ BeautifulSoup)

    มี <main> ที่มีเนื้อหาจริง → ใช้แค่ใน main (เดิมได้ปุ่ม Sign In/แชร์ 2,500 ตัวแรก · prod 10-04) ·
    เนื้อหาเหลือน้อย (เว็บ JS) → เติม og:description ที่เว็บเขียนสรุปไว้ให้"""
    text = _strip_html(html)
    mains = re.findall(r"<main[\s>].*?</main>", html, flags=re.DOTALL | re.IGNORECASE)
    if mains:
        main_text = _strip_html(" ".join(mains))
        if len(main_text) >= _MAIN_MIN_CHARS:
            text = main_text
    if len(text) < _THIN_TEXT_CHARS:
        m = _META_DESC.search(html)
        desc = re.sub(r"\s+", " ", html_lib.unescape(m.group(1))).strip() if m else ""
        if desc and desc not in text:
            text = f"{desc} {text}".strip()
    return text[:max_chars]


_TERM_SPLIT = re.compile(r"[\s,.;:!?\"'()\[\]{}|/\\\-–—]+")


def focus_passages(text: str, query: str, max_chars: int, window: int = 400) -> str:
    """เลือกช่วงของหน้าที่ตรงคำค้น แทนการตัดหัวหน้า (หน้า wiki 76k ตัวอักษร เนื้อที่ถามอยู่ลึก)

    แบ่งเป็นช่วงละ `window` ตัวอักษร · ช่วงได้คะแนนตามคำค้นที่มี ถ่วงด้วยความหายาก (idf)
    — คำที่อยู่ทุกช่วง (เช่นชื่อตัวเอก) ได้ 0 · คืนช่วงคะแนนสูงสุดเรียงตามลำดับในหน้า
    ไม่มีคำค้น/ไม่ตรงเลย = ตัดหัวหน้าแบบเดิม"""
    if len(text) <= max_chars:
        return text
    terms = {t.lower() for t in _TERM_SPLIT.split(query or "") if len(t) >= 2}
    if not terms:
        return text[:max_chars]
    chunks = [text[i:i + window] for i in range(0, len(text), window)]
    low = [c.lower() for c in chunks]
    n = len(chunks)
    idf = {}
    for t in terms:
        df = sum(t in c for c in low)
        if df:
            idf[t] = math.log((n + 1) / (df + 1))
    scores = [sum(w for t, w in idf.items() if t in c) for c in low]
    ranked = [i for i in sorted(range(n), key=lambda i: -scores[i]) if scores[i] > 0]
    if not ranked:
        return text[:max_chars]
    picked = sorted(ranked[:max(1, max_chars // window)])
    out, prev = [], None
    for i in picked:
        if prev is not None and i != prev + 1:
            out.append(" … ")
        out.append(chunks[i])
        prev = i
    return "".join(out)


# เพดานข้อความดิบต่อหน้าก่อนเลือกช่วง (หน้า wiki ~76k) — กัน regex/หน่วยความจำกับหน้าใหญ่ผิดปกติ
_FETCH_RAW_MAX_CHARS = 200_000


def _fetch_url(url: str) -> str:
    """ดึง HTML จาก URL แล้ว extract text — best effort

    ผ่านเกราะ SSRF เดียวกับ tool fetch_url (`utils/urlguard`) — URL จาก DDG
    เสี่ยงต่ำกว่า URL จากบทสนทนา แต่ผลค้นก็ redirect ไปที่ไหนก็ได้เหมือนกัน
    """
    try:
        from utils.urlguard import fetch_url_safe
        # deadline = เพดานเวลารวม · timeout อย่างเดียวไม่กันเว็บที่ทยอยส่ง (ดู fetch_url_safe)
        res = fetch_url_safe(url, timeout=_FETCH_TIMEOUT, deadline=_FETCH_TIMEOUT)
        if "html" not in res.content_type and "text" not in res.content_type:
            return ""
        return _extract_text(res.text, max_chars=_FETCH_RAW_MAX_CHARS)
    except Exception as e:
        logger.debug(f"[WebSearch] fetch {url} failed: {e}")
        return ""


def _enrich_with_fetch(results: list[dict], top_n: int = _FETCH_TOP_N, query: str = "") -> list[dict]:
    """ดึง HTML ของ top results ขนานกัน — เติม field 'fetched_text' (ช่วงที่ตรง `query` ≤ _FETCH_MAX_CHARS)"""
    if not results:
        return results
    targets = results[:top_n]
    # ไม่ใช้ `with` — ตอนออกมันรอเธรดที่ค้างจนเสร็จ (เคยรอ 35.5 วิ เพราะหน้าเดียว)
    ex = ThreadPoolExecutor(max_workers=top_n)
    futures = {ex.submit(_fetch_url, r.get("href", "")): r for r in targets if r.get("href")}
    try:
        for fut in as_completed(futures, timeout=_FETCH_TIMEOUT + 2):
            r = futures[fut]
            try:
                r["fetched_text"] = focus_passages(fut.result() or "", query, _FETCH_MAX_CHARS)
            except Exception:
                r["fetched_text"] = ""
    except FuturesTimeout:
        # 🔴 เดิมไม่ดัก ⇒ หน้าช้าหน้าเดียว = web_search ล้มทั้งก้อน ทิ้งผลค้นที่ได้แล้ว
        # (2026-09-23 · "current gold price" → apmex.com) · หน้าช้า = ไม่มีเนื้อหา ใช้ snippet แทน
        slow = [futures[f].get("href", "") for f in futures if not f.done()]
        logger.warning(f"[WebSearch] fetch เกิน {_FETCH_TIMEOUT + 2} วิ ทิ้ง {len(slow)} หน้า "
                       f"(ใช้ snippet แทน): {slow}")
        for f in futures:
            if not f.done():
                futures[f]["fetched_text"] = ""
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    return results


def _select_and_fetch(results: list[dict], query: str, top_n: int = _FETCH_TOP_N) -> list[dict]:
    """เลือกหน้าที่จะ fetch จากความตรงคำถาม (title+snippet) **ก่อน** แล้วค่อย fetch — คืนเฉพาะผลที่ถูกเลือก

    เดิม fetch `results[:top_n]` ตามลำดับ provider แล้วค่อย rerank ⇒ ผลที่ชนะ rerank ไม่เคยถูก fetch
    (prod 10-04 โหมดเสียง: Brave ให้ YouTube/Facebook ก่อน หน้านิยายที่ตรงได้แค่ snippet บรรทัดเดียว)
    · เก็บอันดับ 1 ของ provider ไว้เสมอ — ลำดับ provider มีสัญญาณความน่าเชื่อถือ
    (วัด prod: pre-rank อย่างเดียวทำ goldtraders.or.th หลุดจาก "ราคาทองวันนี้")
    · คะแนนรอบนี้ใช้แค่เลือก — rerank รอบสุดท้าย (title+fetched_text+body) ไม่เปลี่ยน ⇒ พื้น 0.35 ยังใช้ได้"""
    if len(results) <= top_n:
        return _enrich_with_fetch(results, top_n=top_n, query=query)
    try:
        from utils.embed import rerank_by_similarity
        ranked = rerank_by_similarity(query, results, text_keys=("title", "body"), top_k=len(results))
    except Exception as e:
        logger.warning(f"[WebSearch] จัดอันดับก่อน fetch ล้ม ใช้ลำดับ provider: {e}")
        return _enrich_with_fetch(results, top_n=top_n, query=query)
    ranked = sorted(ranked, key=lambda r: -(r.get("_rerank_score") or 0)
                    * _domain_score(r.get("href", ""))[0])
    picked = ranked[:top_n]
    first = results[0].get("href")
    if first and all(r.get("href") != first for r in picked):
        picked.append(results[0])
    return _enrich_with_fetch(picked, top_n=len(picked), query=query)


# ── Brave Search ─────────────────────────────────────────────────────────────
# provider ตัวแรกของชั้นค้นเว็บ (2026-08-31) — user เลือกเพราะ **ไม่ผูกกับ Google
# Cloud project**: ก่อนหน้านี้ Gemini grounding 429 ทุกครั้ง (free tier ไม่เปิด)
# และ CSE 403 ทุกครั้งเพราะคีย์อยู่คนละ project กับที่เปิด API ไว้ — การไล่แก้คีย์
# วนกลับมาที่เดิมทุกครั้งที่ย้าย project เหลือ DDG ตัวเดียวซึ่งคืนเว็บโป๊มาเป็นผลค้น
_BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"

# free tier = 1 คำขอ/วินาที · `_web_search_impl` ยิง sub-query ติดกันในลูปเดียว
# ⇒ ไม่หน่วง = ตัวที่ 2 เป็นต้นไปได้ 429 ทุกครั้ง แล้วเราจะสรุปผิดว่า "Brave ใช้ไม่ได้"
# ทั้งที่เป็นความผิดฝั่งเราเอง · lock ด้วยเพราะ _enrich_with_fetch ใช้ threadpool
_brave_last_call = 0.0
_brave_lock = threading.Lock()


def _brave_min_interval() -> float:
    """ค่าบวกเท่านั้น — 0/ติดลบ ทำให้ตัวหน่วงหายไปเงียบๆ (บทเรียน TTS_MAX_CHARS=0)"""
    try:
        v = float(BRAVE_MIN_INTERVAL)
    except ValueError:
        v = 0.0
    if v <= 0:
        logger.warning("[Brave] BRAVE_MIN_INTERVAL ไม่ถูกต้อง — ใช้ค่า default 1.1")
        return 1.1
    return v


def _brave_search(query: str, max_results: int = 5) -> list[dict]:
    """ค้นผ่าน Brave Search API — ปล่อย BRAVE_SEARCH_API_KEY ว่าง = ปิด"""
    import requests
    token = BRAVE_SEARCH_API_KEY
    if not token:
        return []

    global _brave_last_call
    with _brave_lock:
        wait = _brave_min_interval() - (time.monotonic() - _brave_last_call)
        if wait > 0:
            time.sleep(wait)
        _brave_last_call = time.monotonic()

    try:
        resp = requests.get(
            _BRAVE_ENDPOINT,
            # token ไปทาง header ไม่ใช่ query string — URL ถูก log/แคชได้ header ไม่
            headers={"X-Subscription-Token": token, "Accept": "application/json"},
            params={"q": query, "count": min(max_results, 20),
                    # ขอกรองที่ต้นทาง — DDG รับ safesearch แล้วไม่กรองให้จริง
                    # (มีเทสยืนยัน) พื้นคะแนน WEB_SEARCH_MIN_SCORE เป็นด่านที่สอง
                    "safesearch": "strict"},
            timeout=10,
        )
        # ⚠️ ต้องดูสถานะก่อนอ่าน body เสมอ — บทเรียนสดจาก _google_search ที่ 403
        # มา 48/48 ครั้งโดยกลายเป็น "0 results" ระดับ INFO (commit 436f22b)
        if resp.status_code != 200:
            try:
                detail = str(resp.json())[:150]
            except Exception:
                detail = ""
            logger.error(f"[Brave] ค้นไม่ได้ HTTP {resp.status_code}: "
                         f"{detail or 'ไม่มีรายละเอียด'} — ตกไปใช้ provider ถัดไป")
            return []

        items = (resp.json().get("web") or {}).get("results", []) or []
        results = [{"title": i.get("title", ""), "body": i.get("description", ""),
                    "href": i.get("url", "")} for i in items]
        logger.info(f"[Brave] '{query}' → {len(results)} results")
        return results
    except Exception as e:
        # ห้ามมีคีย์ใน log ไม่ว่า exception จะสะท้อนอะไรกลับมา (audit 2026-09-24 ข้อ 3)
        logger.error(f"[Brave] search failed: {type(e).__name__}: "
                     f"{_redact_secrets(str(e), [token])}")
        return []


_KEY_PARAM_RE = re.compile(r"(?i)\b(key|api_key|apikey|token)=([^&\s'\"]+)")


def _redact_secrets(text: str, secrets: list[str]) -> str:
    """บังค่าความลับก่อน log — ทั้งค่าดิบที่รู้จัก และรูปแบบ `key=<ค่า>` ใน URL/query ทุกตัว"""
    out = text
    for sec in secrets:
        if sec:
            out = out.replace(sec, "***")
    return _KEY_PARAM_RE.sub(lambda m: f"{m.group(1)}=***", out)


def _ddg_search(query: str, max_results: int = 5, region: str = "th-th",
                safesearch: str = "on") -> list[dict]:
    """เรียก DuckDuckGo ครั้งเดียว — safesearch='on' กัน NSFW ที่ต้นทาง"""
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS
    with DDGS() as ddgs:
        return list(ddgs.text(
            query,
            region=region,
            safesearch=safesearch,
            max_results=max_results,
        ))


def search_web(query: str, max_results: int = 5, region: str = "th-th") -> list[dict]:
    """ค้นหา — Brave → DDG (retry 1 ครั้งกัน throttle ชั่วคราว)

    ⛔ Google CSE ถูกถอดออก 2026-10-01 — Google ปิดรับลูกค้าใหม่ + ปิดถาวร 2027-01-01
    และ project ของเรา 403 ทุกครั้ง · อย่าเอากลับมาเป็นชั้นสำรอง (ไม่มีทางเปิดใช้ได้แล้ว)
    """
    results = _brave_search(query, max_results)
    if results:
        return results

    # fallback → DuckDuckGo (ยิงได้ถึง 2 ครั้ง: รอบแรกว่าง = น่าจะโดน throttle → ลองซ้ำ)
    for attempt in range(2):
        try:
            results = _ddg_search(query, max_results, region)
        except Exception as e:
            logger.warning(f"[WebSearch] DuckDuckGo failed (attempt {attempt + 1}): {e}")
            results = []
        if results:
            logger.info(f"[WebSearch] '{query}' → {len(results)} results (DDG, attempt {attempt + 1})")
            return results

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
        if fetched and len(fetched) >= len(snippet):   # ดึงได้แค่ชื่อเรื่อง (เว็บ JS) ห้ามแทน snippet ที่ยาวกว่า
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


WEATHER_HOME_CITY = env_str("WEATHER_HOME_CITY", "Phrae", group=_G, doc=(
    "เมืองบ้านของผู้ใช้ (ชื่อที่ wttr.in รู้จัก) — คำถามอากาศที่ไม่ระบุเมือง/พูดว่า \"ที่บ้าน\" ใช้เมืองนี้"))

# 77 จังหวัด (ชื่อที่ wttr.in รู้จัก) — เดิมมีแค่ 8 เมือง ไม่เจอ = Bangkok ⇒ prod 10-04 ถามแพร่ได้อากาศกรุงเทพ (ต่อ 89)
_TH_PROVINCES = {
    "กรุงเทพ": "Bangkok", "กระบี่": "Krabi", "กาญจนบุรี": "Kanchanaburi", "กาฬสินธุ์": "Kalasin",
    "กำแพงเพชร": "Kamphaeng Phet", "ขอนแก่น": "Khon Kaen", "จันทบุรี": "Chanthaburi", "ฉะเชิงเทรา": "Chachoengsao",
    "ชลบุรี": "Chonburi", "ชัยนาท": "Chai Nat", "ชัยภูมิ": "Chaiyaphum", "ชุมพร": "Chumphon",
    "เชียงราย": "Chiang Rai", "เชียงใหม่": "Chiang Mai", "ตรัง": "Trang", "ตราด": "Trat", "ตาก": "Tak",
    "นครนายก": "Nakhon Nayok", "นครปฐม": "Nakhon Pathom", "นครพนม": "Nakhon Phanom",
    "นครราชสีมา": "Nakhon Ratchasima", "นครศรีธรรมราช": "Nakhon Si Thammarat", "นครสวรรค์": "Nakhon Sawan",
    "นนทบุรี": "Nonthaburi", "นราธิวาส": "Narathiwat", "น่าน": "Nan", "บึงกาฬ": "Bueng Kan",
    "บุรีรัมย์": "Buriram", "ปทุมธานี": "Pathum Thani", "ประจวบคีรีขันธ์": "Prachuap Khiri Khan",
    "ปราจีนบุรี": "Prachinburi", "ปัตตานี": "Pattani", "พระนครศรีอยุธยา": "Ayutthaya", "พะเยา": "Phayao",
    "พังงา": "Phang Nga", "พัทลุง": "Phatthalung", "พิจิตร": "Phichit", "พิษณุโลก": "Phitsanulok",
    "เพชรบุรี": "Phetchaburi", "เพชรบูรณ์": "Phetchabun", "แพร่": "Phrae", "ภูเก็ต": "Phuket",
    "มหาสารคาม": "Maha Sarakham", "มุกดาหาร": "Mukdahan", "แม่ฮ่องสอน": "Mae Hong Son", "ยโสธร": "Yasothon",
    "ยะลา": "Yala", "ร้อยเอ็ด": "Roi Et", "ระนอง": "Ranong", "ระยอง": "Rayong", "ราชบุรี": "Ratchaburi",
    "ลพบุรี": "Lopburi", "ลำปาง": "Lampang", "ลำพูน": "Lamphun", "เลย": "Loei", "ศรีสะเกษ": "Sisaket",
    "สกลนคร": "Sakon Nakhon", "สงขลา": "Songkhla", "สตูล": "Satun", "สมุทรปราการ": "Samut Prakan",
    "สมุทรสงคราม": "Samut Songkhram", "สมุทรสาคร": "Samut Sakhon", "สระแก้ว": "Sa Kaeo", "สระบุรี": "Saraburi",
    "สิงห์บุรี": "Sing Buri", "สุโขทัย": "Sukhothai", "สุพรรณบุรี": "Suphan Buri", "สุราษฎร์ธานี": "Surat Thani",
    "สุรินทร์": "Surin", "หนองคาย": "Nong Khai", "หนองบัวลำภู": "Nong Bua Lamphu", "อ่างทอง": "Ang Thong",
    "อำนาจเจริญ": "Amnat Charoen", "อุดรธานี": "Udon Thani", "อุตรดิตถ์": "Uttaradit", "อุทัยธานี": "Uthai Thani",
    "อุบลราชธานี": "Ubon Ratchathani",
}
# ชื่อเรียกอื่น/เมืองที่ไม่ใช่จังหวัด (ไม่นับใน 77)
_CITY_ALIASES = {"กทม": "Bangkok", "โคราช": "Nakhon Ratchasima", "อยุธยา": "Ayutthaya",
                 "พัทยา": "Pattaya", "หาดใหญ่": "Hat Yai"}
# ชื่อที่เป็นคำทั่วไปด้วย ("ตากผ้า" "ได้เลย" "เผยแพร่" "น่านน้ำ") — นับเป็นจังหวัดเมื่อมีคำบอกสถานที่นำหน้าเท่านั้น
_AMBIGUOUS_CITY = {"ตาก", "เลย", "แพร่", "น่าน"}
_PLACE_MARKERS = ("จังหวัด", "จ.", "ที่", "ใน", "แถว", "เมือง", "บ้าน", "อำเภอ", "อ.")
_CITY_NAMES = {**_TH_PROVINCES, **_CITY_ALIASES}.items()


def _extract_city(query: str) -> str:
    """หาเมืองจากคำถาม — ไม่ระบุ = `WEATHER_HOME_CITY` · คำกำกวมดูทุกตำแหน่งที่เจอ ("เผยแพร่…ที่แพร่")"""
    for th, en in _CITY_NAMES:
        start = query.find(th)
        while start != -1:
            before = query[:start].rstrip()
            if th not in _AMBIGUOUS_CITY or before.endswith(_PLACE_MARKERS):
                return en
            start = query.find(th, start + 1)
    return WEATHER_HOME_CITY


# ชื่อเปล่าบางจังหวัด wttr.in เดาผิดประเทศ (Nan/Loei → ฝรั่งเศส · Tak → อัฟกานิสถาน · วัด 10-04)
# "X,Thailand" ห้ามมีวรรคหลังจุลภาค ("Nan, Thailand" → สระบุรี) · Surat Thani,Thailand คลาด ~82 กม. → พิกัด
_WTTR_COORDS = {"surat thani": "9.14,99.33"}
_TH_CITY_EN = {en.lower(): en for en in {**_TH_PROVINCES, **_CITY_ALIASES}.values()}


def _wttr_location(city: str) -> str:
    """ชื่อเมือง → ตัวระบุที่ส่งให้ wttr.in · เมืองไทยที่รู้จัก = "X,Thailand" · อื่นๆ คงเดิม"""
    key = (city or "").strip().lower()
    if key in _WTTR_COORDS:
        return _WTTR_COORDS[key]
    if key in _TH_CITY_EN:
        return f"{_TH_CITY_EN[key]},Thailand"
    return city


# agent ไม่รู้วันที่ปัจจุบัน — วันที่ดิบ 2026-10-04/05/06 ⇒ เดาว่าวันแรกคือ "พรุ่งนี้" (prod 10-04 ต่อ 102)
# ⇒ ติดป้ายตามเวลาไทยให้เลย · wttr.in j1 ไม่มี localObsDateTime แล้ว มีแต่ observation_time (UTC)
_DAY_LABELS = {0: "วันนี้", 1: "พรุ่งนี้", 2: "มะรืนนี้"}
_BKK = timezone(timedelta(hours=7))


def _now_bkk() -> datetime:
    return datetime.now(_BKK).replace(tzinfo=None)


_TH_WEEKDAYS = ("จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์")
_TH_MONTHS = ("ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค.")


def _day_label(date: str, today) -> str:
    """"2026-10-05" → "พรุ่งนี้ (จันทร์ 5 ต.ค.)" · นอกช่วงวันนี้–มะรืนนี้/อ่านไม่ได้ = คงเดิม
    ห้ามเหลือ ISO ข้างป้าย — ป้าย "(พรุ่งนี้)" ข้าง 2026-10-05 แล้ว qwen ยังแปลงเป็น "4 ต.ค. วันศุกร์" เอง"""
    try:
        d = datetime.strptime(date, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return date
    label = _DAY_LABELS.get((d - today).days)
    if not label:
        return date
    return f"{label} ({_TH_WEEKDAYS[d.weekday()]} {d.day} {_TH_MONTHS[d.month - 1]})"


def _obs_time_bkk(obs_utc: str) -> str:
    """"02:38 PM" (UTC) → "21:38 น." · อ่านไม่ได้ = "" (ไม่ใส่วงเล็บว่าง)"""
    try:
        t = datetime.strptime((obs_utc or "").strip(), "%I:%M %p")
    except ValueError:
        return ""
    return f"{(t.hour + 7) % 24:02d}:{t.minute:02d} น."


def fetch_weather_by_city(city: str) -> str:
    """ดึงข้อมูลอากาศจาก wttr.in ด้วยชื่อเมืองตรงๆ (ไม่ผ่าน text parsing)"""
    try:
        import requests
        url = f"https://wttr.in/{_wttr_location(city)}?lang=th&format=j1"
        resp = requests.get(url, timeout=8, headers={"User-Agent": _UA})
        if resp.status_code != 200:
            return ""
        import json as _json
        d = _json.loads(resp.text)
        cur = d.get("current_condition", [{}])[0]
        forecast = d.get("weather", [])

        lines = [f"📍 **สภาพอากาศจริงของ {city}** (จาก wttr.in)\n"]
        obs = _obs_time_bkk(cur.get("observation_time", ""))
        lines.append(f"**ปัจจุบัน** (ข้อมูล ณ {obs})" if obs else "**ปัจจุบัน**")
        lines.append(f"- อุณหภูมิ: {cur.get('temp_C','-')}°C (รู้สึกเหมือน {cur.get('FeelsLikeC','-')}°C)")
        lines.append(f"- สภาพ: {cur.get('lang_th',[{}])[0].get('value', cur.get('weatherDesc',[{}])[0].get('value',''))}")
        lines.append(f"- ความชื้น: {cur.get('humidity','-')}% | ลม: {cur.get('windspeedKmph','-')} km/h")
        lines.append(f"- ฝน: {cur.get('precipMM','-')} mm | เมฆ: {cur.get('cloudcover','-')}%")
        lines.append("")

        today = _now_bkk().date()
        for day in forecast[:3]:
            date = day.get("date", "")
            avg = day.get("avgtempC", "-")
            mx = day.get("maxtempC", "-")
            mn = day.get("mintempC", "-")
            sun = day.get("sunHour", "-")
            noon = day.get("hourly", [{}])[4] if len(day.get("hourly", [])) > 4 else {}
            desc = noon.get("lang_th", [{}])[0].get("value", "") if noon else ""
            date = _day_label(date, today)
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
    ctx, results, _ = _web_search_impl(query, max_results, top_k)
    return ctx, results


def web_search_with_status(query: str, max_results: int = 5, top_k: int = 3) -> tuple[str, list[dict], str]:
    """เหมือน `web_search_with_results` + สถานะ: `"ok"` · `"empty"` (ค้นแล้วไม่มีผลที่เชื่อได้)
    · `"unavailable"` (มีผลแต่ให้คะแนนไม่ได้เลย = ระบบ embed ล่ม) — สองอย่างหลังต้องบอกผู้ใช้ต่างกัน"""
    return _web_search_impl(query, max_results, top_k)


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
    ctx, _, _ = _web_search_impl(query, max_results, top_k)
    return ctx


def _web_search_impl(query: str, max_results: int = 5, top_k: int = 3) -> tuple[str, list[dict], str]:
    """internal — รวม logic ทั้งหมดและคืน (context, raw_results สำหรับ citations, สถานะ)"""
    if _WEATHER_KEYWORDS.search(query):
        weather = fetch_weather(query)
        if weather:
            logger.info(f"[WebSearch] weather → wttr.in ({len(weather)} chars)")
            return weather, [], "ok"

    if _WIKI_KEYWORDS.search(query):
        wiki = fetch_wikipedia(query)
        if wiki:
            logger.info(f"[WebSearch] wiki → Wikipedia ({len(wiki)} chars)")
            return wiki, [], "ok"

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

    results = _select_and_fetch(results, query)

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

    # พื้นคะแนนสัมบูรณ์ — ต้องอยู่ "หลัง" rerank และ "ก่อน" format/citations
    # ไม่มีผลที่เชื่อได้ = คืน context ว่าง ให้โมเดลบอกว่าหาไม่เจอ ดีกว่าสรุปจากขยะ
    before = len(results)
    unscored = rerank_unavailable(results)
    results = _drop_below_min_score(results)
    if not results and unscored:
        logger.error(
            f"[WebSearch] '{query[:60]}' → ให้คะแนนไม่ได้ทั้ง {before} ผล (embed ล่ม) "
            "— ไม่ฉีด context · แจ้งว่าระบบขัดข้อง ไม่ใช่หาไม่เจอ"
        )
        return "", [], "unavailable"
    if not results and before:
        logger.warning(
            f"[WebSearch] '{query[:60]}' → ทุกผล ({before}) ต่ำกว่าเกณฑ์ "
            f"{WEB_SEARCH_MIN_SCORE} — ไม่ฉีด context"
        )

    ctx = format_for_context(results, query)
    return ctx, results, ("ok" if ctx else "empty")


def rerank_unavailable(results: list[dict]) -> bool:
    """มีผลค้น แต่ไม่มีผลไหนได้คะแนนเลย = rerank ล้ม (ไม่ใช่ "ไม่เกี่ยวข้อง")
    ใช้ร่วมทั้ง 2 pipeline (ที่นี่ + `agents/tools.py:_t_web_search`)"""
    return bool(results) and all(
        not isinstance(r.get("_rerank_score"), (int, float)) for r in results)


# ── โหมดเสียง: เพดานเวลารวม + ข้อความตอบโมเดลตามสถานะ ────────────────────────
# prod 2026-10-01: ค้นค้าง 3.5 นาที → user วางสายก่อนได้คำตอบ (ระหว่างค้นโมเดลเงียบสนิท)
VOICE_SEARCH_TIMEOUT_DEFAULT = 20.0
VOICE_SEARCH_TIMEOUT = env_float("VOICE_SEARCH_TIMEOUT", VOICE_SEARCH_TIMEOUT_DEFAULT, group=_G, doc=(
    "วินาทีสูงสุดที่โหมดเสียงรอผลค้นเว็บ — เกินแล้วบอกโมเดลว่าค้นไม่ทัน (ระหว่างรอขวัญเงียบสนิท)\n"
    "ค้นปกติ 2–6 วิ (วัด prod 2026-10-01)"))
# แนบหน้าผลค้นทุกครั้ง (ต่อ 60/68 · prod 10-01 20:19–20:32 โหมดเสียงใช้ผลค้นผิด 3 แบบ: ค้นภาคเกมผิดต่อ 5 ครั้ง
# หลัง user แก้ · แต่งชื่อที่ไม่มีในผล · มีชื่อในผลแต่ตอบกว้าง) · ⚠️ ห้ามสั่ง "ค้นใหม่" — tool description
# สั่งค้นครั้งเดียวต่อคำถาม (ทุกครั้งที่ค้น = เงียบ) · อยู่ใน payload ไม่ใช่ config ⇒ ไม่แตะเสียง 🔒
VOICE_SEARCH_GUIDE = (
    "[คำสั่งตอนตอบจากผลค้นนี้]\n"
    "1. ชื่อเฉพาะ ตัวเลข ราคา ปุ่มกด ขั้นตอน — พูดเฉพาะที่มีในข้อมูลด้านล่าง ถ้าไม่มีให้บอกว่า"
    "ในข้อมูลที่ค้นเจอไม่ได้ระบุ ห้ามเดาหรือแต่งเติม\n"
    "2. ถ้าข้อมูลด้านล่างเป็นคนละเรื่อง คนละภาค หรือคนละรุ่นกับที่ผู้ใช้ถาม ให้บอกผู้ใช้ตรงๆ ว่าที่ค้นเจอเป็นของอะไร "
    "อย่าเอามาตอบเหมือนเป็นเรื่องเดียวกัน\n"
    "3. ถ้าข้อมูลมีชื่อเฉพาะที่ตอบคำถามได้ (ชื่ออาวุธ ชื่อตัวละคร ชื่อสินค้า) ให้บอกชื่อนั้นตรงๆ ไม่ตอบกว้างๆ\n"
    "4. คำค้นครั้งต่อไปในบทสนทนานี้ ให้ใช้ชื่อเรื่อง/ภาค/รุ่นล่าสุดที่ผู้ใช้บอก\n"
    "5. ถ้าข้อมูลด้านล่างตอบได้แค่บางส่วน ให้ขึ้นต้นด้วยสิ่งที่ใกล้ที่สุดที่เจอทันที พร้อมบอกว่ามาจากไหน "
    "(เช่น ชื่อบท เลขตอน ชื่อเว็บ) แล้วบอกสั้นๆ ว่าส่วนไหนในข้อมูลไม่มี — จบคำตอบตรงนั้น "
    "ไม่ต้องถามกลับให้ผู้ใช้เล่ารายละเอียดเพิ่ม\n\n"
)
VOICE_SEARCH_EMPTY = "หาไม่เจอ ให้บอกผู้ใช้ตรงๆ ว่าหาไม่เจอ ห้ามแต่ง"
VOICE_SEARCH_UNAVAILABLE = ("ระบบค้นข้อมูลขัดข้องชั่วคราว (ไม่ใช่ว่าไม่มีข้อมูล) "
                            "ให้บอกผู้ใช้ตรงๆ ว่าตอนนี้ค้นไม่ได้ ลองใหม่ภายหลัง ห้ามแต่งคำตอบ")
VOICE_SEARCH_TIMED_OUT = ("ค้นนานเกินกำหนดจึงยกเลิก (ไม่ใช่ว่าไม่มีข้อมูล) "
                          "ให้บอกผู้ใช้ตรงๆ ว่าค้นไม่ทัน ลองถามใหม่อีกครั้ง ห้ามแต่งคำตอบ")


def _voice_search_sync(query: str) -> tuple[str, int, str]:
    from utils.llm import gemini_web_search
    ctx, srcs = gemini_web_search(query)
    if ctx:
        return ctx, len(srcs or []), "ok"
    ctx, results, status = web_search_with_status(query)
    return ctx, len(results), status


async def voice_search_payload(query: str) -> dict:
    """ค้นให้โหมดเสียง แล้วคืน payload ของ FunctionResponse — **ตอบทันทีเมื่อชนเพดาน**
    (งานค้นใน thread วิ่งต่อจนจบเองเบื้องหลัง · เรียกซ้ำจะเจอ embed ที่ถูกข้ามแล้ว)"""
    t0 = time.monotonic()
    try:
        ctx, n, status = await asyncio.wait_for(
            asyncio.to_thread(_voice_search_sync, query), timeout=VOICE_SEARCH_TIMEOUT)
    except asyncio.TimeoutError:
        logger.error(f"[Voice WS] ค้น {query!r} เกินเพดาน {VOICE_SEARCH_TIMEOUT:.0f}s → ตอบว่าค้นไม่ทัน")
        return {"error": VOICE_SEARCH_TIMED_OUT}
    logger.info(f"[Voice WS] ค้น {query!r} → {len(ctx)} ตัวอักษร {n} แหล่ง · {status} · "
                f"{time.monotonic() - t0:.1f}s")
    if status == "ok" and ctx:
        return {"result": VOICE_SEARCH_GUIDE + ctx}
    if status == "unavailable":
        return {"error": VOICE_SEARCH_UNAVAILABLE}
    return {"error": VOICE_SEARCH_EMPTY}
