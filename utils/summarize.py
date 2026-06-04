"""Document Summarization — Map-Reduce ด้วย DeepSeek-R1 (LMStudio) หรือ Ollama fallback

Flow:
  text ยาว
    → chunk_text() ตัดเป็นท่อนๆ
    → MAP: สรุปแต่ละ chunk ด้วย local model
    → REDUCE: รวม summaries เป็น final summary
"""
import os
import logging
from openai import OpenAI

logger = logging.getLogger(__name__)

_LMSTUDIO_BASE_URL = os.getenv("LMSTUDIO_BASE_URL", "")
_LMSTUDIO_API_KEY  = os.getenv("LMSTUDIO_API_KEY", "lmstudio")
_LMSTUDIO_REASON_MODEL = os.getenv("LMSTUDIO_REASON_MODEL", "deepseek/deepseek-r1-0528-qwen3-8b")
_LMSTUDIO_TIMEOUT  = int(os.getenv("LMSTUDIO_TIMEOUT", "180"))

_OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
_OLLAMA_MODEL    = os.getenv("OLLAMA_MODEL", "llama3")

_CHUNK_SIZE = 3000   # chars ต่อ chunk
_MAX_TOKENS = 1024   # tokens ต่อ summary


def _get_client() -> tuple[OpenAI, str]:
    """คืน (client, model) — LMStudio ก่อน fallback Ollama"""
    if _LMSTUDIO_BASE_URL:
        return (
            OpenAI(base_url=_LMSTUDIO_BASE_URL, api_key=_LMSTUDIO_API_KEY, timeout=_LMSTUDIO_TIMEOUT),
            _LMSTUDIO_REASON_MODEL,
        )
    return (
        OpenAI(base_url=_OLLAMA_BASE_URL, api_key="ollama", timeout=120),
        _OLLAMA_MODEL,
    )


def _call_gemini(system: str, user: str) -> str:
    """fallback — เรียก Gemini ถ้า local model ต่อไม่ได้"""
    gemini_key = os.getenv("GEMINI_API_KEY", "")
    if not gemini_key:
        return ""
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=gemini_key)
        model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        resp = client.models.generate_content(
            model=model,
            contents=f"{system}\n\n{user}",
            config=types.GenerateContentConfig(max_output_tokens=_MAX_TOKENS * 2, temperature=0.3),
        )
        return (resp.text or "").strip()
    except Exception as e:
        logger.warning(f"[Summarize] Gemini fallback failed: {e}")
        return ""


def _call_llm(client: OpenAI, model: str, system: str, user: str) -> str:
    """เรียก LLM แบบ non-streaming — local model ก่อน fallback Gemini"""
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=_MAX_TOKENS,
            temperature=0.3,
        )
        result = (resp.choices[0].message.content or "").strip()
        if result:
            return result
    except Exception as e:
        logger.warning(f"[Summarize] local LLM failed: {e} → fallback Gemini")
    return _call_gemini(system, user)


def chunk_text(text: str, chunk_size: int = _CHUNK_SIZE) -> list[str]:
    """ตัดข้อความเป็น chunks — พยายามตัดที่จบประโยค"""
    if len(text) <= chunk_size:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        if end < len(text):
            # หาจุดตัดที่ดีกว่า — จบย่อหน้า หรือจบประโยค
            for sep in ("\n\n", "\n", "。", ".", " "):
                pos = text.rfind(sep, start, end)
                if pos > start:
                    end = pos + len(sep)
                    break
        chunks.append(text[start:end].strip())
        start = end
    return [c for c in chunks if c]


def summarize_chunk(chunk: str, client: OpenAI, model: str, chunk_idx: int, total: int) -> str:
    """MAP — สรุป chunk เดียว"""
    system = (
        "คุณเป็นผู้เชี่ยวชาญด้านการสรุปเอกสาร "
        "สรุปเนื้อหาอย่างกระชับ ครอบคลุมประเด็นสำคัญ ไม่ตัดข้อมูลสำคัญออก "
        "ตอบเป็นภาษาเดียวกับเอกสาร"
    )
    user = (
        f"[ส่วนที่ {chunk_idx + 1}/{total}]\n\n"
        f"{chunk}\n\n"
        "สรุปเนื้อหาส่วนนี้ในรูปแบบ bullet points:"
    )
    result = _call_llm(client, model, system, user)
    logger.info(f"[Summarize] chunk {chunk_idx + 1}/{total} → {len(result)} chars")
    return result or f"[ส่วนที่ {chunk_idx + 1}: ไม่สามารถสรุปได้]"


def reduce_summaries(summaries: list[str], client: OpenAI, model: str,
                     filename: str = "", summary_type: str = "general") -> str:
    """REDUCE — รวม chunk summaries เป็น final summary"""
    combined = "\n\n---\n\n".join(
        f"[ส่วนที่ {i + 1}]\n{s}" for i, s in enumerate(summaries)
    )

    type_instruction = {
        "general": "สรุปภาพรวมครอบคลุมทุกประเด็นสำคัญ",
        "legal":   "เน้น: คู่สัญญา, ข้อกำหนด, วันที่, ค่าใช้จ่าย, เงื่อนไขพิเศษ",
        "financial": "เน้น: ตัวเลข, งบประมาณ, รายได้/รายจ่าย, แนวโน้ม",
        "academic": "เน้น: วัตถุประสงค์, วิธีการ, ผลลัพธ์, ข้อสรุป",
    }.get(summary_type, "สรุปภาพรวมครอบคลุมทุกประเด็นสำคัญ")

    system = (
        "คุณเป็นผู้เชี่ยวชาญด้านการสรุปเอกสาร "
        "รวมสรุปย่อยหลายส่วนให้เป็นสรุปเดียวที่สอดคล้องกัน ไม่ซ้ำซ้อน "
        "ตอบเป็นภาษาเดียวกับเอกสาร"
    )
    user = (
        f"เอกสาร: {filename}\n\n"
        f"นี่คือสรุปแต่ละส่วนของเอกสาร:\n\n{combined}\n\n"
        f"กรุณา{type_instruction} โดยจัดเป็นหัวข้อชัดเจน:"
    )
    return _call_llm(client, model, system, user)


def summarize_document(
    text: str,
    filename: str = "document",
    summary_type: str = "general",
    chunk_size: int = _CHUNK_SIZE,
) -> dict:
    """API หลัก — รับ text คืน {summary, chunks_count, model, provider}

    summary_type: general | legal | financial | academic
    """
    client, model = _get_client()
    provider = "lmstudio" if _LMSTUDIO_BASE_URL else "ollama"
    logger.info(f"[Summarize] '{filename}' ({len(text)} chars) via {provider}/{model}")

    chunks = chunk_text(text, chunk_size)
    logger.info(f"[Summarize] {len(chunks)} chunks")

    if len(chunks) == 1:
        # เอกสารสั้น — สรุปตรงเลย ไม่ต้อง map-reduce
        summary = summarize_chunk(chunks[0], client, model, 0, 1)
    else:
        # MAP
        chunk_summaries = [
            summarize_chunk(c, client, model, i, len(chunks))
            for i, c in enumerate(chunks)
        ]
        # REDUCE
        summary = reduce_summaries(chunk_summaries, client, model,
                                   filename=filename, summary_type=summary_type)

    return {
        "ok": True,
        "filename": filename,
        "summary": summary,
        "chunks_count": len(chunks),
        "chars_total": len(text),
        "model": model,
        "provider": provider,
        "summary_type": summary_type,
    }
