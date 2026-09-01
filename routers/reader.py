"""Reader API — อ่านหนังสือ/นิยายทีละท่อน พักได้ จำที่คั่นหน้าได้

user เคาะ 2026-08-09: "โยนนิยาย PDF ให้อ่านให้ฟัง — **พักได้ และจำได้ว่าอ่านถึงตรงไหน**"

Endpoints:
  POST /api/reader/add      — {source, content} เก็บเล่มใหม่ (ซ่อม PUA ให้ระหว่างทาง)
  GET  /api/reader/books    — รายชื่อเล่ม + ความคืบหน้า
  GET  /api/reader/state    — ?source= ดูว่าอ่านถึงไหน (**ไม่ขยับที่คั่น**)
  POST /api/reader/next     — {source} ขอท่อนถัดไป (**ขยับที่คั่น**)
  POST /api/reader/seek     — {source, pos} ย้ายที่คั่นหน้า
  DELETE /api/reader/{source} — ลบเล่ม

🔑 **ทำไมไม่มีสถานะ "กำลังเล่น":** ฝั่ง client แค่เรียก `/next` ซ้ำๆ ตอนเล่น และ
หยุดเรียกตอนพัก — ที่คั่นหน้าเดินหน้าเองทุกครั้งที่ยิง ⇒ แอปดับกลางคัน/เน็ตหลุด
เสียหายมากสุดคือหนึ่งท่อน และไม่มี state ค้างฝั่ง server ให้ต้องล้าง
"""

import logging
import os

from fastapi import APIRouter, HTTPException, Request

from core.config import READER_DB_DEFAULT
from utils.http_limits import MAX_BODY_BYTES, json_body_capped
from utils.reader import BookmarkStore, BookStore, next_block
from utils.thaipdf import (
    fix_inserted_spaces,
    fix_leading_vowel_gaps,
    fix_thai_pua,
    has_inserted_spaces,
)

router = APIRouter(prefix="/api/reader", tags=["reader"])
logger = logging.getLogger(__name__)

# แยกไฟล์จาก chat_history.db เพื่อให้ backup/ล้างแยกกันได้ (เล่มละหลายเมกะไบต์)
# 🔴 **ค่า default** อยู่ที่ core/config.py ที่เดียว — ห้ามเขียน "reader.db" ซ้ำที่นี่
#    (เดิมประกาศ default เอง แล้ว utils/db_backup.py ไม่รู้จัก ⇒ ไม่เคยถูก backup เลย
#     23 วัน) · ส่วน getenv ต้องอยู่ตรงนี้ ไม่งั้น reload ในเทสจะไม่เห็น env ใหม่
#     แล้วเทสจะไปเขียนทับ DB ตัวจริง — มีเทสตรึงทั้งสองข้อ
_DB = os.getenv("READER_DB_PATH", READER_DB_DEFAULT)
os.makedirs(os.path.dirname(_DB) or ".", exist_ok=True)

_books = BookStore(_DB)
_marks = BookmarkStore(_DB)


# เพดานอ่านไฟล์จากดิสก์ — คนละเรื่องกับเพดาน HTTP (อันนั้นกัน RAM 2.5x/req ของ body)
# อ่านจากดิสก์ไม่ผ่าน body จึงตั้งกว้างได้: เล่มใหญ่สุดที่มีจริง 56.8 MB → เผื่อ ~3.5 เท่า
_MAX_DISK_BYTES = int(os.getenv("READER_MAX_DISK_BYTES", str(200 * 1024 * 1024)))


