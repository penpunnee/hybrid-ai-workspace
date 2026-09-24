import logging
import requests

from core.env_registry import env_str

logger = logging.getLogger(__name__)

# ไฟล์นี้เป็นเจ้าของ (ก้อน 4 · 2026-09-24) — Dream Cycle ล้มเหลวจึงยิง LINE Notify
LINE_NOTIFY_TOKEN = env_str("LINE_NOTIFY_TOKEN", "", group="Dream Cycle", doc=(
    "LINE Notify token — แจ้งเตือนเมื่อ Dream Cycle ล้มเหลว · ขอได้ที่ https://notify-bot.line.me/my/\n"
    "ว่าง = ไม่แจ้ง"))


def send_line_notify(message: str) -> bool:
    """ส่ง LINE Notify — คืน True ถ้าสำเร็จ"""
    if not LINE_NOTIFY_TOKEN:
        return False
    try:
        r = requests.post(
            "https://notify-api.line.me/api/notify",
            headers={"Authorization": f"Bearer {LINE_NOTIFY_TOKEN}"},
            data={"message": message},
            timeout=10,
        )
        return r.status_code == 200
    except Exception as e:
        logger.warning(f"send_line_notify failed: {e}")
        return False
