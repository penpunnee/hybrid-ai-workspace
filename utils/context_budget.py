"""Context Budget — trim retrieval items ตาม score + token budget

หลักการ:
  - Drop items ที่ score < min_score (default 0.3)
  - ถ้า total tokens เกิน max_tokens → ตัดจากล่างสุด (score ต่ำสุด)
  - ใช้ approx token counting (4 chars ≈ 1 token เฉลี่ย)
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)


def approx_tokens(text: str) -> int:
    """approximate token count — 4 chars ≈ 1 token (mix ไทย/อังกฤษ)"""
    if not text:
        return 0
    return max(1, len(text) // 4)


def filter_by_score(
    items: list[dict],
    score_key: str = "score",
    min_score: float = 0.3,
) -> list[dict]:
    """ตัด items ที่ score ต่ำกว่า threshold"""
    if not items:
        return items
    kept = [it for it in items if float(it.get(score_key, 1.0)) >= min_score]
    if len(kept) < len(items):
        logger.debug(f"[Budget] filter score≥{min_score}: {len(items)}→{len(kept)}")
    return kept


def trim_to_budget(
    items: list[dict],
    text_keys: tuple[str, ...] = ("text", "content", "body"),
    max_tokens: int = 1500,
    score_key: str = "score",
) -> list[dict]:
    """เก็บ items เรียงตาม score (สูงไปต่ำ) แล้วตัดเมื่อรวม tokens เกิน budget

    Args:
        items: list ของ dict ที่มี score + text field
        text_keys: ค้น text จาก fields เหล่านี้ตามลำดับ
        max_tokens: budget tokens สูงสุด
        score_key: ชื่อ field สำหรับ sort

    Returns:
        list[dict] เรียงตาม score, จำกัด budget
    """
    if not items:
        return items

    def _get_text(it: dict) -> str:
        for k in text_keys:
            v = it.get(k)
            if isinstance(v, str) and v:
                return v
        return ""

    # sort by score desc
    sorted_items = sorted(items, key=lambda x: float(x.get(score_key, 0.0)), reverse=True)

    out: list[dict] = []
    used = 0
    for it in sorted_items:
        cost = approx_tokens(_get_text(it))
        if used + cost > max_tokens and out:
            break
        out.append(it)
        used += cost
    return out


def stats(items_before: list[Any], items_after: list[Any], text_key: str = "text") -> dict:
    """summary — สำหรับ logging"""
    tok_before = sum(approx_tokens(it.get(text_key, "")) for it in items_before)
    tok_after = sum(approx_tokens(it.get(text_key, "")) for it in items_after)
    return {
        "items_before": len(items_before),
        "items_after": len(items_after),
        "tokens_before": tok_before,
        "tokens_after": tok_after,
        "savings_pct": round(100 * (1 - tok_after / max(1, tok_before)), 1),
    }
