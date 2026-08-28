"""Agent Orchestrator — Plan → Tool → Observe → Answer loop

Yields tuples:
  ("event", dict)  — agent events (thinking/tool_call/tool_result/answering/error)
  ("chunk", str)   — text chunks ของคำตอบสุดท้าย

รองรับหลาย provider:
  - "gemini"    → google.genai SDK (function calling)
  - "lmstudio"  → OpenAI-compatible client
  - "ollama"    → ReAct text loop (Thought/Action/Observation/Answer)
"""
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Generator, Any

from .tools import execute_tool, get_openai_tools, get_gemini_tools, list_tools

logger = logging.getLogger(__name__)

_FORCE_SYNTH_PROMPT = (
    "ตอบคำถามจากข้อมูล tools ที่ได้มาให้ครบถ้วน — เก็บรายละเอียดสำคัญ ตัวเลข "
    "และแหล่งที่มาให้ครบ ความยาวให้เหมาะกับคำถาม (user ขอละเอียด = ตอบละเอียด) "
    "ห้ามเรียก tool เพิ่ม"
)


def _chunk_parts(chunk) -> list:
    """ดึง parts จาก Gemini stream chunk แบบทน None"""
    cands = getattr(chunk, "candidates", None) or []
    if not cands:
        return []
    content = getattr(cands[0], "content", None)
    return getattr(content, "parts", None) or []


def _is_retryable_gemini(e: Exception) -> bool:
    """error ชั่วคราวที่ retry ได้ (503 overloaded / 429 / 5xx) — ยกเว้น limit:0
    (free-tier ปิดโมเดลถาวร retry ไม่ช่วย, CLAUDE.md quirk)"""
    s = str(e).lower()
    if "limit: 0" in s or '"limit": 0' in s:
        return False
    try:
        from google.genai import errors as ge
        if isinstance(e, ge.ServerError):
            return True
    except Exception:
        pass
    code = getattr(e, "code", None) or getattr(e, "status_code", None)
    if code in (429, 500, 502, 503, 504):
        return True
    return any(k in s for k in ("unavailable", "overloaded", "high demand",
                                "try again", "resource_exhausted", "503", "502", "504"))


def _gemini_stream_with_retry(chat, message, max_retries: int = 2, base_delay: float = 1.0):
    """Generator stream chunks — retry เฉพาะ error ชั่วคราวที่เกิด *ก่อน* chunk แรก
    ออกมา (กัน duplicate ครึ่งคำตอบ ถ้า fail กลางทาง)"""
    attempt = 0
    while True:
        produced = False
        try:
            for chunk in chat.send_message_stream(message):
                produced = True
                yield chunk
            return
        except Exception as e:
            if produced or attempt >= max_retries or not _is_retryable_gemini(e):
                raise
            delay = base_delay * (2 ** attempt)
            logger.warning(
                f"[Agent/Gemini] retryable error (try {attempt+1}/{max_retries}): {e} "
                f"— backoff {delay}s"
            )
            time.sleep(delay)
            attempt += 1


class _MarkerFilter:
    """ตัด marker จาก chat template ของ LM Studio (เช่น [TOOL_RESULT]) ที่โมเดล echo
    ออกมาในคำตอบ — ทำงานแบบ stateful รองรับ marker ที่โดนแบ่งข้าม chunk
    (pattern เดียวกับ _partial_tag_suffix_len ใน reasoning/parser.py)"""

    _MARKERS = ("[TOOL_RESULT]", "[END_TOOL_RESULT]")

    def __init__(self):
        self._buf = ""
        self._emitted = False  # ยังไม่ส่งอะไรออก → lstrip ช่องว่างนำหน้า

    def _hold_len(self) -> int:
        """ความยาว suffix ของ buffer ที่อาจเป็น marker ที่ยังมาไม่ครบ"""
        hold = 0
        for m in self._MARKERS:
            for k in range(min(len(m) - 1, len(self._buf)), 0, -1):
                if self._buf.endswith(m[:k]):
                    hold = max(hold, k)
                    break
        return hold

    def feed(self, chunk: str) -> str:
        self._buf += chunk
        for m in self._MARKERS:
            self._buf = self._buf.replace(m, "")
        cut = len(self._buf) - self._hold_len()
        out, self._buf = self._buf[:cut], self._buf[cut:]
        if not self._emitted:
            out = out.lstrip()
        if out:
            self._emitted = True
        return out

    def flush(self) -> str:
        out, self._buf = self._buf, ""
        return out if self._emitted else out.lstrip()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