def _ingest(source: str, content: str) -> dict:
    """pipeline ขาเข้าร่วมของ /add และ /add-from-disk — สองเส้นต้องได้เล่มเหมือนกันเป๊ะ

    ซ่อม PUA ก่อนเสมอ (มาร์กในโซน PUA มองไม่เห็นใน detector/สูตรช่องว่าง) แล้วซ่อม
    ช่องว่างแทรกเฉพาะเล่มที่ detector ชี้ — สูตรมีขั้น A2 ที่กลืนวรรคจริงหลังมาร์ก
    เล่มสะอาดห้ามโดน (ดู utils/thaipdf.py)
    """
    content = fix_thai_pua(content)
    spacing_fixed = has_inserted_spaces(content)
    if spacing_fixed:
        content = fix_inserted_spaces(content)
    # โรคสระหน้า+วรรค ("เข้าไ ป") มีได้แม้ในเล่มที่ detector ไม่ชี้ (xianni 564 จุด)
    # — ตัวซ่อมเบา join เดียว ไม่กลืนวรรคจริง เล่มสะอาดแท้เป็น no-op (utils/thaipdf.py)
    content = fix_leading_vowel_gaps(content)
    content = content.strip()
    if not source:
        raise HTTPException(400, "ต้องมี source")
    if not content:
        raise HTTPException(400, "content ว่างเปล่า")

    _books.put(source, content)
    _marks.set(source, 0)

    blocks, p = 0, 0
    while p < len(content):
        _b, p = next_block(content, p)
        blocks += 1
    logger.info(
        f"[Reader] เก็บเล่ม {source!r}: {len(content)} ตัวอักษร / {blocks} ท่อน"
        f" (ซ่อมช่องว่างแทรก: {'ใช่' if spacing_fixed else 'ไม่จำเป็น'})"
    )
    return {"ok": True, "source": source, "chars": len(content), "blocks": blocks,
            "spacing_fixed": spacing_fixed}


def _require_book(source: str) -> str:
    text = _books.text(source)
    if text is None:
        raise HTTPException(404, f"ยังไม่มีเล่มนี้: {source}")
    return text


def _progress(source: str, text: str) -> dict:
    pos = min(_marks.get(source), len(text))
    return {
        "source": source,
        "pos": pos,
        "chars": len(text),
        # จบเล่มต้องได้ 100 เป๊ะ ไม่ใช่ 99.97 — ผู้ใช้อ่านตัวเลขนี้เป็น "จบหรือยัง"
        "percent": 100 if pos >= len(text) else int(pos * 100 / len(text)) if text else 0,
        "done": pos >= len(text),
    }


@router.post("/add")
async def add(request: Request):
    """เก็บเล่มใหม่ — ซ่อมวรรณยุกต์ที่ PDF เข้ารหัสเป็น PUA ให้ **ก่อน** เก็บ

    ⚠️ ต้องซ่อมตอนขาเข้าเท่านั้น — ซ่อมทีหลังจะทำให้ความยาวข้อความเปลี่ยน
    แล้วที่คั่นหน้าที่บันทึกไว้ก่อนหน้าเลื่อนทั้งหมด
    (ที่จริง `fix_thai_pua` แทนที่แบบตัวต่อตัวจึงยาวเท่าเดิม แต่ไม่ควรพึ่งคุณสมบัตินั้น)
    """
    data = await json_body_capped(request, MAX_BODY_BYTES)
    return _ingest((data.get("source") or "").strip(), data.get("content") or "")


