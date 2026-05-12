import os
from datetime import datetime
from fastapi import APIRouter, Request, UploadFile, File

from utils.skills import (
    get_skill_count, auto_extract_skills, _load_skills_db, _save_skills_db,
    search_skills, cleanup_junk_skills,
)
from utils.llm import stream_response

router = APIRouter(prefix="/api", tags=["skills"])


@router.get("/skills")
def list_skills():
    db = _load_skills_db()
    skills_dir = os.path.join(os.path.dirname(__file__), "..", "skills")
    md_files = [f for f in os.listdir(skills_dir) if f.endswith(".md")] if os.path.isdir(skills_dir) else []
    chroma_count = get_skill_count()
    return {"skills": db, "count": len(db), "md_files": len(md_files), "chroma_count": chroma_count}


@router.get("/skills/list")
def skills_list():
    skills_dir = os.path.join(os.path.dirname(__file__), "..", "skills")
    if not os.path.isdir(skills_dir):
        return {"files": []}
    files = [
        {"name": f, "size": os.path.getsize(os.path.join(skills_dir, f))}
        for f in sorted(os.listdir(skills_dir))
        if os.path.isfile(os.path.join(skills_dir, f)) and f.endswith(".md")
    ]
    return {"files": files}


@router.post("/skills/extract")
async def skills_extract(request: Request):
    import logging
    logger = logging.getLogger(__name__)
    data = await request.json()
    content = data.get("content", "").strip()
    topic = data.get("topic", "").strip()
    if not content:
        return {"ok": False, "error": "ไม่มี content"}
    if not topic:
        topic = f"skill-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    safe_topic = "".join(c if c.isalnum() or c in "-_" else "-" for c in topic.lower()).strip("-")
    filename = f"{safe_topic}.md"
    skills_dir = os.path.join(os.path.dirname(__file__), "..", "skills")
    os.makedirs(skills_dir, exist_ok=True)
    filepath = os.path.join(skills_dir, filename)

    msgs = [
        {"role": "system", "content": (
            "คุณคือ Technical Writer ที่เชี่ยวชาญ\n"
            "งาน: อ่าน content ด้านล่าง แล้วสกัดออกมาเป็น Skill Reference .md ที่ดี\n"
            "รูปแบบที่ต้องการ:\n"
            "- ใช้ # สำหรับชื่อหัวข้อหลัก\n"
            "- ใช้ ## สำหรับแต่ละ subtopic\n"
            "- ใส่ code block ``` ทุกครั้งที่มี code\n"
            "- สรุปกระชับ อ่านง่าย เป็น quick reference\n"
            "- ตอบเป็น markdown ล้วนๆ ไม่ต้องมีคำอธิบายเพิ่ม\n"
            f"- ชื่อหัวข้อหลัก: {topic}"
        )},
        {"role": "user", "content": content[:6000]},
    ]
    try:
        md_content = "".join(stream_response(msgs, provider="gemini"))
    except Exception as e:
        return {"ok": False, "error": f"Gemini error: {e}"}

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(md_content)
    except Exception as e:
        return {"ok": False, "error": f"บันทึกไฟล์ไม่ได้: {e}"}

    try:
        db = _load_skills_db()
        db[topic] = {
            "summary": md_content[:300].strip(),
            "source": filename,
            "updated": datetime.now().isoformat(),
        }
        _save_skills_db(db)
    except Exception as e:
        logger.warning(f"skills_db update failed: {e}")

    return {"ok": True, "filename": filename, "path": filepath, "preview": md_content[:500]}


@router.delete("/skills/{skill_id}")
def skills_delete(skill_id: str):
    from urllib.parse import unquote
    skill_id = unquote(skill_id)
    deleted_file = False
    deleted_db = False
    skills_dir = os.path.join(os.path.dirname(__file__), "..", "skills")
    if ".." not in skill_id and "/" not in skill_id:
        for fname in [skill_id, f"{skill_id}.md"]:
            fp = os.path.join(skills_dir, fname)
            if os.path.exists(fp):
                os.remove(fp)
                deleted_file = True
                break
    db = _load_skills_db()
    for key in [skill_id, skill_id.replace(".md", "")]:
        if key in db:
            del db[key]
            _save_skills_db(db)
            deleted_db = True
    if deleted_file or deleted_db:
        return {"ok": True, "deleted_file": deleted_file, "deleted_db": deleted_db}
    return {"ok": False, "error": "ไม่พบ skill นี้"}


