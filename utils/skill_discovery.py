"""Skill Auto-Discovery — สแกน chat history หา topic ที่ user ถามบ่อย → propose skill

ขั้นตอน:
  1. ดึง user prompts ในช่วง N วัน
  2. Embed prompts (LMStudio) → cluster ด้วย greedy similarity grouping
  3. กลุ่มที่มี ≥ min_cluster prompts → candidate skill
  4. เทียบกับ skills_db.json (กัน duplicate) — skip ถ้าใกล้ของเดิม
  5. ใช้ LLM สรุปกลุ่มเป็น topic + summary

API:
  discover_skills(...) → list[SkillProposal]
  accept_proposal(proposal_id, ...) → create .md + update skills_db
"""
import json
import logging
import os
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Optional

from utils.embed import embed_texts, cosine_similarity, embed_query
from utils.history import _get_conn

logger = logging.getLogger(__name__)

_SKILLS_DIR = os.path.join(os.path.dirname(__file__), "..", "skills")
_SKILLS_DB = os.path.join(os.path.dirname(__file__), "..", "skills_db.json")

# in-memory cache สำหรับ accept (proposal_id → proposal)
_proposals_cache: dict[str, "SkillProposal"] = {}


@dataclass
class SkillProposal:
    """ข้อเสนอ skill จาก clustering"""
    id: str
    topic: str
    summary: str
    examples: list[str] = field(default_factory=list)   # user prompts ตัวอย่าง
    cluster_size: int = 0
    avg_similarity: float = 0.0
    detected_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _fetch_recent_prompts(days: int = 30, limit: int = 500) -> list[str]:
    """ดึง user prompts ล่าสุด"""
    since = (datetime.now() - timedelta(days=days)).isoformat()
    conn = _get_conn()
    try:
        rows = conn.execute(
            """SELECT content FROM messages
               WHERE role = 'user' AND created_at >= ?
               ORDER BY id DESC LIMIT ?""",
            (since, limit),
        ).fetchall()
    finally:
        conn.close()
    # filter ออก prompts สั้นๆ ที่เป็น noise
    return [r[0] for r in rows if r[0] and 8 <= len(r[0]) <= 500]


def _greedy_cluster(
    prompts: list[str],
    vectors: list[list[float]],
    threshold: float = 0.72,
) -> list[list[int]]:
    """greedy clustering — รวม prompt เข้า cluster ที่ similarity เฉลี่ยสูงสุดและ > threshold"""
    clusters: list[list[int]] = []          # list of indices
    centroids: list[list[float]] = []       # mean vector ของแต่ละ cluster

    for i, vec in enumerate(vectors):
        if not vec:
            continue
        best_j, best_sim = -1, -1.0
        for j, cen in enumerate(centroids):
            sim = cosine_similarity(vec, cen)
            if sim > best_sim:
                best_sim, best_j = sim, j
        if best_j >= 0 and best_sim >= threshold:
            clusters[best_j].append(i)
            # update centroid (running mean)
            n = len(clusters[best_j])
            old = centroids[best_j]
            centroids[best_j] = [(old[k] * (n - 1) + vec[k]) / n for k in range(len(vec))]
        else:
            clusters.append([i])
            centroids.append(list(vec))
    return clusters


def _load_existing_skill_topics() -> list[tuple[str, list[float]]]:
    """โหลด topics เดิม + embed เพื่อกัน duplicate"""
    if not os.path.isfile(_SKILLS_DB):
        return []
    try:
        with open(_SKILLS_DB, "r", encoding="utf-8") as f:
            db = json.load(f)
        topics = list(db.keys())[:200]
        vectors = embed_texts(topics) if topics else []
        return list(zip(topics, vectors))
    except Exception as e:
        logger.warning(f"[SkillDiscovery] load existing failed: {e}")
        return []


def _is_duplicate(topic_vec: list[float], existing: list[tuple[str, list[float]]],
                  threshold: float = 0.82) -> Optional[str]:
    """คืนชื่อ skill เดิมที่ใกล้กัน — None ถ้าไม่ใช่ duplicate"""
    if not topic_vec:
        return None
    for name, vec in existing:
        if not vec:
            continue
        if cosine_similarity(topic_vec, vec) >= threshold:
            return name
    return None


def _summarize_cluster(prompts: list[str]) -> tuple[str, str]:
    """ใช้ LLM สรุป cluster เป็น (topic, summary) — fallback ใช้ heuristic ถ้า fail"""
    sample = "\n".join(f"- {p[:200]}" for p in prompts[:8])
    sys_msg = (
        "คุณคือ Knowledge Curator วิเคราะห์กลุ่มคำถามจาก user แล้วสรุปเป็น skill\n"
        "ตอบเป็น JSON เท่านั้น schema: {\"topic\": str, \"summary\": str}\n"
        "- topic: ชื่อสั้น 2-5 คำ บอกธีมหลัก (ภาษาไทยหรืออังกฤษตามคำถามส่วนใหญ่)\n"
        "- summary: 1-2 ประโยค บอก context ที่ user มักถาม"
    )
    user_msg = f"กลุ่มคำถาม ({len(prompts)} ข้อ):\n{sample}\n\nสรุปเป็น JSON"

    try:
        from openai import OpenAI
        client = OpenAI(
            base_url=os.getenv("LMSTUDIO_BASE_URL", "http://192.168.51.235:1234/v1"),
            api_key="lmstudio",
            timeout=15,
        )
        resp = client.chat.completions.create(
            model=os.getenv("LMSTUDIO_CHAT_MODEL", "google/gemma-4-e4b"),
            messages=[{"role": "system", "content": sys_msg},
                      {"role": "user", "content": user_msg}],
            temperature=0.3,
            max_tokens=200,
            stream=False,
        )
        text = (resp.choices[0].message.content or "").strip()
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            data = json.loads(m.group(0))
            topic = str(data.get("topic", "")).strip()
            summary = str(data.get("summary", "")).strip()
            if topic and summary:
                return topic[:60], summary[:300]
    except Exception as e:
        logger.warning(f"[SkillDiscovery] summarize failed: {e}")

    # Fallback heuristic: ใช้ prompt แรก เป็น topic
    first = prompts[0]
    return first[:50], f"พบคำถามคล้ายกัน {len(prompts)} ครั้งในช่วงที่ผ่านมา"


