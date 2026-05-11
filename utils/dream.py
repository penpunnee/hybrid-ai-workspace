"""
Dream Cycle — จำลองการจัดระเบียบความจำของสมองมนุษย์ตอนนอน
รันตี 2 ทุกคืนผ่าน cron job

3 Phases:
  1. Light Sleep  — คัดเลือกข้อมูลดิบของวันนั้น
  2. REM Sleep    — หา pattern + theme + cross-links
  3. Deep Sleep   — เลื่อนข้อมูลสำคัญเข้า long-term memory

Logic Flow:
- Light Sleep: ดึง memory ดิบจาก ChromaDB (GBRAIN) ย้อนหลัง N ชั่วโมง
- REM Sleep: ใช้ AI (stream_response) วิเคราะห์ pattern และสรุปเป็น themes
- Deep Sleep: บันทึก themes ที่สำคัญลง skills_db.json และ ChromaDB long_term_memory
"""
import os
import json
import logging
from datetime import datetime, timedelta
from collections import Counter
from pathlib import Path

from utils.memory import _get_client
from utils.llm import stream_response
from utils.skills import save_skill

# Configure logging for dream cycle
logger = logging.getLogger(__name__)


DREAM_REPORTS_DIR = Path(__file__).parent.parent / "dream_reports"
DREAM_REPORTS_DIR.mkdir(exist_ok=True)

# เกณฑ์เลื่อนขั้นเข้า Deep Sleep (long-term memory)
PROMOTE_MIN_SCORE = 0.5
PROMOTE_MIN_HITS = 1
PROMOTE_MIN_QUERIES = 1


# ---------- Phase 1: Light Sleep ----------
def light_sleep(hours: int = 24) -> list[dict]:
    """
    คัดเลือก memory ดิบที่ถูกสร้างใน N ชั่วโมงที่ผ่านมา
    
    Logic:
    1. ดึง ChromaDB client จาก GBRAIN
    2. วนลูปทุก collection ที่ขึ้นต้นด้วย "memory_"
    3. ดึง documents ทั้งหมดจากแต่ละ collection
    4. กรองเฉพาะ memory ที่มี timestamp >= วันที่ cutoff
    5. คืนค่ารายการ memories ที่คัดเลือกได้
    
    Args:
        hours: จำนวนชั่วโมงย้อนหลังที่จะดึง (default: 24)
    
    Returns:
        list[dict]: รายการ memory ที่คัดเลือกได้
    """
    client = _get_client()
    if client is None:
        logger.error("Dream/LightSleep: ChromaDB client not available")
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
        logger.error(f"Dream/LightSleep error: {str(e)}")

    return raw_memories


