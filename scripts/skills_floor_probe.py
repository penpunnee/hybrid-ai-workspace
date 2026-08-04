#!/usr/bin/env python3
"""วัดสเกลคะแนนของ `search_skills()` ก่อนตั้งพื้นคะแนน — backlog ข้อ 1 (openclaw)

**ห้ามตั้งเลขก่อนวัด** (บทเรียนเกณฑ์ bundle 600 kB ที่ตั้งก่อนรู้ floor) สคริปต์นี้
ตอบ 3 คำถามที่ยังไม่รู้คำตอบ — ไม่ใช่แค่พิมพ์คะแนนออกมาดู:

1. **`skills_collection` ใช้ space อะไร** — `utils/skills_search.py:44` สร้าง collection
   ด้วย `client.create_collection()` ตรงๆ ข้าม `get_or_create_collection()` ที่ตั้ง
   `hnsw:space: cosine` ให้ทุก collection อื่นในโปรเจกต์ → ถ้าเป็น **l2** (default ของ
   chroma) สเกล distance จะไม่มีขอบบน และ `1.0 - distance` ที่ `utils/skills_shadow.py:159`
   ใช้อยู่ก็แปลผลผิดทั้งชุด (คือเครื่องมือวัดของข้อ 21 เอง)

2. **มี "ที่ราบ" ระหว่างของที่เกี่ยวกับของที่ไม่เกี่ยวไหม** — ต้องยิงทั้งสองกลุ่ม
   ไม่ใช่ยิงแต่คำถามที่รู้คำตอบ · เกณฑ์ที่เชื่อได้ต้องมาจากช่องว่างที่กว้าง
   (web search: ขยะ 0.10–0.24 · ของดี 0.60–0.82 → ช่องว่าง 0.36) ถ้าสองกลุ่มทับกัน
   แปลว่าพื้นคะแนนแก้ไม่ได้ ต้องไปแก้ที่ embedding/สิ่งที่เอาไป embed แทน

3. **เคส `openclaw` พังตรงไหน** — ถามแล้วได้ skill ที่ไม่เกี่ยว แปลว่าอย่างใดอย่างหนึ่ง:
   (ก) `openclaw` ไม่มีใน collection เลย → ปัญหาอยู่ที่ sync ไม่ใช่ที่เกณฑ์
   (ข) มีอยู่แต่แพ้ตัวอื่น → ปัญหาอยู่ที่ embedding
   (ค) มีอยู่และชนะ แต่ตัวที่ไม่เกี่ยวตามมาด้วยเพราะไม่มีพื้น → พื้นคะแนนแก้ได้จริง

รันในคอนเทนเนอร์เท่านั้น (ChromaDB + Ollama embeddings อยู่ในวง NAS):

    ssh nas 'sudo -n /usr/local/bin/docker exec ai-backend-1 \
      sh -c "cd /app && python scripts/skills_floor_probe.py"'

อ่านอย่างเดียว ไม่เขียนอะไรลง prod
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# คำถามที่ "ควรเจอ" — อิงจากไฟล์ที่มีอยู่จริงใน skills/ (ถามด้วยภาษาที่คนถามจริง
# ไม่ใช่ลอกชื่อไฟล์มา — ลอกชื่อไฟล์จะได้คะแนนสูงปลอมๆ แล้วเกณฑ์จะหลวมเกินจริง)
RELEVANT = [
    ("openclaw คืออะไร", "openclaw.md"),
    ("deploy ขึ้น NAS ยังไง", "docker-deployment-nas.md"),
    ("gemini quota หมดทำไง", "gemini-api-quota-sdk-gotchas.md"),
    ("ระบบ memory ใช้อะไรเก็บ", "memory-system-chromadb.md"),
    ("ปลุกคอมด้วย wake on lan", "home-network-tools-nas-wol.md"),
    ("โมเดลมันกุข้อมูลตลอด แก้ยังไง", "anti-hallucination-local-llm.md"),
]

# คำถามที่ "ไม่ควรเจออะไรเลย" — กลุ่มควบคุม ต้องเป็นคำถามที่คนถามจริงในแชทนี้ได้
# ไม่ใช่คำมั่วๆ (คำมั่วจะได้คะแนนต่ำง่ายเกินไป → เกณฑ์ที่ได้จะหลวมเกินจริง)
IRRELEVANT = [
    "วันนี้อากาศเป็นยังไง",
    "ทำต้มยำกุ้งยังไงให้อร่อย",
    "ราคาทองคำวันนี้เท่าไหร่",
    "แนะนำหนังสนุกๆ หน่อย",
    "ปวดหัวข้างเดียวเกิดจากอะไร",
]

TOP_N = 5


def main() -> int:
    from utils.skills_search import get_skills_search

    search = get_skills_search()
    if not search.available:
        print("❌ skills search ใช้ไม่ได้ — ต่อ ChromaDB ไม่ได้ (ต้องรันในคอนเทนเนอร์)")
        return 1

    col = search.collection

    # ── คำถามที่ 1: space จริงคืออะไร ────────────────────────────────────────
    meta = dict(col.metadata or {})
    space = meta.get("hnsw:space", "l2 (ไม่ได้ตั้ง = default ของ chroma)")
    print("=" * 72)
    print(f"collection : {search.collection_name}")
    print(f"count      : {col.count()}")
    print(f"metadata   : {meta}")
    print(f"→ space    : {space}")
    if "cosine" not in str(space):
        print("  🔴 ไม่ใช่ cosine → `1.0 - distance` ใน skills_shadow.py:159 แปลผลผิด")
        print("     และ distance ไม่มีขอบบน (เทียบกับเกณฑ์ 0.35 ของเส้นอื่นไม่ได้)")
    print("=" * 72)

    # ── คำถามที่ 3(ก): openclaw อยู่ใน collection ไหม ────────────────────────
    got = col.get(include=["metadatas"])
    sources = sorted({(m or {}).get("source", "?") for m in got.get("metadatas", [])})
    print(f"\nไฟล์ที่อยู่ใน index จริง ({len(sources)}):")
    for s in sources:
        print(f"  · {s}")
    print()

    # ── คำถามที่ 2: ยิงทั้งสองกลุ่มแล้วดูว่ามีที่ราบไหม ──────────────────────
    def probe(q: str, expect: str | None) -> list[float]:
        rows = search.search(q, n_results=TOP_N)
        print(f"\n▸ {q!r}" + (f"   (ควรเจอ: {expect})" if expect else "   (ไม่ควรเจออะไรเลย)"))
        if not rows:
            print("    (ไม่มีผลลัพธ์)")
            return []
        dists = []
        for i, r in enumerate(rows, 1):
            d = r.get("distance")
            dists.append(d)
            hit = ""
            if expect and (r.get("source") == expect or expect.startswith(str(r.get("topic", "\0")))):
                hit = "  ← ตัวที่ควรเจอ"
            ds = f"{d:.4f}" if d is not None else "None"
            print(f"    {i}. d={ds}  [{r.get('source')}] {str(r.get('topic'))[:40]}{hit}")
        return [d for d in dists if d is not None]

    print("─" * 72)
    print("กลุ่ม A — คำถามที่ควรเจอ skill จริง")
    print("─" * 72)
    rel_top: list[float] = []
    for q, expect in RELEVANT:
        ds = probe(q, expect)
        if ds:
            rel_top.append(ds[0])

    print()
    print("─" * 72)
    print("กลุ่ม B — คำถามที่ไม่ควรเจออะไรเลย (กลุ่มควบคุม)")
    print("─" * 72)
    irr_top: list[float] = []
    for q in IRRELEVANT:
        ds = probe(q, None)
        if ds:
            irr_top.append(ds[0])

    # ── สรุปช่องว่าง — เกณฑ์ต้องมาจากที่ราบ ไม่ใช่จากค่ากลาง ────────────────
    print()
    print("=" * 72)
    print("สรุป (ดู distance: ต่ำ = ใกล้/เกี่ยวข้องมาก)")
    if rel_top:
        print(f"  กลุ่ม A (ควรเจอ)      อันดับ 1: {min(rel_top):.4f} – {max(rel_top):.4f}")
    if irr_top:
        print(f"  กลุ่ม B (ไม่ควรเจอ)   อันดับ 1: {min(irr_top):.4f} – {max(irr_top):.4f}")
    if rel_top and irr_top:
        gap = min(irr_top) - max(rel_top)
        print(f"  ช่องว่าง             : {gap:+.4f}")
        if gap > 0:
            print(f"  → มีที่ราบจริง เกณฑ์ควรอยู่ระหว่าง {max(rel_top):.4f} กับ {min(irr_top):.4f}")
        else:
            print("  → 🔴 สองกลุ่มทับกัน — พื้นคะแนนแก้ไม่ได้ ต้นเหตุอยู่ที่ embedding/สิ่งที่เอาไป embed")
            print("     (อย่าตั้งเลขทับ ต้องกลับไปดูข้อ 17 embedding dilution)")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
