"""Query Rewriting — ขยาย/ปรับ query ก่อน retrieval

หน้าที่:
  - เติม context เวลา/สถานที่ให้ query ที่กำกวม ("วันนี้" → วันที่จริง)
  - ขยาย abbreviation/คำย่อ
  - แตก query ซับซ้อนเป็น sub-queries
  - สกัด keywords สำคัญ

ใช้ LMStudio (เร็ว) เป็นหลัก — ถ้า fail คืน fallback ที่สร้างจาก rule-based
ทุก call cache ด้วย lru_cache 256 entries
"""
import json
import logging
import os
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from functools import lru_cache
from typing import Optional

from openai import OpenAI

logger = logging.getLogger(__name__)

_LMSTUDIO_BASE_URL = os.getenv("LMSTUDIO_BASE_URL", "http://192.168.51.235:1234/v1")
_REWRITE_MODEL = os.getenv("QUERY_REWRITE_MODEL", os.getenv("LMSTUDIO_CHAT_MODEL", "google/gemma-4-e4b"))
_REWRITE_TIMEOUT = int(os.getenv("QUERY_REWRITE_TIMEOUT", "8"))
_REWRITE_ENABLED = os.getenv("QUERY_REWRITE_ENABLED", "true").lower() == "true"

_client = OpenAI(base_url=_LMSTUDIO_BASE_URL, api_key="lmstudio", timeout=_REWRITE_TIMEOUT)


@dataclass
class RewriteResult:
    """ผลลัพธ์การ rewrite — ใช้ทั้งใน websearch และ retrieval"""
    original: str
    rewritten: str
    sub_queries: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    used_llm: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def all_queries(self) -> list[str]:
        """รวม rewritten + sub_queries สำหรับ multi-query retrieval"""
        seen = set()
        out = []
        for q in [self.rewritten, *self.sub_queries]:
            q = (q or "").strip()
            if q and q not in seen:
                seen.add(q)
                out.append(q)
        return out


# ── Rule-based helpers (ไม่ต้องเรียก LLM) ───────────────────────────────────
_TIME_PATTERNS = [
    (re.compile(r"\bวันนี้\b"),     lambda: f"วันนี้ ({datetime.now().strftime('%d %B %Y')})"),
    (re.compile(r"\bพรุ่งนี้\b"),    lambda: f"พรุ่งนี้"),
    (re.compile(r"\bเมื่อวาน\b"),    lambda: f"เมื่อวาน"),
    (re.compile(r"\btoday\b", re.I), lambda: f"today ({datetime.now().strftime('%Y-%m-%d')})"),
    (re.compile(r"\btomorrow\b", re.I), lambda: f"tomorrow"),
]

_STOPWORDS = {
    "ที่", "ของ", "เป็น", "และ", "หรือ", "ใน", "กับ", "ให้", "ไป", "มา",
    "อะไร", "ไหม", "ครับ", "ค่ะ", "คะ", "นะ", "ละ", "บ้าง", "ด้วย",
    "the", "a", "an", "is", "are", "was", "were", "of", "in", "on", "at",
    "to", "for", "and", "or", "but", "what", "how", "why", "when", "where",
}


def _inject_time_context(query: str) -> str:
    """แทนคำเวลาที่กำกวมด้วยวันที่จริง"""
    out = query
    for pat, repl in _TIME_PATTERNS:
        if pat.search(out):
            out = pat.sub(lambda _: repl(), out, count=1)
    return out


def _extract_keywords_rule(query: str, max_n: int = 5) -> list[str]:
    """สกัด keyword โดยตัด stopwords + คำสั้น"""
    tokens = re.findall(r"[฀-๿a-zA-Z0-9]+", query.lower())
    seen, out = set(), []
    for t in tokens:
        if len(t) <= 1 or t in _STOPWORDS or t in seen:
            continue
        seen.add(t)
        out.append(t)
        if len(out) >= max_n:
            break
    return out