# ---------- Phase 2: REM Sleep ----------
def rem_sleep(memories: list[dict], provider: str = "ollama") -> dict:
    """
    วิเคราะห์ pattern + หาธีม + cross-links
    
    Logic:
    1. รวมเนื้อหา memories ทั้งหมดเป็น text (จำกัด 50 รายการ)
    2. สร้าง prompt ให้ AI วิเคราะห์เป็น JSON (themes, insights, connections)
    3. เรียก stream_response จาก llm.py เพื่อให้ AI วิเคราะห์
    4. แยก JSON จาก response ที่ได้
    5. คืนค่าผลการวิเคราะห์
    
    Args:
        memories: รายการ memory จาก Light Sleep
        provider: AI provider (default: "ollama")
    
    Returns:
        dict: ผลการวิเคราะห์ {themes, insights, connections}
    """
    if not memories:
        logger.info("Dream/REM: No memories to analyze")
        return {"themes": [], "insights": [], "connections": []}

    combined = "\n---\n".join(
        f"[{m.get('timestamp', '')[:16]}] {m['doc'][:300]}"
        for m in memories[:30]
    )

    # Few-shot prompt — แสดง output จริงไม่ใช่ placeholder
    system_msg = (
        "You are a memory consolidation system. "
        "Analyze conversation memories and output ONLY valid JSON — no markdown, no explanation.\n\n"
        "Output format example (use real content, not these placeholder words):\n"
        '{"themes":[{"name":"Docker Deployment","summary":"User frequently deploys to NAS using docker compose","count":3}],'
        '"insights":["User prefers concise Thai responses","System uses LM Studio for local inference"],'
        '"connections":[{"from":"Docker","to":"NAS","reason":"All deployments target the Synology NAS"}]}'
    )

    user_msg = (
        f"Analyze these {len(memories)} memories from the past {memories[0].get('timestamp','')[:10] if memories else 'N/A'}.\n"
        "Find recurring themes, extract insights, and identify connections.\n"
        "Respond with JSON only — no other text.\n\n"
        f"=== MEMORIES ===\n{combined}"
    )

    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]

    def _try_parse(raw: str) -> dict | None:
        """พยายาม parse JSON จาก response ที่อาจมี markdown wrapper"""
        raw = raw.strip()
        # กรณี ```json ... ```
        if "```" in raw:
            import re
            m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
            if m:
                raw = m.group(1)
        # หา { ... } ที่ใหญ่สุด
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            result = json.loads(raw[start:end + 1])
            # ตรวจว่าไม่ใช่ template (ไม่มี placeholder)
            themes = result.get("themes", [])
            if themes and any(
                t.get("name", "") in ("ชื่อธีม", "theme name", "Theme Name")
                for t in themes
            ):
                logger.warning("Dream/REM: got template placeholder, retrying")
                return None
            return result
        except json.JSONDecodeError:
            return None

    logger.info(f"Dream/REM: Analyzing {len(memories)} memories (provider={provider})")

    # Attempt 1 — full prompt
    try:
        response = "".join(stream_response(messages, provider=provider))
        result = _try_parse(response)
        if result:
            logger.info(f"Dream/REM: Found {len(result.get('themes', []))} themes")
            return result
        logger.warning(f"Dream/REM: attempt 1 failed to parse, raw={response[:200]}")
    except Exception as e:
        logger.error(f"Dream/REM attempt 1 error: {e}")
        response = ""

    # Attempt 2 — simplified prompt (fallback)
    try:
        simple_msgs = [
            {"role": "system", "content": "Output only JSON. No markdown."},
            {"role": "user", "content": (
                f"Summarize these memories into JSON:\n{combined[:1000]}\n\n"
                'Format: {"themes":[{"name":"<actual topic>","summary":"<actual summary>","count":1}],'
                '"insights":["<actual insight>"],"connections":[]}'
            )},
        ]
        response2 = "".join(stream_response(simple_msgs, provider=provider))
        result = _try_parse(response2)
        if result:
            logger.info(f"Dream/REM: attempt 2 succeeded — {len(result.get('themes', []))} themes")
            return result
        logger.warning(f"Dream/REM: attempt 2 also failed, raw={response2[:200]}")
    except Exception as e:
        logger.error(f"Dream/REM attempt 2 error: {e}")

    return {"themes": [], "insights": [], "connections": [], "raw": response[:500]}


