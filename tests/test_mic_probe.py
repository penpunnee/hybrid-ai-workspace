"""เครื่องมือวัดสภาพไมค์ฝั่ง client — ส่งกลับมา log ที่ server

🎯 **ทำไมต้องมี:** งานวิจัย 3 รอบ (2026-08-24) ตอบคำถามชี้ขาดไม่ได้ 1 ข้อ —
**บนเครื่องของ user จริง `track.muted` และ event `mute`/`unmute` ยิงไหม**

หลักฐานที่มีอยู่ขัดกันเอง:
  · twilio-video.js#941 (ยุค iOS 13) : "ไม่ใช่ธง `muted`"
  · โค้ด production ของ Twilio วันนี้  : ใช้ `track.muted` + event `unmute` เป็นตัวจุดชนวน
  · LiveKit `needsReAcquisition`      : ใช้ `track.muted`
  · Amazon Chime                     : ฟัง `mute`/`unmute` ส่งต่อ observer
  · Caleb Chiam (ทดลองเอง 2025-04)   : iOS ตั้ง `muted:true` จริงตอนสายเข้า
                                        แล้วกลับเป็น `false` ทั้งที่ blob ยัง 0 ไบต์

⇒ ถ้าเดาผิด ตัวจุดชนวนของงาน ค. (ปุ่มกู้ไมค์) จะไม่มีวันยิง หรือยิงผิดจังหวะ
⇒ **วัดก่อน แล้วค่อยออกแบบ** — ไฟล์นี้คือชั้นวัด ไม่ใช่ตัวกู้

🔑 ทำไมต้องส่งกลับมาที่ server ไม่ใช่ `console.log`: อาการเกิดบน iPhone จริง
เท่านั้น และเราไม่มีทางเปิด devtools ตอนสายเข้า · ทุกอย่างที่พิสูจน์ได้วันนี้
พิสูจน์จาก `server.log` ทั้งนั้น
"""

from utils.voice import mic_probe_log_line


class TestFieldsThatAnswerTheOpenQuestion:
    def test_reports_track_muted_and_events(self):
        """3 ค่าที่งานวิจัยตอบไม่ได้ ต้องอยู่ในบรรทัดเดียวกันหมด"""
        line = mic_probe_log_line({
            "event": "silent", "reason": "zeros", "track_muted": True,
            "track_ready": "live", "cap_state": "running", "silent_ms": 10120,
        })
        assert "muted=True" in line
        assert "ready=live" in line
        assert "cap=running" in line
        assert "zeros" in line

    def test_distinguishes_the_two_detection_modes(self):
        """'zeros' (track ตาย) กับ 'no-callback' (context ค้าง) = คนละต้นเหตุ คนละตัวแก้"""
        a = mic_probe_log_line({"event": "silent", "reason": "zeros"})
        b = mic_probe_log_line({"event": "silent", "reason": "no-callback"})
        assert a != b

    def test_unmute_event_is_reported(self):
        """`unmute` = จังหวะที่การขัดจังหวะจบ — ตัวจุดชนวนที่ Twilio/LiveKit ใช้"""
        assert "unmute" in mic_probe_log_line({"event": "unmute", "track_muted": False})


class TestUnknownValuesMustNotLookLikeMeasuredOnes:
    def test_missing_track_muted_prints_as_unknown_not_false(self):
        """🔴 ค่าที่ยังไม่รู้ ห้ามพิมพ์เป็น False

        ถ้าไม่รู้แล้วพิมพ์ False เราจะสรุปว่า "iOS ไม่ตั้งธง muted" ทั้งที่จริง
        คือโค้ดอ่านค่าไม่ได้ — บทเรียนเดียวกับ `silence_s=None` ใน
        `interrupt_log_line` (ไม่รู้ค่า ≠ เข้าเงื่อนไข)
        """
        line = mic_probe_log_line({"event": "silent"})
        assert "muted=?" in line
        assert "muted=False" not in line

    def test_empty_payload_does_not_crash(self):
        """ชั้นวัดพังต้องไม่ล้ม session เสียง"""
        assert isinstance(mic_probe_log_line({}), str)

    def test_junk_payload_does_not_crash(self):
        assert isinstance(mic_probe_log_line({"event": 123, "track_muted": "yes"}), str)


