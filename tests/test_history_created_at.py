"""เวลาใน history ต้องส่งถึง UI แบบแปลงโซนเวลาได้

ที่มา (2026-08-11): container prod รันเป็น UTC แต่ `save_message` เก็บ
`datetime.now().isoformat()` = สตริง naive ไม่มี offset — UI (pinned modal ฯลฯ)
เอา substring ไปโชว์ตรงๆ ผู้ใช้ไทยเห็นเวลาเพี้ยน +7 ชม. มาตลอดโดยไม่มีจุดเทียบ

กติกาใหม่:
- `save_message` ต้องเก็บ ISO แบบมี UTC offset (`+00:00`/`+07:00`) เสมอ
  → browser `new Date(iso)` แปลงเป็นโซนผู้ใช้ได้ถูกทุกเครื่อง
- `load_history(include_meta=True)` ต้องคืน `created_at` ให้ UI ใช้
  (เดิมคืนแค่ db_id/role/content/pinned — UI ไม่มีทางรู้เวลาเลย)
"""

import re

from utils.history import load_history, save_message

ASST = "เทส-เวลา"
SID = "s-created-at"

# ท้ายสตริงต้องเป็น offset เช่น +07:00 / +00:00 (หรือ Z)
_OFFSET_RE = re.compile(r"([+-]\d{2}:\d{2}|Z)$")


def test_include_meta_returns_created_at_with_offset(tmp_path):
    save_message(ASST, "user", "กี่โมงแล้ว", session_id=SID)
    rows = load_history(ASST, SID, include_meta=True)
    assert rows, "ต้องมีแถวที่เพิ่งบันทึก"
    row = rows[-1]
    assert "created_at" in row, "include_meta ต้องคืน created_at ให้ UI"
    assert _OFFSET_RE.search(row["created_at"]), (
        f"created_at ต้องมี UTC offset ท้ายสตริง (ได้ {row['created_at']!r}) "
        "— naive string ทำให้ UI โชว์เวลา UTC ตรงๆ บน prod"
    )
