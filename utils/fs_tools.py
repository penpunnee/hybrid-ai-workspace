"""File System Tools — list/read/write/search ภายใต้ whitelist root

ความปลอดภัย:
  - ทุก path ต้องอยู่ภายใต้ allowed roots (resolve symlinks ก่อนเทียบ)
  - ปฏิเสธ path ที่มี '..' หรือ absolute path นอก roots
  - จำกัด file size สำหรับ read/write

Configure ผ่าน env:
  FS_TOOLS_ROOTS — colon-separated paths (default: ~/Desktop/ui/sandbox)
  FS_TOOLS_MAX_READ — bytes (default 1MB)
  FS_TOOLS_MAX_WRITE — bytes (default 256KB)
"""
import logging
import os
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_ROOT = os.path.expanduser("~/Desktop/ui/sandbox")
_ROOTS_ENV = os.getenv("FS_TOOLS_ROOTS", _DEFAULT_ROOT)
_ROOTS = [Path(p).expanduser().resolve() for p in _ROOTS_ENV.split(":") if p.strip()]

_MAX_READ = int(os.getenv("FS_TOOLS_MAX_READ", str(1024 * 1024)))      # 1MB
_MAX_WRITE = int(os.getenv("FS_TOOLS_MAX_WRITE", str(256 * 1024)))     # 256KB
_MAX_LIST = int(os.getenv("FS_TOOLS_MAX_LIST", "500"))                  # entries

# ensure default root exists
for r in _ROOTS:
    try:
        r.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.warning(f"[FS] cannot create root {r}: {e}")


class FSError(Exception):
    """fs operation ผิด — ใช้แทน HTTPException เพื่อให้ tool/REST ใช้ร่วมกัน"""


def _resolve_safe(path: str) -> Path:
    """resolve path + เช็คว่าอยู่ใน allowed roots"""
    if not path:
        raise FSError("empty path")
    p = Path(path).expanduser()
    if not p.is_absolute():
        # ใช้ root แรกเป็น base ถ้าเป็น relative
        p = _ROOTS[0] / p
    try:
        resolved = p.resolve()
    except (OSError, RuntimeError) as e:
        raise FSError(f"cannot resolve path: {e}")
    for root in _ROOTS:
        try:
            resolved.relative_to(root)
            return resolved
        except ValueError:
            continue
    raise FSError(f"path outside allowed roots: {resolved}")


def list_dir(path: str = "") -> dict:
    """รายชื่อไฟล์/โฟลเดอร์ในตำแหน่ง path

    Returns:
        {ok, path, entries: [{name, type: file|dir, size?}]}
    """
    try:
        target = _resolve_safe(path or str(_ROOTS[0]))
        if not target.exists():
            return {"ok": False, "error": "not found", "path": str(target)}
        if not target.is_dir():
            return {"ok": False, "error": "not a directory", "path": str(target)}

        entries = []
        for child in sorted(target.iterdir()):
            try:
                kind = "dir" if child.is_dir() else "file"
                entry = {"name": child.name, "type": kind}
                if kind == "file":
                    entry["size"] = child.stat().st_size
                entries.append(entry)
            except (PermissionError, OSError) as e:
                logger.debug(f"[FS] skip {child}: {e}")
            if len(entries) >= _MAX_LIST:
                break
        return {"ok": True, "path": str(target), "entries": entries, "count": len(entries)}
    except FSError as e:
        return {"ok": False, "error": str(e)}


def read_file(path: str, max_bytes: Optional[int] = None) -> dict:
    """อ่านไฟล์ — text (utf-8 best effort)

    Returns:
        {ok, path, content, size, truncated}
    """
    try:
        target = _resolve_safe(path)
        if not target.is_file():
            return {"ok": False, "error": "not a file", "path": str(target)}
        size = target.stat().st_size
        limit = max_bytes if max_bytes and max_bytes > 0 else _MAX_READ
        limit = min(limit, _MAX_READ)
        truncated = size > limit
        with open(target, "rb") as f:
            raw = f.read(limit)
        # try decode utf-8 → fallback latin-1
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            content = raw.decode("utf-8", errors="replace")
        return {
            "ok": True, "path": str(target), "content": content,
            "size": size, "truncated": truncated,
        }
    except FSError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"read failed: {e}"}


def write_file(path: str, content: str, overwrite: bool = False) -> dict:
    """เขียนไฟล์ — ปฏิเสธถ้ามีอยู่แล้วและไม่มี overwrite=True

    Returns:
        {ok, path, bytes_written}
    """
    try:
        if content is None:
            content = ""
        data = content.encode("utf-8")
        if len(data) > _MAX_WRITE:
            return {"ok": False, "error": f"content too large (>{_MAX_WRITE} bytes)"}

        target = _resolve_safe(path)
        if target.exists() and not overwrite:
            return {"ok": False, "error": "file exists — pass overwrite=true to replace"}
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "wb") as f:
            f.write(data)
        return {"ok": True, "path": str(target), "bytes_written": len(data)}
    except FSError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"write failed: {e}"}


def delete_file(path: str) -> dict:
    """ลบไฟล์ (ไม่ลบ directory — ต้องเขียน delete_dir แยก ถ้าจำเป็น)"""
    try:
        target = _resolve_safe(path)
        if not target.exists():
            return {"ok": False, "error": "not found"}
        if not target.is_file():
            return {"ok": False, "error": "not a file (use delete_dir for dirs)"}
        target.unlink()
        return {"ok": True, "path": str(target)}
    except FSError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"delete failed: {e}"}


def search_files(
    pattern: str,
    path: str = "",
    file_glob: str = "*",
    max_results: int = 50,
    max_per_file: int = 5,
) -> dict:
    """grep-like — หา substring/regex pattern ในไฟล์ใต้ path

    Returns:
        {ok, pattern, matches: [{file, line, text}]}
    """
    if not pattern:
        return {"ok": False, "error": "empty pattern"}
    try:
        root = _resolve_safe(path or str(_ROOTS[0]))
        if not root.is_dir():
            return {"ok": False, "error": "path not a directory"}

        try:
            regex = re.compile(pattern)
        except re.error:
            # fallback to literal substring
            regex = re.compile(re.escape(pattern))

        matches = []
        files_scanned = 0
        for file in root.rglob(file_glob):
            if not file.is_file():
                continue
            files_scanned += 1
            if file.stat().st_size > _MAX_READ:
                continue
            try:
                with open(file, "r", encoding="utf-8", errors="ignore") as f:
                    per_file = 0
                    for lineno, line in enumerate(f, 1):
                        if regex.search(line):
                            matches.append({
                                "file": str(file),
                                "line": lineno,
                                "text": line.rstrip()[:300],
                            })
                            per_file += 1
                            if per_file >= max_per_file or len(matches) >= max_results:
                                break
            except Exception as e:
                logger.debug(f"[FS] search skip {file}: {e}")
                continue
            if len(matches) >= max_results:
                break
        return {
            "ok": True, "pattern": pattern, "matches": matches,
            "files_scanned": files_scanned, "count": len(matches),
        }
    except FSError as e:
        return {"ok": False, "error": str(e)}


def info() -> dict:
    """รายงาน roots + limits"""
    return {
        "roots": [str(r) for r in _ROOTS],
        "max_read": _MAX_READ,
        "max_write": _MAX_WRITE,
        "max_list": _MAX_LIST,
    }
