"""Code Execution Sandbox — รัน Python/shell ใน Docker หรือ subprocess (fallback)

Strategy:
  1. ถ้ามี Docker → ใช้ container แยกต่อรอบ (--network none, memory/cpu limits)
  2. ถ้าไม่มี Docker → fallback subprocess timeout (ต้องเปิดด้วย CODE_SANDBOX_ALLOW_LOCAL=true)

Output schema:
  {ok, stdout, stderr, exit_code, runtime_ms, mode: "docker" | "local" | "blocked"}
"""
import logging
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, asdict
from typing import Optional

logger = logging.getLogger(__name__)

_DOCKER_IMAGE = os.getenv("CODE_SANDBOX_IMAGE", "python:3.11-slim")
_DEFAULT_TIMEOUT = int(os.getenv("CODE_SANDBOX_TIMEOUT", "10"))
_MAX_TIMEOUT = int(os.getenv("CODE_SANDBOX_MAX_TIMEOUT", "60"))
_MEM_LIMIT = os.getenv("CODE_SANDBOX_MEM", "256m")
_CPU_LIMIT = os.getenv("CODE_SANDBOX_CPU", "0.5")
_ALLOW_LOCAL = os.getenv("CODE_SANDBOX_ALLOW_LOCAL", "false").lower() == "true"
_MAX_CODE_BYTES = 100 * 1024  # 100 KB


@dataclass
class SandboxResult:
    ok: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: int = -1
    runtime_ms: int = 0
    mode: str = "blocked"
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


_docker_cache: dict = {"ok": None, "checked_at": 0.0}


def _has_docker() -> bool:
    """ตรวจว่า Docker daemon ทำงานอยู่ (cache 30s)"""
    now = time.time()
    if _docker_cache["ok"] is not None and now - _docker_cache["checked_at"] < 30:
        return _docker_cache["ok"]

    if shutil.which("docker") is None:
        _docker_cache.update({"ok": False, "checked_at": now})
        return False
    try:
        proc = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True, text=True, timeout=3,
        )
        ok = proc.returncode == 0 and bool(proc.stdout.strip())
    except Exception:
        ok = False
    _docker_cache.update({"ok": ok, "checked_at": now})
    return ok


def _clamp_timeout(t: Optional[int]) -> int:
    if not t or t <= 0:
        return _DEFAULT_TIMEOUT
    return min(int(t), _MAX_TIMEOUT)


def _truncate(s: str, max_chars: int = 8000) -> str:
    if not s:
        return ""
    if len(s) > max_chars:
        return s[:max_chars] + f"\n...[truncated {len(s) - max_chars} chars]"
    return s


def run_python_docker(code: str, timeout: int) -> SandboxResult:
    """รัน code ใน Docker container — แยกขาดจาก host"""
    start = time.time()
    tmpdir = tempfile.mkdtemp(prefix="sbx_")
    code_path = os.path.join(tmpdir, "main.py")
    try:
        with open(code_path, "w", encoding="utf-8") as f:
            f.write(code)

        cname = f"sbx_{uuid.uuid4().hex[:8]}"
        cmd = [
            "docker", "run", "--rm",
            "--name", cname,
            "--network", "none",
            "--memory", _MEM_LIMIT,
            "--cpus", _CPU_LIMIT,
            "--read-only",
            "--tmpfs", "/tmp:rw,size=64m",
            "-v", f"{tmpdir}:/work:ro",
            "-w", "/work",
            _DOCKER_IMAGE,
            "python", "main.py",
        ]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout + 2,
            )
        except subprocess.TimeoutExpired:
            # kill container ถ้ายังรันอยู่
            subprocess.run(["docker", "kill", cname], capture_output=True, timeout=5)
            return SandboxResult(
                ok=False, mode="docker", exit_code=-1,
                stderr=f"timeout after {timeout}s",
                runtime_ms=int((time.time() - start) * 1000),
                error="timeout",
            )

        return SandboxResult(
            ok=proc.returncode == 0,
            stdout=_truncate(proc.stdout),
            stderr=_truncate(proc.stderr),
            exit_code=proc.returncode,
            runtime_ms=int((time.time() - start) * 1000),
            mode="docker",
        )
    finally:
        try:
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass


def run_python_local(code: str, timeout: int) -> SandboxResult:
    """fallback: subprocess บน host — กัน path injection แต่ ไม่กัน import"""
    if not _ALLOW_LOCAL:
        return SandboxResult(
            ok=False, mode="blocked",
            error=(
                "Docker not available และ CODE_SANDBOX_ALLOW_LOCAL=false — "
                "การรัน code นอก sandbox ถูก block เพื่อความปลอดภัย. "
                "ตั้ง env CODE_SANDBOX_ALLOW_LOCAL=true หรือ ติดตั้ง Docker"
            ),
        )

    start = time.time()
    tmpdir = tempfile.mkdtemp(prefix="sbx_local_")
    code_path = os.path.join(tmpdir, "main.py")
    try:
        with open(code_path, "w", encoding="utf-8") as f:
            f.write(code)
        try:
            proc = subprocess.run(
                ["python3", code_path],
                capture_output=True, text=True, timeout=timeout,
                cwd=tmpdir,
                env={"PATH": "/usr/bin:/bin", "HOME": tmpdir, "TMPDIR": tmpdir},
            )
        except subprocess.TimeoutExpired:
            return SandboxResult(
                ok=False, mode="local", exit_code=-1,
                stderr=f"timeout after {timeout}s",
                runtime_ms=int((time.time() - start) * 1000),
                error="timeout",
            )
        return SandboxResult(
            ok=proc.returncode == 0,
            stdout=_truncate(proc.stdout),
            stderr=_truncate(proc.stderr),
            exit_code=proc.returncode,
            runtime_ms=int((time.time() - start) * 1000),
            mode="local",
        )
    finally:
        try:
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass


def run_python(code: str, timeout: int = 0) -> SandboxResult:
    """Public entry — รัน Python code

    Args:
        code: source code
        timeout: วินาที (0 = default, clamp ที่ _MAX_TIMEOUT)

    Returns:
        SandboxResult
    """
    if not code or not code.strip():
        return SandboxResult(ok=False, mode="blocked", error="empty code")
    if len(code.encode("utf-8")) > _MAX_CODE_BYTES:
        return SandboxResult(
            ok=False, mode="blocked",
            error=f"code too large (>{_MAX_CODE_BYTES} bytes)",
        )

    t = _clamp_timeout(timeout)
    if _has_docker():
        try:
            return run_python_docker(code, t)
        except Exception as e:
            logger.warning(f"[Sandbox] Docker exec failed, fallback local: {e}")
            return run_python_local(code, t)
    return run_python_local(code, t)


def info() -> dict:
    """สถานะ sandbox — สำหรับ /api/system หรือ debug"""
    return {
        "docker_available": _has_docker(),
        "docker_image": _DOCKER_IMAGE,
        "allow_local": _ALLOW_LOCAL,
        "default_timeout": _DEFAULT_TIMEOUT,
        "max_timeout": _MAX_TIMEOUT,
        "memory_limit": _MEM_LIMIT,
        "cpu_limit": _CPU_LIMIT,
    }
