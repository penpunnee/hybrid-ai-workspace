"""DeepSeek R1 Response Parser

DeepSeek R1 ส่ง output ในรูปแบบ:
  <think>
  ... reasoning process ...
  </think>
  ... final answer ...

Parser นี้แยก think block ออกจาก answer
และ stream ทั้งสองแยกกัน
"""
import re
from typing import Generator, Iterator


_OPEN_TAG = "<think>"
_CLOSE_TAG = "</think>"


def _partial_tag_suffix_len(buffer: str, tag: str) -> int:
    """คืนความยาวส่วนท้าย buffer ที่ "อาจ" เป็นจุดเริ่มของ tag (prefix ของ tag)

    ใช้กันกรณี tag ถูกแบ่งข้าม chunk เช่น "<thi" + "nk>" — เราต้องเก็บ "<thi" ไว้
    รอ chunk ถัดไปแทนที่จะ flush เป็น answer ทันที (ซึ่งทำให้ tag รั่ว)
    """
    max_k = min(len(tag) - 1, len(buffer))
    for k in range(max_k, 0, -1):
        if buffer.endswith(tag[:k]):
            return k
    return 0


def parse_think_stream(chunks: Iterator[str]) -> Generator[dict, None, None]:
    """
    รับ stream chunks จาก DeepSeek R1
    yield dict: {"type": "think"|"answer", "text": str}

    think = reasoning process (แสดงหรือซ่อนก็ได้)
    answer = คำตอบสุดท้าย

    รองรับ tag ที่ถูกแบ่งข้าม chunk boundary (เก็บส่วนท้ายที่อาจเป็น tag ครึ่งไว้รอ)
    """
    buffer = ""
    in_think = False
    think_buffer = ""

    for chunk in chunks:
        buffer += chunk
        progressed = True
        while progressed and buffer:
            progressed = False
            if not in_think:
                idx = buffer.find(_OPEN_TAG)
                if idx != -1:
                    if idx > 0:
                        yield {"type": "answer", "text": buffer[:idx]}
                    buffer = buffer[idx + len(_OPEN_TAG):]
                    in_think = True
                    think_buffer = ""
                    progressed = True
                else:
                    # ยังไม่เจอ <think> เต็ม — emit ส่วนที่ปลอดภัย เก็บ tail ที่อาจเป็น tag ครึ่ง
                    hold = _partial_tag_suffix_len(buffer, _OPEN_TAG)
                    emit = buffer[:len(buffer) - hold]
                    if emit:
                        yield {"type": "answer", "text": emit}
                    buffer = buffer[len(buffer) - hold:]
            else:
                idx = buffer.find(_CLOSE_TAG)
                if idx != -1:
                    think_buffer += buffer[:idx]
                    if think_buffer.strip():
                        yield {"type": "think", "text": think_buffer.strip()}
                    buffer = buffer[idx + len(_CLOSE_TAG):]
                    in_think = False
                    think_buffer = ""
                    progressed = True
                else:
                    # ยังไม่เจอ </think> เต็ม — สะสม think เก็บ tail ที่อาจเป็น tag ครึ่ง
                    hold = _partial_tag_suffix_len(buffer, _CLOSE_TAG)
                    think_buffer += buffer[:len(buffer) - hold]
                    buffer = buffer[len(buffer) - hold:]

    # flush ที่เหลือ (tail ที่ค้างถือว่าเป็น literal text แล้ว)
    if in_think:
        think_buffer += buffer
        if think_buffer.strip():
            yield {"type": "think", "text": think_buffer.strip()}
    elif buffer.strip():
        yield {"type": "answer", "text": buffer}


def stream_with_thinking(chunks: Iterator[str], show_thinking: bool = False):
    """
    Generator สำหรับ SSE streaming
    show_thinking=True → ส่ง thinking process ด้วย (prefix ด้วย 💭)
    show_thinking=False → ส่งแค่ final answer
    """
    has_thinking = False
    answer_started = False

    for event in parse_think_stream(chunks):
        if event["type"] == "think":
            has_thinking = True
            if show_thinking:
                # ส่ง thinking block เป็น special marker
                yield f"\n💭 **กำลังคิด...**\n```\n{event['text'][:500]}\n```\n\n"
        elif event["type"] == "answer":
            if has_thinking and not answer_started:
                answer_started = True
            yield event["text"]


def extract_final_answer(full_text: str) -> tuple[str, str]:
    """
    แยก think block ออกจาก full response
    คืนค่า (thinking_process, final_answer)
    """
    think_match = re.search(r"<think>(.*?)</think>", full_text, re.DOTALL)
    thinking = think_match.group(1).strip() if think_match else ""
    answer = re.sub(r"<think>.*?</think>", "", full_text, flags=re.DOTALL).strip()
    return thinking, answer
