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
            return f"[PDF: {filename} — {len(reader.pages)} หน้า]\n" + "\n\n".join(pages)
        except ImportError:
            raise HTTPException(415, "ไม่พบ library pypdf (pip install pypdf)")
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
        raw = await file.read()
        if len(raw) > _MAX_BYTES:
            raise HTTPException(413, f"file too large (>{_MAX_BYTES} bytes)")
        content = _decode_bytes(raw, file.filename or "upload")
        src = source or file.filename or "upload"
        meta = {"content_type": file.content_type or "", "size": len(raw)}
        return index_document(content, source=src, metadata=meta)

    # Path B: JSON {source, content}
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "expected multipart file or JSON body")

    content = (data.get("content") or "").strip()
    src = (data.get("source") or "").strip()
    if not content or not src:
        raise HTTPException(400, "fields 'source' and 'content' required")
    if len(content.encode("utf-8")) > _MAX_BYTES:
        raise HTTPException(413, f"content too large (>{_MAX_BYTES} bytes)")
    meta = data.get("metadata") or {}
    return index_document(content, source=src, metadata=meta if isinstance(meta, dict) else {})


@router.get("")
def list_all():
    """list documents ที่ index ไว้ — group by source"""
    return {"documents": list_documents()}


@router.post("/search")
async def search(request: Request):
    """semantic search — body: {query, top_k?, source?}"""
    data = await request.json()
    query = (data.get("query") or "").strip()
    if not query:
        raise HTTPException(400, "field 'query' required")
    top_k = int(data.get("top_k", 5))
    source = data.get("source") or None
    results = retrieve_chunks(query, top_k=top_k, source_filter=source)
    return {"query": query, "results": results, "count": len(results)}


@router.delete("/{source:path}")
def delete(source: str):
    """ลบ document ทั้งก้อนตาม source"""
    ok = delete_document(source)
    if not ok:
        raise HTTPException(500, "delete failed (ChromaDB unavailable?)")
    return {"ok": True, "source": source}
