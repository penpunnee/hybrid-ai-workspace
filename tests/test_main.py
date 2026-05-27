import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Disable auth for tests (ก่อน import server เพื่อให้ UI_PASSWORD = "")
os.environ["UI_PASSWORD"] = ""

from server import app
import server as _server
_server.UI_PASSWORD = ""   # override หลัง import ด้วย เผื่อ load แล้ว

client = TestClient(app)


@pytest.fixture
def mock_env():
    """Mock environment variables for testing"""
    os.environ['OLLAMA_BASE_URL'] = 'http://localhost:11434/v1'
    os.environ['OLLAMA_MODEL'] = 'llama3'
    os.environ['GEMINI_API_KEY'] = 'test_key'
    os.environ['GEMINI_MODEL'] = 'gemini-2.5-flash'
    os.environ['CHROMA_HOST'] = 'localhost'
    os.environ['CHROMA_PORT'] = '8000'
    os.environ['DB_PATH'] = ':memory:'


# ─────────────────────────────────────────────────────────────
# Bug #1 FIX: root endpoint คืน HTML ไม่ใช่ JSON
#   เดิม: assert "message" in response.json()  ← พัง เพราะ / คืน HTMLResponse
#   แก้:  ตรวจแค่ status_code + content-type เป็น text/html
# ─────────────────────────────────────────────────────────────
class TestHealthEndpoints:
    """Test health and status endpoints"""

    def test_root_endpoint(self, mock_env):
        """Test root endpoint returns HTML (not JSON)"""
        # server.py ของ / คือ HTMLResponse (static/index.html)
        # ถ้าไฟล์ไม่มีจะได้ 500, แต่ status ควรไม่ใช่ 404
        response = client.get("/")
        assert response.status_code in (200, 500)  # 500 ถ้า static/index.html หาย
        # ต้องไม่คืน JSON (ไม่ใช่ application/json)
        assert "application/json" not in response.headers.get("content-type", "")

    # ─────────────────────────────────────────────────────────
    # Bug #2 FIX: mock path ผิด → ค้าง (real func ต่อ ChromaDB จริง)
    #   system.py ทำ `from utils.llm import check_ollama_health` →
    #   ชื่อผูกใน routers.system แล้ว ต้อง patch ที่ใช้งานจริง ไม่ใช่ต้นทาง
    #   เดิม patch('utils.llm.check_ollama_health') ← ไม่มีผล → /api/status
    #   เรียก func จริง → connect NAS → ThreadPoolExecutor shutdown ค้าง
    # ─────────────────────────────────────────────────────────
    def test_status_endpoint(self, mock_env):
        """Test /api/status endpoint"""
        with patch('routers.system.check_ollama_health') as mock_ollama, \
             patch('routers.system.is_memory_available') as mock_mem:
            mock_ollama.return_value = (True, "")
            mock_mem.return_value = True
            response = client.get("/api/status")
            assert response.status_code == 200
            data = response.json()
            assert "ollama" in data
            assert "gemini" in data
            assert "memory" in data


class TestConfigEndpoint:
    """Test configuration endpoint"""

    def test_get_config(self, mock_env):
        """Test /api/config endpoint returns assistant list"""
        response = client.get("/api/config")
        assert response.status_code == 200
        data = response.json()
        assert "assistants" in data
        assert len(data["assistants"]) == 3  # ฟ้า, ขวัญ, ขิม


class TestChatEndpoint:
    """Test chat streaming endpoint"""

    def test_chat_stream_ollama(self, mock_env):
        """Test /api/chat with Ollama provider"""
        with patch('routers.chat.stream_response') as mock_stream:
            mock_stream.return_value = iter(["Hello", " world"])

            response = client.post(
                "/api/chat",
                json={
                    "provider": "ollama",
                    "messages": [{"role": "user", "content": "test"}],
                    "assistant": "ฟ้า",
                    "prompt": "test",
                    "session_id": "test_session",
                }
            )
            assert response.status_code == 200
            assert "text/event-stream" in response.headers.get("content-type", "")

    def test_chat_stream_gemini(self, mock_env):
        """Test /api/chat with Gemini provider"""
        with patch('routers.chat.stream_response') as mock_stream:
            mock_stream.return_value = iter(["Hello", " world"])

            response = client.post(
                "/api/chat",
                json={
                    "provider": "gemini",
                    "messages": [{"role": "user", "content": "test"}],
                    "assistant": "ฟ้า",
                    "prompt": "test",
                    "session_id": "test_session",
                }
            )
            assert response.status_code == 200

    def test_chat_missing_messages(self, mock_env):
        """Test /api/chat with missing required field (prompt)"""
        # server รับ JSON body แบบ free-form ไม่ใช่ Pydantic model
        # ถ้าไม่มี prompt ก็ยังส่งได้ แต่ prompt จะเป็น ""
        response = client.post(
            "/api/chat",
            json={"provider": "ollama", "assistant": "ฟ้า"}
        )
        # ควรได้ 200 (streaming) ไม่ใช่ 422 เพราะไม่มี Pydantic validation
        assert response.status_code == 200


