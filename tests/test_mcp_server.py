"""Tests สำหรับ mcp_server.py — wrap TOOL_REGISTRY → MCP tools (stdio)

ทดสอบ core (build_tool_list / run_tool) โดยไม่ต้อง spin MCP client จริง
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import mcp.types as types
import mcp_server
from agents.tools import TOOL_REGISTRY


# ── build_tool_list ───────────────────────────────────────────────────────────
def test_tool_list_covers_full_registry():
    tools = mcp_server.build_tool_list()
    assert {t.name for t in tools} == set(TOOL_REGISTRY.keys())
    assert len(tools) == len(TOOL_REGISTRY)


def test_tool_list_schema_maps_parameters():
    tools = {t.name: t for t in mcp_server.build_tool_list()}
    for name, spec in TOOL_REGISTRY.items():
        assert tools[name].inputSchema == spec["parameters"]
        assert tools[name].description  # non-empty


def test_tool_list_items_are_mcp_tool_type():
    assert all(isinstance(t, types.Tool) for t in mcp_server.build_tool_list())


# ── run_tool dispatch ─────────────────────────────────────────────────────────
def test_run_tool_calculator():
    out = asyncio.run(mcp_server.run_tool("calculator", {"expression": "6*7"}))
    assert len(out) == 1
    assert isinstance(out[0], types.TextContent)
    assert out[0].type == "text"
    assert out[0].text == "6*7 = 42"


def test_run_tool_current_time_no_backend():
    out = asyncio.run(mcp_server.run_tool("current_time", {}))
    assert any(c.isdigit() for c in out[0].text)


def test_run_tool_unknown_returns_error_text():
    out = asyncio.run(mcp_server.run_tool("does_not_exist", {}))
    assert "ไม่รู้จัก" in out[0].text


def test_run_tool_bad_args_returns_error_text():
    # calculator ต้องการ expression — ไม่ส่ง → execute_tool คืนข้อความ error (ไม่ throw)
    out = asyncio.run(mcp_server.run_tool("calculator", {}))
    assert out[0].text.startswith("❌")


def test_run_tool_none_arguments_ok():
    # arguments=None → ถือเป็น {} ไม่ crash
    out = asyncio.run(mcp_server.run_tool("current_time", None))
    assert isinstance(out[0], types.TextContent)
