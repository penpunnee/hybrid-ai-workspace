# Deploy Cheatsheet — Hybrid AI Workspace

## ⚡ Deploy ตรงจาก Mac ผ่าน SSH (เร็วสุด — ใช้ได้ตั้งแต่ 2026-06-12)

SSH key auth เข้า NAS ผ่านแล้ว (หลังปลด 2FA) + sudo docker ไม่ต้องรหัส:
```bash
# push จาก Mac แล้วสั่ง NAS pull + restart ในคำสั่งเดียว
git push origin main && ssh -o BatchMode=yes pawin@192.168.51.49 \
  'cd /var/services/homes/pawin/ui && git fetch origin main && git reset --hard origin/main \
   && sudo -n /usr/local/bin/docker restart ai-backend-1'
```
- โค้ด Python (utils/ routers/ agents/ ฯลฯ) = volume mount → **restart พอ ไม่ต้อง rebuild**
- `static/` เสิร์ฟจาก disk ต่อ request → **ไม่ต้อง restart เลย** (แค่ browser hard refresh)
- rebuild เฉพาะตอน `requirements.txt`/`Dockerfile` เปลี่ยน
- skills .md ใหม่ → ต้อง `cp skills/*.md data/skills/` บน NAS ด้วย (container อ่าน data/skills)
- ถ้า SSH ตัน (Auto Block/2FA กลับมา) → fallback: DSM Task Scheduler `deploy-hybrid-ai`

## Deploy บน NAS (คำสั่งหลัก)

```bash
cd /var/services/homes/pawin/ui
git pull
sudo docker compose up -d hybrid-ai --force-recreate
```

## Rebuild Image (เมื่อ requirements.txt เปลี่ยน)

```bash
sudo docker compose build hybrid-ai
sudo docker compose up -d hybrid-ai --force-recreate
```

## Restart Container (reload Python code)

```bash
sudo docker compose restart hybrid-ai
```

## ดู Logs

```bash
sudo docker compose logs -f hybrid-ai
sudo docker logs ai-backend-1 --tail 50
```

## ตรวจสถานะ

```bash
sudo docker ps
curl http://localhost:8080/api/status
curl http://localhost:8080/api/health
```

## Volume Mounts (อัปเดตได้โดยไม่ rebuild)

| Path บน NAS | Path ใน Container | อัปเดตทันที |
|---|---|---|
| `./static/` | `/app/static/` | ✅ ทันที (refresh browser) |
| `./utils/` | `/app/utils/` | ⚠️ ต้อง restart |
| `./assistants/` | `/app/assistants/` | ⚠️ ต้อง restart |
| `./server.py` | `/app/server.py` | ⚠️ ต้อง restart |
| `./tests/` | `/app/tests/` | ✅ ทันที |
| `./data/skills/` | `/app/skills/` | ✅ ทันที |

## Run Tests ใน Container

```bash
sudo docker exec ai-backend-1 python3 -m pytest tests/ -v
```

## Fix .git Permission (ถ้า git pull ไม่ได้)

```bash
sudo chown -R pawin:users .git
git pull
```

## Sync Skills → ChromaDB

```bash
curl -X POST http://localhost:8080/api/admin/sync-skills \
  -H 'Content-Type: application/json' -d '{}'
```

## URLs

- LAN: `http://192.168.51.49:8080`
- Public: `https://ai.pawinhome.com`
