#!/usr/bin/env python3
"""เทียบเวอร์ชันที่ติดตั้งอยู่ตอนนี้ กับ requirements.lock ที่ prod ใช้จริง

ใช้ใน canary workflow (`.github/workflows/canary.yml`) หลัง `pip install -r requirements.txt`
เพื่อตอบว่า **"ถ้าอัป lock วันนี้ จะได้อะไรใหม่บ้าง"** — ถ้าเทสในรอบเดียวกันแดง จะได้เห็นทันที
ว่าน่าจะเป็นตัวไหน แทนที่จะต้องมานั่งไล่เอง (ตอนวินิจฉัยข้อ 22 ต้อง resolve มือ กว่าจะเห็นว่า
`cryptography` ข้าม major)

**สคริปต์นี้ไม่เคยล้ม** (exit 0 เสมอ) — drift เป็นเรื่องปกติ ไม่ใช่ความผิดพลาด
ตัวที่เป็นด่านตัดสินคือ `pytest` ในสเต็ปถัดไป ไม่ใช่ไฟล์นี้

รันมือ:  python scripts/deps_drift.py
"""

from __future__ import annotations

import os
import re
import sys
from importlib import metadata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOCK = REPO / "requirements.lock"


def _norm(name: str) -> str:
    """ชื่อแพ็กเกจตาม PEP 503 — `PyYAML` / `pyyaml` / `py_yaml` คือตัวเดียวกัน"""
    return re.sub(r"[-_.]+", "-", name).lower()


def _lock_versions() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in LOCK.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "==" not in line:
            continue
        name, version = line.split("==", 1)
        out[_norm(name)] = version.strip()
    return out


def _installed_versions() -> dict[str, str]:
    out: dict[str, str] = {}
    for dist in metadata.distributions():
        name = dist.metadata["Name"]
        if name:
            out[_norm(name)] = dist.version
    return out


def _major(version: str) -> str:
    return version.split(".")[0]


def main() -> int:
    lock = _lock_versions()
    installed = _installed_versions()

    both = sorted(set(lock) & set(installed))
    drift = [(p, lock[p], installed[p]) for p in both if lock[p] != installed[p]]
    major = [(p, o, n) for p, o, n in drift if _major(o) != _major(n)]
    # เฉพาะที่ lock มีแต่ไม่ได้ติดตั้ง — ทิศทางที่อันตรายกว่า (prod มีของที่ canary ไม่ได้เทส)
    missing = sorted(set(lock) - set(installed))

    lines: list[str] = []
    lines.append(f"เทียบกับ requirements.lock ({len(lock)} แพ็กเกจ) — ตรงกัน "
                 f"{len(both) - len(drift)}/{len(both)} · ต่าง {len(drift)}")
    if major:
        lines.append("")
        lines.append(f"⚠️  ข้าม major version {len(major)} ตัว — ตรวจ changelog ก่อนอัป lock:")
        for p, o, n in major:
            lines.append(f"      {p:34} {o:>14} → {n}")
    if drift:
        lines.append("")
        lines.append(f"{'package':34} {'lock (prod)':>14}    canary")
        lines.append("-" * 68)
        for p, o, n in drift:
            mark = "  ⚠️" if (p, o, n) in major else ""
            lines.append(f"{p:34} {o:>14} → {n}{mark}")
    if missing:
        lines.append("")
        lines.append(f"🔴 มีใน lock แต่ canary ไม่ได้ติดตั้ง ({len(missing)}): {', '.join(missing)}")
        lines.append("   → prod รันของที่รอบนี้ไม่ได้เทสเลย ตรวจว่า requirements.txt ตกอะไรไปหรือเปล่า")
    if not drift and not missing:
        lines.append("")
        lines.append("✅ ไม่มี drift — upstream ยังไม่ขยับจาก lock")

    report = "\n".join(lines)
    print(report)

    # โชว์บนหน้าสรุปของ GitHub Actions ด้วย จะได้ไม่ต้องเปิด log ทีละสเต็ป
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(f"### deps drift เทียบ requirements.lock\n\n```\n{report}\n```\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
