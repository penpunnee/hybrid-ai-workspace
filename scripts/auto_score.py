#!/usr/bin/env python3
"""auto_score.py — เฟส 3 (RLAIF): Claude ให้คะแนนคำตอบขวัญอัตโนมัติ → คัดเข้า training pool

ทำไม: ไม่ต้องรอกด 👍 เอง — Claude สแกนคำตอบที่ผ่านมา ให้คะแนน คัดอันดี (≥ threshold)
   append ลง data/finetune_auto.jsonl เอง → data ไหลเข้า fine-tune ต่อเนื่อง

⚠️ auto-label = สัญญาณอ่อนกว่า 👍 ของคนจริง — เก็บ **แยกไฟล์** (finetune_auto.jsonl)
   เพื่อ weight/คัด/เทียบได้. คำตอบดีจาก Claude/Gemini → คัดเข้า = distillation
   เทรน: cat data/finetune_seed.jsonl data/finetune_sft.jsonl data/finetune_auto.jsonl > all.jsonl

Usage:
  ANTHROPIC_API_KEY=sk-ant-... python scripts/auto_score.py --threshold 7.5 --limit 100
  (track id ที่ score แล้วใน data/.auto_score_state.json — รันซ้ำจะ score เฉพาะใหม่)
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_DEFAULT_OUT = "data/finetune_auto.jsonl"
_DEFAULT_STATE = "data/.auto_score_state.json"

_SCORE_SYS = (
    "คุณคือกรรมการให้คะแนนคำตอบของผู้ช่วย AI ชื่อ 'ขวัญ' (สดใส อบอุ่น แทนตัวว่าขวัญ "
    "เรียกผู้ใช้ว่าพี่ปอย ตอบภาษาไทยล้วน ตรงประเด็น)\n"
    "ให้คะแนน 0-10 จากเกณฑ์: ถูกต้อง/ไม่มั่ว, ครบประเด็น, สไตล์ขวัญ(อบอุ่น/ไทยล้วน), อ่านเข้าใจ\n"
    "เข้มงวด: 8-10 = ดีจนอยากเก็บเป็นตัวอย่างเทรน, 5-7 = พอใช้, <5 = ไม่ดี\n"
    'ตอบ JSON เท่านั้น: {"score": <number 0-10>, "reason": "สั้นๆ"}'
)


def _parse_score(text: str) -> dict:
    """ดึง {score, reason} จากคำตอบกรรมการ — fail → score 0"""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return {"score": 0.0, "reason": "parse_fail"}
    try:
        d = json.loads(m.group(0))
        return {"score": max(0.0, min(10.0, float(d.get("score", 0)))),
                "reason": str(d.get("reason", ""))[:200]}
    except Exception:
        return {"score": 0.0, "reason": "json_fail"}


def _qualifies(score: float, threshold: float) -> bool:
    return score >= threshold


def _load_state(path: str) -> int:
    try:
        with open(path, encoding="utf-8") as f:
            return int(json.load(f).get("last_id", 0))
    except Exception:
        return 0


def _save_state(path: str, last_id: int) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"last_id": last_id}, f)


def _fetch_unscored(conn, after_id: int, limit: int) -> list[dict]:
    """ดึง assistant answers (id > after_id) + คำถาม user ก่อนหน้า"""
    rows = conn.execute(
        """SELECT id, assistant, session_id, content FROM messages
           WHERE role='assistant' AND id > ? ORDER BY id ASC LIMIT ?""",
        (after_id, limit),
    ).fetchall()
    out = []
    for mid, asst, sid, content in rows:
        prev = conn.execute(
            """SELECT content FROM messages
               WHERE assistant=? AND session_id=? AND id < ? AND role='user'
               ORDER BY id DESC LIMIT 1""",
            (asst, sid, mid),
        ).fetchone()
        out.append({"id": mid, "assistant": asst, "user": prev[0] if prev else "",
                    "answer": content})
    return out


def run_auto_score(threshold: float = 7.5, limit: int = 100,
                   out_path: str = _DEFAULT_OUT, state_path: str = _DEFAULT_STATE,
                   score_fn=None) -> dict:
    """score คำตอบใหม่ → คัดอันดีเข้า out_path. score_fn(user, answer)->dict (inject ตอน test)"""
    from utils.history import _get_conn
    from assistants.config import ASSISTANTS

    system = ASSISTANTS["🧡 ขวัญ (Logic)"]["system_prompt"]
    if score_fn is None:
        score_fn = _make_claude_scorer()

    conn = _get_conn()
    try:
        last_id = _load_state(state_path)
        items = _fetch_unscored(conn, last_id, limit)
    finally:
        conn.close()

    scored = qualified = 0
    max_id = last_id
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "a", encoding="utf-8") as f:
        for it in items:
            max_id = max(max_id, it["id"])
            if not it["user"] or not it["answer"].strip():
                continue
            scored += 1
            res = score_fn(it["user"], it["answer"])
            if _qualifies(res["score"], threshold):
                ex = {"messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": it["user"]},
                    {"role": "assistant", "content": it["answer"]},
                ]}
                f.write(json.dumps(ex, ensure_ascii=False) + "\n")
                qualified += 1

    if max_id > last_id:
        _save_state(state_path, max_id)
    return {"scored": scored, "qualified": qualified, "last_id": max_id,
            "threshold": threshold, "out": out_path}


def _make_claude_scorer():
    """สร้าง scorer ที่เรียก Claude จริง"""
    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
    model = os.getenv("EVAL_JUDGE_MODEL", "claude-opus-4-8")

    def _score(user: str, answer: str) -> dict:
        u = f"คำถาม:\n{user}\n\nคำตอบของขวัญ:\n{answer}\n\nให้คะแนน JSON ตาม schema"
        resp = client.messages.create(   # ไม่ใส่ temperature (opus-4-8 ไม่รับ)
            model=model, max_tokens=300, system=_SCORE_SYS,
            messages=[{"role": "user", "content": u}],
        )
        text = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), "")
        return _parse_score(text)
    return _score


def main():
    ap = argparse.ArgumentParser(description="เฟส 3 RLAIF — Claude ให้คะแนน → คัดเข้า training pool")
    ap.add_argument("--threshold", type=float, default=7.5, help="คะแนนขั้นต่ำที่คัดเข้า (0-10)")
    ap.add_argument("--limit", type=int, default=100, help="score กี่คำตอบต่อรอบ")
    ap.add_argument("--out", default=_DEFAULT_OUT)
    args = ap.parse_args()

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("❌ ต้องตั้ง ANTHROPIC_API_KEY (Claude ให้คะแนน)"); sys.exit(2)

    r = run_auto_score(threshold=args.threshold, limit=args.limit, out_path=args.out)
    print(f"✅ score {r['scored']} คำตอบ → คัดเข้า {r['qualified']} (คะแนน ≥ {r['threshold']}) "
          f"→ {r['out']}")
    print(f"   last_id = {r['last_id']} (รันซ้ำจะ score เฉพาะใหม่)")
    if r["qualified"] == 0:
        print("   💡 ยังไม่มีคำตอบผ่านเกณฑ์ — ลองลด threshold หรือใช้ Claude/Gemini ตอบให้ดีขึ้น")


if __name__ == "__main__":
    main()
