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
DBS=(
  "$UI_DIR/chat_history.db"
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

ARCHIVE="$DEST/db_backup_${TS}.tar.gz"
tar -czf "$ARCHIVE" -C "$WORK" .
echo "✅ backed up $backed db(s) → $ARCHIVE ($(du -h "$ARCHIVE" | cut -f1))"

# retention — ลบ backup เก่ากว่า RETAIN_DAYS วัน
find "$DEST" -name 'db_backup_*.tar.gz' -type f -mtime +"$RETAIN_DAYS" -delete 2>/dev/null || true
echo "🧹 เก็บ backup ที่ใหม่กว่า ${RETAIN_DAYS} วัน ใน $DEST"