@router.get("/skills/discover")
def skills_discover(days: int = 30, min_cluster: int = 3, threshold: float = 0.72):
    """สแกน chat history หา topic ที่ user ถามบ่อย → return proposals"""
    from utils.skill_discovery import discover_skills
    proposals = discover_skills(
        days=days, min_cluster=min_cluster, threshold=threshold,
    )
    return {"proposals": [p.to_dict() for p in proposals], "count": len(proposals)}


@router.post("/skills/discover/accept")
async def skills_discover_accept(request: Request):
    """รับ proposal_id → สร้าง .md ใน skills/"""
    from utils.skill_discovery import accept_proposal
    data = await request.json()
    pid = (data.get("proposal_id") or "").strip()
    if not pid:
        return {"ok": False, "error": "proposal_id required"}
    return accept_proposal(
        pid,
        custom_topic=data.get("topic"),
        custom_content=data.get("content"),
    )


@router.get("/skills/discover/cached")
def skills_discover_cached():
    """proposals ที่รอ accept อยู่ใน memory"""
    from utils.skill_discovery import list_cached_proposals
    return {"proposals": list_cached_proposals()}


@router.post("/admin/cleanup-skills")
def cleanup_skills_endpoint():
    """ลบ junk skills ออกจาก db + re-sync ChromaDB"""
    result = cleanup_junk_skills()
    return {"ok": True, **result}


@router.post("/admin/sync-skills")
def sync_skills_endpoint():
    try:
        from utils.skills_search import sync_skills_to_search
        db = _load_skills_db()
        if not db:
            return {"ok": False, "error": "No skills found in skills_db.json"}
        sync_skills_to_search(db)
        return {"ok": True, "synced": len(db), "message": f"Synced {len(db)} skills to ChromaDB"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    import base64 as _b64, io
    content = await file.read()
    name = file.filename or "file"
    mime = file.content_type or ""
    ext = name.lower().rsplit(".", 1)[-1] if "." in name else ""

    if mime.startswith("image/") or ext in ('jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp'):
        b64 = _b64.b64encode(content).decode()
        return {"ok": True, "filename": name, "is_image": True, "b64": b64, "mime": mime or "image/jpeg"}

    if ext == "pdf" or mime == "application/pdf":
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(content))
            pages_text = [page.extract_text() or "" for page in reader.pages]
            raw_text = "\n\n".join(pages_text)
            text = f"[PDF: {name} — {len(reader.pages)} หน้า]\n{raw_text}"
        except ImportError:
            return {"ok": False, "error": "ไม่พบ library pypdf"}
        except Exception as e:
            return {"ok": False, "error": f"อ่าน PDF ไม่ได้: {e}"}
        extracted = auto_extract_skills(raw_text, name)
        return {"ok": True, "filename": name, "is_image": False, "text": text[:8000], "skills_extracted": extracted}

    if ext == "docx" or "wordprocessingml" in mime:
        try:
            import docx
            doc = docx.Document(io.BytesIO(content))
            raw_text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            text = f"[DOCX: {name}]\n{raw_text}"
        except ImportError:
            return {"ok": False, "error": "ไม่พบ library python-docx"}
        except Exception as e:
            return {"ok": False, "error": f"อ่าน DOCX ไม่ได้: {e}"}
        extracted = auto_extract_skills(raw_text, name)
        return {"ok": True, "filename": name, "is_image": False, "text": text[:8000], "skills_extracted": extracted}

    try:
        if ext == "json":
            import json as _json
            parsed = _json.loads(content)
            raw_text = _json.dumps(parsed, ensure_ascii=False, indent=2)
            text = f"[ไฟล์ JSON: {name}]\n{raw_text}"
        else:
            raw_text = content.decode('utf-8', errors='ignore')
            text = f"[ไฟล์: {name}]\n{raw_text}"
    except Exception as e:
        return {"ok": False, "error": str(e)}
    extracted = auto_extract_skills(raw_text, name)
    return {"ok": True, "filename": name, "is_image": False, "text": text[:8000], "skills_extracted": extracted}
