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
import re
import time
from dataclasses import dataclass, field
from typing import Generator, Any

from .tools import execute_tool, get_openai_tools, get_gemini_tools, list_tools

logger = logging.getLogger(__name__)
_monotonic = time.monotonic   # นาฬิกาของเพดานเวลารวม LM Studio step — แยกชื่อไว้ให้เทสแทนได้โดยไม่แตะ time ทั้งระบบ

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


def _gemini_stream_with_retry(chat, message, max_retries: int = 2, base_delay: float = 1.0, config=None):
    """Generator stream chunks — retry เฉพาะ error ชั่วคราวที่เกิด *ก่อน* chunk แรก
    ออกมา (กัน duplicate ครึ่งคำตอบ ถ้า fail กลางทาง) · `config` = ต่อคำขอ (SDK แทนที่ config ของ chat ทั้งก้อน)"""
    attempt = 0
    while True:
        produced = False
        try:
            stream = (chat.send_message_stream(message, config=config) if config is not None
                      else chat.send_message_stream(message))
            for chunk in stream:
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

from utils.llm import GEMINI_MODEL  # ที่เดียว (ดู utils/llm.py:GEMINI_MODEL_DEFAULT)
from utils.llm import _stop_if_cancelled  # ธงยกเลิกของ request (ก้อน 10/12)
from utils.llm import _fit_lmstudio_context  # ตัดประวัติให้พอดี context — กติกาเดียวกับแชท (ต่อ 75)
from assistants.config import SUGGEST_AGENT_MODE
# ⬇️ env ทุกตัวของไฟล์นี้มีเจ้าของอยู่ที่ core/config.py — import ค่า ห้ามอ่านซ้ำ
# (ก้อน 4 · 2026-09-23 · ตัวกัน: tests/test_env_registry.py + test_orchestrator_config.py)
# ชื่อระดับโมดูลคงไว้เหมือนเดิม — เทสใช้ patch("agents.orchestrator.GEMINI_API_KEY") ฯลฯ
from core.config import (
    GEMINI_API_KEY,
    LMSTUDIO_API_KEY,
    LMSTUDIO_BASE_URL,
    LMSTUDIO_TIMEOUT,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OLLAMA_NUM_CTX,
    OLLAMA_TIMEOUT,
)
from core.config import LMSTUDIO_CHAT_MODEL as _CFG_LMSTUDIO_CHAT_MODEL

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



def _agent_system(system_text: str, hint: str) -> str:
    """system ของ agent = persona − ประโยค "แนะนำให้เปิด Agent mode" + hint (อยู่ใน agent แล้ว)"""
    return (system_text or "").replace(SUGGEST_AGENT_MODE, "") + hint


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
    image_b64: str = "",
    image_mime: str = "",
    cancel=None,
) -> Generator[tuple[str, Any], None, None]:
    """รัน agent loop

    Args:
        messages: chat history (รวม system prompt)
        model: model id (ปล่อยว่าง = ใช้ default ของ provider)
        max_steps: max tool-calling rounds
        provider: "gemini" | "lmstudio" | "ollama"
        image_b64/image_mime: รูปแนบ — ต่อเข้า user message ล่าสุดของ provider
            ที่มองรูปได้ · provider ที่ไม่มี vision ต้อง **บอก** ไม่ใช่ทิ้งเงียบ
        cancel: `utils.llm.StreamCancel` ของ request (ก้อน 12) — ผู้ใช้กด Stop แล้วตัด LM Studio ทันที
            ใช้เฉพาะ lmstudio: เส้นอื่นหยุดที่ yield ถัดไปอยู่แล้ว (`_guard_disconnect` ปิด generator)
            ส่วน LM Studio step เดิมเป็น non-stream ที่ค้างได้ถึง LMSTUDIO_TIMEOUT และ GPU คิดต่อทิ้งเปล่า
    """
    if provider == "gemini":
        yield from _run_agent_gemini(messages, model or GEMINI_MODEL, max_steps,
                                     image_b64=image_b64, image_mime=image_mime)
    elif provider == "lmstudio":
        yield from _run_agent_lmstudio(messages, model, max_steps,
                                       image_b64=image_b64, image_mime=image_mime, cancel=cancel)
    elif provider == "ollama":
        if image_b64:
            # ReAct/llama3 ไม่มี vision — เงียบไปเฉยๆ = user ไม่รู้ว่ารูปไม่ถูกอ่าน
            logger.warning("[Agent/Ollama] มีรูปแนบมาแต่ ReAct path ไม่รองรับ vision — ข้ามรูป")
            yield ("event", {"type": "warning",
                             "message": "โหมด agent บน Ollama อ่านรูปไม่ได้ — รูปที่แนบมาถูกข้าม "
                                        "(ใช้ provider gemini หรือ lmstudio ถ้าต้องการให้ดูรูป)"})
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


