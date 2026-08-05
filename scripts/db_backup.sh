#!/usr/bin/env bash
# db_backup.sh — สำรอง SQLite databases ของ Hybrid AI Workspace
#
# ทำไม: chat_history.db เก็บ sessions/messages/**feedback (👍/👎)**/pins/shares
#   ซึ่งเป็น source-of-truth + เป็น data ที่ fine-tune ต้องใช้ — ถ้า disk/container
#   พังจะหายถาวร (ChromaDB เคยหายมาแล้วจาก volume-mount bug)
#
# วิธี: ใช้ `sqlite3 .backup` (online snapshot — consistent แม้แอปกำลังเขียน,
#   ปลอดภัยกว่า cp ตอน WAL). ถ้าไม่มี sqlite3 CLI → fallback copy .db + -wal + -shm
#   แล้ว tar+gzip เก็บ N วัน
#
# ตั้งเป็น DSM Task Scheduler รายวัน (แนะนำ 03:30 — ก่อน chroma_backup 04:00), user=root:
#   bash /volume1/homes/pawin/ui/scripts/db_backup.sh
#
# ปรับได้ผ่าน env: UI_DIR / DB_BACKUP_DEST / DB_BACKUP_RETAIN
set -euo pipefail

UI_DIR="${UI_DIR:-/volume1/homes/pawin/ui}"
DEST="${DB_BACKUP_DEST:-/volume1/homes/pawin/db_backups}"
RETAIN_DAYS="${DB_BACKUP_RETAIN:-7}"

TS="$(date +%Y%m%d_%H%M%S)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

mkdir -p "$DEST"

# databases ที่จะ backup — chat_history = สำคัญสุด; cache dbs = bonus (regenerable)
# prod (NAS): DB จริง mount จาก data/chat_history.db — ตัวที่ root repo เป็นไฟล์ค้างเก่า
# (เจอจริง 2026-07-12: backup ได้ตัว root 12KB แทนตัวจริง 933KB)
if [ -f "$UI_DIR/data/chat_history.db" ]; then
  CHAT_DB="$UI_DIR/data/chat_history.db"
else
  CHAT_DB="$UI_DIR/chat_history.db"
fi
DBS=(
  "$CHAT_DB"
  "$UI_DIR/data/embed_cache.db"
  "$UI_DIR/data/response_cache.db"
)

_backup_one() {
  local db="$1" name dst
  name="$(basename "$db")"
  dst="$WORK/$name"
  if command -v sqlite3 >/dev/null 2>&1; then
    # online backup — snapshot ที่ consistent แม้มี writer (จัดการ WAL ให้เอง)
    sqlite3 "$db" ".backup '$dst'"
  else
    # fallback: คัด .db + WAL sidecars (กัน write ที่ยังไม่ checkpoint หาย)
    cp "$db" "$dst"
    [ -f "${db}-wal" ] && cp "${db}-wal" "${dst}-wal" || true
    [ -f "${db}-shm" ] && cp "${db}-shm" "${dst}-shm" || true
  fi
}

