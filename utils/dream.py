"""
Dream Cycle — จำลองการจัดระเบียบความจำของสมองมนุษย์ตอนนอน
รันตี 2 ทุกคืนผ่าน cron job

3 Phases:
  1. Light Sleep  — คัดเลือกข้อมูลดิบของวันนั้น
  2. REM Sleep    — หา pattern + theme + cross-links
  3. Deep Sleep   — เลื่อนข้อมูลสำคัญเข้า long-term memory
"""
import os
import json
from datetime import datetime, timedelta
from collections import Counter
from pathlib import Path

from utils.memory import _get_client
from utils.llm import stream_response
from utils.skills import save_skill


DREAM_REPORTS_DIR = Path(__file__).parent.parent / "dream_reports"
DREAM_REPORTS_DIR.mkdir(exist_ok=True)

# เกณฑ์เลื่อนขั้นเข้า Deep Sleep (long-term memory)
PROMOTE_MIN_SCORE = 0.8
PROMOTE_MIN_HITS = 3
PROMOTE_MIN_QUERIES = 3


# ---------- Phase 1: Light Sleep ----------
def light_sleep(hours: int = 24) -> list[dict]:
    """คัดเลือก memory ดิบที่ถูกสร้างใน N ชั่วโมงที่ผ่านมา"""
    client = _get_client()
    if client is None:
        return []

    since = (datetime.now() - timedelta(hours=hours)).isoformat()
    raw_memories = []

    try:
        collections = client.list_collections()
        for col_info in collections:
            name = col_info.name if hasattr(col_info, "name") else str(col_info)
            if name.startswith("memory_"):
                col = client.get_collection(name)
                data = col.get()
                for i, doc in enumerate(data.get("documents", [])):
                    meta = data.get("metadatas", [{}])[i] or {}
                    ts = meta.get("timestamp", "")
                    if ts >= since:
                        raw_memories.append({
                            "collection": name,
                            "id": data.get("ids", [""])[i],
                            "doc": doc,
                            "timestamp": ts,
                            "assistant": meta.get("assistant", ""),
                        })
    except Exception as e:
        print(f"[Dream/LightSleep] error: {e}")

    return raw_memories


# ---------- Phase 2: REM Sleep ----------
def rem_sleep(memories: list[dict], provider: str = "ollama") -> dict:
    """วิเคราะห์ pattern + หาธีม + cross-links"""
    if not memories:
        return {"themes": [], "insights": [], "connections": []}

    # รวมเนื้อหาทั้งหมดเป็น text สำหรับให้ AI สรุป
    combined = "\n\n---\n\n".join(
        f"[{m.get('timestamp','')}] {m['doc'][:500]}"
        for m in memories[:50]  # จำกัดไม่ให้ context บาน
    )

    prompt = (
        "นี่คือบทสนทนา/memory ของผู้ใช้ใน 24 ชั่วโมงที่ผ่านมา "
        "กรุณาวิเคราะห์เป็น JSON ตามรูปแบบนี้เท่านั้น (ไม่ต้องมีข้อความอื่น):\n"
        '{"themes":[{"name":"ชื่อธีม","summary":"สรุป 1-2 ประโยค","count":จำนวนครั้งที่ปรากฏ}],'
        '"insights":["insight 1","insight 2"],'
        '"connections":[{"from":"เรื่อง A","to":"เรื่อง B","reason":"เชื่อมโยงเพราะ..."}]}'
        "\n\n=== ข้อมูล ===\n" + combined
    )

    messages = [
        {"role": "system", "content": "คุณคือระบบวิเคราะห์ความจำ ตอบเป็น JSON เท่านั้น"},
        {"role": "user", "content": prompt},
    ]

    try:
        response = "".join(stream_response(messages, provider=provider))
        # หา JSON ในคำตอบ
        start = response.find("{")
        end = response.rfind("}")
        if start >= 0 and end > start:
            return json.loads(response[start:end+1])
    except Exception as e:
        print(f"[Dream/REM] parse error: {e}")

    return {"themes": [], "insights": [], "connections": [], "raw": response if 'response' in dir() else ""}


