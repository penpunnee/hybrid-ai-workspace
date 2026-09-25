"""ตัวอ่านฟิลด์จาก JSON body ที่ client ส่งมา — ของผิดชนิดต้องได้ค่า default/ว่าง ไม่ใช่ 500

(audit 2026-09-24 MEDIUM: `int(data.get(...))` ดิบ และ `.strip()` บน non-str ทำ 500 ใน 8 เส้น)
· `as_int`: None/bool/ขยะ → default · แล้ว clamp [lo, hi] ถ้าให้มา
· `as_str`: None → "" · ไม่ใช่ str → "" (ถือว่าไม่ได้ส่ง — ให้ handler เดิน path "ว่าง" ของมันเอง)
"""


def as_int(value, default: int, lo: int | None = None, hi: int | None = None) -> int:
    if value is None or isinstance(value, bool):
        n = default
    else:
        try:
            n = int(value)
        except (TypeError, ValueError):
            n = default
    if lo is not None:
        n = max(lo, n)
    if hi is not None:
        n = min(hi, n)
    return n


def as_str(value, strip: bool = True) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip() if strip else value
