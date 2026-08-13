"""ซ่อมโรคกระจายที่ไม่เริ่มด้วยสระหน้า ("ก ร ะต่าย" · "ข ณ ะ" · "เท่านั้ น") — ตระกูลที่ 6

เจอ 2026-08-13 หลังปิดตระกูลสระหน้า (ดู `thaipdf.py`): PW เหลือ ~7,300 region ·
xianni ~560 (shape "พยัญชนะท้ายคำหลุดก่อนวรรคจริง": "เท่านั้ น หาก") — ตระกูลนี้
**ไม่มีลายเซ็นปลอดภัยเชิง regex**: สมาชิกกระจายเป็นพยัญชนะเปล่า/สระตาม/คำจริงปนกัน
และ "ว่า เจ้า" ในบทพูดคือวรรคจริง ⇒ ต้องใช้ความรู้ระดับคำ (pythainlp newmm + thai_words)

## อัลกอริทึม (สอบกับข้อความ prod จริงทั้งสองเล่ม 2026-08-13)

1. seed = token ไทยล้วนสั้น ≤3 ตัวอักษรที่ไม่ใช่คำในพจนานุกรม (ก · ร · มัง · ะ...)
   — ณ/ธ/ๆ/ฯ เป็น seed ไม่ได้ (คำจริงยืนเดี่ยว) แต่ ณ/ธ เป็น *สมาชิก* ได้ (ชิ้นของ "ข ณ ะ")
2. region = เพื่อนบ้านซ้าย 1 + โซ่ seed ไปทางขวา (คั่นวรรคเดียวเป๊ะ — ห้ามข้าม \n)
3. ลองทุก variant join/keep ของแต่ละวรรค เลือกตาม 3 ชั้น:
   ตัวอักษรนอกพจนานุกรมต่ำสุด → จำนวนคำต่ำสุด (คำประสมกลับมาติดกัน) →
   **เก็บวรรคมากสุด** (รักษา prosody ของวรรคจริง — ต่างจาก pass LV ที่ join ทิ้งได้เลย
   เพราะที่นี่ region มีคำจริงปนอยู่)
4. ด่านปิดท้าย: วรรคที่เก็บไว้ห้ามอยู่กลางคำ — ต่อสองข้างแล้วตัดคำ ไม่มีขอบคำตรง
   รอยต่อ = join เพิ่ม
5. รับผลเมื่อดีขึ้นจริงเท่านั้น (uncovered ลด หรือเท่าเดิม+คำลด) — ไม่ดีขึ้นไม่แตะ
   ⇒ ชื่อเฉพาะจีนที่ไม่อยู่ในพจนานุกรมถูกปล่อยไว้ (conservative)

## ข้อจำกัดที่รู้ (อย่าพยายามแก้โดยไม่มีข้อมูลใหม่)

- newmm ตัด "บอกว่า" เป็น บอ|กว่า (กว่า ยาวกว่า ว่า) ⇒ "บ อ กว่า" ซ่อมได้แค่
  "บอ กว่า" — เสียงอ่านเพี้ยนเล็กน้อยแต่ไม่ join มั่ว
- "สิง โต เก้า" (ทุก token เป็นคำจริง ไม่มี seed) ไม่ถูกแตะ — แยกไม่ออกจากวรรคจริง

## สองโหมดโดยตั้งใจ — prod image ไม่ต้องแบก pythainlp

- `compute_removals` ต้องมี pythainlp (lazy import) — รันนอก prod แล้วส่งตำแหน่ง
  วรรคที่ลบ (JSON + md5 กันข้อความเคลื่อน) เข้าไป
- `apply_removals` / `shift_bookmark` ไม่มี dependency — รันในคอนเทนเนอร์ได้
- ใช้ตอน **ขาเข้า/migration เท่านั้น** (ความยาวเปลี่ยน ที่คั่นหน้าเลื่อน)
- CLI: `scripts/fix_scatter_dict.py`
"""

import re as _re

_STANDALONE = {"ณ", "ธ", "ๆ", "ฯ"}
_THAI_TOKEN = _re.compile(r"^[ก-๙]+$")
_MAX_REGION = 12  # tokens — ห้ามตัดกลางโซ่ seed (เคยได้ "ขณ ะ" เพราะเพดาน 6)


# ── ฝั่ง apply: ไม่มี dependency ─────────────────────────────────────────────