# ---------- Phase 3: Deep Sleep ----------
def deep_sleep(memories: list[dict], themes: list[dict]) -> dict:
    """เลื่อนข้อมูลสำคัญเข้า long-term (skills_db.json)"""
    promoted = []
    client = _get_client()

    # คำนวณคะแนนจากความถี่ของคำในธีม
    theme_counts = Counter()
    for t in themes:
        name = t.get("name", "").strip()
        count = t.get("count", 0)
        if name and count >= PROMOTE_MIN_HITS:
            theme_counts[name] = count

    # บันทึก theme ที่ผ่านเกณฑ์เข้า skills
    for theme_name, count in theme_counts.items():
        matching = next((t for t in themes if t.get("name") == theme_name), {})
        summary = matching.get("summary", "")
        if summary and len(summary) > 10:
            save_skill(
                topic=f"[Dream] {theme_name}",
                summary=f"{summary} (consolidated {count} times on {datetime.now().strftime('%Y-%m-%d')})",
                source="dream_cycle",
            )
            promoted.append(theme_name)

    # บันทึกเข้า ChromaDB collection "long_term_memory"
    if client is not None and promoted:
        try:
            col = client.get_or_create_collection(
                "long_term_memory",
                metadata={"hnsw:space": "cosine"},
            )
            for theme_name in promoted:
                matching = next((t for t in themes if t.get("name") == theme_name), {})
                summary = matching.get("summary", "")
                doc_id = f"lt_{datetime.now().strftime('%Y%m%d')}_{theme_name[:20]}"
                col.upsert(
                    ids=[doc_id],
                    documents=[f"[{theme_name}] {summary}"],
                    metadatas=[{
                        "theme": theme_name,
                        "consolidated_at": datetime.now().isoformat(),
                        "hits": theme_counts[theme_name],
                    }],
                )
        except Exception as e:
            print(f"[Dream/DeepSleep] error: {e}")

    return {"promoted": promoted, "count": len(promoted)}


# ---------- Main Dream Cycle ----------
def run_dream_cycle(provider: str = "ollama", hours: int = 24) -> dict:
    """รันวงจรฝันเต็มรูปแบบ"""
    start = datetime.now()
    report = {
        "started_at": start.isoformat(),
        "provider": provider,
        "hours_window": hours,
    }

    # Phase 1
    memories = light_sleep(hours=hours)
    report["phase1_light"] = {"raw_count": len(memories)}

    if not memories:
        report["skipped"] = "no memories in window"
        _save_report(report)
        return report

    # Phase 2
    analysis = rem_sleep(memories, provider=provider)
    report["phase2_rem"] = analysis

    # Phase 3
    result = deep_sleep(memories, analysis.get("themes", []))
    report["phase3_deep"] = result

    end = datetime.now()
    report["finished_at"] = end.isoformat()
    report["duration_sec"] = (end - start).total_seconds()

    _save_report(report)
    return report


def _save_report(report: dict):
    """บันทึก report เก็บไว้ดูย้อนหลัง"""
    fname = f"dream_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    try:
        with open(DREAM_REPORTS_DIR / fname, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def get_latest_report() -> dict:
    """ดึง dream report ล่าสุด"""
    files = sorted(DREAM_REPORTS_DIR.glob("dream_*.json"), reverse=True)
    if not files:
        return {"error": "no reports yet"}
    try:
        with open(files[0], "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"error": str(e)}


def list_reports(limit: int = 10) -> list[dict]:
    """ลิสต์ dream reports ล่าสุด"""
    files = sorted(DREAM_REPORTS_DIR.glob("dream_*.json"), reverse=True)[:limit]
    out = []
    for f in files:
        try:
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)
                out.append({
                    "file": f.name,
                    "started_at": data.get("started_at", ""),
                    "themes_count": len(data.get("phase2_rem", {}).get("themes", [])),
                    "promoted": data.get("phase3_deep", {}).get("count", 0),
                })
        except Exception:
            pass
    return out


if __name__ == "__main__":
    # รันจาก command line: python -m utils.dream
    import sys
    provider = sys.argv[1] if len(sys.argv) > 1 else "ollama"
    result = run_dream_cycle(provider=provider)
    print(json.dumps(result, ensure_ascii=False, indent=2))
