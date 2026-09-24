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
import time
from pathlib import Path
from typing import Optional

from core.env_registry import env_float, env_int, env_str

logger = logging.getLogger(__name__)

# env ของ FS tools — ไฟล์นี้เป็นเจ้าของ 6 ชื่อ (ก้อน 4 · 2026-09-23 · ตัวกัน: tests/test_env_registry.py)
_G = "FS Tools (agent)"
_DEFAULT_ROOT = os.path.expanduser("~/Desktop/ui/sandbox")
# ลงทะเบียน "" ไม่ใช่ _DEFAULT_ROOT — default นั้นคำนวณจาก home ของเครื่องที่ generate .env.example
# (แบบเดียวกับ ROUTER_IP) · ว่าง/ไม่ตั้ง = _DEFAULT_ROOT (เดิม: ตั้ง "" ได้ = ไม่มี root เลย)
_ROOTS_ENV = env_str("FS_TOOLS_ROOTS", "", group=_G, doc=(
    "โฟลเดอร์ที่ agent อ่าน/เขียนได้ คั่นด้วย : (whitelist — นอกนี้ปฏิเสธทั้งหมด)\n"
    "ว่าง = ~/Desktop/ui/sandbox · ในคอนเทนเนอร์ต้องตั้งให้ตรง volume mount ของ sandbox\n"
    "(ดูคู่กันใน docker-compose.yml — ห้ามเขียน path ในคอนเทนเนอร์ตรงนี้: CI ตรวจว่า repo root\n"
    "ของเครื่องที่ generate ไม่หลุดเข้า .env.example และในอิมเมจ repo root คือ path นั้นพอดี)")) or _DEFAULT_ROOT
_ROOTS = [Path(p).expanduser().resolve() for p in _ROOTS_ENV.split(":") if p.strip()]

_MAX_READ = env_int("FS_TOOLS_MAX_READ", 1024 * 1024, group=_G, doc="ไบต์สูงสุดต่อการอ่านไฟล์ (1 MB)")
_MAX_WRITE = env_int("FS_TOOLS_MAX_WRITE", 256 * 1024, group=_G, doc="ไบต์สูงสุดต่อการเขียนไฟล์ (256 KB)")
_MAX_LIST = env_int("FS_TOOLS_MAX_LIST", 500, group=_G, doc="จำนวนรายการสูงสุดต่อการ list โฟลเดอร์")
_MAX_PATTERN = env_int("FS_TOOLS_MAX_PATTERN", 200, group=_G, doc="ความยาว regex สูงสุดของ search_files (ตัวอักษร)")
_SEARCH_DEADLINE = env_float("FS_TOOLS_SEARCH_DEADLINE", 5.0, group=_G,
                             doc="วินาทีสูงสุดของ search_files ทั้งก้อน (กัน regex/โฟลเดอร์ใหญ่กินเวลา)")

# quantifier ซ้อน quantifier — คลาสคลาสสิกของ catastrophic backtracking
# ((a+)+ / (a*)* / (a+){3,}) · `re` ของ CPython ไม่มี timeout และ **หยุดกลางคันไม่ได้**
# → กันที่ตัว pattern เป็นทางเดียวที่ได้ผลจริง (deadline ด้านล่างช่วยได้เฉพาะสแกนที่ช้าแบบปกติ)
# ⚠️ heuristic ไม่ใช่การพิสูจน์ — ไม่ครอบ (a|a)* ซึ่งกันไม่ได้โดยไม่ทิ้ง (foo|bar)+ ที่ใช้จริง
_NESTED_QUANT = re.compile(r"\((?![?#])[^)]*[*+][^)]*\)\s*[*+{]")

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
    if len(pattern) > _MAX_PATTERN:
        return {"ok": False, "error": f"pattern too long (>{_MAX_PATTERN} chars)"}
    if _NESTED_QUANT.search(pattern):
        return {"ok": False, "error": (
            "unsafe pattern — nested quantifier ทำให้ regex ระเบิด (catastrophic "
            "backtracking) และหยุดกลางคันไม่ได้ · ใช้ pattern ที่ง่ายกว่านี้หรือค้นแบบ literal"
        )}
    # glob เป็นชั้นแรก: `..` / absolute ทำให้ rglob เดินออกนอก root ได้ (pathlib ไม่กันให้ —
    # docs บอกแค่ "relative pattern") · พิสูจน์บน prod: "../../../../../../proc/self/environ"
    # อ่าน env ทั้งก้อนได้ (audit 2026-09-24 ข้อ 5) · absolute เดิมโยน NotImplementedError หลุดออกไป
    glob_parts = re.split(r"[\\/]", file_glob or "")
    if not file_glob or file_glob[0] in "/\\" or ".." in glob_parts:
        return {"ok": False, "error": "file_glob ต้องเป็น pattern ภายใน root (ห้าม .. / absolute)"}
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
        timed_out = False
        deadline = time.monotonic() + _SEARCH_DEADLINE
        for file in root.rglob(file_glob):
            # ชั้นหลัก: ทุก match ต้องผ่านด่านเดียวกับ read/write — resolve symlink แล้วเทียบ root
            # (glob ที่ไม่มี `..` ก็เดินผ่าน symlink ใต้ root ออกไปได้ · ตัวเลข files_scanned
            # ต้องไม่นับตัวที่ถูกกัน ไม่งั้นหลอกว่าสแกนไฟล์นอก root)
            try:
                _resolve_safe(str(file))
            except FSError:
                continue
            if not file.is_file():
                continue
            if time.monotonic() > deadline:
                timed_out = True
                break
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
            "timed_out": timed_out,
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
