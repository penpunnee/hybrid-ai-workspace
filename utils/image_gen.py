"""Image Generation — สร้างรูปด้วย Gemini (gemini-2.5-flash-image)

Flow:
  user พิมพ์ "วาดรูป..." ใน chat
  → detect_image_request() จับ intent
  → generate_image() เรียก Gemini → ได้ PNG bytes
  → เซฟลง GEN_IMAGE_DIR (เสิร์ฟผ่าน /gen/<file>)
  → chat ตอบเป็น markdown ![..](/gen/xxx.png) — React render + persist ลง history

ปิด/เปิด: ใช้ GEMINI_API_KEY เดิม (ไม่มี key = แจ้งผู้ใช้ตรงๆ)
"""
import logging
import os
import re
import time
import uuid

from core.config import NAS_DATA_PATH

logger = logging.getLogger(__name__)

IMAGE_GEN_MODEL = os.getenv("IMAGE_GEN_MODEL", "gemini-2.5-flash-image")
GEN_IMAGE_DIR = os.path.join(NAS_DATA_PATH, "gen_images")

# จับเฉพาะ "คำสั่งให้สร้าง/วาดรูป" — ระวัง false positive:
#   "ภาพรวม" (overview), "รูปแบบ" (format), "ถามถึงรูปที่ส่งมา"
_IMAGE_INTENT = re.compile(
    r"วาดรูป|วาดภาพ|วาดให้|ช่วยวาด"
    r"|สร้างรูป|สร้างภาพ(?!รวม)|ทำรูป(?!แบบ)|ทำภาพ(?!รวม)"
    r"|ออกแบบโลโก้|ออกแบบโปสเตอร์|ทำโปสเตอร์"
    r"|generate\s+(?:an?\s+)?image|draw\s+(?:me\s+)?(?:a\s+)?(?:picture|image)"
    r"|text.?to.?image",
    re.IGNORECASE,
)


def detect_image_request(prompt: str) -> bool:
    """True ถ้า prompt เป็นคำสั่งให้สร้าง/วาดรูป"""
    if not prompt:
        return False
    return bool(_IMAGE_INTENT.search(prompt))


def _get_client():
    """Gemini client จาก utils.llm (single source — ใช้ GEMINI_API_KEY เดียวกัน)"""
    try:
        from utils.llm import gemini_client
        return gemini_client
    except Exception as e:  # SDK ไม่มี/หาย
        logger.warning(f"[ImageGen] gemini client unavailable: {e}")
        return None


def generate_image(prompt: str, image_b64: str = "", image_mime: str = "image/png") -> dict:
    """สร้างรูปจาก prompt (แนบ image_b64 = แก้รูปเดิม / image-to-image)

    Returns:
        {"ok": True, "url": "/gen/<file>.png", "text": "<คำบรรยายจากโมเดล>"}
        {"ok": False, "error": "<เหตุผล>"}
    """
    client = _get_client()
    if client is None:
        return {"ok": False,
                "error": "ยังไม่ได้ตั้งค่า GEMINI_API_KEY — สร้างรูปไม่ได้ (เปิด .env แล้วใส่ key)"}

    try:
        contents: list = [prompt]
        if image_b64:
            import base64
            from google.genai import types
            contents.append(types.Part(inline_data=types.Blob(
                data=base64.b64decode(image_b64), mime_type=image_mime or "image/png")))

        resp = client.models.generate_content(model=IMAGE_GEN_MODEL, contents=contents)

        img_bytes, caption = b"", ""
        for part in (resp.candidates[0].content.parts or []):
            if getattr(part, "inline_data", None) and getattr(part.inline_data, "data", None):
                img_bytes = part.inline_data.data
            elif getattr(part, "text", None):
                caption += part.text

        if not img_bytes:
            return {"ok": False,
                    "error": caption or "โมเดลไม่คืนรูปกลับมา ลองปรับ prompt ใหม่"}

        os.makedirs(GEN_IMAGE_DIR, exist_ok=True)
        fname = f"gen_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.png"
        path = os.path.join(GEN_IMAGE_DIR, fname)
        with open(path, "wb") as f:
            f.write(img_bytes)
        logger.info(f"[ImageGen] saved {fname} ({len(img_bytes)} bytes) model={IMAGE_GEN_MODEL}")
        return {"ok": True, "url": f"/gen/{fname}", "text": caption.strip()}

    except Exception as e:
        err = str(e)
        logger.error(f"[ImageGen] failed: {err}")
        if "429" in err or "quota" in err.lower() or "resource_exhausted" in err.lower():
            # limit: 0 = free tier ไม่มีโควต้าให้โมเดลนี้เลย (ไม่ใช่หมดชั่วคราว) — retry ไม่ช่วย
            if "limit: 0" in err:
                return {"ok": False,
                        "error": "โมเดลสร้างรูปไม่เปิดให้ใช้บน free tier (quota limit=0) — "
                                 "ต้องเปิด billing บนโปรเจกต์ Google AI ก่อนถึงจะใช้ได้ค่ะ"}
            return {"ok": False, "error": "Gemini quota หมดชั่วคราว — ลองใหม่ภายหลังนะคะ"}
        return {"ok": False, "error": f"สร้างรูปไม่สำเร็จ: {err[:200]}"}
