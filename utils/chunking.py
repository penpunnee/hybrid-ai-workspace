"""Document Chunking — แบ่ง document เป็น chunks สำหรับ retrieval

หลักการ:
  - แบ่งโดยพยายามรักษา semantic boundary (paragraph → sentence → char)
  - มี overlap เพื่อกัน context หาย
  - คืน metadata (index, start, end, source) สำหรับ citation tracking

Default: chunk_size=500 chars, overlap=50 chars
"""
import re
import logging
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger(__name__)

# regex แบ่ง paragraph และ sentence (รองรับไทย+อังกฤษ)
_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n+")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?。！？])\s+|(?<=[ฯะาิีึืุูเแโใไๆ])\s{2,}")


@dataclass
class Chunk:
    """หน่วย retrieval — เก็บ text + ตำแหน่งใน source"""
    text: str
    index: int                    # ลำดับ chunk ใน document
    source: str                   # ชื่อ document/file
    start: int = 0                # offset เริ่มใน original text
    end: int = 0                  # offset จบใน original text
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _split_paragraphs(text: str) -> list[tuple[str, int]]:
    """แบ่ง paragraph + คืน (text, start_offset)"""
    out = []
    cursor = 0
    for m in _PARAGRAPH_SPLIT.finditer(text):
        para = text[cursor:m.start()]
        if para.strip():
            out.append((para, cursor))
        cursor = m.end()
    tail = text[cursor:]
    if tail.strip():
        out.append((tail, cursor))
    return out


def _split_sentences(text: str, base_offset: int = 0) -> list[tuple[str, int]]:
    """แบ่งประโยค fallback เมื่อ paragraph ยาวเกิน chunk_size"""
    out = []
    cursor = 0
    for m in _SENTENCE_SPLIT.finditer(text):
        sent = text[cursor:m.end()]
        if sent.strip():
            out.append((sent, base_offset + cursor))
        cursor = m.end()
    tail = text[cursor:]
    if tail.strip():
        out.append((tail, base_offset + cursor))
    return out


def chunk_text(
    text: str,
    source: str = "document",
    chunk_size: int = 500,
    overlap: int = 50,
    metadata: Optional[dict] = None,
) -> list[Chunk]:
    """แบ่ง text เป็น chunks

    Algorithm:
      1. แบ่ง paragraph ก่อน (\\n\\n)
      2. ถ้า paragraph ยังยาวเกิน chunk_size → แบ่ง sentence
      3. ถ้า sentence ยังยาว → ตัดตาม char พร้อม overlap
      4. รวม chunk เล็กๆ ติดกันให้ใกล้ chunk_size

    Args:
        text: เนื้อหา document
        source: ชื่อ document (สำหรับ citation)
        chunk_size: เป้าหมาย chars ต่อ chunk
        overlap: chars overlap ระหว่าง chunks (เฉพาะ char-based split)
        metadata: dict metadata เพิ่มเติม

    Returns:
        list[Chunk]
    """
    if not text or not text.strip():
        return []

    metadata = metadata or {}
    text = text.strip()

    # Step 1: paragraph split
    parts = _split_paragraphs(text)

    # Step 2: expand paragraphs ที่ใหญ่เกิน
    expanded: list[tuple[str, int]] = []
    for para, off in parts:
        if len(para) <= chunk_size:
            expanded.append((para, off))
            continue
        # ลอง sentence split
        sentences = _split_sentences(para, base_offset=off)
        for sent, soff in sentences:
            if len(sent) <= chunk_size:
                expanded.append((sent, soff))
                continue
            # char-based fallback พร้อม overlap
            step = chunk_size - overlap
            for i in range(0, len(sent), step):
                seg = sent[i:i + chunk_size]
                if seg.strip():
                    expanded.append((seg, soff + i))

    # Step 3: merge เล็กๆ ติดกัน
    merged: list[Chunk] = []
    buf, buf_start = "", -1
    for piece, off in expanded:
        if buf_start < 0:
            buf, buf_start = piece, off
            continue
        # ถ้ารวมแล้วยังไม่เกิน chunk_size → merge
        if len(buf) + 2 + len(piece) <= chunk_size:
            sep = "\n\n" if not buf.endswith("\n") else ""
            buf = f"{buf}{sep}{piece}"
        else:
            merged.append(Chunk(
                text=buf.strip(),
                index=len(merged),
                source=source,
                start=buf_start,
                end=buf_start + len(buf),
                metadata=dict(metadata),
            ))
            buf, buf_start = piece, off

    if buf.strip():
        merged.append(Chunk(
            text=buf.strip(),
            index=len(merged),
            source=source,
            start=buf_start,
            end=buf_start + len(buf),
            metadata=dict(metadata),
        ))

    logger.debug(f"[Chunk] {source}: {len(text)} chars → {len(merged)} chunks")
    return merged


def chunk_stats(chunks: list[Chunk]) -> dict:
    """summary stats — ใช้ debug/logging"""
    if not chunks:
        return {"count": 0}
    sizes = [len(c.text) for c in chunks]
    return {
        "count": len(chunks),
        "min": min(sizes),
        "max": max(sizes),
        "avg": sum(sizes) // len(sizes),
        "total": sum(sizes),
    }