class TestLineIsGreppable:
    def test_has_stable_prefix(self):
        """ต้อง grep เจอด้วย pattern เดียวเหมือน [Voice WS] อื่นๆ"""
        assert mic_probe_log_line({"event": "silent"}).startswith("mic_probe")


# ── ตรึงการต่อสายใน server.py ────────────────────────────────────────────────
# ⚠️ เคยพลาดแบบนี้มาแล้ว: ก๊อป `reread` ไปวางผิด handler ตั้งแต่ `f4e62e8`
# → NameError ฆ่า session เสียง + CI แดง 3 commit ติด (คอมเมนต์เตือนไว้ที่
#   server.py ตรง elif chain ของ /ws/voice)
import pathlib

SERVER = pathlib.Path(__file__).resolve().parent.parent / "server.py"
SRC = SERVER.read_text(encoding="utf-8")


def test_voice_ws_handles_mic_probe():
    """/ws/voice ต้องรับ type='mic_probe' — ไม่งั้นข้อความหล่นหายเงียบๆ"""
    assert 'elif t == "mic_probe"' in SRC


def test_mic_probe_is_wired_to_the_pure_log_helper():
    """ต้องเรียก mic_probe_log_line ไม่ใช่ประกอบสตริงเองในนั้น (เทสไม่ถึง)"""
    assert "mic_probe_log_line" in SRC


def test_mic_probe_helper_is_imported():
    """กัน NameError แบบเดียวกับที่เคยฆ่า session เสียงทั้งเส้น"""
    import re
    imports = re.findall(r"from utils\.voice import \(([^)]*)\)|from utils\.voice import ([^\n]*)", SRC)
    flat = " ".join(a + b for a, b in imports)
    assert "mic_probe_log_line" in flat, "เรียกใช้แต่ไม่ได้ import = NameError ตอนรันจริง"


class TestFieldsAddedAfterScrutinize20260825:
    """field ที่เพิ่มหลัง /scrutinize — ถ้า server ไม่พิมพ์ ก็เท่ากับ client ส่งลม"""

    def test_พิมพ์_visibility(self):
        line = mic_probe_log_line({"event": "silent", "visibility": "hidden"})
        assert "vis=hidden" in line

    def test_พิมพ์_note_ของ_resume_ที่ล้ม(self):
        line = mic_probe_log_line({"event": "resume-failed", "note": "cap:NotAllowedError"})
        assert "cap:NotAllowedError" in line

    def test_ไม่รู้ค่าต้องเป็นเครื่องหมายคำถาม_ไม่ใช่ค่าปลอม(self):
        line = mic_probe_log_line({"event": "silent"})
        assert "vis=?" in line


class TestHeartbeatFields:
    """ตัวนับดิบของ heartbeat — client ส่งมาแล้ว server ต้องพิมพ์ ไม่งั้นเท่ากับส่งลม"""

    def test_พิมพ์ตัวนับครบสามตัว(self):
        line = mic_probe_log_line({
            "event": "heartbeat", "frames": 58, "signal_frames": 58, "armed_ms": 4980,
        })
        assert "frames=58" in line
        assert "signal=58" in line
        assert "armed_ms=4980" in line

    def test_ศูนย์เฟรมต้องอ่านออกว่าเป็นศูนย์_ไม่ใช่_ไม่รู้(self):
        """0 = ไม่มีเฟรมเข้ามาเลย (ของจริง) · ? = อ่านค่าไม่ได้ — คนละเรื่องกัน"""
        line = mic_probe_log_line({"event": "heartbeat", "frames": 0, "signal_frames": 0})
        assert "frames=0" in line and "frames=?" not in line

    def test_probe_ของ_user_ไม่มีตัวนับ_ต้องเป็นเครื่องหมายคำถาม(self):
        assert "frames=?" in mic_probe_log_line({"event": "user-mute"})