def _tool_status(result: str) -> str:
    """สถานะผล tool สำหรับ log — ดูแค่เครื่องหมายนำหน้า (execute_tool ขึ้นต้น ❌ เมื่อล้มเสมอ · ⚠️ = tool รายงานไม่แน่ใจ)
    ⚠️ tool บางตัวรายงาน "ว่าง" โดยไม่มีเครื่องหมาย (เช่น NAS ไม่มีข้อมูล volume) → นับเป็น ok ที่นี่ · log ใช้วัด ไม่ใช่ guard"""
    t = (result or "").strip()
    if not t:
        return "empty"
    if t.startswith("❌"):
        return "error"
    if t.startswith("⚠️"):
        return "warn"
    return "ok"


def _run_agent_fc(adapter, max_steps: int) -> Generator[tuple[str, Any], None, None]:
    """loop กลาง provider-agnostic: thinking → generate → ถ้ามี tool call รัน
    แล้ววนต่อ, ไม่มี = คำตอบสุดท้าย (stream). ครบ max_steps → บังคับ synthesize.
    adapter ต้องมี: .name, .step()→yield ('text',str)|('call',ToolCall),
    .add_tool_results(list[(ToolCall,str)]), .synthesize()→yield ('text',str)
    · adapter.cancel (ถ้ามี) = ธงยกเลิก — ถูกตัดกลางคันแล้วจบเงียบ ห้าม yield ข้อความ error/"ไม่มีคำตอบ"
      (router บันทึกคำตอบบางส่วน + "หยุดกลางคัน" เอง · ข้อความ error จะไปปนในคำตอบที่บันทึก)"""
    cancel = getattr(adapter, "cancel", None)
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
            if _stop_if_cancelled(cancel):      # exception จาก socket ที่เราตัดเอง ไม่ใช่ error จริง
                logger.info(f"[Agent/{adapter.name}] ถูกยกเลิก (client ตัดสาย) — หยุดที่ step {step+1}")
                return
            logger.exception(f"[Agent/{adapter.name}] step failed")
            yield ("event", {"type": "error", "message": str(e)})
            yield ("chunk", f"❌ {adapter.name} agent error: {e}")
            return
        if cancel is not None and cancel.aborted:
            logger.info(f"[Agent/{adapter.name}] ถูกยกเลิก (client ตัดสาย) — หยุดที่ step {step+1}")
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
            # 1 บรรทัดต่อ tool — **ไม่ใส่เนื้อหา** (ผล web/memory อาจมีข้อมูลส่วนตัว · log rotate เก็บ 5 ไฟล์)
            # ใช้วัดว่า tool ได้ข้อมูลจริงบ่อยแค่ไหน ก่อนตัดสินเรื่อง guard "ไม่มีข้อมูลจริง" (ขั้น 4 · 09-29)
            logger.info(f"[Agent/{adapter.name}] tool {call.name} step={step + 1} "
                        f"len={len(result)} status={_tool_status(result)}")
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
        if cancel is not None and cancel.aborted:
            logger.info(f"[Agent/{adapter.name}] ถูกยกเลิก (client ตัดสาย) — หยุดระหว่างสรุป")
            return
        if not answered:
            yield ("chunk", "(ไม่มีคำตอบ)")
    except Exception as e:
        if _stop_if_cancelled(cancel):
            logger.info(f"[Agent/{adapter.name}] ถูกยกเลิก (client ตัดสาย) — หยุดระหว่างสรุป")
            return
        yield ("chunk", f"❌ Final synthesis failed: {e}")


