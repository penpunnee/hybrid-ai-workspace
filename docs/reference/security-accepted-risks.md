# ความเสี่ยงที่ยอมรับไว้ (accepted risk) — pip-audit

ช่องโหว่ใน `requirements.lock` ที่**ตั้งใจยังไม่ bump** พร้อมเหตุผล · ปอยเคาะ 2026-10-07
· รัน `uvx pip-audit -r requirements.lock --no-deps --disable-pip` แล้วเจอรายการในตารางนี้ = ปกติ
· **เจอรายการที่ไม่อยู่ในตาราง = ของใหม่ ต้องประเมิน**

| แพ็กเกจ | เวอร์ชันใน lock | ช่องโหว่ | เวอร์ชันที่แก้ | ทำไมยังไม่ bump | ทบทวนเมื่อ |
|---|---|---|---|---|---|
| cryptography | 49.0.0 | PYSEC-2026-3552 (GHSA-g6cj-pr64-35w5) — `pkcs7_decrypt_der/pem/smime` บอกผลถอดรหัสผิดแบบที่รั่วข้อมูลได้ | 50.0.0 (major) | แอปไม่เรียก PKCS#7 decrypt เลย (ใช้ผ่าน google-auth + PyJWT เท่านั้น) · bump major ต้องเทส Gemini auth/JWT ใหม่ทั้งเส้น ไม่คุ้มกับความเสี่ยงที่แทบเป็นศูนย์ | มีโค้ดเรียก `pkcs7` · google-auth/PyJWT บังคับ ≥50 · หรือมี CVE ใหม่ของ 49.x |
| oauthlib | 3.3.1 | PYSEC-2026-4114 (CVE-2026-49265) — timing side-channel ใน PKCE ฝั่ง authorization server | 4.0.0 (major) | มาทางสาย chromadb → kubernetes → requests-oauthlib · เราไม่ได้รัน OAuth authorization server · โค้ดเราไม่ได้ import | เริ่มใช้ oauthlib ตรงๆ · มี CVE ฝั่ง client |
| chromadb | 1.5.9 | PYSEC-2026-311 · -3813 · -3814 · -3815 — code injection ผ่าน `trust_remote_code` + RBAC/tenant ข้ามกันได้ | ยังไม่มี | **ช่องโหว่อยู่ฝั่งเซิร์ฟเวอร์** ส่วนแพ็กเกจใน backend เป็นแค่ client · เซิร์ฟเวอร์จริงคือคอนเทนเนอร์ `chromadb` (อิมเมจ pin digest · `/api/v2/version` = `1.0.0`) ⚠️ ยังไม่ยืนยันว่า CVE ใช้กับอิมเมจนั้นด้วยหรือเปล่า · ⚠️ ปัญหาที่ใหญ่กว่าคือพอร์ต `8000` เปิดใน LAN แบบไม่มี auth → ปอยเลือกทาง (ข) ปิดพอร์ต · สืบผู้ใช้พอร์ตก่อนแก้ (devlog 10-07) | มีเวอร์ชันที่แก้แล้ว · หรือปิดพอร์ต 8000 เสร็จ (ให้แก้แถวนี้) |

## ที่ bump ไปแล้ว (บันทึกไว้กันสับสน)
- 2026-10-07 `1a95b72`: pypdf 6.19.0 · PyJWT 2.15.1
- 2026-10-07: urllib3 2.8.0 (สำคัญสุด — `utils/urlguard.py` stream หน้าเว็บภายนอก) · aiohttp 3.14.3 · multidict 6.9.1 · anyio 4.14.2 · pyasn1 0.6.4 · **ลบ h2 ออกจาก lock**
  ⚠️ เหตุผลตอนลบ ("ไม่มีแพ็กเกจไหนดึง") **ผิด**: `ddgs` → `httpx[brotli,http2,socks]` → h2
  (`uv pip show` ไม่แสดงการดึงผ่าน extra) ⇒ h2 ยังถูกติดตั้งแต่**ไม่ได้ pin** ตอนนี้ได้ 4.4.1 (ตัวที่แก้แล้ว · ตรวจในอิมเมจ prod 10-07)
  · ปอยเคาะ 10-07 → **pin `h2==4.4.1` กลับเข้า lock แล้ว** (ตรงกับที่อิมเมจ prod ลงอยู่ · ไม่ต้อง rebuild)
  · เช็คว่าใครดึงแพ็กเกจไหนให้ไล่ `importlib.metadata` `requires` **รวม extra** ไม่ใช่ `Required-by`
