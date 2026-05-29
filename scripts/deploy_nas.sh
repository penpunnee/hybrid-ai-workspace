#!/usr/bin/env bash
# deploy_nas.sh — sync + build + recreate hybrid-ai บน NAS (รันผ่าน DSM Task Scheduler, user=root)
#
# ทำให้: (1) git reset --hard origin/main  (2) ensure .env (LM Studio integration)
#         (3) docker compose build (เพราะ requirements เพิ่ม anthropic+mcp)  (4) recreate + logs
#
# รันครั้งแรก (bootstrap จาก DSM Task Scheduler, User=root):
#   cd /volume1/homes/pawin/ui && git config --global --add safe.directory /volume1/homes/pawin/ui \
#     && git fetch origin && git checkout origin/main -- scripts/deploy_nas.sh && bash scripts/deploy_nas.sh
# ครั้งถัดไป: bash /volume1/homes/pawin/ui/scripts/deploy_nas.sh
set -uo pipefail   # ไม่ใช้ -e เพื่อให้ log ครบแม้บาง step เตือน

UI_DIR="${UI_DIR:-/volume1/homes/pawin/ui}"
cd "$UI_DIR" || { echo "❌ ไม่พบ $UI_DIR"; exit 1; }

echo "═══ 1) git sync → origin/main ═══"
git config --global --add safe.directory "$UI_DIR" 2>/dev/null || true
chown -R pawin:users .git 2>/dev/null || true
git fetch origin && git reset --hard origin/main
echo "HEAD = $(git rev-parse --short HEAD)"

echo "═══ 2) ensure .env (LM Studio) — .env gitignored จึงไม่โดน reset ═══"
touch .env
_ensure() {   # _ensure KEY VALUE — เพิ่มถ้ายังไม่มี (ไม่ทับของเดิม)
  if grep -q "^$1=" .env; then echo "  • $1 มีอยู่แล้ว (คงไว้)"; else echo "$1=$2" >> .env; echo "  + เพิ่ม $1=$2"; fi
}
_ensure LMSTUDIO_BASE_URL   "http://192.168.51.235:1234/v1"
_ensure LMSTUDIO_CHAT_MODEL "meta-llama-3.1-8b-instruct"
grep -q "^ANTHROPIC_API_KEY=" .env \
  && echo "  • ANTHROPIC_API_KEY มีอยู่แล้ว (Claude พร้อม)" \
  || echo "  ⚠️ ยังไม่มี ANTHROPIC_API_KEY — Claude จะยังใช้ไม่ได้ (เพิ่มเองใน .env ภายหลังถ้าต้องการ)"

echo "═══ 3) build (anthropic+mcp ใหม่) + recreate ═══"
docker compose build hybrid-ai && docker compose up -d hybrid-ai --force-recreate

echo "═══ 4) logs (40 บรรทัดท้าย) ═══"
sleep 3
docker compose logs hybrid-ai --tail 40

echo ""
echo "✅ เสร็จ — เปิด https://ai.pawinhome.com แล้ว hard refresh (Cmd+Shift+R)"
echo "   จะเห็น: ปุ่ม ✨Claude + token counter + slash / + draft autosave"
echo "   ถ้าจะใช้ Claude: เพิ่ม ANTHROPIC_API_KEY ใน $UI_DIR/.env แล้ว:"
echo "     docker compose up -d hybrid-ai --force-recreate"
