import os
import logging
import requests

logger = logging.getLogger(__name__)

LINE_NOTIFY_TOKEN = os.getenv("LINE_NOTIFY_TOKEN", "")


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