LMSTUDIO_BASE_URL = os.getenv("LMSTUDIO_BASE_URL", "")
LMSTUDIO_API_KEY = os.getenv("LMSTUDIO_API_KEY", "lmstudio")
LMSTUDIO_TIMEOUT = int(os.getenv("LMSTUDIO_TIMEOUT", "180"))
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "120"))

AGENT_SYSTEM_HINT = (
    "\n\n[Agent Mode] คุณมีเครื่องมือที่ใช้ได้:\n"
    "- web_search: ค้นหาข้อมูลในเน็ต\n"
    "- fetch_url: อ่านเนื้อหาเต็มจากหน้าเว็บตาม URL (ใช้เมื่อ user วางลิงก์/รู้ URL แล้ว)\n"
    "- weather: พยากรณ์อากาศ\n"
    "- wikipedia: ข้อมูลจาก Wikipedia\n"
    "- memory_recall: ค้นความทรงจำเก่า\n"
    "- current_time: เวลาปัจจุบัน\n"
    "- calculator: คำนวณตัวเลข\n"
    "- skill_search / obsidian_search: ค้นความรู้ส่วนตัว\n"
    "- run_python / fs_list / fs_read / fs_write / fs_search: รันโค้ด + จัดการไฟล์ใน sandbox\n"
    "- ping_network: ping Router+NAS+PC จริง | ping_device: ping IP จริง\n"
    "- nas_disk: พื้นที่ดิสก์ NAS | nas_docker: container บน NAS | wol_pc: ปลุก PC\n"
    "- ha_search_entities: ค้น entity ใน Home Assistant\n"
    "- ha_get_state: ดูสถานะอุปกรณ์ใน Home Assistant\n"
    "- ha_call_service: สั่งเปิด/ปิด/ตั้งค่าอุปกรณ์ใน Home Assistant\n\n"
    "**กฎ:**\n"
    "1. ถ้าต้องการข้อมูลปัจจุบัน/จริง → เรียก tool\n"
    "2. ถ้าเป็นคำถามทั่วไปที่รู้อยู่แล้ว → ตอบตรงๆ ไม่ต้อง tool\n"
    "3. **คำถามสถานะ network/router/NAS/disk/container/อุปกรณ์ออนไลน์ → ต้องเรียก tool เสมอ "
    "ห้ามเดา/แต่งผลเอง** (มี ping_network/nas_disk/nas_docker ให้ใช้)\n"
    "4. **สั่งอุปกรณ์ในบ้าน (ไฟ/แอร์/ปลั๊ก/automation) → เรียก ha_search_entities ก่อน "
    "เพื่อหา entity_id จริง แล้วค่อย ha_call_service**\n"
    "5. หลังได้ผลจาก tool → สรุปคำตอบจากข้อมูลจริงเท่านั้น ห้ามแต่ง\n"
    "6. **user พูดว่า 'ไปหาในเน็ต'/'เช็คเน็ต'/'ดูในเน็ต'/'อินเทอร์เน็ต'/'search'/'ค้นหา' "
    "→ ต้องเรียก web_search ทันที ห้ามตอบจากความจำ**\n"
)