def apply_removals(text: str, positions: list[int]) -> str:
    """ลบตัวอักษรตามตำแหน่ง — ทุกตำแหน่งต้องเป็นวรรคจริงเท่านั้น ไม่ใช่ = ValueError

    สัญญาเดียวกับด่านนิรภัยของ migration ตระกูล 1-5: ตัวซ่อมช่องว่างลบได้แต่ช่องว่าง
    """
    rm = set(positions)
    for p in rm:
        if p < 0 or p >= len(text) or text[p] != " ":
            raise ValueError(f"ตำแหน่ง {p} ไม่ใช่ช่องว่าง — ข้อความเคลื่อนจากตอน compute?")
    return "".join(ch for i, ch in enumerate(text) if i not in rm)


def shift_bookmark(pos: int, positions: list[int]) -> int:
    """ที่คั่นหน้าใหม่หลังลบวรรค = ถอยตามจำนวนวรรคที่ลบก่อนถึงมัน"""
    return pos - sum(1 for p in positions if p < pos)


# ── ฝั่ง compute: ต้องมี pythainlp ───────────────────────────────────────────

def compute_removals(text: str) -> list[int]:
    """คืนตำแหน่งวรรค (ดัชนีใน text) ที่ควรลบ — เรียงจากน้อยไปมาก"""
    from functools import lru_cache

    from pythainlp.corpus import thai_words
    from pythainlp.tokenize import word_tokenize

    words = thai_words()

    @lru_cache(maxsize=500_000)
    def seg(s: str) -> tuple[int, int]:
        toks = [w for w in word_tokenize(s, engine="newmm") if w.strip()]
        return sum(len(w) for w in toks if w not in words), len(toks)

    @lru_cache(maxsize=500_000)
    def is_seed(tok: str) -> bool:
        return (
            len(tok) <= 3
            and tok not in _STANDALONE
            and _THAI_TOKEN.match(tok) is not None
            and "ๆ" not in tok
            and tok not in words
        )

    def is_member(tok: str) -> bool:
        return _THAI_TOKEN.match(tok) is not None and "ๆ" not in tok

    tokens = [(m.start(), m.end(), m.group()) for m in _re.finditer(r"\S+", text)]
    removed: list[int] = []
    n = len(tokens)

    def single_space(a: int, b: int) -> bool:
        return tokens[b][0] - tokens[a][1] == 1 and text[tokens[a][1]] == " "

    i = 0
    while i < n:
        if not is_seed(tokens[i][2]):
            i += 1
            continue
        lo = i
        if lo > 0 and is_member(tokens[lo - 1][2]) and single_space(lo - 1, lo):
            lo -= 1
        hi = i
        while (
            hi + 1 < n
            and hi - lo + 1 < _MAX_REGION
            and single_space(hi, hi + 1)
            and is_member(tokens[hi + 1][2])
            and (is_seed(tokens[hi + 1][2]) or hi + 1 == i + 1 or is_seed(tokens[hi][2]))
        ):
            hi += 1
        if hi == lo:
            i += 1
            continue

        parts = [tokens[k][2] for k in range(lo, hi + 1)]
        gaps = hi - lo
        base_u = base_nw = 0
        for pt in parts:
            su, sn = seg(pt)
            base_u += su
            base_nw += sn

        def segments(mask: int) -> list[str]:
            segs = [parts[0]]
            for g in range(gaps):
                if mask >> g & 1:
                    segs[-1] += parts[g + 1]
                else:
                    segs.append(parts[g + 1])
            return segs

        best = None  # (uncovered, nwords, njoins, mask)
        for mask in range(1, 2 ** gaps):
            u = nw = 0
            for s in segments(mask):
                su, sn = seg(s)
                u += su
                nw += sn
            cand = (u, nw, bin(mask).count("1"), mask)
            if best is None or cand < best:
                best = cand

        if best is not None and (best[0], best[1]) < (base_u, base_nw):
            mask = best[3]
            # ด่านปิดท้าย: วรรคที่เก็บไว้ห้ามอยู่กลางคำ
            changed = True
            while changed:
                changed = False
                segs = segments(mask)
                kept = [g for g in range(gaps) if not mask >> g & 1]
                for k, g in enumerate(kept):
                    joined = segs[k] + segs[k + 1]
                    cut = len(segs[k])
                    acc, boundary = 0, False
                    for w in word_tokenize(joined, engine="newmm"):
                        acc += len(w)
                        if acc >= cut:
                            boundary = acc == cut
                            break
                    if not boundary:
                        mask |= 1 << g
                        changed = True
                        break
            for g in range(gaps):
                if mask >> g & 1:
                    removed.append(tokens[lo + g][1])
        i = hi + 1

    return sorted(removed)