class _GeminiAdapter:
    name = "Gemini"

    def __init__(self, chat, last_user, base_config=None):
        self.chat = chat
        self._pending = last_user      # str (step1/synth) | list[Part] (หลัง tool)
        self._unsent_results = False   # add_tool_results แล้วแต่ step ยังไม่ได้ส่ง
        self._base_config = base_config

    def step(self):
        self._unsent_results = False
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
        self._unsent_results = True

    def _synth_config(self):
        """config ต่อคำขอของรอบสรุป: ของเดิม + ห้ามเรียก tool + คำสั่งสรุปอยู่ใน system_instruction
        (ไม่ยัด text part ปนกับ function_response — SDK 2.10 เองประกอบเทิร์นตอบ tool เป็น function_response ล้วน)"""
        if self._base_config is None:
            return None
        from google.genai import types as genai_types
        sys_text = (self._base_config.system_instruction or "")
        return self._base_config.model_copy(update={
            "system_instruction": f"{sys_text}\n\n{_FORCE_SYNTH_PROMPT}" if sys_text else _FORCE_SYNTH_PROMPT,
            "tool_config": genai_types.ToolConfig(function_calling_config=genai_types.FunctionCallingConfig(
                mode=genai_types.FunctionCallingConfigMode.NONE)),
        })

    def synthesize(self):
        # ⚠️ ครบ max_steps ตอนเพิ่ง add_tool_results → ผลของ tool ยังไม่ถึงโมเดล (audit 2026-09-24 MEDIUM)
        # เดิมส่ง _FORCE_SYNTH_PROMPT (text) ตรงนี้ = history model(function_call)→user(text) ไม่มี function_response
        # คั่น (API 400 · ข้อมูลที่เพิ่งค้นมาหาย) ⇒ ส่ง function responses ที่ค้าง + config ห้ามเรียก tool
        message = self._pending if self._unsent_results else _FORCE_SYNTH_PROMPT
        self._unsent_results = False
        for chunk in _gemini_stream_with_retry(self.chat, message, config=self._synth_config()):
            for part in _chunk_parts(chunk):
                txt = getattr(part, "text", None)
                if txt:
                    yield ("text", txt)


