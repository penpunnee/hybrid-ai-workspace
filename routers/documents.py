"""Documents API — upload, list, search, delete

Endpoints:
  POST   /api/documents/upload   — upload file (multipart) หรือ raw text (JSON)
  GET    /api/documents          — list documents ที่ index ไว้
  POST   /api/documents/search   — semantic search ใน documents (debug/UI)
  DELETE /api/documents/{source} — ลบ document
"""
import logging
from fastapi import APIRouter, Request, UploadFile, File, Form, HTTPException

from utils.documents import (
    index_document, retrieve_chunks, list_documents, delete_document,
)
from utils.summarize import summarize_document
from utils.ocr import ocr_pdf, ocr_image
from starlette.concurrency import run_in_threadpool

from utils.http_limits import read_capped, json_body_capped

router = APIRouter(prefix="/api/documents", tags=["documents"])
logger = logging.getLogger(__name__)


_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_ALLOWED_EXT = {
    ".txt", ".md", ".json", ".py", ".html", ".csv", ".log",
    ".pdf", ".docx", ".xlsx", ".xls",
}


def _decode_bytes(raw: bytes, filename: str) -> str:
    """decode bytes → text รองรับ PDF / DOCX / XLSX / text"""
    import io
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""

    if ext == ".pdf":
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(raw))
            pages = [p.extract_text() or "" for p in reader.pages]
            text = "\n\n".join(pages).strip()
            # ถ้าไม่มีข้อความ (PDF scan) → ใช้ OCR
            if not text:
                logger.info(f"[Documents] PDF scan detected → OCR: {filename}")
                result = ocr_pdf(raw, filename=filename)
                if not result.get("ok"):
                    raise HTTPException(422, result.get("error", "OCR ล้มเหลว"))
                return f"[PDF scan: {filename} — {result['pages']} หน้า (OCR via {result['provider']})]\n{result['text']}"
            return f"[PDF: {filename} — {len(reader.pages)} หน้า]\n{text}"
        except ImportError:
            raise HTTPException(415, "ไม่พบ library pypdf (pip install pypdf)")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(422, f"อ่าน PDF ไม่ได้: {e}")

    if ext == ".docx":
        try:
            import docx
            doc = docx.Document(io.BytesIO(raw))
            text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            return f"[DOCX: {filename}]\n{text}"
        except ImportError:
            raise HTTPException(415, "ไม่พบ library python-docx (pip install python-docx)")
        except Exception as e:
            raise HTTPException(422, f"อ่าน DOCX ไม่ได้: {e}")

    if ext in (".xlsx", ".xls"):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
            parts = []
            for sheet in wb.worksheets:
                rows = []
                for row in sheet.iter_rows(values_only=True):
                    cells = [str(c) if c is not None else "" for c in row]
                    if any(cells):
                        rows.append("\t".join(cells))
                if rows:
                    parts.append(f"[Sheet: {sheet.title}]\n" + "\n".join(rows))
            return f"[Excel: {filename}]\n" + "\n\n".join(parts)
        except ImportError:
            raise HTTPException(415, "ไม่พบ library openpyxl (pip install openpyxl)")
        except Exception as e:
            raise HTTPException(422, f"อ่าน Excel ไม่ได้: {e}")

    # text-based files
    for enc in ("utf-8", "utf-8-sig", "tis-620", "cp874", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


@router.post("/upload")
async def upload(
    request: Request,
    file: UploadFile | None = File(None),
    source: str | None = Form(None),
):
    """รับไฟล์ (multipart) หรือ raw text (JSON {source, content})"""
    # Path A: multipart file
    if file is not None:
        ext = "." + (file.filename or "").rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else ""
        if ext and ext not in _ALLOWED_EXT:
            raise HTTPException(415, f"unsupported file extension: {ext}")
        raw = await read_capped(file, _MAX_BYTES)
        content = await run_in_threadpool(_decode_bytes, raw, file.filename or "upload")
        src = source or file.filename or "upload"
        meta = {"content_type": file.content_type or "", "size": len(raw)}
        return await run_in_threadpool(index_document, content, source=src, metadata=meta)

    # Path B: JSON {source, content}
    data = await json_body_capped(request, _MAX_BYTES)

    content = (data.get("content") or "").strip()
    src = (data.get("source") or "").strip()
    if not content or not src:
        raise HTTPException(400, "fields 'source' and 'content' required")
    if len(content.encode("utf-8")) > _MAX_BYTES:
        raise HTTPException(413, f"content too large (>{_MAX_BYTES} bytes)")
    meta = data.get("metadata") or {}
    return await run_in_threadpool(index_document, content, source=src,
                                   metadata=meta if isinstance(meta, dict) else {})


@router.get("")
def list_all():
    """list documents ที่ index ไว้ — group by source"""
    return {"documents": list_documents()}


@router.post("/search")
async def search(request: Request):
    """semantic search — body: {query, top_k?, source?}"""
    data = await json_body_capped(request, _MAX_BYTES)
    query = (data.get("query") or "").strip()
    if not query:
        raise HTTPException(400, "field 'query' required")
    top_k = int(data.get("top_k", 5))
    source = data.get("source") or None
    results = await run_in_threadpool(retrieve_chunks, query, top_k=top_k, source_filter=source)
    return {"query": query, "results": results, "count": len(results)}


@router.post("/ocr")
async def ocr_endpoint(
    request: Request,
    file: UploadFile | None = File(None),
):
    """OCR PDF scan หรือรูปภาพ → คืนข้อความ

    รองรับ: .pdf .jpg .jpeg .png .webp
    """
    _OCR_EXT = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}
    if file is None:
        raise HTTPException(400, "field 'file' required")
    ext = ("." + (file.filename or "").rsplit(".", 1)[-1].lower()) if "." in (file.filename or "") else ""
    if ext not in _OCR_EXT:
        raise HTTPException(415, f"รองรับเฉพาะ: {', '.join(_OCR_EXT)}")
    raw = await read_capped(file, _MAX_BYTES)
    filename = file.filename or "upload"

    if ext == ".pdf":
        result = await run_in_threadpool(ocr_pdf, raw, filename=filename)
    else:
        result = await run_in_threadpool(ocr_image, raw, filename=filename)

    if not result.get("ok"):
        raise HTTPException(422, result.get("error", "OCR ล้มเหลว"))
    return result


