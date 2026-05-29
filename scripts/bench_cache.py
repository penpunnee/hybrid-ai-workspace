#!/usr/bin/env python3
"""bench_cache.py — วัด hit rate จริงของ Phase E cache layers (Phase G4)

2 โหมด:
  synthetic — สร้าง query stream คุม repeat ratio เอง → วัด cache mechanics
  replay    — ดึง user prompts จริงจาก chat_history.db → projected hit rate

ตัวอย่าง:
  python scripts/bench_cache.py synthetic --n 300 --repeat 0.4
  python scripts/bench_cache.py replay --limit 500
  python scripts/bench_cache.py synthetic --fake-embed --json   # ไม่ต้องมี LM Studio

หมายเหตุ:
  - default ใช้ embed จริง (ต้องมี LMSTUDIO_BASE_URL ที่ใช้งานได้) → วัด semantic hit จริง
  - --fake-embed: ใส่ embedding deterministic (vector ต่อ text คงที่) → วัดได้เฉพาะ
    exact-repeat hit, รันได้ทุกที่ (ใช้ตอน dev/test/CI)
  - bench แยก response_cache ไป temp db เสมอ — ไม่แตะ cache จริงของ production
"""
import argparse
import json
import os
import random
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils.retrieval_cache as rc
import utils.response_cache as resp
import utils.embed as embed

_ASSUMED_LLM_MS = 2000      # สมมติ LLM generate 1 คำตอบ ~2s
_ASSUMED_RETR_MS = 300      # สมมติ retrieval (embed+ChromaDB) ~300ms


# ── fake embedding (deterministic ต่อ text) ───────────────────────────────────
def _fake_vec(text: str, dim: int = 16) -> list[float]:
    rng = random.Random(text)            # seed = text → vector คงที่ต่อข้อความ
    return [rng.gauss(0.0, 1.0) for _ in range(dim)]


def _install_fake_embed() -> None:
    """แทน embed_query ใน cache modules ด้วย fake — exact repeat → cosine 1.0"""
    rc.embed_query = _fake_vec
    resp.embed_query = _fake_vec


# ── isolation ─────────────────────────────────────────────────────────────────
def _isolate_response_db() -> None:
    """ชี้ response_cache → temp db (กันแตะ production cache)"""
    tmp = os.path.join(tempfile.gettempdir(), f"bench_response_{os.getpid()}.db")
    for ext in ("", "-wal", "-shm"):
        try:
            os.remove(tmp + ext)
        except FileNotFoundError:
            pass
    resp._DB_PATH = tmp
    resp._ENABLED = True
    resp._conn = None


def _reset_all() -> None:
    rc._cache.clear()
    rc.reset_metrics()
    resp.reset_metrics()
    embed.reset_metrics()


# ── core driver ───────────────────────────────────────────────────────────────
def _drive(queries: list[str], assistant: str = "bench") -> dict:
    """ยิง query stream ผ่าน response + retrieval cache (save ทุก miss)

    จำลอง: lookup → ถ้า miss ให้ 'generate' แล้ว save (สมมติ thumbs-up ทุกครั้ง)
    """
    t0 = time.time()
    for i, q in enumerate(queries):
        sid = "bench-session"

        # response cache (semantic Q&A)
        if resp.lookup(assistant, q) is None:
            resp.save(assistant, q, response=f"answer for: {q}", model="bench")

        # retrieval cache (per-session)
        if rc.get_cached(sid, q) is None:
            rc.store(sid, q, chunks=[{"text": f"chunk for {q}"}])

    elapsed = round(time.time() - t0, 3)

    r_stats = resp.stats()
    rc_stats = rc.stats()
    e_stats = embed.cache_stats()

    resp_hits = r_stats.get("runtime_hits", 0)
    retr_hits = rc_stats.get("hits", 0)
    saved_ms = resp_hits * _ASSUMED_LLM_MS + retr_hits * _ASSUMED_RETR_MS

    return {
        "queries": len(queries),
        "elapsed_sec": elapsed,
        "response_cache": {
            "lookups": r_stats.get("lookups"),
            "hits": resp_hits,
            "misses": r_stats.get("misses"),
            "hit_rate": r_stats.get("hit_rate"),
            "entries": r_stats.get("entries"),
        },
        "retrieval_cache": {
            "lookups": rc_stats.get("lookups"),
            "hits": retr_hits,
            "misses": rc_stats.get("misses"),
            "hit_rate": rc_stats.get("hit_rate"),
            "sessions": rc_stats.get("sessions"),
        },
        "embed": {
            "lru_hit_rate": e_stats.get("lru_hit_rate"),
            "lru_hits": e_stats.get("lru_hits"),
            "lru_misses": e_stats.get("lru_misses"),
            "sqlite_hits": e_stats.get("sqlite_hits"),
            "api_calls": e_stats.get("api_calls"),
        },
        "estimated_ms_saved": saved_ms,
    }