# ---------- Phase 3: Deep Sleep ----------
def deep_sleep(memories: list[dict], themes: list[dict]) -> dict:
    """
    เลื่อนข้อมูลสำคัญเข้า long-term (skills_db.json)
    
    Logic:
    1. นับความถี่ของแต่ละ theme จาก AI response
    2. กรอง themes ที่ผ่านเกณฑ์ (PROMOTE_MIN_HITS)
    3. บันทึก themes ที่ผ่านเกณฑ์ลง skills_db.json ผ่าน save_skill()
    4. บันทึก themes ที่ผ่านเกณฑ์ลง ChromaDB collection "long_term_memory"
    5. คืนค่ารายการ themes ที่ถูก promote
    
    Args:
        memories: รายการ memory จาก Light Sleep
        themes: รายการ themes จาก REM Sleep
    
    Returns:
        dict: {promoted: list, count: int}
    """
    promoted = []
    client = _get_client()

    if client is None:
        logger.error("Dream/DeepSleep: ChromaDB client not available")
        return {"promoted": [], "count": 0}

    # คำนวณคะแนนจากความถี่ของคำในธีม
    theme_counts = Counter()
    for t in themes:
        name = t.get("name", "").strip()
        count = t.get("count", 1)  # default 1 ถ้า AI ไม่ส่ง count
        if name and count >= PROMOTE_MIN_HITS:
            theme_counts[name] = count

    # บันทึก theme ที่ผ่านเกณฑ์เข้า skills (sync=False เพื่อไม่ sync ทุกรายการ)
    for theme_name, count in theme_counts.items():
        matching = next((t for t in themes if t.get("name") == theme_name), {})
        summary = matching.get("summary", "")
        if summary and len(summary) > 10:
            save_skill(
                topic=f"[Dream] {theme_name}",
                summary=f"{summary} (consolidated {count} times on {datetime.now().strftime('%Y-%m-%d')})",
                source="dream_cycle",
                sync=False,  # sync ครั้งเดียวหลัง loop จบ
            )
            promoted.append(theme_name)

    # sync skills ครั้งเดียวหลังบันทึกครบทุก theme
    if promoted:
        try:
            from utils.skills_search import sync_skills_to_search
            from utils.skills import _load_skills_db
            sync_skills_to_search(_load_skills_db())
            logger.info(f"Dream/DeepSleep: Skills synced after promoting {len(promoted)} themes")
        except Exception as e:
            logger.warning(f"Dream/DeepSleep: Skills sync failed (non-critical): {e}")

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
            logger.info(f"Dream/DeepSleep: Promoted {len(promoted)} themes to long-term memory")
        except Exception as e:
            logger.error(f"Dream/DeepSleep error: {str(e)}")

    return {"promoted": promoted, "count": len(promoted)}


# ---------- Main Dream Cycle ----------
def run_dream_cycle(provider: str = "ollama", hours: int = 24) -> dict:
    """
    รันวงจรฝันเต็มรูปแบบ
    
    Logic:
    1. Phase 1 (Light Sleep): ดึง memory ดิบจาก ChromaDB
    2. ถ้าไม่มี memory: ข้ามและบันทึก report
    3. Phase 2 (REM Sleep): ใช้ AI วิเคราะห์ pattern
    4. Phase 3 (Deep Sleep): Promote ข้อมูลสำคัญไป long-term
    5. บันทึก report ลง dream_reports/
    
    Args:
        provider: AI provider (default: "ollama")
        hours: จำนวนชั่วโมงย้อนหลัง (default: 24)
    
    Returns:
        dict: Report สรุปผลการทำงานทั้ง 3 phases
    """
    start = datetime.now()
    logger.info(f"Dream cycle started at {start.isoformat()} (provider={provider}, hours={hours})")
    
    report = {
        "started_at": start.isoformat(),
        "provider": provider,
        "hours_window": hours,
        "memories_processed": 0,
    }

    # Phase 1
    memories = light_sleep(hours=hours)
    report["phase1_light"] = {"raw_count": len(memories)}
    report["memories_processed"] = len(memories)
    logger.info(f"Dream Phase 1 (Light Sleep): Found {len(memories)} memories")

    if not memories:
        end = datetime.now()
        report["skipped"] = "no memories in window"
        report["finished_at"] = end.isoformat()
        report["duration_sec"] = (end - start).total_seconds()
        logger.info("Dream cycle skipped: no memories in window")
        _save_report(report)
        return report

    # Phase 2
    analysis = rem_sleep(memories, provider=provider)
    report["phase2_rem"] = analysis
    logger.info(f"Dream Phase 2 (REM): Analysis complete - {len(analysis.get('themes', []))} themes found")

    # Phase 3
    result = deep_sleep(memories, analysis.get("themes", []))
    report["phase3_deep"] = result
    logger.info(f"Dream Phase 3 (Deep Sleep): Promoted {result.get('count', 0)} themes to long-term memory")

    end = datetime.now()
    report["finished_at"] = end.isoformat()
    report["duration_sec"] = (end - start).total_seconds()
    
    logger.info(f"Dream cycle completed in {report['duration_sec']:.2f}s")
    _save_report(report)
    return report


