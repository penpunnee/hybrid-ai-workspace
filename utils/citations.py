"""Citation Tracking — เก็บแหล่งที่มาของข้อมูลที่ inject เข้า context

ใช้ใน routers/chat.py เพื่อ:
  1. รวบ citations จากทุก source (web/document/vault/skill)
  2. ส่งกลับ frontend เป็น SSE event {"citations": [...]} เพื่อ render footnote/source list

Citation ทุกอันมี id เรียงตามลำดับที่ถูกใช้ใน context (1, 2, 3, ...)
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, asdict
from typing import Iterable

logger = logging.getLogger(__name__)


@dataclass
class Citation:
    """หน่วยอ้างอิงเดียว — 1 source ที่ inject เข้า context"""
    id: int
    type: str                 # web | document | vault | skill | memory
    source: str               # ชื่อไฟล์/URL/title
    snippet: str              # excerpt (max 400 chars)
    score: float = 0.0        # relevance 0-1
    url: str = ""             # optional link

    def to_dict(self) -> dict:
        return asdict(self)


class CitationTracker:
    """Accumulator ที่ใช้ตลอด chat request — เรียก add_*() ขณะประกอบ context"""

    def __init__(self) -> None:
        self._items: list[Citation] = []

    def __len__(self) -> int:
        return len(self._items)

    def __bool__(self) -> bool:
        return bool(self._items)

    @property
    def next_id(self) -> int:
        return len(self._items) + 1

    def _truncate(self, text: str, max_chars: int = 400) -> str:
        text = (text or "").strip().replace("\n", " ")
        return text[:max_chars]

    def add(self, *, type: str, source: str, snippet: str,
            score: float = 0.0, url: str = "") -> Citation:
        c = Citation(
            id=self.next_id,
            type=type,
            source=source[:200],
            snippet=self._truncate(snippet),
            score=round(float(score or 0.0), 4),
            url=url[:500],
        )
        self._items.append(c)
        return c

    # ── factory helpers — รับผลจาก retrievers ตรงๆ ──────────────────────────
    def add_web_results(self, results: Iterable[dict]) -> list[Citation]:
        """websearch results: [{title, body, href, fetched_text, _rerank_score}]"""
        out = []
        for r in results:
            snippet = (r.get("fetched_text") or r.get("body") or "").strip()
            if not snippet:
                continue
            out.append(self.add(
                type="web",
                source=r.get("title") or r.get("href") or "web",
                snippet=snippet,
                score=r.get("_rerank_score") or 0.0,
                url=r.get("href") or "",
            ))
        return out

    def add_doc_chunks(self, chunks: Iterable[dict]) -> list[Citation]:
        """document retrieve_chunks results: [{text, source, score, chunk_index}]"""
        out = []
        for ch in chunks:
            out.append(self.add(
                type="document",
                source=f"{ch.get('source','?')}#{ch.get('chunk_index',0)}",
                snippet=ch.get("text", ""),
                score=ch.get("score", 0.0),
            ))
        return out

    def add_vault_notes(self, notes: Iterable[dict]) -> list[Citation]:
        """obsidian vault: [{title, content, path?}]"""
        out = []
        for n in notes:
            out.append(self.add(
                type="vault",
                source=n.get("title") or n.get("path") or "vault",
                snippet=n.get("content", ""),
                score=n.get("score", 0.0),
            ))
        return out

    def add_skills(self, skills: Iterable[dict]) -> list[Citation]:
        """skills_search results: [{topic, content, score?}]"""
        out = []
        for s in skills:
            out.append(self.add(
                type="skill",
                source=s.get("topic") or s.get("filename") or "skill",
                snippet=s.get("content", "") or s.get("text", ""),
                score=s.get("score", 0.0),
            ))
        return out

    # ── output ──────────────────────────────────────────────────────────────
    def to_list(self) -> list[dict]:
        return [c.to_dict() for c in self._items]

    def format_inline_legend(self) -> str:
        """ใส่ท้าย context เป็นตาราง legend (ให้ LLM อ้างอิงได้)"""
        if not self._items:
            return ""
        lines = ["", "📎 **แหล่งอ้างอิง (ใช้เลข [n] ในการอ้างอิงในคำตอบ):**"]
        for c in self._items:
            tag = f"[{c.id}]"
            label = c.source if not c.url else f"{c.source} ({c.url})"
            lines.append(f"{tag} {c.type}: {label}")
        return "\n".join(lines)
