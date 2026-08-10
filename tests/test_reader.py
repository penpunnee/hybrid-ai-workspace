"""ตัวอ่านหนังสือทีละท่อน + จำที่คั่นหน้า — user เคาะ 2026-08-09:
"โยนนิยาย PDF ให้อ่านให้ฟัง · **สามารถพักได้ และจำได้ว่าอ่านถึงตรงไหนด้วย**"

**ทำไมต้องมีชั้นนี้แยกจาก TTS:** ส่วนที่ user อยากได้ที่สุด (พัก/อ่านต่อ/จำที่คั่น)
**ไม่กินโควตาเลยสักนิด** — เป็น state ในดาต้าเบสของเราล้วนๆ ⇒ สร้างและเทสได้เต็มที่
โดยไม่ต้องรอตัดสินใจเรื่องแหล่งเสียง และเปลี่ยนแหล่งเสียงทีหลังได้โดยไม่ต้องรื้อส่วนนี้

**ทำไมตัดด้วยตัวอักษรไม่ใช่ chunk ของ ChromaDB:** chunk ที่ index ไว้ถูกออกแบบมาเพื่อ
*ค้นความหมาย* (500 ตัวอักษร + overlap 50) — overlap แปลว่าถ้าอ่านเรียงกันจะ**อ่านซ้ำ**
ท่อนละ 50 ตัวอักษรทุกท่อน · ที่คั่นหน้าจึงต้องเป็น **ตำแหน่งตัวอักษรในต้นฉบับ** ซึ่งตรงเป๊ะ
และรอดแม้จะ re-index ใหม่ด้วยขนาด chunk คนละแบบ

⚠️ **ข้อจำกัด:** ไฟล์นี้เทสการตัดท่อนกับที่คั่นหน้าเท่านั้น — ไม่ได้พิสูจน์ว่า TTS
อ่านออกเสียงถูก หรือ pypdf แกะ PDF ได้ครบ
"""

import pytest

from utils.reader import READ_BLOCK_CHARS, next_block

# ภาษาไทยไม่เว้นวรรคระหว่างคำ แต่เว้นระหว่างวลี/ประโยค → ช่องว่างคือรอยต่อที่ปลอดภัยที่สุด
THAI = (
    "ในความมืดมิดของคุกใต้ดินที่เย็นเยียบ "
    "สือเฮ่านั่งขัดสมาธิอยู่บนพื้นหินที่ชื้นแฉะ "
    "โซ่ตรวนที่พันธนาการร่างกายของเขาส่งเสียงกระทบกันเบาๆ "
    "ยามที่เขาขยับตัว"
)