# ตรวจว่า snapshot ของ DB หลัก "มีข้อมูลจริง" ไม่ใช่แค่ "เขียนไฟล์สำเร็จ"
# ทำไม: 2026-07-12 เส้นนี้ผลิต archive 989 ไบต์ที่ขึ้น ✅ เหมือนรอบปกติทุกประการ
#   (ตัวจริง 146,676 ไบต์) ตอนนั้นแก้ให้ "เลือกไฟล์ถูกใบ" แต่ไม่ได้แก้ให้
#   "รู้ตัวว่าใบที่เลือกมาว่างเปล่า" — ฝั่ง in-app ปิดช่องนี้แล้ว (utils/db_backup.py)
# echo ข้อความปัญหาออก stdout / ไม่มีปัญหา = ไม่ echo อะไร
_verify_critical() {
  local snap="$WORK/$(basename "$CHAT_DB")"
  if [ ! -f "$snap" ]; then
    echo "ไม่มี $(basename "$CHAT_DB") ใน archive — สำรองได้แต่ไฟล์รอง ซึ่งกู้ระบบกลับไม่ได้"
    return
  fi

  # อ่าน DB ได้ 2 ทาง — ห้ามผูกกับ sqlite3 CLI ตัวเดียว
  #   NAS host    : มีทั้ง /usr/bin/sqlite3 และ /usr/bin/python3
  #   คอนเทนเนอร์ : **ไม่มี sqlite3 CLI** (python:3.11-slim ไม่ได้ลงมาให้)
  # เจอจริง 2026-08-05: เทสเขียวบนแมค (ซึ่งมี sqlite3) แต่ CI ที่รันในอิมเมจแดง
  # → ตัวตรวจที่พึ่งเครื่องมือซึ่งมีเฉพาะเครื่อง dev = ตัวตรวจที่ไม่มีอยู่จริงบนเครื่องอื่น
  # เอา python3 ขึ้นก่อนเพราะมีครบทั้งสองที่ (และทำงานได้แม้ snapshot มาจาก cp fallback)
  local rows=""
  if command -v python3 >/dev/null 2>&1; then
    rows="$(python3 -c 'import sqlite3,sys
try:
    c=sqlite3.connect(sys.argv[1])
    if c.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
        print("BAD"); raise SystemExit
    q=chr(34)
    ts=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type=? AND name NOT LIKE ?",("table","sqlite_%"))]
    print(sum(c.execute("SELECT COUNT(*) FROM "+q+t.replace(q,q+q)+q).fetchone()[0] for t in ts))
except Exception:
    print("BAD")' "$snap" 2>/dev/null)"
  elif command -v sqlite3 >/dev/null 2>&1; then
    if [ "$(sqlite3 "$snap" "PRAGMA integrity_check;" 2>/dev/null)" != "ok" ]; then
      rows="BAD"
    else
      local t
      rows=0
      for t in $(sqlite3 "$snap" "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';" 2>/dev/null); do
        rows=$((rows + $(sqlite3 "$snap" "SELECT COUNT(*) FROM \"$t\";" 2>/dev/null || echo 0)))
      done
    fi
  else
    # ⚠️ "ตรวจไม่ได้" ต้องไม่ถูกนับเป็น "ตรวจแล้วผ่าน" — แต่ก็ไม่ใช่ความล้มเหลว
    echo "__SKIP__"
    return
  fi

  if [ "$rows" = "BAD" ] || [ -z "$rows" ]; then
    echo "$(basename "$CHAT_DB") ใน archive อ่านไม่ได้/integrity_check ไม่ผ่าน"
  elif [ "$rows" -eq 0 ] 2>/dev/null; then
    echo "$(basename "$CHAT_DB") ใน archive ว่างเปล่า (0 แถวทุกตาราง) — ตรงกับอาการ backup 989 ไบต์ เมื่อ 2026-07-12"
  fi
}

backed=0
for db in "${DBS[@]}"; do
  if [ -f "$db" ]; then
    _backup_one "$db"
    backed=$((backed + 1))
  else
    echo "skip (not found): $db"
  fi
done

if [ "$backed" -eq 0 ]; then
  echo "❌ ไม่พบ database ใด ๆ ใน $UI_DIR — ไม่มีอะไรให้ backup (ตรวจ UI_DIR)"
  exit 1
fi

PROBLEM="$(_verify_critical)"

# ชื่อไฟล์คือสิ่งเดียวที่เดินทางไปกับ archive — ตอนกู้จริงคนหยิบจากชื่อ ไม่ไล่ log
# ⚠️ ยังขึ้นต้น db_backup_ เพื่อให้ retention (find -name 'db_backup_*') เห็น
SUFFIX=""
[ -n "$PROBLEM" ] && [ "$PROBLEM" != "__SKIP__" ] && SUFFIX="_UNHEALTHY"
ARCHIVE="$DEST/db_backup_${TS}${SUFFIX}.tar.gz"
tar -czf "$ARCHIVE" -C "$WORK" .

if [ -n "$PROBLEM" ] && [ "$PROBLEM" != "__SKIP__" ]; then
  # ⚠️ ไม่แตะ retention — รอบนี้ได้ของเสีย การลบของเก่าตามอายุจะทำลาย backup
  #    ที่ยังดีอยู่ทิ้งไปด้วย (พังชั่วคราว → พังถาวรภายในสัปดาห์เดียว)
  echo "❌ archive ไม่ผ่านการตรวจ: $PROBLEM"
  echo "   เก็บไว้ที่ $ARCHIVE ($(du -h "$ARCHIVE" | cut -f1)) — ไม่ลบ backup เก่า"
  exit 1
fi

if [ "$PROBLEM" = "__SKIP__" ]; then
  # "ตรวจไม่ได้" ต่างจาก "ตรวจแล้วผ่าน" — ต้องพูดออกมา ไม่ใช่ขึ้น ✅ เฉยๆ
  echo "⚠️ ไม่มีทั้ง python3 และ sqlite3 — ข้ามการตรวจว่า archive มีข้อมูลจริง (ยืนยันไม่ได้ว่ากู้ได้)"
fi

echo "✅ backed up $backed db(s) → $ARCHIVE ($(du -h "$ARCHIVE" | cut -f1))"

# retention — ลบ backup เก่ากว่า RETAIN_DAYS วัน
find "$DEST" -name 'db_backup_*.tar.gz' -type f -mtime +"$RETAIN_DAYS" -delete 2>/dev/null || true
echo "🧹 เก็บ backup ที่ใหม่กว่า ${RETAIN_DAYS} วัน ใน $DEST"
