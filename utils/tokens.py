def count_tokens_approx(messages: list[dict]) -> int:
    """
    นับจำนวน token แบบประมาณการ (ไม่ต้องติดตั้ง tiktoken)
    สูตร: ~1 token ≈ 4 ตัวอักษรภาษาอังกฤษ, ~2 ตัวอักษรภาษาไทย
    """
    total_chars = sum(len(m.get("content", "")) for m in messages)
    return total_chars // 3


CONTEXT_LIMITS = {
    "llama3": 8192,
    "llama3.2": 128000,
    "llama3:8b": 8192,
    "llama3:70b": 8192,
    "llama2": 4096,
    "gemini-1.5-flash": 1048576,
    "gemini-1.5-pro": 2097152,
    "gemini-2.0-flash": 1048576,
    "gemini-2.5-flash": 1048576,
}


def get_context_limit(model: str) -> int:
    """คืนค่า context window limit ของ model นั้น"""
    return CONTEXT_LIMITS.get(model, 8192)


def get_token_status(used: int, limit: int) -> tuple[str, str]:
    """
    คืนค่า (สี, ข้อความ) สำหรับแสดง status bar
    สี: 'normal' | 'warning' | 'error'
    """
    pct = used / limit if limit > 0 else 0
    if pct < 0.6:
        return "normal", f"~{used:,} / {limit:,} tokens ({pct:.0%})"
    elif pct < 0.85:
        return "warning", f"⚠️ ~{used:,} / {limit:,} tokens ({pct:.0%}) — ใกล้เต็ม"
    else:
        return "error", f"🔴 ~{used:,} / {limit:,} tokens ({pct:.0%}) — เกือบเต็ม ควรล้างแชท"
