"""จับเวลางาน sync ที่รันบน event loop ของ WebSocket (/ws/voice · /ws/reader) — ขั้น 5B 2026-09-29

⚠️ วัดอย่างเดียว ไม่เปลี่ยนพฤติกรรม: ห่อแล้ว call ยังเป็น sync ตัวเดิม (ไม่ย้าย thread ไม่ await) ⇒ `_marks.set()`
ยังเสร็จในจังหวะเดียวกับที่เรียก (ที่คั่นไม่เสียหายเมื่อถูก cancel — server.py) · 🔒 ไม่แตะค่าเสียงใดๆ

ทำไมไม่ใช้ `core.observability.log_timing`: มันเก็บค่าใน contextvar ให้ /api/chat ใส่ใน `done` — **ไม่เขียน log**
ทำไมไม่ใช้ asyncio debug mode (`slow_callback_duration`): เปิดการตรวจทั้งลูป ไม่เหมาะ prod และไม่บอกว่าช้าที่ call ไหน
(https://docs.python.org/3/library/asyncio-dev.html)

ใช้: ห่อ object ครั้งเดียวที่บรรทัด import ของ handler (call site ไม่เปลี่ยน — เทสยึดข้อความไว้)
  · WARNING ต่อ call ที่เกิน `slow_ms` (default 50 ms — เกณฑ์สำหรับวัด ไม่ใช่ตัวกัน)
  · `summary()` = หนึ่งบรรทัดตอนปิดสาย: `name n=… max=…ms total=…ms` · `always` = ชื่อที่ต้องโผล่แม้ n=0
"""
import logging
import time

logger = logging.getLogger(__name__)
_now = time.perf_counter          # แยกไว้ให้เทสแทนนาฬิกาได้


class SyncCallTimer:
    def __init__(self, tag: str, slow_ms: float = 50.0, always: tuple[str, ...] = ()):
        self.tag, self.slow_ms = tag, slow_ms
        self._stats: dict[str, list[float]] = {name: [0, 0.0, 0.0] for name in always}   # n, total, max

    def _record(self, name: str, ms: float) -> None:
        s = self._stats.setdefault(name, [0, 0.0, 0.0])
        s[0] += 1
        s[1] += ms
        s[2] = max(s[2], ms)
        if ms > self.slow_ms:
            logger.warning(f"[LoopTiming] {self.tag} {name} {ms:.1f}ms (เกิน {self.slow_ms:.0f}ms บน event loop)")

    def wrap(self, name: str, fn):
        def timed(*args, **kwargs):
            t0 = _now()
            try:
                return fn(*args, **kwargs)
            finally:                              # exception ส่งต่อเหมือนเดิม แต่ยังนับเวลา
                self._record(name, (_now() - t0) * 1000)
        return timed

    def proxy(self, obj, prefix: str):
        return _TimedProxy(self, obj, prefix)

    def summary(self) -> str:
        if not self._stats:
            return "(ไม่มี call)"
        return " · ".join(f"{name} n={int(n)} max={mx:.1f}ms total={tot:.1f}ms"
                          for name, (n, tot, mx) in self._stats.items())


class _TimedProxy:
    """ส่งผ่านทุก attribute · เฉพาะ callable ถูกห่อจับเวลา (ชื่อ `<prefix>.<attr>`)"""

    def __init__(self, timer: SyncCallTimer, obj, prefix: str):
        self._timer, self._obj, self._prefix = timer, obj, prefix

    def __getattr__(self, attr):
        value = getattr(self._obj, attr)
        if callable(value):
            return self._timer.wrap(f"{self._prefix}.{attr}", value)
        return value
