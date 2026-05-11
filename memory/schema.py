"""Memory schema — ทุก memory entry ต้องมี metadata ครบ"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

MemoryType   = Literal["fact", "skill", "preference", "event", "correction"]
MemorySource = Literal["user_taught", "dream", "conversation", "document"]


@dataclass
class MemoryEntry:
    content: str
    assistant: str = ""
    type: MemoryType = "event"
    confidence: float = 0.7        # 0–1 ยิ่งสูงยิ่งเชื่อถือ
    source: MemorySource = "conversation"
    verified: bool = False         # True = user สอนโดยตรง
    access_count: int = 0          # นับว่า retrieve กี่ครั้ง
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_accessed: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_metadata(self) -> dict:
        return {
            "assistant":     self.assistant,
            "type":          self.type,
            "confidence":    self.confidence,
            "source":        self.source,
            "verified":      self.verified,
            "access_count":  self.access_count,
            "created_at":    self.created_at,
            "last_accessed": self.last_accessed,
        }

    @staticmethod
    def confidence_label(score: float) -> str:
        if score >= 0.9: return "✅ verified"
        if score >= 0.7: return "🟡 probable"
        if score >= 0.5: return "🟠 uncertain"
        return "🔴 low"