# ReAct system prompt สำหรับ Ollama (text-based loop แทน function calling)
_REACT_SYSTEM = """คุณเป็น AI assistant ที่มีเครื่องมือ (tools) ใช้ได้ดังนี้:
{tool_list}

วิธีใช้ tool: เขียนในรูปแบบนี้เท่านั้น
Thought: [เหตุผลว่าต้องทำอะไร]
Action: {{"tool": "ชื่อtool", "args": {{...}}}}

จากนั้นระบบจะตอบกลับด้วย:
Observation: [ผลลัพธ์จาก tool]

เมื่อได้คำตอบครบแล้ว ให้เขียน:
Answer: [คำตอบสุดท้าย]

กฎเหล็ก:
- ห้ามแต่งผลลัพธ์จาก tool เอง — รอ Observation จริงเสมอ
- user พูดว่า "หาในเน็ต" / "เช็คเน็ต" / "ดูในเน็ต" / "อินเทอร์เน็ต" / "search" → เรียก web_search ทันที ห้ามตอบจากความจำ
- สั่งอุปกรณ์ในบ้าน → เรียก ha_search_entities ก่อนเพื่อหา entity_id จริง
- คำถามสถานะ network/disk/container → เรียก tool เสมอ ห้ามเดา
- ถ้าไม่ต้องใช้ tool → เขียน Answer: ตรงๆ ได้เลย
"""


def run_agent(
    messages: list[dict],
    model: str = "",
    max_steps: int = 4,
    provider: str = "gemini",
) -> Generator[tuple[str, Any], None, None]:
    """รัน agent loop

    Args:
        messages: chat history (รวม system prompt)
        model: model id (ปล่อยว่าง = ใช้ default ของ provider)
        max_steps: max tool-calling rounds
        provider: "gemini" | "lmstudio"
    """
    if provider == "gemini":
        yield from _run_agent_gemini(messages, model or GEMINI_MODEL, max_steps)
    elif provider == "lmstudio":
        yield from _run_agent_lmstudio(messages, model, max_steps)
    elif provider == "ollama":
        yield from _run_agent_ollama(messages, model or OLLAMA_MODEL, max_steps)
    else:
        yield ("event", {"type": "error", "message": f"ไม่รู้จัก agent provider: '{provider}'"})
        yield ("chunk", f"❌ ไม่รู้จัก agent provider: {provider}")


# ── Unified function-calling agent loop (item E) ─────────────────────────────
# Gemini + LM Studio share loop เดียวกัน — ต่างแค่ adapter (วิธี generate +
# format tool-result). Ollama ReAct เป็นคนละ paradigm เก็บแยก

@dataclass
class ToolCall:
    name: str
    args: dict = field(default_factory=dict)
    id: str = ""


def _run_agent_fc(adapter, max_steps: int) -> Generator[tuple[str, Any], None, None]:
    """loop กลาง provider-agnostic: thinking → generate → ถ้ามี tool call รัน
    แล้ววนต่อ, ไม่มี = คำตอบสุดท้าย (stream). ครบ max_steps → บังคับ synthesize.
    adapter ต้องมี: .name, .step()→yield ('text',str)|('call',ToolCall),
    .add_tool_results(list[(ToolCall,str)]), .synthesize()→yield ('text',str)"""
    for step in range(max_steps):
        yield ("event", {"type": "thinking", "step": step + 1})
        logger.info(f"[Agent/{adapter.name}] step {step+1}/{max_steps}")
        calls: list[ToolCall] = []
        answered = False
        try:
            for kind, payload in adapter.step():
                if kind == "call":
                    calls.append(payload)
                elif kind == "text" and payload:
                    if not answered:
                        yield ("event", {"type": "answering"})
                        answered = True
                    yield ("chunk", payload)
        except Exception as e:
            logger.exception(f"[Agent/{adapter.name}] step failed")
            yield ("event", {"type": "error", "message": str(e)})
            yield ("chunk", f"❌ {adapter.name} agent error: {e}")
            return

        if not calls:
            if not answered:
                yield ("chunk", "(agent ไม่มีคำตอบ)")
            return

        results: list[tuple[ToolCall, str]] = []
        for call in calls:
            ev = {"type": "tool_call", "name": call.name, "args": call.args}
            if call.id:
                ev["id"] = call.id
            yield ("event", ev)
            result = execute_tool(call.name, call.args)
            rev = {"type": "tool_result", "name": call.name, "preview": result[:300], "length": len(result)}
            if call.id:
                rev["id"] = call.id
            yield ("event", rev)
            results.append((call, result))
        adapter.add_tool_results(results)

    yield ("event", {"type": "max_steps_reached"})
    answered = False
    try:
        for kind, payload in adapter.synthesize():
            if kind == "text" and payload:
                answered = True
                yield ("chunk", payload)
        if not answered:
            yield ("chunk", "(ไม่มีคำตอบ)")
    except Exception as e:
        yield ("chunk", f"❌ Final synthesis failed: {e}")


