"""Agent endpoint — multi-step tool use ด้วย SSE events

POST /api/agent
  Body: {"assistant", "session_id", "prompt"}
  Returns: SSE stream
    data: {"type": "thinking", "step": 1}
    data: {"type": "tool_call", "name": "weather", "args": {...}, "id": "..."}
    data: {"type": "tool_result", "name": "weather", "preview": "...", "length": N}
    data: {"type": "answering"}
    data: {"type": "chunk", "text": "..."}
    data: {"type": "done"}
"""
import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from agents.orchestrator import run_agent
from agents.tools import list_tools
from assistants.config import ASSISTANTS
from utils.history import save_message, load_history

router = APIRouter(prefix="/api", tags=["agent"])
logger = logging.getLogger(__name__)


@router.get("/agent/tools")
def list_available_tools():
    """รายชื่อ tools ที่ agent ใช้ได้"""
    from agents.tools import TOOL_REGISTRY
    return {
        "count": len(TOOL_REGISTRY),
        "tools": [
            {
                "name": name,
                "description": spec["description"],
                "parameters": list(spec["parameters"].get("properties", {}).keys()),
            }
            for name, spec in TOOL_REGISTRY.items()
        ],
    }


@router.post("/agent")
async def agent_chat(request: Request):
    data = await request.json()
    assistant = data.get("assistant", list(ASSISTANTS.keys())[0])
    session_id = data.get("session_id", "default")
    prompt = data.get("prompt", "")
    max_steps = int(data.get("max_steps", 4))

    config = ASSISTANTS.get(assistant, list(ASSISTANTS.values())[0])
    base_prompt = config["system_prompt"]

    history = load_history(assistant, session_id)
    save_message(assistant, "user", prompt, "agent", session_id)

    messages = [{"role": "system", "content": base_prompt}]
    messages += [{"role": m["role"], "content": m["content"]} for m in history]
    messages.append({"role": "user", "content": prompt})

    def sse():
        full = ""
        try:
            for kind, payload in run_agent(messages, max_steps=max_steps):
                if kind == "event":
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                elif kind == "chunk":
                    full += payload
                    yield f"data: {json.dumps({'type': 'chunk', 'text': payload}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.exception("[Agent] sse failed")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
        if full:
            try:
                save_message(assistant, "assistant", full, "agent", session_id)
            except Exception as e:
                logger.warning(f"[Agent] save failed: {e}")
        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Agent-Tools": ",".join(list_tools()),
            "Access-Control-Expose-Headers": "X-Agent-Tools",
        },
    )