def discover_skills(
    days: int = 30,
    min_cluster: int = 3,
    threshold: float = 0.72,
    max_proposals: int = 10,
) -> list[SkillProposal]:
    """หา proposals จาก chat history

    Args:
        days: ดู prompts ย้อนหลังกี่วัน
        min_cluster: ขนาด cluster ขั้นต่ำ (ถามอย่างน้อย N ครั้ง)
        threshold: cosine similarity threshold (สูง = strict)
        max_proposals: จำกัด proposals ที่คืน (เร็วและไม่ overwhelm)

    Returns:
        list[SkillProposal] เรียงตาม cluster_size desc
    """
    prompts = _fetch_recent_prompts(days=days)
    if len(prompts) < min_cluster:
        return []

    vectors = embed_texts(prompts)
    if not vectors or len(vectors) != len(prompts):
        logger.warning(f"[SkillDiscovery] embed failed ({len(vectors)}/{len(prompts)})")
        return []

    clusters = _greedy_cluster(prompts, vectors, threshold=threshold)
    existing = _load_existing_skill_topics()

    proposals: list[SkillProposal] = []
    now_str = datetime.now().isoformat()

    for cluster in clusters:
        if len(cluster) < min_cluster:
            continue
        cluster_prompts = [prompts[i] for i in cluster]
        cluster_vecs = [vectors[i] for i in cluster]

        # check duplicate กับ skill เดิม (ใช้ centroid ของ cluster)
        dim = len(cluster_vecs[0])
        centroid = [sum(v[k] for v in cluster_vecs) / len(cluster_vecs) for k in range(dim)]
        if _is_duplicate(centroid, existing):
            continue

        topic, summary = _summarize_cluster(cluster_prompts)

        # check duplicate อีกครั้งด้วย topic ที่สรุป
        topic_vec = embed_query(topic)
        dup_name = _is_duplicate(topic_vec, existing)
        if dup_name:
            logger.info(f"[SkillDiscovery] skip duplicate of {dup_name!r}")
            continue

        # avg pairwise sim
        sims = [cosine_similarity(v, centroid) for v in cluster_vecs]
        avg = round(sum(sims) / len(sims), 3) if sims else 0.0

        pid = f"prop_{uuid.uuid4().hex[:8]}"
        proposal = SkillProposal(
            id=pid,
            topic=topic,
            summary=summary,
            examples=cluster_prompts[:5],
            cluster_size=len(cluster),
            avg_similarity=avg,
            detected_at=now_str,
        )
        proposals.append(proposal)
        _proposals_cache[pid] = proposal

    proposals.sort(key=lambda p: p.cluster_size, reverse=True)
    return proposals[:max_proposals]


def accept_proposal(
    proposal_id: str,
    custom_topic: Optional[str] = None,
    custom_content: Optional[str] = None,
) -> dict:
    """รับ proposal → สร้างไฟล์ .md ใน skills/ + เพิ่มเข้า skills_db.json"""
    proposal = _proposals_cache.get(proposal_id)
    if not proposal:
        return {"ok": False, "error": "proposal not found (อาจหมดอายุ — เรียก /discover ใหม่)"}

    topic = (custom_topic or proposal.topic).strip()
    if not topic:
        return {"ok": False, "error": "empty topic"}

    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in topic.lower()).strip("-")
    filename = f"{safe or 'skill'}-{int(time.time())}.md"

    if custom_content:
        md_body = custom_content
    else:
        examples = "\n".join(f"- {e}" for e in proposal.examples)
        md_body = (
            f"# {topic}\n\n"
            f"> Auto-discovered skill — {proposal.detected_at}\n\n"
            f"## สรุป\n{proposal.summary}\n\n"
            f"## คำถามที่พบบ่อย ({proposal.cluster_size} ครั้ง)\n{examples}\n"
        )

    os.makedirs(_SKILLS_DIR, exist_ok=True)
    filepath = os.path.join(_SKILLS_DIR, filename)
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(md_body)
    except Exception as e:
        return {"ok": False, "error": f"write file failed: {e}"}

    # update skills_db.json
    try:
        db = {}
        if os.path.isfile(_SKILLS_DB):
            with open(_SKILLS_DB, "r", encoding="utf-8") as f:
                db = json.load(f)
        db[topic] = {
            "topic": topic,
            "summary": proposal.summary,
            "source": filename,
            "auto_discovered": True,
            "cluster_size": proposal.cluster_size,
            "created_at": proposal.detected_at,
        }
        with open(_SKILLS_DB, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"[SkillDiscovery] update skills_db failed: {e}")

    # ลบ proposal ออกจาก cache
    _proposals_cache.pop(proposal_id, None)

    # sync ChromaDB (best-effort)
    try:
        from utils.skills_search import sync_skills_to_search
        sync_skills_to_search({topic: db[topic]})
    except Exception as e:
        logger.debug(f"[SkillDiscovery] sync ChromaDB skipped: {e}")

    return {"ok": True, "filename": filename, "topic": topic, "path": filepath}


def list_cached_proposals() -> list[dict]:
    """list proposals ที่ยังไม่หมดอายุใน cache"""
    return [p.to_dict() for p in _proposals_cache.values()]
