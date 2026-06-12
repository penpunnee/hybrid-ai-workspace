# Stream Sanitization — โมเดล echo marker จาก chat template

บทเรียนจริง 2 รอบ: `<think>` รั่ว (2026-05-27, `reasoning/parser.py`) และ `[TOOL_RESULT]`
ขึ้นต้นคำตอบ agent (2026-06-12, `agents/orchestrator.py`)

## อาการ
- คำตอบ AI ขึ้นต้นหรือแทรกด้วย marker แปลกๆ: `[TOOL_RESULT]`, `<think>`, `<|im_end|>` ฯลฯ
- เจอเฉพาะบาง provider/โมเดล — เพราะ marker มาจาก **chat template ของ runtime**
  (LM Studio render ข้อความ role `tool` เป็น `[TOOL_RESULT]...[END_TOOL_RESULT]` ใน prompt)
  → โมเดลเล็กเลียนแบบ pattern ที่เห็นใน context ขึ้นต้นคำตอบตัวเอง

## Root cause หลักคิด
marker **ไม่อยู่ในโค้ดเราเลย** — grep ทั้ง repo ไม่เจอ literal = สัญญาณว่ามาจาก template/โมเดล
ห้ามไปแก้ prompt ขอร้องโมเดล (ไม่เวิร์กกับโมเดลเล็ก) → ต้อง **กรองที่ output stream**

## Pattern แก้: stateful filter ที่รอด marker แบ่งข้าม chunk
จุดตาย: stream มาเป็น chunk เล็กๆ → marker อาจโดนหั่น (`"[TOOL_"` + `"RESULT]"`)
→ replace ตรงๆ ต่อ chunk ไม่พอ ต้อง **hold suffix ที่อาจเป็น marker ครึ่งตัว** ไว้รอ chunk ถัดไป

```python
class _MarkerFilter:
    _MARKERS = ("[TOOL_RESULT]", "[END_TOOL_RESULT]")
    def __init__(self):
        self._buf = ""; self._emitted = False
    def _hold_len(self):           # suffix ที่อาจเป็น marker มาไม่ครบ
        hold = 0
        for m in self._MARKERS:
            for k in range(min(len(m)-1, len(self._buf)), 0, -1):
                if self._buf.endswith(m[:k]): hold = max(hold, k); break
        return hold
    def feed(self, chunk):
        self._buf += chunk
        for m in self._MARKERS: self._buf = self._buf.replace(m, "")
        cut = len(self._buf) - self._hold_len()
        out, self._buf = self._buf[:cut], self._buf[cut:]
        if not self._emitted: out = out.lstrip()   # ตัดช่องว่างหน้าคำตอบ
        if out: self._emitted = True
        return out
    def flush(self):               # เรียกตอน stream จบ — คาย tail ที่ค้าง
        out, self._buf = self._buf, ""
        return out if self._emitted else out.lstrip()
```

ใช้: `mf.feed(delta)` ทุก chunk + `mf.flush()` ตอนจบ (อย่าลืม flush ไม่งั้นตัวท้ายหาย)
ที่อยู่จริง: `agents/orchestrator.py:_MarkerFilter` (lmstudio path 2 จุด) —
แบบเดียวกับ `_partial_tag_suffix_len` ใน `reasoning/parser.py` (`<think>` ข้าม chunk)

## วิธี debug เร็ว
1. ดึงตัวอย่างจริงจาก DB: `sqlite3 chat_history.db "SELECT id, substr(content,1,200) FROM messages WHERE content LIKE '%MARKER%'"`
2. grep repo หา literal — ไม่เจอ = มาจาก template/โมเดล ไม่ใช่โค้ดเรา
3. ดูว่าหลุดเส้นไหน (provider ใน done event) → กรองที่ yield point ของเส้นนั้น
4. เทสต้องมีเคส marker แบ่งข้าม chunk เสมอ (บั๊กตัวจริงอยู่ตรงนั้น)
