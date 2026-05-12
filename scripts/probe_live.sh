#!/usr/bin/env bash
# probe_live.sh — ทดสอบ end-to-end หลังเปิด NAS + LMStudio
# Usage: bash scripts/probe_live.sh

set -u
NAS_API=${NAS_API:-https://ai.pawinhome.com}
LAN_CHROMA=${LAN_CHROMA:-192.168.51.49:8000}
LAN_LMSTUDIO=${LAN_LMSTUDIO:-192.168.51.235:1234}

green() { printf '\033[32m%s\033[0m\n' "$*"; }
red()   { printf '\033[31m%s\033[0m\n' "$*"; }
yellow(){ printf '\033[33m%s\033[0m\n' "$*"; }
hdr()   { printf '\n\033[1;36m═══ %s ═══\033[0m\n' "$*"; }

probe() {
  local name=$1 url=$2
  local code
  code=$(curl -sS --max-time 6 -o /tmp/probe_$$.out -w '%{http_code}' "$url" 2>/dev/null || echo "ERR")
  if [[ "$code" == "200" ]]; then
    green "✓ $name ($code)"
    head -c 200 /tmp/probe_$$.out 2>/dev/null
    echo
  else
    red "✗ $name ($code) — $url"
  fi
  rm -f /tmp/probe_$$.out
}

hdr "1. Reachability"
probe "Cloudflare tunnel" "$NAS_API/api/system/status"
probe "ChromaDB heartbeat" "http://$LAN_CHROMA/api/v1/heartbeat"
probe "LMStudio models"    "http://$LAN_LMSTUDIO/v1/models"

hdr "2. Memory system"
probe "Memory stats"   "$NAS_API/api/memory/stats"
probe "Skills count"   "$NAS_API/api/skills"
probe "Cache layers"   "$NAS_API/api/cache/stats"

hdr "3. Dream Cycle history"
probe "Latest report" "$NAS_API/api/dream/report"
probe "Report list"   "$NAS_API/api/dream/history?limit=5"

hdr "4. Skill discovery (Phase C)"
probe "Discovery cached" "$NAS_API/api/skills/discover/cached"
yellow "→ (ลอง POST /api/skills/discover?days=30 เพื่อ scan ใหม่ — ใช้เวลา 10-30s)"

hdr "5. Live chat smoke test"
yellow "→ ส่งคำถามทดสอบไป /api/chat (ไม่ stream ดูแค่ header X-Provider-Used)"
curl -sS --max-time 30 -D - -o /dev/null \
  -H "Content-Type: application/json" \
  -X POST "$NAS_API/api/chat" \
  -d '{"prompt":"สวัสดี ทดสอบระบบ","assistant":"kwan","session_id":"probe_test"}' \
  2>/dev/null | grep -E "^(HTTP|X-|x-)" | head -8

hdr "Done"
echo "ถ้ามี ✗ ที่ไหน → service ตรงนั้นยังไม่ขึ้น"
echo "ถ้าทุกอันเขียว → ระบบพร้อม! รัน Dream cycle เทสได้: curl -X POST $NAS_API/api/dream"