class _LMStudioAdapter:
    name = "LM Studio"

    def __init__(self, client, model, messages, tools_schema, cancel=None):
        self.client = client
        self.model = model
        self.messages = messages
        self.tools = tools_schema
        self.cancel = cancel
        self._has_tool_results = False

    def _open(self, **kw):
        """เปิด stream แล้วลงทะเบียนกับธงยกเลิก — `cancel()` จะ shutdown socket ให้ตัวอ่านที่ค้างหลุดทันที
        (ลงทะเบียนหลังยกเลิกไปแล้ว = ตัดทันที เช่นยกเลิกระหว่างโหลดโมเดลที่ header ยังไม่มา)"""
        stream = self.client.chat.completions.create(model=self.model, messages=self.messages, stream=True, **kw)
        if self.cancel is not None:
            self.cancel.register(stream)
        return stream

    def step(self):
        # ⚠️ stream ไม่ใช่เพื่อแสดงผลทีละคำ (ยังประกอบให้ครบก่อน yield เหมือนเดิม) — non-stream ตัดกลางทางไม่ได้
        # ประกอบเอง ห้ามใช้ openai ChatCompletionStreamState: โยน LengthFinishReasonError เมื่อ finish=length
        # ซึ่งเดิมได้ "(agent ไม่มีคำตอบ)" · timeout ของ httpx เป็นต่อการอ่านหนึ่งครั้ง ⇒ ต้องมีเพดานรวมเอง
        # (non-stream เดิมถูกคุมที่ LMSTUDIO_TIMEOUT โดยปริยาย) · probe LM Studio จริง: tests/test_agent_stream_cancel.py
        deadline = _monotonic() + LMSTUDIO_TIMEOUT
        stream = self._open(tools=self.tools, tool_choice="auto", temperature=0.3)
        content: list[str] = []
        acc: dict = {}                 # index → {"id","name","args"} ตามลำดับที่มาถึง
        for chunk in stream:
            if _stop_if_cancelled(self.cancel):   # เช็คทุก raw chunk — รวม reasoning ที่ไม่มี content
                stream.close()                    # เผื่อ cancel() หา socket ไม่เจอ — ปิดเองใน thread นี้ให้ LM Studio หยุด
                return
            if _monotonic() > deadline:
                stream.close()
                raise TimeoutError(f"LM Studio ตอบเกิน {LMSTUDIO_TIMEOUT} วินาที")
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                content.append(delta.content)
            for tc in (getattr(delta, "tool_calls", None) or []):
                e = acc.setdefault(tc.index, {"id": "", "name": "", "args": ""})
                if tc.id:                  # บาง server ส่ง id/name ซ้ำทุกชิ้น — แทนที่ ไม่ต่อ
                    e["id"] = tc.id
                fn = tc.function
                if fn is not None and fn.name:
                    e["name"] = fn.name
                if fn is not None and fn.arguments:
                    e["args"] += fn.arguments
        text = "".join(content)
        tool_calls = [acc[k] for k in acc]
        if not tool_calls:
            mf = _MarkerFilter()
            final = (mf.feed(text) + mf.flush()).strip()
            if not final and self._has_tool_results:
                # qwen3.5 หลังผล tool มักตอบโดยไม่ปิด `<think>` ที่ template เปิดไว้ → LM Studio ยัดคำตอบทั้งก้อนลง
                # reasoning_content · content ว่าง (probe 09-29: 11/12 · LM Studio #1602) · ปิด thinking ผ่าน API ไม่ได้
                # กับรุ่นนี้ (#1990) และ reasoning ไม่ใช่คำตอบสะอาด ห้ามโชว์แทน ⇒ ขอสรุปจากผล tool อีกรอบ (15/15)
                logger.warning("[Agent/LM Studio] หลังผล tool ได้ content ว่าง (คำตอบค้างใน reasoning) — ขอสรุปใหม่")
                yield from self.synthesize()
                return
            yield ("text", final or "(agent ไม่มีคำตอบ)")
            return
        self.messages.append({
            "role": "assistant", "content": text,
            "tool_calls": [
                {"id": tc["id"], "type": "function",
                 "function": {"name": tc["name"], "arguments": tc["args"]}}
                for tc in tool_calls
            ],
        })
        for tc in tool_calls:
            try:
                args = json.loads(tc["args"] or "{}")
            except json.JSONDecodeError:
                args = {}
            yield ("call", ToolCall(name=tc["name"], args=args, id=tc["id"]))

    def add_tool_results(self, results):
        self._has_tool_results = True
        for call, result in results:
            self.messages.append({"role": "tool", "tool_call_id": call.id,
                                  "name": call.name, "content": result})

    def synthesize(self):
        self.messages.append({"role": "user", "content": _FORCE_SYNTH_PROMPT})
        stream = self._open(temperature=0.3)      # เส้นนี้เป็น stream มาแต่เดิม — ไม่มีเพดานรวม คงไว้เหมือนเดิม
        mf = _MarkerFilter()
        for chunk in stream:
            if _stop_if_cancelled(self.cancel):
                stream.close()
                return
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
    image_b64: str = "",
    image_mime: str = "",
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
    system_text = _agent_system(system_text, AGENT_SYSTEM_HINT)

    gen_config = genai_types.GenerateContentConfig(
        system_instruction=system_text,
        tools=[gemini_tool],
        temperature=0.3,
    )
    chat = client.chats.create(model=model, config=gen_config, history=history)

    # รูปต้องไปกับ user message ล่าสุด (เส้นเดียวกับ _stream_gemini ใน utils/llm.py)
    pending = _gemini_pending_with_image(last_user, image_b64, image_mime)

    # loop กลาง (item E) — streaming (A) + retry (F) + Content-fix อยู่ใน _GeminiAdapter
    yield from _run_agent_fc(_GeminiAdapter(chat, pending, base_config=gen_config), max_steps)