# ── modes ─────────────────────────────────────────────────────────────────────
def run_synthetic(n: int = 200, repeat: float = 0.4, fake_embed: bool = False) -> dict:
    """สร้าง query stream: (1-repeat) เป็น prompt ใหม่, repeat เป็น exact-repeat ของเดิม"""
    _isolate_response_db()
    if fake_embed:
        _install_fake_embed()
    _reset_all()

    topics = ["docker deploy", "python async", "react hooks", "postgres index",
              "git rebase", "nginx config", "redis cache", "k8s pod"]
    seen: list[str] = []
    queries: list[str] = []
    rng = random.Random(42)
    for i in range(n):
        if seen and rng.random() < repeat:
            queries.append(rng.choice(seen))          # exact repeat → ควร hit
        else:
            q = f"{rng.choice(topics)} question {i}"   # prompt ใหม่ (unique)
            seen.append(q)
            queries.append(q)

    result = _drive(queries)
    result["mode"] = "synthetic"
    result["config"] = {"n": n, "repeat": repeat, "fake_embed": fake_embed}
    return result


def run_replay(limit: int = 300, fake_embed: bool = False) -> dict:
    """ดึง user prompts จริงจาก chat_history.db มา replay"""
    _isolate_response_db()
    if fake_embed:
        _install_fake_embed()
    _reset_all()

    from utils.history import _get_conn
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT content FROM messages WHERE role='user' ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    queries = [r[0] for r in rows if r[0] and r[0].strip()]
    queries.reverse()      # เรียงตามเวลาเดิม (เก่า→ใหม่)

    result = _drive(queries)
    result["mode"] = "replay"
    result["config"] = {"limit": limit, "fake_embed": fake_embed, "found": len(queries)}
    return result


# ── reporting ─────────────────────────────────────────────────────────────────
def _pct(x):
    return f"{x*100:.1f}%" if isinstance(x, (int, float)) else "—"


def print_report(r: dict) -> None:
    print(f"\n{'='*52}")
    print(f" Cache Bench — mode={r['mode']}  ({r['queries']} queries, {r['elapsed_sec']}s)")
    print(f" config: {r['config']}")
    print(f"{'='*52}")
    for layer, label in [("response_cache", "Response (semantic Q&A)"),
                         ("retrieval_cache", "Retrieval (per-session)")]:
        s = r[layer]
        print(f"\n▸ {label}")
        print(f"    lookups={s['lookups']}  hits={s['hits']}  misses={s['misses']}")
        print(f"    hit_rate = {_pct(s['hit_rate'])}")
    e = r["embed"]
    print(f"\n▸ Embed (LMStudio)")
    print(f"    lru_hit_rate={_pct(e['lru_hit_rate'])}  lru_hits={e['lru_hits']} "
          f"lru_misses={e['lru_misses']}  sqlite_hits={e['sqlite_hits']}  api_calls={e['api_calls']}")
    print(f"\n⏱  estimated latency saved ≈ {r['estimated_ms_saved']/1000:.1f}s")
    print(f"{'='*52}\n")


def main():
    ap = argparse.ArgumentParser(description="วัด hit rate ของ Phase E cache")
    sub = ap.add_subparsers(dest="mode", required=True)

    sp = sub.add_parser("synthetic", help="query stream สังเคราะห์")
    sp.add_argument("--n", type=int, default=200)
    sp.add_argument("--repeat", type=float, default=0.4, help="สัดส่วน exact-repeat (0-1)")
    sp.add_argument("--fake-embed", action="store_true")
    sp.add_argument("--json", action="store_true")

    rp = sub.add_parser("replay", help="replay prompt จริงจาก chat_history.db")
    rp.add_argument("--limit", type=int, default=300)
    rp.add_argument("--fake-embed", action="store_true")
    rp.add_argument("--json", action="store_true")

    args = ap.parse_args()
    if args.mode == "synthetic":
        result = run_synthetic(n=args.n, repeat=args.repeat, fake_embed=args.fake_embed)
    else:
        result = run_replay(limit=args.limit, fake_embed=args.fake_embed)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_report(result)


if __name__ == "__main__":
    main()