class _GeminiAdapter:
    name = "Gemini"

    def __init__(self, chat, last_user):
        self.chat = chat
        self._pending = last_user      # str (step1/synth) | list[Part] (หลัง tool)

    def step(self):
        for chunk in _gemini_stream_with_retry(self.chat, self._pending):
            for part in _chunk_parts(chunk):
                fc = getattr(part, "function_call", None)
                if fc:
                    yield ("call", ToolCall(name=fc.name, args=dict(fc.args) if fc.args else {}))
                    continue
                txt = getattr(part, "text", None)
                if txt:
                    yield ("text", txt)

    def add_tool_results(self, results):
        # list[Part] ตรงๆ — SDK ห่อเป็น Content(role=user) เอง (ห้ามส่ง types.Content)
        from google.genai import types as genai_types
        self._pending = [
            genai_types.Part.from_function_response(name=c.name, response={"result": r})
            for c, r in results
        ]

    def synthesize(self):
        for chunk in _gemini_stream_with_retry(self.chat, _FORCE_SYNTH_PROMPT):
            for part in _chunk_parts(chunk):
                txt = getattr(part, "text", None)
                if txt:
                    yield ("text", txt)


class _LMStudioAdapter:
    name = "LM Studio"

    def __init__(self, client, model, messages, tools_schema):
        self.client = client
        self.model = model
        self.messages = messages
        self.tools = tools_schema

    def step(self):
        # non-stream ตอน detect tool (OpenAI stream tool_call args เป็นชิ้น ยุ่ง)
        response = self.client.chat.completions.create(
            model=self.model, messages=self.messages, tools=self.tools,
            tool_choice="auto", temperature=0.3, stream=False,
        )
        msg = response.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None) or []
        if not tool_calls:
            mf = _MarkerFilter()
            final = (mf.feed(msg.content or "") + mf.flush()).strip()
            yield ("text", final or "(agent ไม่มีคำตอบ)")
            return
        self.messages.append({
            "role": "assistant", "content": msg.content or "",
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in tool_calls
            ],
        })
        for tc in tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            yield ("call", ToolCall(name=tc.function.name, args=args, id=tc.id))

    def add_tool_results(self, results):
        for call, result in results:
            self.messages.append({"role": "tool", "tool_call_id": call.id,
                                  "name": call.name, "content": result})

    def synthesize(self):
        self.messages.append({"role": "user", "content": _FORCE_SYNTH_PROMPT})
        stream = self.client.chat.completions.create(
            model=self.model, messages=self.messages, temperature=0.3, stream=True)
        mf = _MarkerFilter()
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                out = mf.feed(delta)
                if out:
                    yield ("text", out)
        tail = mf.flush()
        if tail:
            yield ("text", tail)


# ── Gemini path ──────────────────────────────────────────────────────────────

