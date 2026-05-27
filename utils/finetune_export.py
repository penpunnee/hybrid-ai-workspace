"""Fine-tune dataset export (Stage 1) — คัด 👍 conversations → JSONL (SFT chat format)

รันออฟไลน์ (NAS/Mac) ไม่ต้อง GPU. ดึง assistant message ที่ได้ 👍 +
user prompt ก่อนหน้าใน session เดียวกัน → ตัวอย่างเทรน format chat
(ใช้ได้กับ Unsloth/OpenAI/Axolotl).

exclude 👎, skip ตัวที่ไม่มี user ก่อนหน้า (orphan) หรือเนื้อหาว่าง
"""
import os
import json
import sqlite3
import logging

logger = logging.getLogger(__name__)


def _build_example(system: str, user: str, assistant: str) -> dict:
    """1 ตัวอย่าง SFT (chat format) — ถ้า system ว่างจะไม่ใส่"""
    msgs = []
    if system and system.strip():
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": user})
    msgs.append({"role": "assistant", "content": assistant})
    return {"messages": msgs}


def export_sft(db_path: str, out_path: str,
               system_prompts: dict | None = None,
               assistant: str | None = None) -> dict:
    """export 👍 จาก feedback → JSONL

    Args:
        db_path: path ของ chat_history.db
        out_path: ไฟล์ JSONL ปลายทาง
        system_prompts: {assistant_name: system_prompt} — ใส่เป็น system message
        assistant: filter เฉพาะ assistant นี้ (None = ทั้งหมด)

    Returns:
        {count, path, skipped}
    """
    system_prompts = system_prompts or {}
    conn = sqlite3.connect(db_path)
    examples: list[dict] = []
    skipped = 0
    try:
        clause = "AND m.assistant = ?" if assistant else ""
        params: tuple = (assistant,) if assistant else ()
        good = conn.execute(
            f"""SELECT m.id, m.assistant, m.session_id, m.content
                FROM feedback f JOIN messages m ON m.id = f.message_id
                WHERE f.rating = 'up' AND m.role = 'assistant' {clause}
                ORDER BY m.id ASC""",
            params,
        ).fetchall()

        for msg_id, asst, session_id, asst_content in good:
            prev = conn.execute(
                """SELECT content FROM messages
                   WHERE assistant = ? AND session_id = ? AND role = 'user' AND id < ?
                   ORDER BY id DESC LIMIT 1""",
                (asst, session_id, msg_id),
            ).fetchone()
            user_content = prev[0] if prev else ""
            if not (user_content or "").strip() or not (asst_content or "").strip():
                skipped += 1
                continue
            examples.append(_build_example(
                system_prompts.get(asst, ""), user_content, asst_content))
    finally:
        conn.close()

    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for ex in examples:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    logger.info(f"[FT export] {len(examples)} examples → {out_path} (skipped {skipped})")
    return {"count": len(examples), "path": out_path, "skipped": skipped}