def _gemini_pending_with_image(last_user: str, image_b64: str, image_mime: str):
    """ไม่มีรูป → คืน str ตามเดิม · มีรูป → คืน list[Part] (text + inline_data)"""
    if not image_b64:
        return last_user
    import base64
    from google.genai import types as genai_types
    try:
        img_bytes = base64.b64decode(image_b64)
    except Exception as e:
        logger.warning(f"[Agent/Gemini] decode รูปไม่ได้ ({e}) — ส่งเฉพาะข้อความ")
        return last_user
    img_part = genai_types.Part(inline_data=genai_types.Blob(
        data=img_bytes, mime_type=image_mime or "image/jpeg"))
    # prompt ว่าง (เรียกตรงผ่าน API — UI กันไว้แล้วที่ app.tsx:1229) → ส่งแต่รูป
    # ห้ามแนบ Part(text="") เปล่า: part ว่างเป็นของที่ API ปฏิเสธได้
    if not last_user:
        return [img_part]
    return [genai_types.Part.from_text(text=last_user), img_part]


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
    image_b64: str = "",
    image_mime: str = "",
    cancel=None,
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
        model = _CFG_LMSTUDIO_CHAT_MODEL

    if messages and messages[0]["role"] == "system":
        messages[0]["content"] = _agent_system(messages[0]["content"], AGENT_SYSTEM_HINT)
    else:
        messages.insert(0, {"role": "system", "content": AGENT_SYSTEM_HINT.strip()})

    tools_schema = get_openai_tools()
    # เดิมส่งทั้งก้อน → เกิน context แล้ว LM Studio ตัดเองเงียบๆ (prod 10-02 09:31 · devlog ต่อ 75)
    # tools schema ส่งไปทุก step แต่ไม่อยู่ใน messages ⇒ หักงบเอง (วัดจริง 2,482 token / 24 tools)
    messages, dropped = _fit_lmstudio_context(
        messages, model, extra_tokens=len(json.dumps(tools_schema, ensure_ascii=False)) // 3)
    if dropped:
        logger.info(f"[Agent/LM Studio] ตัดประวัติเก่า {dropped} ข้อความให้พอดี context")

    messages = _attach_image_openai(messages, image_b64, image_mime)

    # loop กลาง (item E) — provider quirks (role:tool, MarkerFilter) อยู่ใน _LMStudioAdapter
    yield from _run_agent_fc(_LMStudioAdapter(client, model, messages, tools_schema, cancel=cancel), max_steps)


def _attach_image_openai(messages: list[dict], image_b64: str, image_mime: str) -> list[dict]:
    """ต่อรูปเข้า user message ล่าสุดแบบ OpenAI content-parts
    (เส้นเดียวกับ _stream_lmstudio ใน utils/llm.py) — ไม่มีรูป = คืนของเดิม"""
    if not image_b64:
        return messages
    for i in range(len(messages) - 1, -1, -1):
        if messages[i]["role"] != "user":
            continue
        out = list(messages)
        text = messages[i].get("content") or ""
        parts = [{"type": "text", "text": text}] if text else []
        parts.append({"type": "image_url", "image_url": {
            "url": f"data:{image_mime or 'image/jpeg'};base64,{image_b64}"}})
        out[i] = {"role": "user", "content": parts}
        return out
    logger.warning("[Agent/LMStudio] มีรูปแต่ไม่มี user message ให้แนบ — ข้ามรูป")
    return messages


# ── Ollama ReAct path ─────────────────────────────────────────────────────────

_ACTION_RE = re.compile(r"Action:\s*")
_ANSWER_RE = re.compile(r"Answer:\s*(.*)", re.DOTALL)
# ให้ Ollama หยุดก่อนแต่งผล tool เอง — แนวทางมาตรฐานของ ReAct
# (parser ข้างล่างยังกันได้เองเผื่อ stop ไม่ถูกเคารพ)
_REACT_STOP = ["Observation:"]


def _parse_react(content: str) -> tuple[str, Any]:
    """แยกผลของโมเดล ReAct → ("action", (tool, args, ข้อความถึงท้าย Action))
    | ("answer", ข้อความ) | ("bad_action", เหตุผล) | ("plain", ข้อความ)

    🔑 **ตำแหน่งตัดสิน** (บั๊ก 2026-09-23 · probe llama3 จริงบน prod):
    โมเดลเขียน `Action:` แล้ว**แต่ง `Observation:` + `Answer:` ต่อเองในข้อความเดียว**
    โค้ดเดิมตรวจ `Answer` ก่อน ⇒ ส่ง "ดิสก์เหลือ 300 GB" (ของจริง 11,353 GB) ให้ user
    ⇒ `Action` มาก่อน `Answer` = ทุกอย่างหลัง Action คือของแต่ง ทิ้ง

    JSON อ่านด้วย `raw_decode` (นับวงเล็บ/สตริงถูกต้อง) — regex non-greedy เดิมหยุดที่ `}`
    ตัวแรก ⇒ `{"tool": ..., "args": {...}}` ซึ่ง `_REACT_SYSTEM` สั่งเอง parse พังทุกครั้ง
    """
    action = _ACTION_RE.search(content)
    answer = _ANSWER_RE.search(content)
    if action and (not answer or action.start() < answer.start()):
        start = content.find("{", action.end())
        if start == -1:
            return "bad_action", "ไม่พบ JSON หลัง Action:"
        try:
            obj, end = json.JSONDecoder().raw_decode(content, start)
        except json.JSONDecodeError as e:
            return "bad_action", f"JSON parse error: {e}"
        if not isinstance(obj, dict):
            return "bad_action", "Action ต้องเป็น JSON object"
        args = obj.get("args") or {}
        return "action", (obj.get("tool", ""), args, content[:end])
    if answer:
        return "answer", answer.group(1).strip()
    return "plain", content


_UNINFORMATIVE_RE = re.compile(r"^(❌|(Memory|Skills|Vault) error\b|ไม่พบ)")


def _is_informative(result: str) -> bool:
    """ผลของ tool ที่ "ได้ข้อมูลจริง" — ว่าง/ขึ้นต้น ❌/รายงาน error ของตัวเอง/"ไม่พบ…" = ไม่นับ
    ⚠️ `execute_tool` ขึ้นต้น ❌ เมื่อล้มก็จริง แต่ tool บางตัวรายงานล้มหรือว่างเองโดยไม่มี ❌
    (`agents/tools.py`: `Memory error:` · `Skills error:` · `Vault error:` · `ไม่พบโน้ต…` · `ไม่พบ entity…`)"""
    s = (result or "").strip()
    return bool(s) and not _UNINFORMATIVE_RE.match(s)


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
        messages[0]["content"] = _agent_system(messages[0]["content"], "\n\n" + react_system)
    else:
        messages.insert(0, {"role": "system", "content": react_system})

    # นับ tool ที่ได้ข้อมูลจริง — `execute_tool` ขึ้นต้น "❌" เมื่อล้มเสมอ (ไม่รู้จัก tool /
    # argument ผิด / exception) · ⚠️ tool ที่รายงาน error ของตัวเองโดยไม่มี ❌
    # (เช่น "Memory error: ...") ตัวนับนี้มองไม่เห็น
    ok_observations = 0

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
                stop=_REACT_STOP,
                extra_body={"options": {"num_ctx": OLLAMA_NUM_CTX}},
            )
        except Exception as e:
            logger.exception("[Agent/Ollama] LLM call failed")
            yield ("event", {"type": "error", "message": str(e)})
            yield ("chunk", f"❌ Ollama agent error: {e}")
            return

        content = (response.choices[0].message.content or "").strip()
        logger.debug(f"[Agent/Ollama] raw output: {content[:300]}")

        kind, parsed = _parse_react(content)
        if kind in ("answer", "plain") and step > 0 and ok_observations == 0:
            # 🔴 เรียก tool ไปแล้วแต่ไม่ได้ข้อมูลจริงสักครั้ง แล้วโมเดลตอบ = ตอบจากการเดา (audit 2026-09-24 MEDIUM)
            # เดิม guard นี้อยู่เฉพาะตอนครบ max_steps → web_search ล้มครั้งเดียวแล้วโมเดลแต่ง "ราคาทอง ~$1,825" หลุดได้
            logger.warning("[Agent/Ollama] โมเดลตอบหลัง tool ไม่ได้ข้อมูลจริง — ไม่ปล่อยคำตอบ")
            yield ("chunk", "❌ เครื่องมือไม่ได้ข้อมูลจริงเลยสักครั้ง จึงไม่ตอบจากการเดา — "
                            "ลองถามใหม่ หรือใช้ Gemini/LM Studio agent")
            return
        if kind in ("answer", "plain"):
            # plain = โมเดลไม่ทำตาม format → ถือว่าเป็นคำตอบตรง (ไม่มี Action ให้แต่งต่อ)
            yield ("event", {"type": "answering"})
            yield ("chunk", parsed)
            return
        if kind == "bad_action":
            # ⚠️ ห้าม yield `content` ดิบ — อาจมี Observation/Answer ที่โมเดลแต่งต่อท้ายอยู่
            logger.warning(f"[Agent/Ollama] {parsed} — raw: {content[:300]}")
            yield ("event", {"type": "error", "message": parsed})
            yield ("chunk", "❌ อ่านคำสั่งเรียกเครื่องมือของโมเดลไม่ได้ — ลองถามใหม่ หรือใช้ Gemini/LM Studio agent")
            return

        tool_name, args, action_text = parsed

        yield ("event", {"type": "tool_call", "name": tool_name, "args": args})
        result = execute_tool(tool_name, args)
        if _is_informative(result):
            ok_observations += 1
        yield ("event", {
            "type": "tool_result",
            "name": tool_name,
            "preview": result[:300],
            "length": len(result),
        })

        # เพิ่ม turn นี้เข้า history เพื่อ loop ต่อ — ตัดที่ท้าย Action
        # (ไม่งั้น Observation ที่โมเดลแต่งจะถูกป้อนกลับปนกับของจริง)
        messages.append({"role": "assistant", "content": action_text})
        messages.append({"role": "user", "content": f"Observation: {result}"})

    # ครบ max_steps → บังคับสรุป
    yield ("event", {"type": "max_steps_reached"})
    if ok_observations == 0:
        # 🔴 ไม่มีข้อมูลจริงสักชิ้น ⇒ ห้ามให้โมเดล "สรุป" — probe จริง 2026-09-23:
        # web_search ล้ม 3 ครั้ง แล้ว llama3 ตอบ "ราคาทอง ~$1,825 (Source: Google Search)"
        logger.warning("[Agent/Ollama] ครบ max_steps โดยไม่มี tool ไหนได้ข้อมูล — ไม่สรุป")
        yield ("chunk", "❌ เครื่องมือไม่ได้ข้อมูลจริงเลยสักครั้ง จึงไม่ตอบจากการเดา — "
                        "ลองถามใหม่ หรือใช้ Gemini/LM Studio agent")
        return
    messages.append({
        "role": "user",
        "content": "ตอบจากข้อมูลที่ได้มาให้ครบถ้วน เก็บรายละเอียดและแหล่งที่มา เขียนแค่ Answer: ... เท่านั้น",
    })
    try:
        final = client.chat.completions.create(
            model=model, messages=messages, temperature=0.3, stream=False,
            extra_body={"options": {"num_ctx": OLLAMA_NUM_CTX}},
        )
        final_content = (final.choices[0].message.content or "").strip()
        answer_match = _ANSWER_RE.search(final_content)
        yield ("chunk", answer_match.group(1).strip() if answer_match else final_content)
    except Exception as e:
        yield ("chunk", f"❌ Final synthesis failed: {e}")
