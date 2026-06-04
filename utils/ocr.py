"""OCR — แปลง PDF scan / รูปภาพ → ข้อความ ด้วย Vision LLM (Gemini / LMStudio)

Flow:
  PDF scan / รูปภาพ
    → แปลงเป็น PNG ทีละหน้า (pdf2image)
    → ส่ง base64 ให้ Vision LLM อ่าน
    → รวมข้อความทุกหน้า → คืนกลับ
"""
import os
import base64
import logging
import io
from typing import Generator

logger = logging.getLogger(__name__)

GEMINI_API_KEY  = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL    = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

_LMSTUDIO_BASE_URL    = os.getenv("LMSTUDIO_BASE_URL", "")
_LMSTUDIO_API_KEY     = os.getenv("LMSTUDIO_API_KEY", "lmstudio")
_LMSTUDIO_VISION_MODEL = os.getenv("LMSTUDIO_VISION_MODEL", "llama-3.2-11b-vision-instruct")
_LMSTUDIO_TIMEOUT     = int(os.getenv("LMSTUDIO_TIMEOUT", "180"))

_OCR_PROMPT = (
    "คุณเป็นระบบ OCR ที่แม่นยำสูง "
    "อ่านข้อความทั้งหมดในรูปภาพนี้ให้ครบถ้วน รวมถึงตาราง หัวข้อ เนื้อหา และตัวเลข "
    "คงรูปแบบและโครงสร้างต้นฉบับให้ใกล้เคียงที่สุด "
    "ถ้ามีตาราง ให้จัดรูปแบบเป็น markdown table "
    "ตอบเฉพาะข้อความที่อ่านได้เท่านั้น ห้ามอธิบายเพิ่มเติม"
)


def _pdf_to_images(pdf_bytes: bytes, dpi: int = 200) -> list[bytes]:
    """แปลง PDF → list of PNG bytes ทีละหน้า"""
    try:
        from pdf2image import convert_from_bytes
        images = convert_from_bytes(pdf_bytes, dpi=dpi, fmt="png")
        result = []
        for img in images:
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            result.append(buf.getvalue())
        logger.info(f"[OCR] pdf→images: {len(result)} หน้า")
        return result
    except ImportError:
        raise RuntimeError("ไม่พบ library pdf2image (pip install pdf2image)")
    except Exception as e:
        raise RuntimeError(f"แปลง PDF เป็นรูปไม่ได้: {e}")


def _ocr_with_gemini(image_bytes: bytes, page_num: int) -> str:
    """ส่งรูปให้ Gemini Vision อ่านข้อความ"""
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=GEMINI_API_KEY)
        img_b64 = base64.b64encode(image_bytes).decode()
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                types.Content(role="user", parts=[
                    types.Part(text=_OCR_PROMPT),
                    types.Part(inline_data=types.Blob(
                        data=base64.b64decode(img_b64),
                        mime_type="image/png",
                    )),
                ])
            ],
            config=types.GenerateContentConfig(
                max_output_tokens=4096,
                temperature=0.1,
            ),
        )
        text = response.text or ""
        logger.info(f"[OCR] Gemini หน้า {page_num}: {len(text)} chars")
        return text.strip()
    except Exception as e:
        logger.warning(f"[OCR] Gemini หน้า {page_num} failed: {e}")
        return ""


def _ocr_with_lmstudio(image_bytes: bytes, page_num: int) -> str:
    """ส่งรูปให้ LMStudio Vision อ่านข้อความ"""
    try:
        from openai import OpenAI
        client = OpenAI(
            base_url=_LMSTUDIO_BASE_URL,
            api_key=_LMSTUDIO_API_KEY,
            timeout=_LMSTUDIO_TIMEOUT,
        )
        img_b64 = base64.b64encode(image_bytes).decode()
        resp = client.chat.completions.create(
            model=_LMSTUDIO_VISION_MODEL,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": _OCR_PROMPT},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/png;base64,{img_b64}"
                    }},
                ],
            }],
            max_tokens=4096,
            temperature=0.1,
        )
        text = (resp.choices[0].message.content or "").strip()
        logger.info(f"[OCR] LMStudio หน้า {page_num}: {len(text)} chars")
        return text
    except Exception as e:
        logger.warning(f"[OCR] LMStudio หน้า {page_num} failed: {e}")
        return ""


def _ocr_page(image_bytes: bytes, page_num: int) -> str:
    """OCR หน้าเดียว — Gemini ก่อน fallback LMStudio"""
    if GEMINI_API_KEY:
        text = _ocr_with_gemini(image_bytes, page_num)
        if text:
            return text
    if _LMSTUDIO_BASE_URL:
        return _ocr_with_lmstudio(image_bytes, page_num)
    raise RuntimeError("ไม่มี Vision LLM — ต้องตั้ง GEMINI_API_KEY หรือ LMSTUDIO_BASE_URL")


def ocr_pdf(pdf_bytes: bytes, filename: str = "document.pdf", dpi: int = 200) -> dict:
    """OCR PDF ทั้งไฟล์ → คืน {text, pages, filename, provider}

    Args:
        pdf_bytes: raw bytes ของ PDF
        filename: ชื่อไฟล์ (สำหรับ log)
        dpi: ความละเอียดรูป (150=เร็ว, 200=สมดุล, 300=แม่น)
    """
    provider = "gemini" if GEMINI_API_KEY else "lmstudio"
    logger.info(f"[OCR] เริ่ม OCR '{filename}' via {provider} (dpi={dpi})")

    images = _pdf_to_images(pdf_bytes, dpi=dpi)
    if not images:
        return {"ok": False, "error": "แปลง PDF เป็นรูปไม่ได้", "text": ""}

    page_texts = []
    for i, img in enumerate(images):
        text = _ocr_page(img, page_num=i + 1)
        page_texts.append(f"=== หน้า {i + 1} ===\n{text}" if text else f"=== หน้า {i + 1} === [ไม่พบข้อความ]")

    full_text = "\n\n".join(page_texts)
    logger.info(f"[OCR] เสร็จ: {len(images)} หน้า, {len(full_text)} chars")

    return {
        "ok": True,
        "filename": filename,
        "text": full_text,
        "pages": len(images),
        "chars": len(full_text),
        "provider": provider,
    }


def ocr_image(image_bytes: bytes, filename: str = "image.png") -> dict:
    """OCR รูปภาพเดียว (JPG/PNG) → คืน {text, filename, provider}"""
    provider = "gemini" if GEMINI_API_KEY else "lmstudio"
    logger.info(f"[OCR] รูปภาพ '{filename}' via {provider}")
    text = _ocr_page(image_bytes, page_num=1)
    return {
        "ok": bool(text),
        "filename": filename,
        "text": text,
        "provider": provider,
    }
