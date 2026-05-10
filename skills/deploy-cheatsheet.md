# Deploy Cheatsheet — Hybrid AI Workspace

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