class TestBlockSplitting:
    def test_returns_text_and_next_position(self):
        block, pos = next_block(THAI, 0, target=40)
        assert block, "ท่อนแรกต้องไม่ว่าง"
        assert pos > 0

    def test_never_cuts_inside_a_word(self):
        """ตัดกลางคำไทย = TTS อ่านเพี้ยนทันที (ไม่มีช่องว่างให้เดาขอบเขตคำ)

        ท่อนที่คืนมาต้องจบตรงช่องว่างของต้นฉบับ หรือจบพอดีที่ท้ายเรื่อง
        """
        block, pos = next_block(THAI, 0, target=40)
        assert pos == len(THAI) or THAI[pos - 1] == " " or THAI[pos] == " ", (
            f"ตัดกลางคำที่ตำแหน่ง {pos}: ...{THAI[max(0,pos-12):pos+12]}..."
        )

    def test_reading_all_blocks_reproduces_the_whole_text(self):
        """🔑 ด่านสำคัญที่สุด: อ่านครบทุกท่อนแล้วต้องได้ต้นฉบับคืนมาเป๊ะ

        กันทั้ง **อ่านตก** (ข้ามเนื้อหา) และ **อ่านซ้ำ** (overlap) ในเทสเดียว —
        สองอาการนี้คือสิ่งที่ผู้ใช้จะจับได้ทันทีตอนฟัง แต่เทสที่ดูแค่ "ได้ข้อความมา"
        มองไม่เห็นเลยสักอาการ
        """
        out, pos, guard = "", 0, 0
        while pos < len(THAI):
            block, pos = next_block(THAI, pos, target=40)
            out += block
            guard += 1
            assert guard < 500, "วนไม่จบ — next_block ไม่เดินหน้า"
        assert out.replace(" ", "") == THAI.replace(" ", "")

    def test_blocks_never_start_with_whitespace(self):
        """ตัดแล้วต้อง "กิน" ช่องว่างไปด้วย ไม่ปล่อยให้ไปขึ้นต้นท่อนถัดไป

        🔴 เพิ่มเพราะ mutation รอด: เปลี่ยน `end = cut + 1` → `end = cut` แล้วเทสเขียวหมด
        (เทส round-trip ตัดช่องว่างออกก่อนเทียบ จึงมองไม่เห็น) — ช่องว่างนำหน้าไม่ทำให้
        เนื้อหาหาย แต่ทำให้ท่อนที่ส่งเข้า TTS ขึ้นต้นด้วยช่องว่างทุกท่อน
        """
        pos, guard = 0, 0
        while pos < len(THAI):
            block, pos = next_block(THAI, pos, target=40)
            assert block == block.lstrip(" "), f"ท่อนขึ้นต้นด้วยช่องว่าง: {block!r}"
            guard += 1
            assert guard < 500

    def test_breaks_on_newlines_too_not_only_spaces(self):
        """🔴 เจอตอนรัน PDF จริง: `pypdf` ใส่ `\\n` ท้ายทุกบรรทัดของ PDF

        บรรทัดภาษาไทยจำนวนมาก **ไม่มีช่องว่างเลยสักตัว** (ไทยไม่เว้นวรรคระหว่างคำ)
        ⇒ ถ้ามองหาแต่ `" "` จะหารอยต่อไม่เจอแล้วตัดแข็งกลางคำ · `\\n` คือขอบเขต
        บรรทัดจริงในต้นฉบับ ปลอดภัยพอ ๆ กับช่องว่าง

        เทสนี้เขียนหลังเห็นข้อความจริงที่แกะจาก PDF ไม่ใช่จากการนึกเอาเอง
        """
        pdfish = "บรรทัดแรกไม่มีช่องว่างเลยสักตัวยาวมากพอสมควร\nบรรทัดที่สองก็ไม่มีช่องว่างเช่นกันยาวพอกัน\nบรรทัดที่สาม"
        block, pos = next_block(pdfish, 0, target=50)
        assert pos == len(pdfish) or pdfish[pos - 1] in " \n", (
            f"ตัดกลางคำเพราะมองไม่เห็น \\n: …{pdfish[max(0,pos-12):pos+12]!r}…"
        )

    def test_always_makes_progress_even_with_no_space_to_break_on(self):
        """ข้อความยาวไม่มีช่องว่างเลย (เช่นตารางหรือ URL ยาวๆ ใน PDF)

        ถ้าไม่ยอมตัดแข็ง `pos` จะไม่ขยับ → ลูปอ่านค้างตลอดกาลและเงียบสนิท
        """
        blob = "ก" * 500
        block, pos = next_block(blob, 0, target=100)
        assert pos > 0 and block

    def test_at_end_of_book_returns_empty_and_stays_put(self):
        block, pos = next_block(THAI, len(THAI), target=40)
        assert block == ""
        assert pos == len(THAI)

    def test_position_past_the_end_is_clamped(self):
        """ที่คั่นหน้าค้างจากไฟล์เวอร์ชันเก่าที่ยาวกว่า → ต้องไม่ระเบิด"""
        block, pos = next_block(THAI, len(THAI) + 9_999, target=40)
        assert block == ""
        assert pos == len(THAI)

    def test_negative_position_is_treated_as_start(self):
        block, _pos = next_block(THAI, -5, target=40)
        assert block.startswith("ในความมืดมิด")

    def test_default_block_size_fits_what_tts_handles(self):
        """เพดานที่วัดจริง: Gemini TTS ตัดทิ้งเงียบๆ ที่ ~950 ตัวอักษร (08-09)

        เผื่อไว้ให้ต่ำกว่านั้นชัดเจน เพราะ edge-tts อาจเปลี่ยนพฤติกรรมได้
        และท่อนสั้นกว่า = พักแล้วอ่านต่อได้ละเอียดกว่า
        """
        assert 300 <= READ_BLOCK_CHARS <= 900

    def test_empty_text_is_not_a_crash(self):
        block, pos = next_block("", 0, target=40)
        assert (block, pos) == ("", 0)


class TestBookmarkStore:
    """ที่คั่นหน้าต้องรอดข้ามการรีสตาร์ต — ไม่งั้น "จำได้ว่าอ่านถึงไหน" ก็ไม่จริง"""

    @pytest.fixture()
    def store(self, tmp_path):
        from utils.reader import BookmarkStore

        return BookmarkStore(str(tmp_path / "b.db"))

    def test_unknown_book_starts_at_the_beginning(self, store):
        assert store.get("ยังไม่เคยอ่าน.pdf") == 0

    def test_saves_and_reads_back(self, store):
        store.set("นิยาย.pdf", 1234)
        assert store.get("นิยาย.pdf") == 1234

    def test_survives_reopening_the_database(self, store, tmp_path):
        """เทสหลักของข้อ "พักแล้วกลับมาอ่านต่อ" — ปิดแอปแล้วเปิดใหม่ต้องยังจำได้"""
        from utils.reader import BookmarkStore

        store.set("นิยาย.pdf", 555)
        assert BookmarkStore(str(tmp_path / "b.db")).get("นิยาย.pdf") == 555

    def test_updating_replaces_instead_of_appending(self, store):
        """เขียนทับ ไม่ใช่สะสมแถว — ไม่งั้น `get` จะหยิบแถวไหนก็ไม่รู้"""
        for p in (10, 20, 30):
            store.set("นิยาย.pdf", p)
        assert store.get("นิยาย.pdf") == 30

    def test_books_do_not_share_a_bookmark(self, store):
        """กลุ่มควบคุม: อ่านสองเล่มสลับกันต้องไม่ทับที่คั่นของกันและกัน"""
        store.set("เล่มหนึ่ง.pdf", 100)
        store.set("เล่มสอง.pdf", 200)
        assert (store.get("เล่มหนึ่ง.pdf"), store.get("เล่มสอง.pdf")) == (100, 200)

    def test_clearing_sends_it_back_to_the_start(self, store):
        store.set("นิยาย.pdf", 900)
        store.clear("นิยาย.pdf")
        assert store.get("นิยาย.pdf") == 0
