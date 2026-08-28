"""File Export — ขวัญเขียนข้อมูลเป็นไฟล์ให้ user ดาวน์โหลดจากแชท

ไฟล์ลงที่ EXPORT_DIR/<token>/<filename> · token = uuid4 hex (เดาไม่ได้ —
ระดับความปลอดภัยเดียวกับ /gen ของ image gen: ไม่มี auth แต่ URL สุ่ม)
เสิร์ฟผ่าน GET /api/files/{token}/{filename} (routers/sandbox.py)

⚠️ อยู่ใต้ NAS_DATA_PATH เพราะ /app/data เป็น volume mount เดียวที่ persist
หลัง recreate (ดูคอมเมนต์ยาวใน docker-compose.yml) — ห้ามย้ายไปที่อื่นใน /app
"""
import logging
import os
import re
import uuid

from core.config import NAS_DATA_PATH

logger = logging.getLogger(__name__)

EXPORT_DIR = os.path.join(NAS_DATA_PATH, "exports")
MAX_EXPORT_BYTES = int(os.getenv("EXPORT_MAX_BYTES", str(1024 * 1024)))  # 1MB

_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")
# อักขระที่พัง markdown link / URL / filesystem — แทนด้วย _
# (ช่องว่างกับวงเล็บทำ regex `\((\/[^)\s]+)\)` ฝั่ง frontend ตัดลิงก์ขาด ·
#  '#' เบราว์เซอร์ตัดเป็น fragment · '%' โดน percent-decode ฝั่ง server แล้วชื่อไม่ตรง)
_BAD_CHARS = re.compile(r'[\\/:*?"<>|()#%\s]+')


def sanitize_filename(filename: str) -> str:
    """เหลือแค่ basename ที่ปลอดภัย — คืน '' ถ้าใช้ไม่ได้เลย"""
    name = os.path.basename(str(filename or "").replace("\\", "/"))
    name = _BAD_CHARS.sub("_", name).strip("._")
    if not name:
        return ""
    return name[:120]


def save_export(filename: str, content: str) -> dict:
    """เขียน content ลงไฟล์ใหม่ แล้วคืน {ok, url} · ล้มเหลวคืน {ok: False, error}"""
    name = sanitize_filename(filename)
    if not name:
        return {"ok": False, "error": f"ชื่อไฟล์ใช้ไม่ได้: {filename!r}"}
    data = content.encode("utf-8")
    if len(data) > MAX_EXPORT_BYTES:
        return {"ok": False, "error": f"เนื้อหาใหญ่เกิน {MAX_EXPORT_BYTES // 1024}KB"}
    token = uuid.uuid4().hex
    folder = os.path.join(EXPORT_DIR, token)
    try:
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, name), "wb") as f:
            f.write(data)
    except OSError as e:
        logger.exception("[Export] เขียนไฟล์ไม่สำเร็จ")
        return {"ok": False, "error": f"เขียนไฟล์ไม่สำเร็จ: {e}"}
    logger.info(f"[Export] {name} ({len(data)}B) → {token}")
    return {"ok": True, "url": f"/api/files/{token}/{name}"}


def resolve_export(token: str, filename: str) -> str | None:
    """แปลง (token, filename) เป็น path จริง — คืน None ถ้าผิดรูป/ไม่มี/หลุด root"""
    if not _TOKEN_RE.fullmatch(token or ""):
        return None
    name = sanitize_filename(filename)
    if not name or name != filename:
        return None  # ชื่อที่ขอมาต้องตรงกับชื่อที่ sanitize แล้วเป๊ะ — กัน traversal ทุกทรง
    path = os.path.realpath(os.path.join(EXPORT_DIR, token, name))
    root = os.path.realpath(EXPORT_DIR)
    if not path.startswith(root + os.sep) or not os.path.isfile(path):
        return None
    return path
