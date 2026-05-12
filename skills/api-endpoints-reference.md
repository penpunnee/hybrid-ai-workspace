# API Endpoints Reference

ทุก endpoint อยู่ใต้ `/api/` (ยกเว้น `/` และ `/shared/{token}` ที่ serve HTML)

## 🔐 Authentication
- LAN IPs (192.168.x, 10.x, 127.x) bypass auth
- Cloudflare requests ต้องมี `x-auth-token` header
- ตั้ง `UI_PASSWORD` env เพื่อ require auth

| Method | Path | Function |
|---|---|---|
| POST | `/api/login` | Exchange password → session token |

## 💬 Chat
| Method | Path | Function |
|---|---|---|
| POST | `/api/chat` | Streaming SSE chat (rich events: chunk, citations, reflection, cache_hit) |
| POST | `/api/regenerate` | Re-stream last AI response |
| POST | `/api/agent` | Multi-step tool-use agent |
| GET | `/api/agent/tools` | List registered tools |
| WS | `/ws/voice/{assistant_slug}` | Voice chat via Gemini Live |

## 🗂️ Sessions & History
| Method | Path | Function |
|---|---|---|
| GET | `/api/sessions/{assistant}` | List sessions of assistant |
| POST | `/api/sessions/{assistant}` | Create/rename session |
| DELETE | `/api/sessions/{assistant}/{session_id}` | Delete session |
| GET | `/api/history/{assistant}/{session_id}` | Load history |
| GET | `/api/pinned/{assistant}/{session_id}` | List pinned messages |
| POST | `/api/pin/{db_id}` | Toggle pin |
| DELETE | `/api/truncate/{db_id}` | Truncate from this message |
| GET | `/api/export/{assistant}/{session_id}` | Export as JSON |
| POST | `/api/share` | Create share token |
| GET | `/shared/{token}` | View shared chat (HTML) |
| GET | `/api/search` | Full-text search messages |

## 🧠 Memory
| Method | Path | Function |
|---|---|---|
| GET | `/api/memory/stats` | Memory inventory (collections, total, long-term, lessons) |
| GET | `/api/memory/summary/{assistant}` | Detail per assistant |
| GET | `/api/memory/recall/{assistant}` | Manual recall preview |
| GET | `/api/memory/lessons` | List learned lessons |
| DELETE | `/api/memory/lessons/{doc_id}` | Delete lesson |
| GET | `/api/memory/preferences` | List user preferences |
| DELETE | `/api/memory/preferences/{doc_id}` | Delete preference |

## 📚 Skills
| Method | Path | Function |
|---|---|---|
| GET | `/api/skills` | List skills_db entries + counts |
| GET | `/api/skills/list` | List .md files |
| POST | `/api/skills/extract` | Extract .md from content (uses Gemini) |
| DELETE | `/api/skills/{skill_id}` | ⚠️ Delete entry + .md file |
| GET | `/api/skills/discover` | Auto-discover skill proposals (Phase C) |
| POST | `/api/skills/discover/accept` | Accept proposal → create .md |
| GET | `/api/skills/discover/cached` | List pending proposals |
| POST | `/api/admin/cleanup-skills` | Run junk filter |
| POST | `/api/admin/sync-skills` | Re-sync skills_db → ChromaDB |

## 🌙 Dream Cycle
| Method | Path | Function |
|---|---|---|
| POST | `/api/dream` | Manually trigger cycle |
| GET | `/api/dream/report` | Latest report |
| GET | `/api/dream/history?limit=N` | Past reports |

## 📁 Documents & Vault (Phase B)
| Method | Path | Function |
|---|---|---|
| POST | `/api/documents/upload` | Upload file/text → chunk + index |
| GET | `/api/documents` | List indexed documents |
| POST | `/api/documents/search` | Semantic search |
| DELETE | `/api/documents/{source}` | Delete document |
| GET | `/api/vault/stats` | Obsidian vault stats |
| POST | `/api/vault/sync` | Sync vault to ChromaDB |
| GET | `/api/vault/search` | Search vault notes |

## 👍 Feedback (Phase C)
| Method | Path | Function |
|---|---|---|
| POST | `/api/feedback` | Submit thumbs up/down |
| GET | `/api/feedback/stats` | Up/down counts |
| GET | `/api/feedback/low-rated` | Down-rated messages |
| GET | `/api/feedback/{message_id}` | Get feedback for message |

## 🧪 Sandbox & FS (Phase D)
| Method | Path | Function |
|---|---|---|
| POST | `/api/sandbox/python` | Run Python in Docker/subprocess sandbox |
| GET | `/api/sandbox/info` | Sandbox status |
| POST | `/api/fs/list` | List directory (whitelist-restricted) |
| POST | `/api/fs/read` | Read file |
| POST | `/api/fs/write` | Write file |
| POST | `/api/fs/search` | Grep-like search |
| GET | `/api/fs/info` | FS roots + limits |

## ⚡ System & Cache
| Method | Path | Function |
|---|---|---|
| GET | `/api/status` | Health: ollama, gemini, memory, skills, dream schedule |
| GET | `/api/cache/stats` | Embed + retrieval + response cache stats (Phase E) |
| GET | `/api/routing/preview?q=...` | Predict which model will be used |
| GET | `/api/config` | App config (model names, paths) |
| GET | `/api/digest` | Daily digest |
| GET | `/api/sysinfo` | OS/CPU/memory info |
| GET | `/api/disk` | Disk usage |
| GET | `/api/docker` | Docker container status |
| GET | `/api/ping/{ip}` | Ping host |
| GET | `/api/health` | Lightweight liveness |
| GET | `/api/check` | Full readiness probe |

## SSE Event Schema (`POST /api/chat`)
```jsonc
data: {"chunk": "text"}                          // streaming response
data: {"citations": [{id, type, source, ...}]}   // source list (Phase B)
data: {"reflection": {score, verdict, ...}}      // critic output (Phase C)
data: {"active_learning": {should_ask, ...}}     // clarification badge (Phase C)
data: {"cache_hit": {similarity, source_prompt}} // semantic cache hit (Phase E)
data: {"agent": {type, step, ...}}               // multi-step agent timeline
data: {"done": true, "model": "...", "provider": "...", "message_id": 123, "timings": {...}, "request_id": "..."}
```

Headers: `X-Request-Id`, `X-Provider-Used`, `X-Model-Used` (เพื่อ trace)
