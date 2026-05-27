# Hybrid AI Workspace - Tests

## Backend Tests (Python/pytest)

### Setup

```bash
cd /Users/pawin/Desktop/ui
pip install -r requirements.txt
```

### Run Tests

```bash
# Run all tests
pytest tests/

# Run specific test file
pytest tests/test_main.py

# Run with verbose output
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=utils --cov=server
```

> ⚠️ `test_main.py` ต้องการ external services (ChromaDB/Ollama) ตอน TestClient lifespan
> — ถ้าค้าง ให้รันชุดอื่นแยก: `pytest tests/ --ignore=tests/test_main.py`

### Test Files

**Integration**
- `test_main.py` - API endpoints (health, config, chat, sessions, memory, share)
- `test_memory.py` - Legacy memory ops `utils/memory.py` (ChromaDB mocked)

**LLM / routing**
- `test_llm_routing.py` - provider routing + LM Studio→Ollama cascade
- `test_llm_internals.py` - `_stream_ollama` retry / `_stream_gemini` error-map / `check_ollama_health`
- `test_classifier.py` - `needs_internet` + complexity classify
- `test_parser.py` - DeepSeek R1 `<think>` stream parser (รองรับ tag ข้าม chunk)

**Security**
- `test_fs_tools.py` - whitelist FS ops (path traversal / symlink escape)
- `test_auth.py` - LAN bypass + cf-header spoof guard + token gate

**Phase B–E utils**
- `test_chunking.py` - document chunker
- `test_citations.py` - `CitationTracker`
- `test_context_budget.py` - score filter + token-budget trim
- `test_tokens.py` - approx token counting + context limits

**Memory package (ใหม่)**
- `test_memory_package.py` - `memory/` schema/working/teach/store/operations

---

## Frontend Tests (Vitest/React Testing Library)

### Setup

```bash
cd /Users/pawin/appscript.ui
npm install
```

### Run Tests

```bash
# Run all tests
npm test

# Run in watch mode
npm test -- --watch

# Run with coverage
npm test -- --coverage
```

### Test Files

- `components/Chat/ChatInput.test.tsx` - Chat input component
- `components/Chat/MessageBubble.test.tsx` - Message bubble component

---

## CI/CD Integration

Add to GitHub Actions or similar:

```yaml
# Backend tests
- run: pip install -r requirements.txt
- run: pytest tests/

# Frontend tests
- run: npm install
- run: npm test
```
