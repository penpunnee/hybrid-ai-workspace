# Anti-Hallucination บนโมเดล Local เล็ก (llama3/llama-3.1-8b)

บทเรียนจริงจาก session 2026-05-31 — แก้เคส "ขวัญกุผล ping/อุปกรณ์บ้าน" ที่ลึกถึง 4 ชั้น

## อาการ
ถาม "ping เช็ค router/NAS" → โมเดลตอบ `Reply from 192.168.51.49 Time<1ms`, `Router 10ms`
ทั้งที่**ไม่ได้ ping จริง** — ตัวเลข/IP/อุปกรณ์ (Archer C7, DS918+) กุล้วนๆ

## Root cause (มี 3 รูปแบบ ซ้อนกัน)
1. **สถาปัตยกรรมแบบ "เล่า" (narration)** — ระบบฉีดข้อมูลเป็น *ข้อความ* เข้า context แล้วให้โมเดล
   เรียบเรียงเป็นคำตอบ → โมเดลเป็นคน "พิมพ์" ผลลัพธ์เอง → กุได้เสมอ (guard ได้แค่ *ลด*)
2. **system prompt อันตราย** — เดิมสั่ง "ไม่เคยปฏิเสธ ไม่บอกว่าทำไม่ได้" → ดันโมเดลให้แต่งแทนยอมรับ
3. **feedback loop ปนเปื้อน** — คำตอบกุถูก **auto-save เป็น lesson** → recall กลับมา prime กุซ้ำ
   (เจอ lessons ปนเปื้อน 8/13 จากบทสนทนา+เทสเก่า) → **self-learning ที่ไม่มี gate = ยิ่งใช้ยิ่งโง่**

## วิธีแก้ — 4 ชั้น (จากอ่อน→แรง)
| ชั้น | ที่อยู่ | ทำอะไร |
|---|---|---|
| 1. system prompt guard | `assistants/config.py:_NO_FABRICATION` | ห้ามแต่งข้อมูล real-time ทุกผู้ช่วย (อยู่ไกล attention) |
| 2. tool-adjacent guard | `utils/home_tools.py:_TOOL_GUARD` + `_join_with_guard()` | แนบกติกา **ติดท้ายข้อมูลที่ฉีด** (ใกล้ attention กว่ามาก) |
| 3. quality gate | `reasoning/learn_gate.py:should_auto_learn()` | กัน auto-learn บันทึก negative_feedback/realtime → ตัด loop |
| 4. **ข้อมูลจริง** | `utils/home_tools.py:ping_network` | ping จริง แทนให้โมเดลเดา ← **ได้ผลที่สุด** |

## ⚠️ เพดาน — prompt-based ปิดไม่ได้ 100%
หลังครบ 4 ชั้น: ข้อเท็จจริงถูกต้องแล้ว (Router/NAS online ตรงจริง) แต่โมเดลเล็ก**ยังหลุด**
(โชว์คำสั่ง `ping -c 3`, ตอบปนอังกฤษ, บางทีไม่ใช้ข้อมูลที่ป้อน) — **เพราะมันเป็นโมเดล "completion"**

### ทางปิดสนิท = เปลี่ยนสถาปัตยกรรม narration → execution
```
narration (ตอนนี้):  ข้อมูลจริง → ฉีด text → [โมเดลเล่า]      ← กุได้
execution (Agent):   [โมเดลเรียก tool] → ระบบรันจริง → โชว์ผลดิบ → [โมเดลสรุปสั้น]  ← กุไม่ได้
```
ความจริงมาจาก **การ execute tool** ไม่ใช่การพิมพ์ → โมเดลกุไม่ได้
**✅ ทำแล้ว:** wire home tools เข้า `agents/tools.py:TOOL_REGISTRY` แล้ว —
`nas_disk`/`nas_docker`/`ping_network`/`ping_device`/`wol_pc` (Agent mode รันจริง โชว์ผลดิบ)

## วิธี debug ที่ได้ผล
- **verify บน production จริงด้วย ground truth** — ยิง `/api/chat` ตรง (LAN bypass auth)
  แล้วเทียบกับผลจริง (`nc -z <ip> <port>`). อย่าเชื่อว่า "deploy แล้ว=แก้แล้ว" ต้องยิงเทสจริง
- การ verify นี่แหละทำให้เจอ 3 ชั้นที่ซ่อนอยู่ (ถ้าไม่เทสจะคิดว่าแค่ prompt ก็จบ)

## หลักการพกพา (เอาไปใช้ที่อื่นได้)
1. โมเดลเล็ก + ข้อมูล real-time = **ป้อนข้อมูลจริง** อย่าหวัง guard อย่างเดียว
2. guard ที่ได้ผล = วาง**ใกล้จุดที่อยากคุม** (ติดข้อมูล) ไม่ใช่ system prompt ที่อยู่ไกล
3. self-learning **ต้องมี quality gate** เสมอ ไม่งั้นปนเปื้อนสะสม
4. งานต้องการความถูกต้องเป๊ะ → ใช้ **tool execution (Agent)** ไม่ใช่ให้โมเดลเล่า
