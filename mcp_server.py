#!/usr/bin/env python3
"""mcp_server.py — expose Hybrid AI Workspace tools ผ่าน MCP (stdio)

wrap `agents.tools.TOOL_REGISTRY` (13 tools) เป็น MCP tools ให้ Claude Code / IDE
อื่นเรียกใช้ — ไม่เขียน tool ซ้ำ, dispatch ไป `execute_tool()` เดิมตรงๆ

รัน (Claude Code จะ launch เป็น subprocess ผ่าน stdio):
    python3 mcp_server.py

ลงทะเบียนกับ Claude Code:
    claude mcp add hybrid-ai -- python3 /Users/pawin/Desktop/ui/mcp_server.py

tools ที่ต้องใช้ backend บน NAS (memory_recall / skill_search / obsidian_search)
ให้ตั้ง env ตอน register เช่น CHROMA_HOST=192.168.51.49 ; run_python ต้องมี Docker
ดู skills/mcp-server-export.md
"""
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server import Server
from mcp.server.stdio import stdio_server
import mcp.types as types

from agents.tools import TOOL_REGISTRY, execute_tool

logger = logging.getLogger(__name__)

SERVER_NAME = "hybrid-ai-tools"


# ── core (testable แยกจาก MCP wiring) ─────────────────────────────────────────
def build_tool_list() -> list[types.Tool]:
    """แปลง TOOL_REGISTRY → MCP Tool list (inputSchema = parameters เดิม)"""
    return [
        types.Tool(
            name=name,
            description=spec["description"],
            inputSchema=spec["parameters"],
        )
        for name, spec in TOOL_REGISTRY.items()
    ]


async def run_tool(name: str, arguments: dict | None) -> list[types.TextContent]:
    """dispatch ไป execute_tool — รันใน thread กัน block event loop (tool บางตัว I/O)"""
    result = await asyncio.to_thread(execute_tool, name, arguments or {})
    return [types.TextContent(type="text", text=result)]


# ── MCP server wiring ─────────────────────────────────────────────────────────
server = Server(SERVER_NAME)


@server.list_tools()
async def _list_tools() -> list[types.Tool]:
    return build_tool_list()


@server.call_tool()
async def _call_tool(name: str, arguments: dict | None) -> list[types.TextContent]:
    logger.info("[MCP] call_tool %s", name)
    return await run_tool(name, arguments)


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
