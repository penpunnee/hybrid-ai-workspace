"""Sandbox & FS API — REST endpoints สำหรับ code execution + file system tools

Endpoints:
  POST /api/sandbox/python    — run python in sandbox
  GET  /api/sandbox/info      — สถานะ sandbox
  POST /api/fs/list           — list dir
  POST /api/fs/read           — read file
  POST /api/fs/write          — write file
  POST /api/fs/search         — grep
  GET  /api/fs/info           — roots/limits
"""
import logging
from fastapi import APIRouter, Request, HTTPException

from utils.code_sandbox import run_python, info as sandbox_info
from utils.fs_tools import list_dir, read_file, write_file, search_files, info as fs_info

router = APIRouter(prefix="/api", tags=["sandbox-fs"])
logger = logging.getLogger(__name__)


@router.post("/sandbox/python")
async def sandbox_python(request: Request):
    """รัน Python code — body: {code, timeout?}"""
    data = await request.json()
    code = data.get("code") or ""
    if not isinstance(code, str) or not code.strip():
        raise HTTPException(400, "field 'code' required")
    try:
        timeout = int(data.get("timeout", 10))
    except (TypeError, ValueError):
        timeout = 10
    result = run_python(code, timeout=timeout)
    return result.to_dict()


@router.get("/sandbox/info")
def sandbox_status():
    return sandbox_info()


@router.post("/fs/list")
async def fs_list(request: Request):
    data = await request.json()
    return list_dir(path=str(data.get("path", "")))


@router.post("/fs/read")
async def fs_read(request: Request):
    data = await request.json()
    path = str(data.get("path", ""))
    if not path:
        raise HTTPException(400, "path required")
    try:
        max_bytes = int(data.get("max_bytes", 0))
    except (TypeError, ValueError):
        max_bytes = 0
    return read_file(path, max_bytes=max_bytes or None)


@router.post("/fs/write")
async def fs_write(request: Request):
    data = await request.json()
    path = str(data.get("path", ""))
    content = data.get("content")
    if not path:
        raise HTTPException(400, "path required")
    if not isinstance(content, str):
        raise HTTPException(400, "content (string) required")
    return write_file(path, content, overwrite=bool(data.get("overwrite", False)))


@router.post("/fs/search")
async def fs_search(request: Request):
    data = await request.json()
    pattern = str(data.get("pattern", ""))
    if not pattern:
        raise HTTPException(400, "pattern required")
    return search_files(
        pattern,
        path=str(data.get("path", "")),
        file_glob=str(data.get("file_glob", "*")),
        max_results=int(data.get("max_results", 50)),
        max_per_file=int(data.get("max_per_file", 5)),
    )


@router.get("/fs/info")
def fs_status():
    return fs_info()
