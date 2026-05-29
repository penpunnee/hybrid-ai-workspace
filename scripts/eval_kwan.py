#!/usr/bin/env python3
"""eval_kwan.py — Eval Gate: เทียบ kwan-ft (candidate) กับรุ่นปัจจุบัน (baseline) ก่อน deploy

🎯 ทำไม: กัน "model collapse" — ห้าม deploy รุ่นที่ fine-tune ใหม่ถ้ามันไม่ดีกว่าเดิม
   (เฟส 2 ของ self-improvement loop — ดู memory: hybrid_ai_status)

วิธี:
  1. ยิงชุดคำถามมาตรฐาน (held-out, ไม่ซ้ำ training) ให้ทั้ง candidate + baseline ตอบ
  2. Claude เป็นกรรมการเทียบทีละคู่ (pairwise) — สลับตำแหน่ง A/B กัน position bias
  3. นับ win rate → PASS (deploy ได้) / FAIL (อย่า deploy)

Usage:
  ANTHROPIC_API_KEY=sk-ant-... python scripts/eval_kwan.py --candidate kwan-ft --baseline llama3
  python scripts/eval_kwan.py --candidate kwan-ft --baseline kwan --threshold 0.55 --json

exit code: 0 = PASS (deploy ได้), 1 = FAIL/inconclusive — ใช้ gate ใน automated pipeline (เฟส 4)

ต้องมี: ANTHROPIC_API_KEY (กรรมการ) + candidate/baseline โหลดใน Ollama (OLLAMA_BASE_URL)
"""
import argparse
import json
import os
import random
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── ชุดคำถามประเมิน (held-out — ตั้งใจให้ต่างจาก seed เพื่อวัด generalization) ──
EVAL_QUESTIONS = [
    "อธิบายความต่างระหว่าง process กับ thread แบบเข้าใจง่าย",
    "เขียนฟังก์ชัน Python ที่รับ list ตัวเลขแล้วคืนค่าเฉลี่ย",
    "ควรใช้ REST หรือ GraphQL สำหรับ API ที่มี client หลากหลาย",
    "git merge กับ rebase ต่างกันยังไง ควรใช้อันไหน",
    "Redis เอาไปใช้ทำอะไรได้บ้าง",
    "อธิบายว่า Docker volume คืออะไร ทำไมต้องใช้",
    "ช่วยวางแผนเรียน FastAPI ให้ใช้งานได้ใน 2 สัปดาห์",
    "วิเคราะห์ข้อดีข้อเสียของ microservices เทียบ monolith",
    "ช่วยสรุปแนวคิด OOP สั้นๆ ให้เข้าใจง่าย",
    "วิธีตั้งเป้าหมายให้ทำได้จริง ไม่ล้มกลางคัน",
    "อธิบายว่า AI ทำงานยังไงแบบง่ายๆ เหมือนเล่าให้เด็กฟัง",
    "ช่วยร่างอีเมลลาป่วย 1 วัน สั้นๆ สุภาพ",
    "เครียดเรื่องงานมากเลยช่วงนี้ แนะนำหน่อย",
    "ความปลอดภัยของรหัสผ่านที่ดีควรเป็นยังไง",
    "ทักทายตอนเช้าให้กำลังใจหน่อย",
    "ช่วยคิดวิธีจัดระเบียบไฟล์ในโปรเจกต์โค้ดให้เป็นระบบ",
]

_JUDGE_SYS = (
    "คุณคือกรรมการประเมินคำตอบของผู้ช่วย AI ชื่อ 'ขวัญ' (เลขาส่วนตัว สดใส อบอุ่น "
    "แทนตัวว่าขวัญ เรียกผู้ใช้ว่าพี่ปอย ตอบภาษาไทยล้วน ตรงประเด็น)\n"
    "เทียบคำตอบ A กับ B จากเกณฑ์: 1)ถูกต้อง/ไม่มั่ว 2)ครบประเด็น 3)สไตล์ขวัญ(อบอุ่น/ไทยล้วน) 4)อ่านเข้าใจ\n"
    'ตอบ JSON เท่านั้น ห้ามมีข้อความอื่น: {"winner":"A"|"B"|"tie","reason":"สั้นๆ"}'
)


def _parse_verdict(text: str) -> dict:
    """ดึง JSON {winner,reason} จากคำตอบกรรมการ — ทนข้อความเสริม"""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return {"winner": "tie", "reason": "parse_fail"}
    try:
        d = json.loads(m.group(0))
        w = str(d.get("winner", "tie")).strip().upper()
        return {"winner": w if w in ("A", "B") else "tie",
                "reason": str(d.get("reason", ""))[:200]}
    except Exception:
        return {"winner": "tie", "reason": "json_fail"}


