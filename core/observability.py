"""Observability — request ID + structured logging + timing

ใช้งาน:
    from core.observability import start_request, log_timing, current_request_id

    rid = start_request()  # uuid prefix 8 chars
    with log_timing("context_assembly"):
        ... # work ...

    # ทุก logger.info() ตั้งแต่จุดนี้จะมี [rid=xxxxx] ใน prefix อัตโนมัติ

Output format:
  - Default: plain text + [rid=xxxxx] prefix
  - LOG_FORMAT=json: structured JSON (สำหรับส่งเข้า log aggregator)
"""
from __future__ import annotations
import contextvars
import json
import logging
import os
import time
import uuid
from contextlib import contextmanager
from typing import Optional

# context-bound request id — ปลอดภัยสำหรับ async/threading
_request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")
_timing_var: contextvars.ContextVar[dict] = contextvars.ContextVar("timings", default={})

logger = logging.getLogger(__name__)


def start_request(prefix: str = "req") -> str:
    """สร้าง request_id ใหม่ + bind เข้า context — เรียกที่จุดเริ่ม request"""
    rid = f"{prefix}_{uuid.uuid4().hex[:8]}"
    _request_id_var.set(rid)
    _timing_var.set({})
    return rid


def current_request_id() -> str:
    return _request_id_var.get()


def get_timings() -> dict:
    return dict(_timing_var.get())


def record_timing(name: str, ms: float) -> None:
    """บันทึก timing ลง context (สะสมต่อ request)"""
    timings = dict(_timing_var.get())
    timings[name] = round(ms, 1)
    _timing_var.set(timings)


@contextmanager
def log_timing(name: str):
    """context manager วัดเวลา + บันทึกลง context"""
    start = time.perf_counter()
    try:
        yield
    finally:
        ms = (time.perf_counter() - start) * 1000
        record_timing(name, ms)


# ── Logging integration ──────────────────────────────────────────────────────
class RequestIdFilter(logging.Filter):
    """แทรก request_id เข้า LogRecord ทุก record"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id_var.get() or "-"
        return True


class _PlainFormatter(logging.Formatter):
    """human-readable: 2026-05-12 12:00:00 INFO [rid=abc12345] module: message"""

    def format(self, record: logging.LogRecord) -> str:
        record.request_id = getattr(record, "request_id", "-")
        return super().format(record)


class _JsonFormatter(logging.Formatter):
    """structured: 1 บรรทัด JSON ต่อ log entry"""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def install_logging(level: Optional[str] = None) -> None:
    """เรียกครั้งเดียวที่ startup — replace root logger config

    Args:
        level: 'DEBUG'|'INFO'|'WARNING'|'ERROR' (default จาก env LOG_LEVEL หรือ INFO)
    """
    lvl_name = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    lvl = getattr(logging, lvl_name, logging.INFO)
    fmt_kind = os.getenv("LOG_FORMAT", "plain").lower()

    if fmt_kind == "json":
        formatter: logging.Formatter = _JsonFormatter()
    else:
        formatter = _PlainFormatter(
            fmt="%(asctime)s %(levelname)s [rid=%(request_id)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    rid_filter = RequestIdFilter()

    # file handler (rotate ขนาด)
    log_path = os.getenv("LOG_FILE", "server.log")
    try:
        from logging.handlers import RotatingFileHandler
        file_handler: logging.Handler = RotatingFileHandler(
            log_path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8",
        )
    except Exception:
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.addFilter(rid_filter)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(rid_filter)

    root = logging.getLogger()
    # ลบ handler เดิมก่อน (ป้องกัน duplicate ตอน reload)
    for h in list(root.handlers):
        root.removeHandler(h)
    root.setLevel(lvl)
    root.addHandler(file_handler)
    root.addHandler(stream_handler)


def timing_summary() -> str:
    """สรุป timing ของ request ปัจจุบัน — เรียกตอนปิด request"""
    t = _timing_var.get()
    if not t:
        return ""
    parts = [f"{k}={v}ms" for k, v in sorted(t.items())]
    return " ".join(parts)