@router.post("/add-from-disk")
async def add_from_disk(request: Request):
    """เก็บเล่มจากไฟล์ในดิสก์ — สำหรับเล่มที่ใหญ่เกินเพดาน HTTP (ห้ามขยายเพดานนั้น)

    เล่มจริงที่ชนปัญหา: Perfect World 56.8 MB = 5.7 เท่าของเพดาน body
    วิธีใช้: วางไฟล์ .txt ใน sandbox ของ fs_tools แล้วยิง {"path": "pw.txt"}

    - path ผ่าน safe-root เดียวกับ fs_* tools ทุกประการ — เส้นนี้เปิดให้ server
      อ่านไฟล์ตามคำสั่งผู้เรียก หลุด root เดียว = อ่านได้ทั้งคอนเทนเนอร์
    - รับเฉพาะไฟล์ข้อความ — PDF ต้องแกะเป็น .txt ก่อน (เล่มจริง 165 MB ใช้เวลา
      ระดับนาที ทำใน request = timeout + ยึด worker)
    """
    data = await json_body_capped(request, MAX_BODY_BYTES)  # body มีแค่ path — เล็กเสมอ
    path = (data.get("path") or "").strip()
    if not path:
        raise HTTPException(400, "ต้องมี path")

    from utils.fs_tools import FSError, _resolve_safe
    try:
        target = _resolve_safe(path)
    except FSError:
        # อย่าสะท้อน path/เหตุผลกลับไป — เป็นข้อมูลไว้เดาโครงสร้างดิสก์
        raise HTTPException(400, "path อยู่นอก sandbox หรือ resolve ไม่ได้")
    if not target.is_file():
        raise HTTPException(404, "ไม่พบไฟล์ใน sandbox")
    if target.suffix.lower() not in (".txt", ".md"):
        raise HTTPException(400, "รับเฉพาะ .txt/.md — PDF ให้แกะข้อความเป็น .txt ก่อน")
    size = target.stat().st_size
    if size > _MAX_DISK_BYTES:
        raise HTTPException(413, f"ไฟล์ {size} ไบต์ เกินเพดาน {_MAX_DISK_BYTES}")

    content = target.read_text(encoding="utf-8", errors="ignore")
    source = (data.get("source") or "").strip() or target.name
    return _ingest(source, content)


@router.get("/books")
def books():
    out = []
    for b in _books.list():
        pos = min(_marks.get(b["source"]), b["chars"])
        out.append({
            **b,
            "pos": pos,
            "percent": 100 if pos >= b["chars"] else int(pos * 100 / b["chars"]) if b["chars"] else 0,
        })
    return {"books": out}


@router.get("/state")
def state(source: str):
    """ดูความคืบหน้า — **ไม่ขยับที่คั่นหน้า** (ต่างจาก /next)"""
    return _progress(source, _require_book(source))


@router.post("/next")
async def next_(request: Request):
    """ขอท่อนถัดไปแล้วขยับที่คั่นหน้า

    จบเล่มคืน ``text: ""`` + ``done: true`` — เป็นสถานะปกติ ไม่ใช่ error
    เพื่อให้ client แยก "อ่านจบ" ออกจาก "พัง" ได้
    """
    data = await json_body_capped(request, MAX_BODY_BYTES)
    source = (data.get("source") or "").strip()
    text = _require_book(source)

    pos = _marks.get(source)
    block, new_pos = next_block(text, pos)
    if new_pos != pos:
        _marks.set(source, new_pos)

    # 🔴 `done` ของเส้นนี้ต้องแปลว่า "ไม่มีอะไรให้อ่านแล้ว" ไม่ใช่ "อ่านถึงท้ายเล่มแล้ว"
    # ของเดิมใช้ `pos >= len(text)` ซึ่งเป็นจริง **ตั้งแต่ตอนคืนท่อนสุดท้าย**
    # ⇒ client ที่เขียน `if done: break` จะทิ้งท่อนสุดท้ายทุกเล่มเสมอ
    # (เจอตอนเทส round-trip ระดับ API — เทสของ next_block เองมองไม่เห็นเพราะ
    #  มันไม่มีคำว่า done · `/state` ยังใช้ความหมาย "อ่านจบแล้ว" ตามเดิมได้ถูกต้อง)
    return {**_progress(source, text), "text": block, "done": not block}


@router.post("/seek")
async def seek(request: Request):
    data = await json_body_capped(request, MAX_BODY_BYTES)
    source = (data.get("source") or "").strip()
    text = _require_book(source)
    try:
        pos = int(data.get("pos", 0))
    except (TypeError, ValueError):
        raise HTTPException(400, "pos ต้องเป็นจำนวนเต็ม")
    _marks.set(source, max(0, min(pos, len(text))))
    return _progress(source, text)


@router.delete("/{source:path}")
def delete(source: str):
    _require_book(source)
    _books.delete(source)
    _marks.clear(source)
    return {"ok": True, "source": source}
