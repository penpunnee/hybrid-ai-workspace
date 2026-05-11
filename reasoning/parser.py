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


def parse_think_stream(chunks: Iterator[str]) -> Generator[dict, None, None]:
    """
    รับ stream chunks จาก DeepSeek R1
    yield dict: {"type": "think"|"answer", "text": str}

    think = reasoning process (แสดงหรือซ่อนก็ได้)
    answer = คำตอบสุดท้าย
    """
    buffer = ""
    in_think = False
    think_buffer = ""

    for chunk in chunks:
        buffer += chunk

        while buffer:
            if not in_think:
                think_start = buffer.find("<think>")
                if think_start == -1:
                    # ไม่มี <think> tag — yield ทุกอย่างเป็น answer
                    if buffer:
                        yield {"type": "answer", "text": buffer}
                    buffer = ""
                else:
                    # yield ส่วนก่อน <think>
                    if think_start > 0:
                        yield {"type": "answer", "text": buffer[:think_start]}
                    buffer = buffer[think_start + 7:]  # ข้าม <think>
                    in_think = True
                    think_buffer = ""
            else:
                think_end = buffer.find("</think>")
                if think_end == -1:
                    # ยังอยู่ใน think block — สะสมต่อ
                    think_buffer += buffer
                    buffer = ""
                else:
                    # พบ </think>
                    think_buffer += buffer[:think_end]
                    if think_buffer.strip():
                        yield {"type": "think", "text": think_buffer.strip()}
                    buffer = buffer[think_end + 8:]  # ข้าม </think>
                    in_think = False
                    think_buffer = ""

    # flush ที่เหลือ
    if in_think and think_buffer.strip():
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
