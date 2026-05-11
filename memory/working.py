"""Working Memory — buffer ข้อมูลล่าสุดของแต่ละ session (in-memory)

ทำหน้าที่เหมือน short-term RAM ของสมอง:
- เก็บ context ที่เกิดขึ้นใน session ปัจจุบัน
- ไม่ต้อง query ChromaDB ทุกครั้ง
- clear อัตโนมัติเมื่อ session จบหรือ idle นาน
"""
from collections import deque
from threading import Lock
from datetime import datetime


class WorkingMemory:
    def __init__(self, max_per_session: int = 20, max_sessions: int = 50):
        self._buffer: dict[str, deque] = {}
        self._last_active: dict[str, str] = {}
        self._lock = Lock()
        self.max_per_session = max_per_session
        self.max_sessions = max_sessions

    def push(self, session_id: str, role: str, content: str):
        with self._lock:
            self._evict_if_needed()
            if session_id not in self._buffer:
                self._buffer[session_id] = deque(maxlen=self.max_per_session)
            self._buffer[session_id].append({
                "role": role,
                "content": content[:500],  # ตัดไม่ให้ใหญ่เกิน
                "ts": datetime.now().isoformat(),
            })
            self._last_active[session_id] = datetime.now().isoformat()

    def get_recent(self, session_id: str, n: int = 5) -> list[dict]:
        with self._lock:
            items = list(self._buffer.get(session_id, []))
            return items[-n:]

    def get_context_text(self, session_id: str, n: int = 5) -> str:
        items = self.get_recent(session_id, n)
        if not items:
            return ""
        lines = [f"[{i['role']}]: {i['content']}" for i in items]
        return "[บทสนทนาล่าสุดใน session]\n" + "\n".join(lines)

    def clear(self, session_id: str):
        with self._lock:
            self._buffer.pop(session_id, None)
            self._last_active.pop(session_id, None)

    def _evict_if_needed(self):
        """ลบ session เก่าสุดถ้า sessions เกิน limit"""
        if len(self._buffer) >= self.max_sessions:
            oldest = min(self._last_active, key=self._last_active.get)
            self._buffer.pop(oldest, None)
            self._last_active.pop(oldest, None)


# Singleton ใช้ทั้งระบบ
working_memory = WorkingMemory()
