#!/usr/bin/env python3
"""สร้าง/ตรวจ `.env.example` จาก registry (ทุกโมดูลใน `core.env_registry.MODULES`)

    python scripts/gen_env_example.py            # ตรวจอย่างเดียว (exit 1 ถ้าไม่ตรง)
    python scripts/gen_env_example.py --write    # เขียนทับ

⚠️ `scripts/` **ไม่ได้ mount เข้าคอนเทนเนอร์** (สำเนาค้างจากตอน build) — ไฟล์นี้
ตั้งใจให้รันบนเครื่อง dev/CI เท่านั้น ไม่ใช่บน prod
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.env_registry import load_all, render_env_example  # noqa: E402

TARGET = Path(__file__).resolve().parent.parent / ".env.example"


def main() -> int:
    load_all()  # ⚠️ import แค่ core.config = ไม่เห็นชื่อของ utils/llm.py
    current = TARGET.read_text() if TARGET.exists() else ""
    rendered = render_env_example(current)
    if "--write" in sys.argv:
        TARGET.write_text(rendered)
        print(f"เขียน {TARGET} แล้ว")
        return 0
    if current != rendered:
        print(".env.example ไม่ตรงกับ registry — รันด้วย --write แล้ว commit")
        return 1
    print(".env.example ตรงกับ registry แล้ว")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
