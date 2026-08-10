"""อ่านหนังสือ/นิยายทีละท่อน + จำที่คั่นหน้า

user เคาะ 2026-08-09: "โยนนิยาย PDF ให้อ่านให้ฟัง — **พักได้ และจำได้ว่าอ่านถึงตรงไหน**"

🔑 **ส่วนนี้ไม่กินโควตาเลยสักนิด** เป็น state ในดาต้าเบสของเราล้วนๆ ⇒ สร้าง/เทสได้เต็มที่
โดยไม่ต้องรอตัดสินใจเรื่องแหล่งเสียง และเปลี่ยนแหล่งเสียงทีหลังได้โดยไม่ต้องรื้อไฟล์นี้

**ทำไมไม่ใช้ chunk ของ ChromaDB:** chunk ที่ `index_document()` สร้างมีไว้ *ค้นความหมาย*
(500 ตัวอักษร + **overlap 50**) — overlap แปลว่าอ่านเรียงกันแล้วจะ**อ่านซ้ำท่อนละ 50
ตัวอักษรทุกท่อน** · ที่คั่นหน้าจึงเก็บเป็น **ตำแหน่งตัวอักษรในต้นฉบับ** ซึ่งตรงเป๊ะและ
รอดแม้ re-index ใหม่ด้วยขนาด chunk คนละแบบ
"""

import sqlite3
import time

# ขนาดท่อนที่ส่งให้ TTS ต่อครั้ง
#
# ⚠️ วัดจริง 2026-08-09: **Gemini TTS ตัดข้อความทิ้งเงียบๆ ที่ ~950 ตัวอักษร**
# (ป้อน 1,500 ได้เสียงเท่ากับพูดจริงแค่ ~950 · ไม่มี error ไม่มี log ได้ไบต์กลับมาปกติ)
# ส่วน edge-tts เทสด้วยวิธีผ่าครึ่งแล้ว **ไม่ตัด** (เต็ม 22.7 วิ ≈ ครึ่ง 10.8 + 12.3)
#
# ตั้งต่ำกว่าเพดานที่วัดได้ชัดเจนเพราะ (1) แหล่งเสียงเปลี่ยนพฤติกรรมได้
# (2) ท่อนสั้นกว่า = พักแล้วอ่านต่อได้ละเอียดกว่า ไม่ต้องย้อนฟังซ้ำเยอะ
READ_BLOCK_CHARS = 600

# ระยะที่ยอมถอยกลับมาหาช่องว่างเพื่อไม่ตัดกลางคำ (เกินนี้ยอมตัดแข็ง)
_BACKTRACK = 120


def next_block(text: str, pos: int, target: int = READ_BLOCK_CHARS) -> tuple[str, int]:
    """คืน ``(ท่อนถัดไป, ตำแหน่งใหม่)`` — pure → เทสได้โดยไม่ต้องมีไฟล์/ดาต้าเบส

    ตัดที่ **ช่องว่าง** เพราะภาษาไทยไม่เว้นวรรคระหว่างคำ แต่เว้นระหว่างวลี/ประโยค
    ⇒ ช่องว่างคือรอยต่อเดียวที่ปลอดภัย · ตัดกลางคำ = TTS อ่านเพี้ยนทันที

    ⚠️ **ต้องเดินหน้าเสมอ** แม้หาช่องว่างไม่เจอ (เช่นตาราง/URL ยาวๆ ที่แกะจาก PDF)
    ไม่งั้นตัวเรียกจะวนอ่านท่อนเดิมตลอดกาลแบบเงียบสนิท
    """
    if not text:
        return "", 0
    n = len(text)
    pos = max(0, min(int(pos), n))
    if pos >= n:
        return "", n

    end = min(pos + max(1, int(target)), n)
    if end < n:
        # ถอยหารอยต่อล่าสุดในระยะที่ยอมรับได้
        #
        # 🔴 ต้องนับ `\n` ด้วย ไม่ใช่แค่ช่องว่าง — `pypdf` ใส่ `\n` ท้ายทุกบรรทัดของ PDF
        # และบรรทัดภาษาไทยจำนวนมาก **ไม่มีช่องว่างเลยสักตัว** (ไทยไม่เว้นวรรคระหว่างคำ)
        # ⇒ มองหาแต่ `" "` จะหารอยต่อไม่เจอแล้วตัดแข็งกลางคำ = TTS อ่านเพี้ยน
        # (เจอตอนรัน PDF จริง ไม่ใช่จากการนึกเอาเอง — เทสสังเคราะห์ที่ใช้ข้อความ
        #  ที่มีช่องว่างสวยงามมองไม่เห็นเคสนี้เลย)
        lo = max(pos, end - _BACKTRACK)
        cut = max(text.rfind(" ", lo, end), text.rfind("\n", lo, end))
        if cut > pos:
            end = cut + 1        # กินรอยต่อไปด้วย ท่อนถัดไปจะได้ไม่ขึ้นต้นด้วยช่องว่าง

    block = text[pos:end]
    if not block.strip():
        # เจอแต่ช่องว่าง/ขึ้นบรรทัด — ข้ามไปเลย แต่ยังต้องเดินหน้า
        return block, end
    return block, end


class BookmarkStore:
    """ที่คั่นหน้าแบบอยู่รอดข้ามการรีสตาร์ต (SQLite)

    คีย์คือ ``source`` (ชื่อไฟล์ที่อัปโหลด) — ตัวเดียวกับที่ `index_document()` ใช้
    จึงอ้างถึงเล่มเดียวกันได้โดยไม่ต้องมีตารางแมปเพิ่ม
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init()

    def _conn(self):
        return sqlite3.connect(self.db_path, timeout=10)

    def _init(self) -> None:
        with self._conn() as c:
            c.execute(
                """CREATE TABLE IF NOT EXISTS reading_progress (
                       source     TEXT PRIMARY KEY,
                       pos        INTEGER NOT NULL,
                       updated_at REAL    NOT NULL
                   )"""
            )

    def get(self, source: str) -> int:
        with self._conn() as c:
            row = c.execute(
                "SELECT pos FROM reading_progress WHERE source = ?", (source,)
            ).fetchone()
        return int(row[0]) if row else 0

    def set(self, source: str, pos: int) -> None:
        """เขียนทับเสมอ — สะสมแถวเมื่อไหร่ `get` จะหยิบแถวไหนก็ไม่รู้"""
        with self._conn() as c:
            c.execute(
                """INSERT INTO reading_progress (source, pos, updated_at) VALUES (?, ?, ?)
                   ON CONFLICT(source) DO UPDATE SET pos = excluded.pos,
                                                     updated_at = excluded.updated_at""",
                (source, max(0, int(pos)), time.time()),
            )

    def clear(self, source: str) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM reading_progress WHERE source = ?", (source,))