def _run_agent_gemini(
    messages: list[dict],
    model: str,
    max_steps: int,
) -> Generator[tuple[str, Any], None, None]:
    if not GEMINI_API_KEY:
        yield ("event", {"type": "error", "message": "GEMINI_API_KEY ไม่ได้ตั้งค่า"})
        yield ("chunk", "❌ Agent mode ต้องการ GEMINI_API_KEY")
        return

    try:
        from google.genai import Client as GenaiClient
        from google.genai import types as genai_types
    except ImportError as e:
        yield ("event", {"type": "error", "message": f"google.genai ไม่พร้อม: {e}"})
        yield ("chunk", "❌ google.genai SDK ไม่ได้ติดตั้ง")
        return

    client = GenaiClient(api_key=GEMINI_API_KEY)
    tools_schema = get_gemini_tools()
    gemini_tool = genai_types.Tool(function_declarations=tools_schema)

    # แปลง messages → Gemini format
    system_text, history, last_user = _split_messages_for_gemini(messages)
    system_text = (system_text or "") + AGENT_SYSTEM_HINT

    chat = client.chats.create(
        model=model,
        config=genai_types.GenerateContentConfig(
            system_instruction=system_text,
            tools=[gemini_tool],
            temperature=0.3,
        ),
        history=history,
    )

    # loop กลาง (item E) — streaming (A) + retry (F) + Content-fix อยู่ใน _GeminiAdapter
    yield from _run_agent_fc(_GeminiAdapter(chat, last_user), max_steps)


def _split_messages_for_gemini(messages: list[dict]) -> tuple[str, list, str]:
    """แยก messages → (system_text, history, last_user_prompt)"""
    from google.genai import types as genai_types

    system_text = ""
    history = []
    last_user = ""

    work = list(messages)
    if work and work[0]["role"] == "system":
        system_text = work.pop(0)["content"]

    # last user message จะส่งผ่าน chat.send_message
    if work and work[-1]["role"] == "user":
        last_user = work.pop()["content"]

    for msg in work:
        role = "user" if msg["role"] == "user" else "model"
        history.append(
            # SDK ใหม่บังคับ keyword-only: from_text(text=...) — positional = TypeError
            genai_types.Content(role=role, parts=[genai_types.Part.from_text(text=msg["content"] or "")])
        )

    return system_text, history, last_user


# ── LM Studio path (เดิม) ─────────────────────────────────────────────────────

def _run_agent_lmstudio(
    messages: list[dict],
    model: str,
    max_steps: int,
) -> Generator[tuple[str, Any], None, None]:
    if not LMSTUDIO_BASE_URL:
        yield ("event", {"type": "error", "message": "LMSTUDIO_BASE_URL ไม่ได้ตั้งค่า"})
        yield ("chunk", "❌ Agent mode (LM Studio) ต้องตั้ง LMSTUDIO_BASE_URL")
        return

    try:
        from openai import OpenAI
    except ImportError as e:
        yield ("event", {"type": "error", "message": f"openai SDK ไม่พร้อม: {e}"})
        return

    client = OpenAI(
        base_url=LMSTUDIO_BASE_URL,
        api_key=LMSTUDIO_API_KEY,
        timeout=LMSTUDIO_TIMEOUT,
    )
    if not model:
        model = os.getenv("LMSTUDIO_CHAT_MODEL", "meta-llama-3.1-8b-instruct")

    if messages and messages[0]["role"] == "system":
        messages[0]["content"] = messages[0]["content"] + AGENT_SYSTEM_HINT
    else:
        messages.insert(0, {"role": "system", "content": AGENT_SYSTEM_HINT.strip()})

    tools_schema = get_openai_tools()

    # loop กลาง (item E) — provider quirks (role:tool, MarkerFilter) อยู่ใน _LMStudioAdapter
    yield from _run_agent_fc(_LMStudioAdapter(client, model, messages, tools_schema), max_steps)


# ── Ollama ReAct path ─────────────────────────────────────────────────────────

_ACTION_RE = re.compile(r"Action:\s*(\{.*?\})", re.DOTALL)
_ANSWER_RE = re.compile(r"Answer:\s*(.*)", re.DOTALL)


