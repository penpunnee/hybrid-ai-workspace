"""`.dockerignore` ต้องมีและกัน secrets/ข้อมูลจริงออกจาก image (audit 2026-09-24 ข้อ 12)

ยืนยันบน NAS: image ที่ `ai-backend-1` ใช้อยู่มี `/app/.env` และ `/app/data` 605 MB ฝังใน layer
(`COPY . .` 660 MB) เพราะไม่มี `.dockerignore` · `docker history`/`save` อ่านคืนได้

⚠️ CI checkout ไม่มี `data/`/`.env` (gitignored) จึง**พิสูจน์ไม่ได้**ว่าไฟล์นี้ตัดจริง —
หลักฐานต้องมาจาก build บนเครื่องที่มี `.env` แล้ว `ls /app/.env` ในอิมเมจต้องไม่มี (devlog [ต่อ 13])
"""

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[1]
DOCKERIGNORE = REPO / ".dockerignore"


def _patterns() -> list[str]:
    return [l.strip() for l in DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")]


def test_มีไฟล์_dockerignore():
    assert DOCKERIGNORE.is_file(), "ไม่มี .dockerignore — COPY . . จะยัด .env และ data/ เข้า image"


def test_ตัด_secrets_และข้อมูลจริง():
    pats = set(_patterns())
    for must in (".env", "data/", ".git/", "*.db", "db_backups/", "logs/"):
        assert must in pats, f"ขาด {must!r} ใน .dockerignore"


def test_ห้ามตัด_env_example_และของที่เทสในอิมเมจต้องใช้():
    """`.env.*` จะพา `.env.example` หายไปด้วย (เทส 4 ตัวอ่าน) · tests/scripts/skills ต้องอยู่ใน image
    เพราะ CI รัน pytest *ในอิมเมจ*"""
    pats = _patterns()
    assert ".env.*" not in pats and ".env*" not in pats
    for keep in ("tests", "tests/", "scripts", "scripts/", "skills", "skills/", ".env.example", "CLAUDE.md"):
        assert keep not in pats, f"{keep!r} ถูกตัด — เทสในอิมเมจจะพัง"


def test_Dockerfile_ยังใช้_COPY_ทั้งโฟลเดอร์():
    """ratchet ตรงข้าม — ถ้าวันหนึ่ง Dockerfile เลิก COPY . . ไฟล์นี้จะกลายเป็นของตกรุ่นเงียบๆ"""
    assert "COPY . ." in (REPO / "Dockerfile").read_text(encoding="utf-8")