def _save_report(report: dict):
    """
    บันทึก report เก็บไว้ดูย้อนหลัง
    
    Logic:
    1. บันทึกเป็น .json ไว้ใน dream_reports/ (สำหรับ debug)
    2. บันทึกเป็น .md ไฟล์ใน Obsidian Vault (สำหรับ review)
    3. ตั้งชื่อไฟล์ตามวันที่ (YYYY-MM-DD-dream.md)
    4. เพิ่ม tags #dream #ai-learning
    """
    # บันทึก JSON (สำหรับ debug)
    fname_json = f"dream_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    try:
        with open(DREAM_REPORTS_DIR / fname_json, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        logger.info(f"Dream report saved: {fname_json}")
    except Exception as e:
        logger.error(f"Dream/_save_report JSON error: {str(e)}")
    
    # บันทึก Markdown ลง Obsidian Vault
    vault_path = os.getenv("OBSIDIAN_VAULT_PATH", "")
    if not vault_path or not os.path.isdir(vault_path):
        logger.warning(f"Dream/_save_report: Obsidian Vault not available: {vault_path}")
        return
    
    try:
        # ตั้งชื่อไฟล์ตามวันที่
        fname_md = f"{datetime.now().strftime('%Y-%m-%d')}-dream.md"
        vault_file = Path(vault_path) / fname_md
        
        # สร้างเนื้อหา Markdown
        md_content = f"""---
tags: [dream, ai-learning]
created: {datetime.now().isoformat()}
---

# Dream Cycle Report

**Date:** {report.get('started_at', '')}  
**Duration:** {report.get('duration_sec', 0):.2f} seconds  
**Provider:** {report.get('provider', '')}  
**Hours Window:** {report.get('hours_window', '')}

---

## Phase 1: Light Sleep
**Raw Memories:** {report.get('phase1_light', {}).get('raw_count', 0)}

---

## Phase 2: REM Sleep
**Themes Found:** {len(report.get('phase2_rem', {}).get('themes', []))}

### Themes
"""
        # เพิ่ม themes
        for theme in report.get('phase2_rem', {}).get('themes', []):
            md_content += f"\n### {theme.get('name', 'Unknown')}\n"
            md_content += f"- Summary: {theme.get('summary', '')}\n"
            md_content += f"- Count: {theme.get('count', 0)}\n"
        
        # เพิ่ม insights
        md_content += "\n### Insights\n"
        for insight in report.get('phase2_rem', {}).get('insights', []):
            md_content += f"- {insight}\n"
        
        # เพิ่ม connections
        md_content += "\n### Connections\n"
        for conn in report.get('phase2_rem', {}).get('connections', []):
            md_content += f"- {conn.get('from', '')} → {conn.get('to', '')}: {conn.get('reason', '')}\n"
        
        # เพิ่ม Deep Sleep
        md_content += f"""
---

## Phase 3: Deep Sleep
**Promoted Themes:** {report.get('phase3_deep', {}).get('count', 0)}

### Promoted Themes
"""
        for theme in report.get('phase3_deep', {}).get('promoted', []):
            md_content += f"- {theme}\n"
        
        # บันทึกไฟล์
        with open(vault_file, "w", encoding="utf-8") as f:
            f.write(md_content)
        logger.info(f"Dream report saved to Obsidian Vault: {fname_md}")
    except Exception as e:
        logger.error(f"Dream/_save_report Markdown error: {str(e)}")


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
                themes = data.get("phase2_rem", {}).get("themes", [])
                promoted_list = data.get("phase3_deep", {}).get("promoted", [])
                out.append({
                    "file": f.name,
                    "started_at": data.get("started_at", ""),
                    "duration_sec": data.get("duration_sec"),
                    "skipped": data.get("skipped"),
                    "phase1_light": data.get("phase1_light", {}),
                    "phase2_rem": {"themes": themes, "insights": data.get("phase2_rem", {}).get("insights", [])},
                    "phase3_deep": {"promoted": promoted_list, "count": len(promoted_list)},
                })
        except Exception as e:
            logger.warning(f"list_reports: failed to read report file '{f}': {e}")
            pass
    return out


if __name__ == "__main__":
    # รันจาก command line: python -m utils.dream
    import sys
    provider = sys.argv[1] if len(sys.argv) > 1 else "ollama"
    result = run_dream_cycle(provider=provider)
    print(json.dumps(result, ensure_ascii=False, indent=2))