def _fallback(query: str) -> RewriteResult:
    """Rule-based rewrite — ใช้เมื่อ LLM ปิด/ล้ม"""
    return RewriteResult(
        original=query,
        rewritten=_inject_time_context(query).strip(),
        sub_queries=[],
        keywords=_extract_keywords_rule(query),
        used_llm=False,
    )


# ── LLM-based rewrite ────────────────────────────────────────────────────────
_SYSTEM_PROMPT = (
    "คุณคือ Query Rewriter สำหรับระบบ retrieval ตอบเป็น JSON เท่านั้น ห้ามมีข้อความอื่น\n"
    "หน้าที่:\n"
    "1. rewritten: เขียน query ให้ชัดเจน ระบุเวลา/สถานที่ถ้าจำเป็น (ไม่เปลี่ยนความหมาย)\n"
    "2. sub_queries: ถ้า query มีหลายประเด็น ให้แตก 1-3 sub-queries (list ว่างถ้าไม่จำเป็น)\n"
    "3. keywords: 3-6 keywords สำคัญสำหรับ search\n\n"
    "Schema: {\"rewritten\": str, \"sub_queries\": [str], \"keywords\": [str]}\n"
    f"วันนี้: {datetime.now().strftime('%Y-%m-%d')}"
)


def _parse_llm_json(text: str) -> Optional[dict]:
    """parse JSON ออกจาก LLM response — ทนต่อข้อความเสริม"""
    text = text.strip()
    # หา {...} block แรก
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def _call_llm(query: str) -> Optional[RewriteResult]:
    """เรียก LMStudio rewrite — คืน None ถ้า fail"""
    try:
        resp = _client.chat.completions.create(
            model=_REWRITE_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": f"Query: {query}"},
            ],
            temperature=0.2,
            max_tokens=200,
            stream=False,
        )
        text = resp.choices[0].message.content or ""
        data = _parse_llm_json(text)
        if not data:
            logger.warning(f"[QueryRewrite] non-JSON response: {text[:100]!r}")
            return None

        rewritten = (data.get("rewritten") or query).strip()
        sub_queries = [s.strip() for s in (data.get("sub_queries") or []) if isinstance(s, str) and s.strip()]
        keywords = [k.strip() for k in (data.get("keywords") or []) if isinstance(k, str) and k.strip()]

        return RewriteResult(
            original=query,
            rewritten=rewritten,
            sub_queries=sub_queries[:3],
            keywords=keywords[:6] or _extract_keywords_rule(query),
            used_llm=True,
        )
    except Exception as e:
        logger.warning(f"[QueryRewrite] LLM call failed for {query[:40]!r}: {e}")
        return None


# ── Public API ───────────────────────────────────────────────────────────────
def _should_rewrite(query: str) -> bool:
    """ตัดสินใจว่าควร rewrite ไหม — กัน latency กับ query สั้นๆ ที่ชัดอยู่แล้ว"""
    if not query or len(query.strip()) < 4:
        return False
    if len(query) > 500:  # ยาวเกิน ไม่ rewrite (เปลือง token)
        return False
    return True


@lru_cache(maxsize=256)
def _rewrite_cached(query: str) -> RewriteResult:
    """internal cached wrapper — รับ str เพื่อให้ hashable"""
    if not _REWRITE_ENABLED or not _should_rewrite(query):
        return _fallback(query)
    result = _call_llm(query)
    if result is None:
        return _fallback(query)
    return result


def rewrite_query(query: str) -> RewriteResult:
    """rewrite query — entry point หลัก

    Args:
        query: คำค้นของ user

    Returns:
        RewriteResult — ถ้า LLM fail จะ fallback เป็น rule-based โดยอัตโนมัติ
    """
    if not query:
        return RewriteResult(original="", rewritten="")
    try:
        return _rewrite_cached(query.strip())
    except Exception as e:
        logger.warning(f"[QueryRewrite] unexpected error: {e}")
        return _fallback(query)


def clear_cache() -> None:
    """ล้าง cache (ใช้ตอน test)"""
    _rewrite_cached.cache_clear()
