"""Agent Orchestrator — Plan → Tool → Observe → Answer loop

Yields tuples:
  ("event", dict)  — agent events (thinking/tool_call/tool_result/answering)
  ("chunk", str)   — text chunks ของคำตอบสุดท้าย

ใช้ OpenAI function calling (LM Studio รองรับ)
"""
import json
import logging
import os
from typing import Generator, Any

from openai import OpenAI

from .tools import execute_tool, get_openai_tools

logger = logging.getLogger(__name__)

_LMSTUDIO_BASE_URL = os.getenv("LMSTUDIO_BASE_URL", "http://192.168.51.235:1234/v1")
_LMSTUDIO_TIMEOUT = int(os.getenv("LMSTUDIO_TIMEOUT", "180"))

_client = OpenAI(
    base_url=_LMSTUDIO_BASE_URL,
    api_key="lmstudio",
    timeout=_LMSTUDIO_TIMEOUT,
)


AGENT_SYSTEM_HINT = (
    "\n\n[Agent Mode] คุณมีเครื่องมือที่ใช้ได้:\n"
    "- web_search: ค้นหาข้อมูลในเน็ต\n"
    "- weather: พยากรณ์อากาศ\n"
    "- wikipedia: ข้อมูลจาก Wikipedia\n"
    "- memory_recall: ค้นความทรงจำเก่า\n"
    "- current_time: เวลาปัจจุบัน\n"
    "- calculator: คำนวณตัวเลข\n"
    "- skill_search / obsidian_search: ค้นความรู้ส่วนตัว\n\n"
    "**กฎ:**\n"
    "1. ถ้าต้องการข้อมูลปัจจุบัน/จริง → เรียก tool\n"
    "2. ถ้าเป็นคำถามทั่วไปที่รู้อยู่แล้ว → ตอบตรงๆ ไม่ต้อง tool\n"
    "3. หลังได้ผลจาก tool → สรุปคำตอบจากข้อมูลจริงเท่านั้น ห้ามแต่ง\n"
)


def run_agent(
    messages: list[dict],
    model: str = "",
    max_steps: int = 4,
) -> Generator[tuple[str, Any], None, None]:
    """รัน agent loop

    Args:
        messages: chat history (รวม system prompt) — จะถูก mutate
        model: LM Studio model id
        max_steps: max tool-calling rounds

    Yields:
        ("event", dict): agent event เช่น {"type": "tool_call", "name": "...", "args": {...}}
        ("chunk", str): text chunk ของคำตอบสุดท้าย
    """
    if not model:
        model = os.getenv("LMSTUDIO_CHAT_MODEL", "meta-llama-3.1-8b-instruct")

    # เสริม agent hint ใน system prompt
    if messages and messages[0]["role"] == "system":
        messages[0]["content"] = messages[0]["content"] + AGENT_SYSTEM_HINT
    else:
        messages.insert(0, {"role": "system", "content": AGENT_SYSTEM_HINT.strip()})

    tools_schema = get_openai_tools()

    for step in range(max_steps):
        yield ("event", {"type": "thinking", "step": step + 1})
        logger.info(f"[Agent] step {step+1}/{max_steps}")

        try:
            response = _client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools_schema,
                tool_choice="auto",
                temperature=0.3,
                stream=False,
            )
        except Exception as e:
            logger.exception("[Agent] LLM call failed")
            yield ("event", {"type": "error", "message": str(e)})
            yield ("chunk", f"❌ Agent error: {e}")
            return

        msg = response.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None) or []

        if not tool_calls:
            # ไม่ใช้ tool แล้ว → stream คำตอบสุดท้าย
            yield ("event", {"type": "answering"})
            final = (msg.content or "").strip()
            if final:
                yield ("chunk", final)
            else:
                yield ("chunk", "(agent ไม่มีคำตอบ)")
            return

        # มี tool call → append assistant message + รัน tools
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in tool_calls
            ],
        })

        for tc in tool_calls:
            tool_name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}

            yield ("event", {
                "type": "tool_call",
                "name": tool_name,
                "args": args,
                "id": tc.id,
            })

            result = execute_tool(tool_name, args)
            yield ("event", {
                "type": "tool_result",
                "name": tool_name,
                "id": tc.id,
                "preview": result[:300],
                "length": len(result),
            })

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "name": tool_name,
                "content": result,
            })

    # ครบ max_steps แต่ยังไม่มี final answer → บังคับสรุป
    yield ("event", {"type": "max_steps_reached"})
    messages.append({
        "role": "user",
        "content": "สรุปคำตอบสุดท้ายจากข้อมูล tools ที่ได้มาแล้ว ห้ามเรียก tool เพิ่ม",
    })
    try:
        final_stream = _client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.3,
            stream=True,
        )
        for chunk in final_stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield ("chunk", delta)
    except Exception as e:
        yield ("chunk", f"❌ Final synthesis failed: {e}")