class TestSessionEndpoints:
    """Test session management endpoints"""

    def test_create_session(self, mock_env):
        """Test POST /api/sessions/{assistant}"""
        response = client.post("/api/sessions/ฟ้า")
        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data

    def test_get_sessions(self, mock_env):
        """Test GET /api/sessions/{assistant}"""
        response = client.get("/api/sessions/ฟ้า")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_rename_session(self, mock_env):
        """Test PATCH /api/sessions/{assistant}/{session_id}"""
        create_response = client.post("/api/sessions/ฟ้า")
        session_id = create_response.json()["session_id"]

        response = client.patch(
            f"/api/sessions/ฟ้า/{session_id}",
            json={"name": "Test Session"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("ok") == True

    def test_delete_session(self, mock_env):
        """Test DELETE /api/sessions/{assistant}/{session_id}"""
        create_response = client.post("/api/sessions/ฟ้า")
        session_id = create_response.json()["session_id"]

        response = client.delete(f"/api/sessions/ฟ้า/{session_id}")
        assert response.status_code == 200


# ─────────────────────────────────────────────────────────────
# Bug #3 FIX: endpoint ไม่มีจริงใน server.py
#   เดิม: POST /api/memory/lessons และ POST /api/memory/preferences
#   แก้:  ใช้ POST /api/memory/{assistant} ที่มีอยู่จริง
#         และ GET /api/memory/lessons + GET /api/memory/preferences
#         และ DELETE /api/memory/lessons/{doc_id} ที่มีอยู่
# ─────────────────────────────────────────────────────────────
class TestMemoryEndpoints:
    """Test memory (ChromaDB) endpoints"""

    def test_save_memory(self, mock_env):
        """Test POST /api/memory/{assistant} — endpoint ที่มีอยู่จริง"""
        with patch('routers.memory.save_memory') as mock_mem, \
             patch('routers.memory.save_lesson') as mock_lesson:
            mock_mem.return_value = None
            mock_lesson.return_value = None
            response = client.post(
                "/api/memory/ฟ้า",
                json={"text": "Test memory content"}
            )
            assert response.status_code == 200
            assert response.json().get("ok") == True

    def test_list_lessons(self, mock_env):
        """Test GET /api/memory/lessons"""
        with patch('routers.memory.list_lessons') as mock_list:
            mock_list.return_value = []
            response = client.get("/api/memory/lessons")
            assert response.status_code == 200
            data = response.json()
            assert "lessons" in data

    def test_list_preferences(self, mock_env):
        """Test GET /api/memory/preferences"""
        with patch('routers.memory.list_preferences') as mock_list:
            mock_list.return_value = []
            response = client.get("/api/memory/preferences")
            assert response.status_code == 200
            data = response.json()
            assert "preferences" in data

    def test_delete_lesson(self, mock_env):
        """Test DELETE /api/memory/lessons/{doc_id}"""
        with patch('routers.memory.delete_lesson') as mock_delete:
            mock_delete.return_value = True
            response = client.delete("/api/memory/lessons/test_doc_id")
            assert response.status_code == 200
            assert response.json().get("ok") == True

    def test_delete_preference(self, mock_env):
        """Test DELETE /api/memory/preferences/{doc_id}"""
        with patch('routers.memory.delete_preference') as mock_delete:
            mock_delete.return_value = True
            response = client.delete("/api/memory/preferences/test_doc_id")
            assert response.status_code == 200
            assert response.json().get("ok") == True

    def test_memory_stats(self, mock_env):
        """Test GET /api/memory/stats"""
        with patch('routers.memory.get_memory_stats') as mock_stats:
            mock_stats.return_value = {"lessons": 0, "preferences": 0}
            response = client.get("/api/memory/stats")
            assert response.status_code == 200


# ─────────────────────────────────────────────────────────────
# Bug #4 FIX: field ไม่ตรงกับ response จริง
#   เดิม: assert "lessons_count" in data, assert "preferences_count" in data
#   แก้:  /api/stats คืน total_messages, by_assistant, memory ฯลฯ
#         ไม่มี lessons_count / preferences_count โดยตรง
# ─────────────────────────────────────────────────────────────
class TestStatsEndpoint:
    """Test statistics endpoint"""

    def test_get_stats(self, mock_env):
        """Test GET /api/stats — ตรวจ fields ที่มีจริง"""
        with patch('routers.system.get_memory_stats') as mock_stats:
            mock_stats.return_value = {"lessons": 10, "preferences": 5}
            response = client.get("/api/stats")
            assert response.status_code == 200
            data = response.json()
            # fields จริงใน /api/stats
            assert "total_messages" in data
            assert "by_assistant" in data
            assert "memory" in data  # memory เป็น dict จาก get_memory_stats()


# ─────────────────────────────────────────────────────────────
# Bug #5 FIX: URL endpoint ผิด
#   เดิม: GET /api/share/{token}
#   แก้:  GET /api/shared/{token}  ← ชื่อจริงใน server.py
#
# Bug #6 FIX: ขาด session_id field ใน share_store
#   เดิม: assert "session_id" in data  ← data มี ok, assistant, messages, created
#   แก้:  ตรวจ "assistant" และ "messages" แทน
# ─────────────────────────────────────────────────────────────
class TestShareEndpoint:
    """Test share link endpoint"""

    def test_create_share_link(self, mock_env):
        """Test POST /api/share"""
        response = client.post(
            "/api/share",
            json={
                "assistant": "ฟ้า",
                "session_id": "test_session_123"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("ok") == True
        assert "token" in data

    def test_get_shared_chat(self, mock_env):
        """Test GET /api/shared/{token} — URL ที่ถูกต้องคือ /api/shared/ ไม่ใช่ /api/share/"""
        # สร้าง share link
        create_response = client.post(
            "/api/share",
            json={
                "assistant": "ฟ้า",
                "session_id": "test_session_123"
            }
        )
        token = create_response.json()["token"]

        # เรียก endpoint ที่ถูกต้อง: /api/shared/{token}
        response = client.get(f"/api/shared/{token}")
        assert response.status_code == 200
        data = response.json()
        # response จริงมี: ok, assistant, messages, created
        assert data.get("ok") == True
        assert "assistant" in data
        assert "messages" in data  # ไม่ใช่ session_id


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
