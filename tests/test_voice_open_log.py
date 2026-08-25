"""log ตอน /ws/voice รับสาย — ตัวชี้ขาดว่า client "ต่อใหม่กลางสาย" หรือ "เริ่มสายใหม่"

🐛 ที่มา (2026-08-25): ไล่อาการ "สายโทรเข้า → ไมค์ตาย → ไม่กลับมาเลย" แล้วติดตรงที่
**พิสูจน์ไม่ได้ว่า WebSocket ฝั่ง client หลุดตอนสายเข้าหรือเปล่า** — `server.py` ไม่เคย
log อะไรตอน `websocket.accept()` เลย

ที่ผ่านมาต้องอนุมานจาก proxy: `AudioLevelMeter` ถูกสร้างนอกลูป reconnect ⇒ ค่า
"ตั้งแต่เริ่ม N นาที" รีเซ็ตเมื่อมี WS handler ใหม่ · ใช้ได้แต่**อ่านได้เฉพาะตอนขวัญพูด**
(meter วัด response.data) ⇒ ถ้าสายเข้าแล้วขวัญเงียบ ก็ไม่มีบรรทัดให้ดูพอดี

🔑 ต้องแยก 2 อย่างนี้ให้ได้**ในบรรทัดเดียว ไม่ต้องเอาเวลาไปไล่เทียบเอง**
(บทเรียนเดียวกับ `since_mic_s` ใน interrupt_log_line — "ไม่มีอะไร log ไว้" ทำให้
เสียเวลาไป 2 รอบ):
  · ครั้งที่ 1 ของ session_id นั้น        = เริ่มสายใหม่
  · ครั้งที่ 2+ ห่างกันไม่กี่วินาที        = client ต่อใหม่ (scheduleRetry ทำงาน)
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from utils.voice import VoiceOpenTracker, voice_open_log_line


class TestVoiceOpenLogLine:
    def test_บอกครั้งที่เท่าไหร่ของ_session(self):
        line = voice_open_log_line("s_1", "kwan", nth=1, since_prev_s=None)
        assert "s_1" in line and "kwan" in line
        assert "ครั้งที่ 1" in line

    def test_ครั้งแรกต้องไม่โชว์ระยะห่าง_และห้ามพิมพ์_0(self):
        """`None` = ไม่มีค่า ≠ 0.0 วินาที — เดาว่าใช่คือวิธีที่ทำให้หลงทาง"""
        line = voice_open_log_line("s_1", "kwan", nth=1, since_prev_s=None)
        assert "0.0" not in line

    def test_ห่างกันไม่กี่วินาที_ติดธงว่าน่าจะต่อใหม่(self):
        again = voice_open_log_line("s_1", "kwan", nth=2, since_prev_s=3.4)
        assert "ครั้งที่ 2" in again
        assert "3.4" in again
        assert "ต่อใหม่" in again

    def test_RED_ห่างกันเป็นชั่วโมงห้ามติดธงต่อใหม่(self):
        """`session_id` = id ของ**ห้องแชท** ไม่ใช่ของสาย (app.tsx:900 ส่ง
        `sessionId || 'voice_default'`) ⇒ เปิดสายรอบสองในห้องเดิม nth=2 เสมอ

        ถ้าติดธงทุกบรรทัดที่ nth>=2 ธงจะไม่มีความหมาย = ตาบอดแบบใหม่
        (กฎเดียวกับที่ `interrupt_log_line` เขียนไว้เองตอนแก้ 2026-08-23)
        """
        line = voice_open_log_line("s_1", "kwan", nth=2, since_prev_s=3600.0)
        assert "ครั้งที่ 2" in line
        assert "3600.0" in line, "ตัวเลขดิบต้องยังอยู่ — คนอ่านตัดสินเองได้"
        assert "ต่อใหม่" not in line, "ห่างเป็นชั่วโมง = สายใหม่ ไม่ใช่ reconnect"

    def test_ระยะห่างดิบต้องพิมพ์เสมอแม้ไม่ติดธง(self):
        """แยก **ข้อมูล** ออกจาก **ข้อสรุป** — ธงหายได้ ตัวเลขห้ามหาย"""
        assert "120.0" in voice_open_log_line("s_1", "kwan", nth=2, since_prev_s=120.0)

    def test_session_id_ที่มีขึ้นบรรทัดใหม่ต้องปลอมบรรทัด_log_ไม่ได้(self):
        """`session_id` มาจาก query param ตรงๆ — บรรทัดนี้เป็นหลักฐานทางนิติเวช
        ถ้าปลอมได้ก็หมดความหมาย"""
        line = voice_open_log_line("s_1\n2026-01-01 00:00:00 [Voice WS] ของปลอม",
                                   "kwan", nth=1, since_prev_s=None)
        assert "\n" not in line and "\r" not in line

    def test_session_id_ยาวเกินต้องถูกตัด(self):
        line = voice_open_log_line("x" * 500, "kwan", nth=1, since_prev_s=None)
        assert len(line) < 200


class TestVoiceOpenTracker:
    def test_session_ใหม่เริ่มที่ครั้งที่_1_และไม่มีระยะห่าง(self):
        t = VoiceOpenTracker()
        assert t.note("s_1", now=100.0) == (1, None)

    def test_session_เดิมนับต่อพร้อมระยะห่าง(self):
        t = VoiceOpenTracker()
        t.note("s_1", now=100.0)
        assert t.note("s_1", now=103.5) == (2, 3.5)

    def test_คนละ_session_ไม่ปนกัน(self):
        t = VoiceOpenTracker()
        t.note("s_1", now=100.0)
        assert t.note("s_2", now=101.0) == (1, None)
        assert t.note("s_1", now=102.0) == (2, 2.0)

    def test_ไม่โตไม่มีเพดาน(self):
        """server อยู่ยาวเป็นเดือน — dict ที่ไม่มีเพดานคือ leak"""
        t = VoiceOpenTracker(max_entries=10)
        for i in range(50):
            t.note(f"s_{i}", now=float(i))
        assert len(t._seen) <= 10

    def test_RED_ไล่ตัวที่ไม่ได้ใช้นานสุด_ไม่ใช่ตัวที่ใส่ก่อนสุด(self):
        """assign ทับ key เดิมใน dict ของ Python **ไม่ย้ายลำดับ**
        ⇒ ถ้า pop ตัวแรกเฉยๆ session ที่ใช้อยู่ตลอดจะโดนไล่ก่อนตัวที่ตายแล้ว
        = `ครั้งที่` เด้งกลับเป็น 1 ทั้งที่เป็นสายเดียวกัน"""
        t = VoiceOpenTracker(max_entries=3)
        t.note("ตัวที่ใช้อยู่", now=0.0)
        t.note("a", now=1.0)
        t.note("b", now=2.0)
        t.note("ตัวที่ใช้อยู่", now=3.0)      # แตะซ้ำ = ยังใช้อยู่
        t.note("c", now=4.0)                   # เต็ม → ต้องไล่ "a" ไม่ใช่ตัวที่ใช้อยู่
        nth, _ = t.note("ตัวที่ใช้อยู่", now=5.0)
        assert nth == 3, "ตัวที่แตะล่าสุดต้องไม่ถูกไล่"


SERVER = (pathlib.Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")


def test_server_เรียก_helper_จริง():
    assert "voice_open_log_line" in SERVER


def test_server_import_helper_แล้ว():
    """กัน NameError แบบเดียวกับที่เคยฆ่า session เสียงทั้งเส้น"""
    import re
    imports = re.findall(r"from utils\.voice import \(([^)]*)\)|from utils\.voice import ([^\n]*)", SERVER)
    flat = " ".join(a + b for a, b in imports)
    assert "voice_open_log_line" in flat
    assert "VoiceOpenTracker" in flat


def test_log_อยู่หลัง_accept_ไม่ใช่ก่อน():
    """ก่อน accept ยังไม่มีสาย — log ตรงนั้นจะนับรวมคนที่โดน gate ปิดด้วย

    ⚠️ ต้องหา **จุดเรียกจริง** ไม่ใช่ชื่อฟังก์ชันเฉยๆ — รอบแรกเทสนี้จับบรรทัด
    `import` ที่อยู่ต้นไฟล์แล้วแดงทั้งที่โค้ดถูก (assertion ชี้ผิดที่ = เทสโกหก)
    """
    accept = SERVER.index("await websocket.accept()")
    call = SERVER.index("logger.info(voice_open_log_line(")
    assert call > accept, "ต้อง log หลัง accept"


def test_ตัวนับอยู่ระดับโมดูล_ไม่ใช่ในตัว_handler():
    """อยู่ใน handler = สร้างใหม่ทุกสาย ⇒ นับได้ 1 ตลอด = วัดสิ่งที่ตั้งใจวัดไม่ได้เลย"""
    decorator = SERVER.index('@app.websocket("/ws/voice/{assistant_slug}")')
    assert SERVER.index("_VOICE_OPENS = VoiceOpenTracker()") < decorator
