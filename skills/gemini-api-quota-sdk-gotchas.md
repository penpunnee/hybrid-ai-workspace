# Gemini API — quota limit:0 และ SDK gotchas

บทเรียนจริง 3 เคส: `gemini-2.5-pro` (2026-06-11), image gen ทุกโมเดล (2026-06-12),
`Part.from_text` TypeError (2026-06-12)

## 1. อ่าน 429 ให้เป็น: "limit: 0" ≠ quota หมดชั่วคราว
error 429 RESOURCE_EXHAUSTED มี 2 ความหมายต่างกันสิ้นเชิง — ดูที่ field `limit` ใน message:
- **`limit: 250` (เลข > 0)** = โควต้าวันนี้/นาทีนี้หมด → รอแล้วหาย retry ช่วย
- **`limit: 0`** = **โมเดลนี้ไม่เปิดให้ free tier เลย** → retry กี่รอบก็ไม่หาย
  ต้องเปลี่ยนโมเดล หรือเปิด billing เท่านั้น (ข้อความ "Please retry in 50s" ของ Google หลอก!)

เคสที่เจอจริง (key free tier เดียวกัน):
- `gemini-2.5-pro` → limit=0 (ใช้ `gemini-2.5-flash` แทน — ตั้งใน `.env` `GEMINI_MODEL`)
- โมเดลสร้างรูป**ทุกตัว** → limit=0 ทั้งหมด: `gemini-2.5-flash-image`
  (resolve เป็น `gemini-2.5-flash-preview-image`), `gemini-3.1-flash-image`;
  ตัว `-preview` คืน 404; `imagen-4.0-*` = paid-only → **image gen บน free tier = ไม่มีทางเลือก**
  ฟีเจอร์วาดรูปใน chat จึงพักไว้จนกว่าจะเปิด billing (~$0.04/รูป)

## 2. วิธีวินิจฉัยเร็ว (จาก Mac, ใช้ key เดียวกับ NAS)
```bash
KEY=$(grep '^GEMINI_API_KEY=' .env | cut -d= -f2)
# ลิสต์โมเดลที่ key เห็น
curl -s "https://generativelanguage.googleapis.com/v1beta/models?key=$KEY" | grep '"name"'
# ยิงเทส 1 request ดู limit ใน error
curl -s -X POST ".../models/<MODEL>:generateContent?key=$KEY" \
  -H 'Content-Type: application/json' -d '{"contents":[{"parts":[{"text":"hi"}]}]}'
```
ฝั่ง prod: `docker logs ai-backend-1 | grep -i imagegen` (หรือ error ของ module นั้น)
— อย่าเดาจากข้อความ error ฝั่ง UI เพราะถูก map รวมแล้ว

## 3. UX: error message ต้องแยก 2 เคสนี้
ห้ามบอก user "ลองใหม่ภายหลัง" ตอน limit=0 — ชวนเข้าใจผิด
ดู `utils/image_gen.py`: เช็ค `"limit: 0" in err` → บอก "ต้องเปิด billing" แทน

## 4. SDK google-genai: Part.from_text เป็น keyword-only
SDK รุ่นใหม่: `Part.from_text(*, text: str)` — ส่ง positional = 
`TypeError: takes 1 positional argument but 2 were given`
```python
genai_types.Part.from_text(text=msg["content"])   # ✅
genai_types.Part.from_text(msg["content"])         # ❌ TypeError
```
**กับดักที่ทำให้บั๊กซ่อนนาน:** โค้ดสร้าง Part เฉพาะตอนมี history คั่นกลาง
→ request แรกของ session ผ่านฉลุย (history ว่าง) แต่ request ที่ 2 พังทุกครั้ง
→ smoke test ที่ยิง session ใหม่ทุกครั้งจะไม่มีวันเจอ — **เทส multi-turn ใน session เดิมด้วยเสมอ**
(เจอจริงใน `agents/orchestrator.py:_split_messages_for_gemini`, แก้ commit `138172b`)

## 5. เช็ค signature SDK local ก่อนเดา
```bash
python3 -c "from google.genai import types; import inspect; print(inspect.signature(types.Part.from_text))"
```
