# Coding Skills — Quick Reference

## Python
```python
# List comprehension
result = [x*2 for x in items if x > 0]

# Dict comprehension
d = {k: v for k, v in pairs}

# f-string
msg = f"Hello {name}, you are {age} years old"

# Context manager
with open("file.txt", "r", encoding="utf-8") as f:
    data = f.read()

# Dataclass
from dataclasses import dataclass
@dataclass
class User:
    name: str
    age: int = 0

# Async/Await
import asyncio
async def fetch(url):
    await asyncio.sleep(1)
    return url

# Type hints
def greet(name: str) -> str:
    return f"Hello {name}"

# Error handling
try:
    result = risky()
except (ValueError, KeyError) as e:
    print(f"Error: {e}")
finally:
    cleanup()

# Lambda + map/filter
nums = list(map(lambda x: x**2, filter(lambda x: x%2==0, range(10))))

# Walrus operator
if (n := len(data)) > 10:
    print(f"Too long: {n}")
```

## FastAPI (Python)
```python
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
import json

app = FastAPI()

@app.get("/api/items")
def list_items():
    return {"items": []}

@app.post("/api/chat")
async def chat(request: Request):
    data = await request.json()
    
    def generate():
        for chunk in stream():
            yield f"data: {json.dumps({'chunk': chunk})}\n\n"
        yield f"data: {json.dumps({'done': True})}\n\n"
    
    return StreamingResponse(generate(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
```

## Gemini API (google-genai SDK)
```python
from google import genai
from google.genai import types
import os

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# Simple generate
response = client.models.generate_content(
    model="gemini-2.0-flash",
    contents="สวัสดี บอกชื่อตัวเองหน่อย"
)
print(response.text)

# Streaming
for chunk in client.models.generate_content_stream(
    model="gemini-2.0-flash",
    contents="เล่านิทานสั้นๆ"
):
    print(chunk.text, end="", flush=True)

# Chat with system prompt + history
config = types.GenerateContentConfig(
    system_instruction="คุณคือ AI ผู้ช่วยภาษาไทย ตอบสั้นกระชับ",
)
history = [
    types.Content(role="user", parts=[types.Part(text="สวัสดี")]),
    types.Content(role="model", parts=[types.Part(text="สวัสดีค่ะ!")]),
    types.Content(role="user", parts=[types.Part(text="ชื่อคุณคืออะไร")]),
]
response = client.models.generate_content(
    model="gemini-2.0-flash",
    contents=history,
    config=config,
)
print(response.text)

# Streaming chat (ใช้ใน FastAPI)
def stream_gemini(messages: list[dict], system: str = ""):
    history = []
    for m in messages:
        if m["role"] == "system":
            continue
        role = "user" if m["role"] == "user" else "model"
        history.append(types.Content(role=role, parts=[types.Part(text=m["content"])]))
    
    config = types.GenerateContentConfig(system_instruction=system)
    for chunk in client.models.generate_content_stream(
        model="gemini-2.0-flash",
        contents=history,
        config=config,
    ):
        if chunk.text:
            yield chunk.text

# Error handling
try:
    response = client.models.generate_content(model="gemini-2.0-flash", contents="test")
except Exception as e:
    err = str(e)
    if "API_KEY_INVALID" in err or "401" in err:
        print("API Key ไม่ถูกต้อง")
    elif "429" in err or "quota" in err.lower():
        print("Quota หมด รอสักครู่")
    else:
        print(f"Error: {e}")

# Available models
# gemini-2.0-flash       → เร็ว ถูก ใช้งานทั่วไป
# gemini-1.5-pro         → ฉลาดกว่า context ยาว
# gemini-1.5-flash       → balance ระหว่างเร็วกับฉลาด
```

