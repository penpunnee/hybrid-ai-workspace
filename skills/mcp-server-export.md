# MCP Server Export — เปิด tools ให้ Claude Code / IDE อื่น

`mcp_server.py` เปิด **13 tools** ของ Hybrid AI Workspace (จาก `agents/tools.py` `TOOL_REGISTRY`)
ผ่าน Model Context Protocol แบบ **stdio** — wrap `execute_tool()` เดิม ไม่เขียน tool ซ้ำ

## ติดตั้ง
```bash
pip install mcp          # อยู่ใน requirements.txt แล้ว (mcp>=1.27)
```

## ลงทะเบียนกับ Claude Code
```bash
# พื้นฐาน (tools ที่ไม่ต้องใช้ backend: calculator, current_time, web_search,
#          weather, wikipedia, fs_*)
claude mcp add hybrid-ai -- python3 /Users/pawin/Desktop/ui/mcp_server.py

# ถ้าอยากให้ memory_recall / skill_search / obsidian_search ทำงาน (ต้องต่อ ChromaDB)
claude mcp add hybrid-ai \
  --env CHROMA_HOST=192.168.51.49 \
  --env CHROMA_PORT=8000 \
  -- python3 /Users/pawin/Desktop/ui/mcp_server.py
```
ตรวจ: `claude mcp list` → ควรเห็น `hybrid-ai` ; ในเซสชัน Claude Code จะมี tool `hybrid-ai__calculator` ฯลฯ

### config JSON (IDE อื่น เช่น Cursor / .mcp.json)
```jsonc
{
  "mcpServers": {
    "hybrid-ai": {
      "command": "python3",
      "args": ["/Users/pawin/Desktop/ui/mcp_server.py"],
      "env": { "CHROMA_HOST": "192.168.51.49", "CHROMA_PORT": "8000" }
    }
  }
}
```

## tools ที่เปิด (13)
| tool | backend ที่ต้องมี |
|---|---|
| `calculator`, `current_time` | — (ไม่ต้อง) |
| `web_search`, `weather`, `wikipedia` | อินเทอร์เน็ต |
| `fs_list`, `fs_read`, `fs_write`, `fs_search` | sandbox dir (FS_TOOLS_ROOTS) |
| `memory_recall`, `skill_search`, `obsidian_search` | ChromaDB (NAS) → ตั้ง `CHROMA_HOST` |
| `run_python` | Docker (ไม่งั้น fallback subprocess; ดู `CODE_SANDBOX_ALLOW_LOCAL`) |

## สถาปัตยกรรม
- `build_tool_list()` — แปลง `TOOL_REGISTRY[*].parameters` → MCP `Tool.inputSchema` ตรงๆ
- `run_tool(name, args)` — `await asyncio.to_thread(execute_tool, ...)` (กัน block event loop เพราะ tool บางตัวเป็น I/O)
- ดังนั้นเพิ่ม tool ใหม่ใน `TOOL_REGISTRY` → โผล่ใน MCP อัตโนมัติ ไม่ต้องแก้ `mcp_server.py`

## ทดสอบเอง (ไม่ต้องมี Claude Code)
```bash
python3 mcp_server.py     # ค้างรอ stdio — Ctrl-C ออก (ปกติ Claude Code เป็นคน launch)
pytest tests/test_mcp_server.py -v
```

## ข้อจำกัด / งานต่อ
- ตอนนี้เป็น **stdio** (local subprocess) — ถ้าต้องการ remote ให้ mount MCP over HTTP
  ใน `server.py` (ส่งผ่าน Cloudflare + x-auth-token) ยังไม่ได้ทำ
- run_python ผ่าน MCP จะรันใน sandbox เดียวกับ backend (ระวังสิทธิ์ FS/Docker)