def _build_react_system(tool_names: list[str]) -> str:
    tool_list = "\n".join(f"- {name}" for name in tool_names)
    return _REACT_SYSTEM.format(tool_list=tool_list)


def _run_agent_ollama(
    messages: list[dict],
    model: str,
    max_steps: int,
) -> Generator[tuple[str, Any], None, None]:
    try:
        from openai import OpenAI
    except ImportError as e:
        yield ("event", {"type": "error", "message": f"openai SDK ไม่พร้อม: {e}"})
        return

    client = OpenAI(
        base_url=OLLAMA_BASE_URL,
        api_key="ollama",
        timeout=OLLAMA_TIMEOUT,
    )

    tool_names = list_tools()
    react_system = _build_react_system(tool_names)

    # ฉีด ReAct system prompt
    if messages and messages[0]["role"] == "system":
        messages[0]["content"] = messages[0]["content"] + "\n\n" + react_system
    else:
        messages.insert(0, {"role": "system", "content": react_system})

    for step in range(max_steps):
        yield ("event", {"type": "thinking", "step": step + 1})
        logger.info(f"[Agent/Ollama] step {step+1}/{max_steps}")

        # รวม history ทั้งหมดเป็น prompt เดียวสำหรับ Ollama
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.3,
                stream=False,
                extra_body={"options": {"num_ctx": int(os.getenv("OLLAMA_NUM_CTX", "4096"))}},
            )
        except Exception as e:
            logger.exception("[Agent/Ollama] LLM call failed")
            yield ("event", {"type": "error", "message": str(e)})
            yield ("chunk", f"❌ Ollama agent error: {e}")
            return

        content = (response.choices[0].message.content or "").strip()
        logger.debug(f"[Agent/Ollama] raw output: {content[:300]}")

        # ตรวจ Answer ก่อน
        answer_match = _ANSWER_RE.search(content)
        if answer_match:
            yield ("event", {"type": "answering"})
            yield ("chunk", answer_match.group(1).strip())
            return

        # ตรวจ Action
        action_match = _ACTION_RE.search(content)
        if not action_match:
            # โมเดลไม่ทำตาม format → ถือว่าเป็นคำตอบตรง
            yield ("event", {"type": "answering"})
            yield ("chunk", content)
            return

        try:
            action = json.loads(action_match.group(1))
            tool_name = action.get("tool", "")
            args = action.get("args", {})
        except json.JSONDecodeError as e:
            logger.warning(f"[Agent/Ollama] JSON parse error: {e} — raw: {action_match.group(1)}")
            yield ("event", {"type": "error", "message": f"JSON parse error: {e}"})
            yield ("chunk", content)
            return

        yield ("event", {"type": "tool_call", "name": tool_name, "args": args})
        result = execute_tool(tool_name, args)
        yield ("event", {
            "type": "tool_result",
            "name": tool_name,
            "preview": result[:300],
            "length": len(result),
        })

        # เพิ่ม turn นี้เข้า history เพื่อ loop ต่อ
        messages.append({"role": "assistant", "content": content})
        messages.append({"role": "user", "content": f"Observation: {result}"})

    # ครบ max_steps → บังคับสรุป
    yield ("event", {"type": "max_steps_reached"})
    messages.append({
        "role": "user",
        "content": "ตอบจากข้อมูลที่ได้มาให้ครบถ้วน เก็บรายละเอียดและแหล่งที่มา เขียนแค่ Answer: ... เท่านั้น",
    })
    try:
        final = client.chat.completions.create(
            model=model, messages=messages, temperature=0.3, stream=False,
            extra_body={"options": {"num_ctx": int(os.getenv("OLLAMA_NUM_CTX", "4096"))}},
        )
        final_content = (final.choices[0].message.content or "").strip()
        answer_match = _ANSWER_RE.search(final_content)
        yield ("chunk", answer_match.group(1).strip() if answer_match else final_content)
    except Exception as e:
        yield ("chunk", f"❌ Final synthesis failed: {e}")
