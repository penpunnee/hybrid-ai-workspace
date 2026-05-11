import uuid
import json
from datetime import datetime
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from core.state import share_store_set, share_store_get
from utils.history import (
    load_history, get_sessions, clear_session, export_history_md,
    pin_message, get_pinned_messages, truncate_from_db_id, rename_session,
)

router = APIRouter(prefix="/api", tags=["sessions"])


@router.get("/sessions/{assistant}")
def list_sessions(assistant: str, q: str = ""):
    sessions = get_sessions(assistant)
    if q.strip():
        q_lower = q.strip().lower()
        sessions = [s for s in sessions if q_lower in s.get("first_msg", "").lower()]
    return sessions


@router.post("/sessions/{assistant}")
def new_session(assistant: str):
    sid = f"s_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    return {"session_id": sid}


@router.patch("/sessions/{assistant}/{session_id}")
async def patch_session(assistant: str, session_id: str, request: Request):
    data = await request.json()
    name = data.get("name", "").strip()
    if not name:
        return {"ok": False, "error": "ชื่อว่างไม่ได้"}
    rename_session(assistant, session_id, name)
    return {"ok": True, "session_id": session_id, "name": name}


@router.delete("/sessions/{assistant}/{session_id}")
def delete_session(assistant: str, session_id: str):
    clear_session(assistant, session_id)
    return {"ok": True}


@router.get("/history/{assistant}/{session_id}")
def get_history(assistant: str, session_id: str):
    return load_history(assistant, session_id, include_meta=True)


@router.post("/pin/{db_id}")
async def toggle_pin(db_id: int, request: Request):
    data = await request.json()
    pinned = data.get("pinned", True)
    pin_message(db_id, pinned)
    return {"ok": True, "db_id": db_id, "pinned": pinned}


@router.get("/pinned/{assistant}/{session_id}")
def list_pinned(assistant: str, session_id: str):
    return get_pinned_messages(assistant, session_id)


@router.get("/export/{assistant}/{session_id}")
def export_session(assistant: str, session_id: str):
    md = export_history_md(assistant, session_id)
    return {"markdown": md}


@router.delete("/truncate/{db_id}")
def truncate_endpoint(db_id: int):
    truncate_from_db_id(db_id)
    return {"ok": True}


@router.post("/share")
async def create_share(request: Request):
    data = await request.json()
    assistant = data.get("assistant", "")
    session_id = data.get("session_id", "")
    if not assistant or not session_id:
        return {"ok": False, "error": "ระบุ assistant และ session_id"}
    import logging
    logger = logging.getLogger(__name__)
    token = uuid.uuid4().hex[:10]
    created = datetime.now().isoformat()
    share_store_set(token, {"assistant": assistant, "session_id": session_id, "created": created})
    try:
        from utils.history import _get_conn
        conn = _get_conn()
        conn.execute("CREATE TABLE IF NOT EXISTS share_links (token TEXT PRIMARY KEY, assistant TEXT, session_id TEXT, created TEXT)")
        conn.execute("INSERT OR REPLACE INTO share_links (token, assistant, session_id, created) VALUES (?,?,?,?)",
                     (token, assistant, session_id, created))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Share link persist failed: {e}")
    return {"ok": True, "token": token}


@router.get("/shared/{token}")
def get_shared_data(token: str):
    import logging
    logger = logging.getLogger(__name__)
    info = share_store_get(token)
    if not info:
        try:
            from utils.history import _get_conn
            conn = _get_conn()
            conn.execute("CREATE TABLE IF NOT EXISTS share_links (token TEXT PRIMARY KEY, assistant TEXT, session_id TEXT, created TEXT)")
            row = conn.execute("SELECT assistant, session_id, created FROM share_links WHERE token=?", (token,)).fetchone()
            conn.close()
            if row:
                info = {"assistant": row[0], "session_id": row[1], "created": row[2]}
                share_store_set(token, info)
        except Exception as e:
            logger.warning(f"Share link lookup failed: {e}")
    if not info:
        return {"ok": False, "error": "ไม่พบ link"}
    msgs = load_history(info["assistant"], info["session_id"], include_meta=False)
    return {"ok": True, "assistant": info["assistant"], "messages": msgs, "created": info["created"]}
