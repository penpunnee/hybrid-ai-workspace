"""Agentic AI Layer — multi-step planning with tool use

Architecture:
  user message
    → orchestrator (Plan → Tool → Observe → ... → Answer)
    → tool registry (web_search, weather, wiki, memory, etc.)
    → SSE stream events to UI
"""
from .tools import TOOL_REGISTRY, execute_tool, get_openai_tools  # noqa
from .orchestrator import run_agent  # noqa
