# Testing Guide — Hybrid AI Workspace

## รัน Tests Local (Mac)

```bash
cd /Users/pawin/Desktop/ui
python3 -m pytest tests/ -v
python3 -m pytest tests/ -q          # สั้น
python3 -m pytest tests/test_main.py -v  # เฉพาะ API tests
python3 -m pytest tests/test_memory.py -v  # เฉพาะ memory tests
```

## รัน Tests ใน Docker Container (NAS)

```bash
sudo docker exec ai-backend-1 python3 -m pytest tests/ -v
sudo docker exec ai-backend-1 python3 -m pytest tests/ -q --tb=short
```

## ผลลัพธ์ปกติ

```
34 passed in ~30s
├── test_main.py   19 tests  (API endpoints)
└── test_memory.py 15 tests  (ChromaDB memory)
```

## Test Files

### `tests/test_main.py` — API Integration Tests

| Class | Tests |
|---|---|
| `TestHealthEndpoints` | `/`, `/api/status` |
| `TestConfigEndpoint` | `/api/config` |
| `TestChatEndpoint` | `/api/chat` (ollama, gemini, missing) |
| `TestSessionEndpoints` | create, get, rename, delete |
| `TestMemoryEndpoints` | save, list, delete lessons/preferences |
| `TestStatsEndpoint` | `/api/stats` |
| `TestShareEndpoint` | create share link, get shared |

### `tests/test_memory.py` — ChromaDB Unit Tests

- `TestSaveLesson` — save, unavailable, error
- `TestSavePreference` — save, unavailable
- `TestGetLessons` — empty, with docs, unavailable
- `TestDeleteLesson` — success, error, unavailable
- `TestDeletePreference` — success, unavailable
- `TestGetMemoryStats` — available, unavailable

## หมายเหตุสำคัญ

- Tests ปิด auth อัตโนมัติ: `os.environ["UI_PASSWORD"] = ""`
- Tests ใช้ mock สำหรับ `stream_response` (ไม่เรียก API จริง)
- `test_memory.py` mock `utils.memory._get_client` (ไม่ต้องการ ChromaDB จริง)
- Dependencies: `pytest>=8.0.0`, `pytest-asyncio>=0.23.0`, `httpx>=0.27.0`

## เพิ่ม Test ใหม่

```python
# tests/test_main.py
class TestMyFeature:
    def test_something(self, mock_env):
        response = client.get("/api/my-endpoint")
        assert response.status_code == 200
        assert response.json()["ok"] == True
```