## JavaScript / TypeScript
```typescript
// Arrow functions
const add = (a: number, b: number): number => a + b

// Destructuring
const { name, age = 0 } = user
const [first, ...rest] = arr

// Optional chaining + nullish coalescing
const city = user?.address?.city ?? "Unknown"

// Async/Await + fetch
const fetchData = async (url: string) => {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

// Array methods
const adults = users
  .filter(u => u.age >= 18)
  .map(u => ({ ...u, status: "adult" }))
  .sort((a, b) => a.name.localeCompare(b.name))

// SSE streaming
const res = await fetch("/api/chat", { method: "POST", body: JSON.stringify(data) })
const reader = res.body!.getReader()
const decoder = new TextDecoder()
while (true) {
  const { done, value } = await reader.read()
  if (done) break
  const text = decoder.decode(value)
  // parse SSE lines
}

// Interface
interface Message {
  id: number
  sender: "user" | "ai"
  text: string
  streaming?: boolean
}
```

## React + Hooks
```typescript
// useState
const [count, setCount] = useState(0)

// useEffect
useEffect(() => {
  fetchData()
  return () => cleanup()  // cleanup
}, [dependency])

// useCallback
const handleClick = useCallback(() => {
  doSomething(id)
}, [id])

// useRef
const inputRef = useRef<HTMLInputElement>(null)
inputRef.current?.focus()

// Custom hook
function useLocalStorage<T>(key: string, initial: T) {
  const [val, setVal] = useState<T>(() => {
    try { return JSON.parse(localStorage.getItem(key) ?? "") }
    catch { return initial }
  })
  const set = (v: T) => { setVal(v); localStorage.setItem(key, JSON.stringify(v)) }
  return [val, set] as const
}
```

## Tailwind CSS
```html
<!-- Layout -->
<div class="flex items-center justify-between gap-4">
<div class="grid grid-cols-3 gap-6">

<!-- Sizing -->
<div class="w-full max-w-xl h-screen min-h-0">

<!-- Typography -->
<p class="text-sm font-medium text-gray-300 truncate">

<!-- Background + Border -->
<div class="bg-white/10 border border-white/20 rounded-xl backdrop-blur-md">

<!-- Hover + Transition -->
<button class="hover:bg-white/20 transition-all duration-200 active:scale-95">

<!-- Responsive -->
<div class="flex-col md:flex-row p-4 md:p-8">

<!-- Dark glass card -->
<div class="bg-white/5 border border-white/10 rounded-2xl p-6 backdrop-blur-xl shadow-xl">
```

## SQL (SQLite)
```sql
-- Create table
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  role TEXT NOT NULL,
  content TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index
CREATE INDEX IF NOT EXISTS idx_session ON messages(session_id);

-- Query
SELECT * FROM messages 
WHERE session_id = ? AND role = 'user'
ORDER BY created_at DESC LIMIT 10;

-- Insert
INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?);

-- Upsert
INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?);
```

## Bash / Shell (NAS / Linux)
```bash
# Docker
sudo docker ps | grep ai
sudo docker logs container_name --tail 50 -f
sudo docker compose up -d service_name
sudo docker exec -it container_name bash

# File operations
mkdir -p /path/to/dir
find /vault -name "*.md" -mtime -7  # modified last 7 days
grep -r "keyword" /path --include="*.py"

# Process
ps aux | grep python
kill -9 $(pgrep -f server.py)

# Network
curl -s http://localhost:8080/api/status
curl -X POST -H "Content-Type: application/json" -d '{}' http://localhost:8080/api/chat
netstat -tlnp | grep 8080

# Environment
export VAR=value
source .env
cat .env | grep KEY
```

## Git
```bash
git add -A && git commit -m "feat: description"
git push origin main
git pull --rebase
git log --oneline -10
git stash && git stash pop
git diff HEAD~1
```

## Docker Compose
```yaml
services:
  app:
    build: .
    container_name: my-app
    restart: unless-stopped
    ports:
      - "8080:8000"
    volumes:
      - ./data:/app/data
      - ${DATA_PATH:-./data}/db.sqlite:/app/db.sqlite
    environment:
      - ENV=production
    env_file:
      - .env
    networks:
      - app-net

networks:
  app-net:
    driver: bridge
```
