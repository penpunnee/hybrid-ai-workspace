# Memory System — ChromaDB-backed 3-Tier Recall

ระบบ memory แบ่ง 3 ชั้นตาม cognitive science model:
**Working (sec) → Episodic (days/weeks) → Long-term (months)**

ทุก tier ดึงพร้อมกันใน `recall(assistant, query, session_id)` แล้ว inject เข้า system prompt ก่อนเรียก AI

## 🧠 Tier 1 — Working Memory

**Storage:** in-memory dict (volatile, ไม่รอด restart)
**Module:** `memory/working.py:working_memory`

- Ring buffer per `session_id` (default keep 20 turns)
- เก็บ user prompt + assistant response เป็นคู่
- ใช้สำหรับ short-term context ใน session ปัจจุบัน
- ดึงผ่าน `get_context_text(session_id, n=3)` — เอา n turns ล่าสุด

## 📔 Tier 2 — Episodic Memory

**Storage:** ChromaDB collection `memory_{assistant_slug}` (per-assistant)
**Modules:** `memory/store.py`, `utils/memory.py`

**Schema (per entry):**
```python
MemoryEntry(
    content="Q: ... \nA: ...",
    assistant="kwan",
    type="event",          # event | fact | preference | correction
    confidence=0.7,        # 0-1
    source="conversation", # conversation | teaching | dream
    verified=False,        # ถ้า user thumbs-up → True
    created_at=ISO,
    access_count=0,
    last_accessed=ISO,
)
```

**Operations:**
- `save_entry()` — เก็บลง upsert
- `search_entries(assistant, query, n_results, min_confidence, verified_only)` — semantic
- `update_confidence(assistant, snippet, new_value)` — thumbs feedback path
- `bump_access_count(ids)` — มากขึ้น = สำคัญขึ้น (ใช้ตอน decay)

## 🌟 Tier 3 — Long-term Memory

**Storage:** ChromaDB collection `long_term_memory` (shared across assistants)
**Source:** Dream Cycle Phase 3 promotes themes ที่ count ≥ threshold

**Schema:**
```python
{
    "documents": "[Theme name] Summary text",
    "metadatas": {
        "theme": "Thai Responses",
        "consolidated_at": ISO,
        "hits": 9,
    }
}
```

- ไม่ลบเอง ไม่ decay (เป็น "ความรู้ที่ตกผลึก")
- ดึงผ่าน `search_long_term(query, n_results=3)`

## 🔁 Unified API (`memory/operations.py`)

```python
remember(assistant, prompt, response)  # save → Tier 2
recall(assistant, query, session_id)   # ดึงทั้ง 3 tier → string
teach(assistant, user_text)            # ตรวจ "จำไว้ว่า..." → save fact
push_working(session_id, role, content)
```

## 🔗 Connect to ChromaDB

`utils/memory.py:_detect_chroma_host()` ลองเรียงนี้:
1. `CHROMA_HOST` env (explicit override)
2. `chromadb` (Docker network name)
3. `192.168.51.49` (NAS IP)
4. `chroma.pawinhome.com` (Cloudflare)
5. fallback `localhost:8000`

ใช้ `chromadb.HttpClient` — auto compatible กับ v1/v2 API

## 🛡️ Graceful Degradation

ทุก function ตรวจ `is_memory_available()` ก่อน:
- ถ้า ChromaDB ไม่ขึ้น → คืน empty result + log warning
- ระบบยังทำงานต่อ (chat ตอบได้ — แค่ไม่มี memory)

## 🌙 Memory Lifecycle

```
1. User chat
   ↓
2. remember() → Tier 2 (confidence 0.7, unverified)
   ↓
3. ถัดๆ ไป — recall() ดึงเข้า context
   ↓
4. ตี 2 ทุกคืน — Dream Cycle:
   • Phase 1: ดึง 24 ชม.ล่าสุด
   • Phase 2 (REM): AI หา themes
   • Phase 2.5: decay เก่าๆ → confidence ลด
   • Phase 3 (Deep): themes สำคัญ → Tier 3 (long-term)
   ↓
5. Feedback:
   • thumbs-up → confidence +0.15, verified=True
   • thumbs-down → confidence -0.25
```

## 📊 Inspect Memory

```bash
# Inventory
curl http://192.168.51.49:8080/api/memory/stats

# Per-assistant detail
curl http://192.168.51.49:8080/api/memory/summary/kwan

# Manual recall preview
curl "http://192.168.51.49:8080/api/memory/recall/kwan?q=คำถามทดสอบ"
```