def _aggregate(results: list[dict], threshold: float = 0.55, min_games: int = 8) -> dict:
    """รวมผล → PASS/FAIL. win_rate = ชนะ / (ชนะ+แพ้) (ไม่นับเสมอ)"""
    wins = sum(1 for r in results if r["winner"] == "candidate")
    losses = sum(1 for r in results if r["winner"] == "baseline")
    ties = sum(1 for r in results if r["winner"] == "tie")
    decisive = wins + losses
    win_rate = (wins / decisive) if decisive else None
    # inconclusive ถ้าตัดสินได้น้อยเกิน (เสมอ/error เยอะ)
    inconclusive = decisive < min_games
    passed = (not inconclusive) and win_rate is not None and win_rate >= threshold
    return {
        "candidate_wins": wins, "baseline_wins": losses, "ties": ties,
        "decisive": decisive, "win_rate": round(win_rate, 3) if win_rate is not None else None,
        "threshold": threshold, "inconclusive": inconclusive, "passed": passed,
    }


# ── live helpers (ต้องมี network — แยกออกเพื่อให้ logic ข้างบน test ได้) ──────
def _ollama_answer(client, model: str, system: str, question: str, max_tokens: int = 512) -> str:
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": question}],
        max_tokens=max_tokens, temperature=0.7, stream=False,
    )
    return (resp.choices[0].message.content or "").strip()


def _judge(judge_client, model: str, question: str, ans_a: str, ans_b: str) -> str:
    """คืน 'A' | 'B' | 'tie' — กรรมการ (Claude) เทียบ A vs B"""
    user = (f"คำถาม:\n{question}\n\n[คำตอบ A]\n{ans_a or '(ว่าง)'}\n\n"
            f"[คำตอบ B]\n{ans_b or '(ว่าง)'}\n\nเปรียบเทียบแล้วตอบ JSON ตาม schema")
    resp = judge_client.messages.create(   # ไม่ใส่ temperature (opus-4-8 ไม่รับ)
        model=model, max_tokens=400,
        system=_JUDGE_SYS,
        messages=[{"role": "user", "content": user}],
    )
    text = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), "")
    return _parse_verdict(text)["winner"]


def run_eval(candidate: str, baseline: str, threshold: float = 0.55,
             questions: list[str] | None = None, seed: int = 42) -> dict:
    """รัน eval เต็ม (live) — ต้องมี ANTHROPIC_API_KEY + Ollama"""
    import anthropic
    from openai import OpenAI
    from assistants.config import ASSISTANTS

    system = ASSISTANTS["🧡 ขวัญ (Logic)"]["system_prompt"]
    qs = questions if questions is not None else EVAL_QUESTIONS
    ollama = OpenAI(base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
                    api_key="ollama", timeout=120)
    judge_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
    judge_model = os.getenv("EVAL_JUDGE_MODEL", "claude-opus-4-8")
    rng = random.Random(seed)

    results = []
    for i, q in enumerate(qs):
        cand_ans = _ollama_answer(ollama, candidate, system, q)
        base_ans = _ollama_answer(ollama, baseline, system, q)
        # สลับตำแหน่ง A/B กัน position bias
        cand_is_a = rng.random() < 0.5
        a, b = (cand_ans, base_ans) if cand_is_a else (base_ans, cand_ans)
        w = _judge(judge_client, judge_model, q, a, b)
        if w == "tie":
            winner = "tie"
        elif (w == "A") == cand_is_a:
            winner = "candidate"
        else:
            winner = "baseline"
        results.append({"q": q, "winner": winner})
        print(f"  [{i+1}/{len(qs)}] {winner:9} | {q[:45]}")

    agg = _aggregate(results, threshold)
    agg["candidate"], agg["baseline"], agg["judge"] = candidate, baseline, judge_model
    agg["results"] = results
    return agg


def main():
    ap = argparse.ArgumentParser(description="Eval gate — เทียบ kwan-ft กับ baseline ก่อน deploy")
    ap.add_argument("--candidate", required=True, help="model ใหม่ (เช่น kwan-ft)")
    ap.add_argument("--baseline", required=True, help="model เดิม (เช่น llama3 / kwan)")
    ap.add_argument("--threshold", type=float, default=0.55, help="win rate ขั้นต่ำที่ถือว่าผ่าน")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("❌ ต้องตั้ง ANTHROPIC_API_KEY (Claude เป็นกรรมการ)"); sys.exit(2)

    print(f"⚖️  Eval: {args.candidate} (candidate) vs {args.baseline} (baseline)")
    agg = run_eval(args.candidate, args.baseline, args.threshold)

    if args.json:
        print(json.dumps(agg, ensure_ascii=False, indent=2))
    else:
        print(f"\n{'='*50}")
        print(f" candidate ชนะ {agg['candidate_wins']} / แพ้ {agg['baseline_wins']} / เสมอ {agg['ties']}")
        print(f" win_rate = {agg['win_rate']} (เกณฑ์ {agg['threshold']})")
        if agg["inconclusive"]:
            print(" ⚠️  INCONCLUSIVE — ตัดสินได้น้อยเกิน (เสมอ/error เยอะ) อย่าเพิ่ง deploy")
        print(f" {'✅ PASS — deploy kwan-ft ได้' if agg['passed'] else '❌ FAIL — อย่า deploy (รุ่นเดิมดีกว่า/พอกัน)'}")
        print(f"{'='*50}")

    sys.exit(0 if agg["passed"] else 1)


if __name__ == "__main__":
    main()