@router.post("/summarize")
async def summarize(request: Request):
    """สรุปเอกสารด้วย DeepSeek-R1 (Map-Reduce)

    Body (multipart): file=<ไฟล์>, summary_type=general|legal|financial|academic
    Body (JSON): {source, content, summary_type}
    """
    content_type = request.headers.get("content-type", "")

    if "multipart" in content_type:
        form = await request.form()
        file = form.get("file")
        summary_type = str(form.get("summary_type", "general"))
        if not file or not hasattr(file, "read"):
            raise HTTPException(400, "field 'file' required")
        raw = await read_capped(file, _MAX_BYTES)
        filename = getattr(file, "filename", "document") or "document"
        text = await run_in_threadpool(_decode_bytes, raw, filename)
    else:
        data = await json_body_capped(request, _MAX_BYTES)
        text = (data.get("content") or "").strip()
        filename = (data.get("source") or "document").strip()
        summary_type = (data.get("summary_type") or "general").strip()
        if not text:
            raise HTTPException(400, "field 'content' required")

    if not text.strip():
        raise HTTPException(422, "ไม่พบข้อความในเอกสาร")

    result = await run_in_threadpool(summarize_document, text,
                                     filename=filename, summary_type=summary_type)
    return result


@router.delete("/{source:path}")
def delete(source: str):
    """ลบ document ทั้งก้อนตาม source"""
    ok = delete_document(source)
    if not ok:
        raise HTTPException(500, "delete failed (ChromaDB unavailable?)")
    return {"ok": True, "source": source}
