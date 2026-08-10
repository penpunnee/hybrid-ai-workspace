"""เส้นทางอัปโหลดเอกสารต้องซ่อมวรรณยุกต์ไทยที่ PDF เข้ารหัสเป็น PUA

`utils/thaipdf.fix_thai_pua()` มีเทสของตัวเองครบแล้ว (`tests/test_thaipdf.py`)
— ไฟล์นี้ตอบคำถามคนละข้อ: **มีใครเรียกมันจริงไหม**

🔑 เขียนแยกเพราะเคยพลาดรูปแบบนี้มาแล้ว: ฟังก์ชันถูกต้อง เทสเขียว แต่ไม่มีใครเรียก
⇒ ฟีเจอร์ตายสนิทโดยไม่มีอะไรแดง (`CLAUDE.md`: "ของที่ shipped ไม่ได้แปลว่าถูก build")

ผลกระทบถ้าไม่ต่อ: ไฟล์นิยายจริงของ user มี PUA **6.6% ของตัวอักษรทั้งเล่ม**
⇒ ทั้ง TTS และการค้นด้วย ChromaDB จะเจอข้อความที่วรรณยุกต์หายหมด
("ไม่"→"ไม" · "เต๋า"→"เตา") ซึ่งค้นยังไงก็ไม่เจอ และอ่านออกเสียงผิดทุกคำ
"""


class TestDecodeBytesRunsThePuaFix:
    """ตรวจที่ `_decode_bytes` โดยตรง — เป็นประตูเดียวที่ทุกไฟล์อัปโหลดผ่าน"""

    def test_pdf_branch_calls_fix_thai_pua(self, monkeypatch):
        """ปลอม pypdf ให้คืนข้อความที่มี PUA แล้วดูว่าออกมาสะอาดไหม

        ไม่ต้องสร้าง PDF จริง — สิ่งที่ต้องพิสูจน์คือ "ข้อความที่ pypdf คืนมา
        ถูกส่งผ่านตัวซ่อมก่อนถึงปลายทางหรือเปล่า" ซึ่งไม่เกี่ยวกับการ parse ไฟล์
        """
        import routers.documents as D

        raw_text = "องครักษ ผานผูเยาว"

        class _Page:
            def extract_text(self):
                return raw_text

        class _Reader:
            def __init__(self, *a, **k):
                self.pages = [_Page()]

        fake = type("pypdf", (), {"PdfReader": _Reader})
        monkeypatch.setitem(__import__("sys").modules, "pypdf", fake)

        out = D._decode_bytes(b"%PDF-fake", "นิยาย.pdf")
        assert "องครักษ์" in out
        assert "ผ่านผู้เยาว์" in out

    def test_no_private_use_characters_reach_the_caller(self, monkeypatch):
        """ด่านกวาดด้วยช่วง codepoint — ตัวที่เรายังไม่รู้จักจะได้ไม่หลุดเงียบๆ"""
        import routers.documents as D
        from utils.thaipdf import has_thai_pua

        class _Page:
            def extract_text(self):
                return "เตา กระเปา กตัญู นาิกา"

        class _Reader:
            def __init__(self, *a, **k):
                self.pages = [_Page()]

        monkeypatch.setitem(
            __import__("sys").modules, "pypdf", type("pypdf", (), {"PdfReader": _Reader})
        )
        assert not has_thai_pua(D._decode_bytes(b"%PDF-fake", "x.pdf"))

    def test_plain_text_upload_is_untouched(self, monkeypatch):
        """กลุ่มควบคุม: ไฟล์ข้อความธรรมดาต้องไม่ถูกแตะ

        ถ้าเทสนี้แดงแปลว่าเราไปแก้ข้อความของไฟล์ประเภทอื่นด้วยโดยไม่ตั้งใจ
        """
        import routers.documents as D

        text = "ผู้เยาว์เดินผ่านเต๋าแห่งหนึ่ง"
        assert text in D._decode_bytes(text.encode("utf-8"), "note.txt")
