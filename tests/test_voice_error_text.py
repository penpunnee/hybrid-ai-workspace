"""ข้อความ error ที่ส่งถึงผู้ใช้เมื่อ Google ตัดสายเสียง — ต้องอ่านรู้เรื่อง ไม่ใช่ข้อความดิบ

prod 10-01/10-02: client ได้ "1011 None. Internal error encountered." ไปโชว์ตรงๆ (ตอนยอมแพ้)
· Google ขัดข้อง กับ โควตาหมด ต้องบอกต่างกัน (อย่างแรกลองใหม่อีกสักครู่ได้ · อย่างหลังต้องรอนาน)
"""
import ast
import os
from pathlib import Path

os.environ.setdefault("UI_PASSWORD", "")

from utils.voice import live_error_text


class _APIError(Exception):
    pass


def test_1011_internal_error_บอกว่า_google_ขัดข้อง():
    t = live_error_text(_APIError("1011 None. Internal error encountered."))
    assert "Google ขัดข้อง" in t and "1011" in t and "Internal error" not in t


def test_1011_quota_บอกว่าโควตาเต็ม_ไม่ปนกับขัดข้อง():
    t = live_error_text(_APIError("1011 None. Resource has been exhausted (e.g. check quota)."))
    assert "โควตา" in t and "ขัดข้อง" not in t


def test_error_อื่น_คงข้อความเดิม():
    assert live_error_text(ValueError("อะไรก็ไม่รู้")) == "อะไรก็ไม่รู้"


def test_1008_คงเดิม_client_ใช้ตัดสินพักสาย():
    msg = "1008 None. The operation was aborted."
    assert live_error_text(_APIError(msg)) == msg


def test_send_loop_ส่งข้อความที่แปลแล้วให้_client():
    src = (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "send_loop":
            seg = ast.get_source_segment(src, node)
            if "[Voice WS] send_loop" in seg:
                tail = seg[seg.index("[Voice WS] send_loop"):]
                assert '"message": live_error_text(e)' in tail
                return
    raise AssertionError("หา send_loop ของ /ws/voice ไม่เจอ — โครงเปลี่ยน")
