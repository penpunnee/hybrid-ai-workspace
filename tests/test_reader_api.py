"""เส้น API ของตัวอ่านหนังสือ — `/api/reader/*`

ชั้นนี้ตอบคำถามที่ `test_reader.py` ตอบไม่ได้: **ต่อสายถูกไหม**
(ตรรกะการตัดท่อนกับที่คั่นหน้ามีเทสของตัวเองครบแล้ว)

รูปแบบที่ user ขอ: "พักได้ และจำได้ว่าอ่านถึงตรงไหน" ⇒ ฝั่ง client แค่เรียก
`/next` ซ้ำๆ ตอนเล่น และ **หยุดเรียกตอนพัก** — ไม่มีสถานะ "กำลังเล่น" ที่ต้องดูแล
ที่คั่นหน้าเดินหน้าเองทุกครั้งที่ยิง ⇒ แอปดับกลางคันเสียหายมากสุดคือหนึ่งท่อน
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """ชี้ดาต้าเบสของตัวอ่านไปที่ tmp — ห้ามแตะของจริงระหว่างเทส"""
    monkeypatch.setenv("READER_DB_PATH", str(tmp_path / "reader.db"))
    import importlib

    import routers.reader as R

    importlib.reload(R)
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(R.router)
    return TestClient(app)


BOOK = "นิยาย.pdf"
TEXT = ("ในความมืดมิดของคุกใต้ดินที่เย็นเยียบ " * 20).strip()


def _add(client, source=BOOK, text=TEXT):
    return client.post("/api/reader/add", json={"source": source, "content": text})


class TestAddingABook:
    def test_add_returns_size_and_block_count(self, client):
        r = _add(client)
        assert r.status_code == 200
        body = r.json()
        assert body["chars"] == len(TEXT)
        assert body["blocks"] >= 1

    def test_rejects_empty_content(self, client):
        assert client.post("/api/reader/add", json={"source": BOOK, "content": "  "}).status_code == 400

    def test_rejects_missing_source(self, client):
        assert client.post("/api/reader/add", json={"content": TEXT}).status_code == 400

    def test_book_shows_up_in_the_list(self, client):
        _add(client)
        books = client.get("/api/reader/books").json()["books"]
        assert [b["source"] for b in books] == [BOOK]

    def test_pua_is_repaired_on_the_way_in(self, client):
        """อัปโหลดข้อความที่ยังมี PUA ค้าง → ต้องถูกซ่อมก่อนเก็บ

        ถ้าปล่อยผ่าน TTS จะอ่านผิดทุกคำ และแก้ทีหลังไม่ได้เพราะที่คั่นหน้าจะเลื่อน
        """
        from utils.thaipdf import has_thai_pua

        # สร้างจาก chr() โดยตั้งใจ — เขียนตัวอักษร PUA ลงไฟล์ตรงๆ แล้วมันหายเงียบ
        # มาแล้ว 3 รอบในเซสชันนี้ (บางเครื่องมือ normalize ทิ้ง) ⇒ fixture ที่ตามอง
        # ไม่เห็นความต่างคือ fixture ที่เชื่อไม่ได้
        dirty = "องครักษ" + chr(0xF70E) + " ผ" + chr(0xF70A) + "านผู" + chr(0xF70B) + "เยาว" + chr(0xF70E)
        _add(client, source="pua.pdf", text=dirty)
        first = client.post("/api/reader/next", json={"source": "pua.pdf"}).json()
        assert not has_thai_pua(first["text"])
        assert "องครักษ์" in first["text"]


class TestReadingAndResuming:
    def test_next_returns_text_and_advances(self, client):
        _add(client)
        a = client.post("/api/reader/next", json={"source": BOOK}).json()
        b = client.post("/api/reader/next", json={"source": BOOK}).json()
        assert a["text"] and b["text"]
        assert b["pos"] > a["pos"]
        assert a["text"] != b["text"], "ยิงสองครั้งได้ท่อนเดิม = ที่คั่นหน้าไม่เดิน"

    def test_state_reports_where_we_are_without_advancing(self, client):
        """ต้องดูความคืบหน้าได้โดยไม่ทำให้เนื้อหาข้าม"""
        _add(client)
        client.post("/api/reader/next", json={"source": BOOK})
        s1 = client.get("/api/reader/state", params={"source": BOOK}).json()
        s2 = client.get("/api/reader/state", params={"source": BOOK}).json()
        assert s1["pos"] == s2["pos"] > 0

    def test_percent_moves_from_zero_to_one_hundred(self, client):
        _add(client)
        assert client.get("/api/reader/state", params={"source": BOOK}).json()["percent"] == 0
        # ทุกลูปที่วิ่งจนกว่า API จะบอกว่าจบ **ต้องมีเบรก** — ถ้าที่คั่นหน้าไม่เดิน
        # เทสจะแขวนแทนที่จะแดง ซึ่งใน CI แยกไม่ออกจาก runner ตาย
        for _ in range(200):
            if not client.post("/api/reader/next", json={"source": BOOK}).json()["text"]:
                break
        else:
            raise AssertionError("อ่านไม่จบใน 200 ท่อน — ที่คั่นหน้าน่าจะไม่เดินหน้า")
        assert client.get("/api/reader/state", params={"source": BOOK}).json()["percent"] == 100

    def test_end_of_book_is_reported_not_an_error(self, client):
        """จบเล่มต้องเป็นสถานะปกติ — client จะได้แยกจาก "พัง" ได้"""
        _add(client, text="สั้นมาก")
        client.post("/api/reader/next", json={"source": BOOK})
        r = client.post("/api/reader/next", json={"source": BOOK}).json()
        assert r["text"] == "" and r["done"] is True

    def test_seek_moves_the_bookmark(self, client):
        _add(client)
        client.post("/api/reader/seek", json={"source": BOOK, "pos": 100})
        assert client.get("/api/reader/state", params={"source": BOOK}).json()["pos"] == 100

    def test_reset_goes_back_to_the_start(self, client):
        _add(client)
        client.post("/api/reader/next", json={"source": BOOK})
        client.post("/api/reader/seek", json={"source": BOOK, "pos": 0})
        assert client.get("/api/reader/state", params={"source": BOOK}).json()["pos"] == 0

    def test_reading_the_whole_book_loses_nothing(self, client):
        """🔑 ด่านของ "ไม่อ่านตก ไม่อ่านซ้ำ" ที่ระดับ API จริง"""
        _add(client)
        out, guard = "", 0
        while True:
            r = client.post("/api/reader/next", json={"source": BOOK}).json()
            if r["done"]:
                break
            out += r["text"]
            guard += 1
            # 🔴 ต้องมีเบรก: ตอน mutation ทดสอบว่า "ถ้าที่คั่นหน้าไม่ขยับจะจับได้ไหม"
            # เทสนี้วนไม่รู้จบจน pytest ค้าง 2 นาที — จับได้ก็จริงแต่จับแบบแขวนเครื่อง
            # แยกไม่ออกจาก CI ตาย · เทสระดับ unit มี guard อยู่แล้ว ระดับ API ลืมใส่
            assert guard < 200, "ที่คั่นหน้าไม่เดินหน้า — /next คืนท่อนเดิมวนไป"
        assert out.replace(" ", "") == TEXT.replace(" ", "")


class TestUnknownBook:
    """กลุ่มควบคุม — เล่มที่ไม่มีต้องตอบ 404 ไม่ใช่เงียบหรือระเบิด"""

    def test_next_on_unknown_book_is_404(self, client):
        assert client.post("/api/reader/next", json={"source": "ไม่มี.pdf"}).status_code == 404

    def test_state_on_unknown_book_is_404(self, client):
        assert client.get("/api/reader/state", params={"source": "ไม่มี.pdf"}).status_code == 404


class TestBookmarkSurvivesRestart:
    def test_progress_is_still_there_after_reloading_the_module(self, client, tmp_path):
        """จำลอง "รีสตาร์ต server" — สร้าง app ใหม่จากไฟล์ดาต้าเบสเดิม

        นี่คือด่านของข้อที่ user อยากได้ที่สุด: พักแล้วกลับมาอ่านต่อ
        """
        _add(client)
        client.post("/api/reader/next", json={"source": BOOK})
        pos = client.get("/api/reader/state", params={"source": BOOK}).json()["pos"]

        import importlib

        import routers.reader as R

        importlib.reload(R)
        from fastapi import FastAPI

        app2 = FastAPI()
        app2.include_router(R.router)
        fresh = TestClient(app2)
        assert fresh.get("/api/reader/state", params={"source": BOOK}).json()["pos"] == pos
