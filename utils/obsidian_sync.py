import os
import re
import hashlib
import logging
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Configure logging for obsidian sync
logger = logging.getLogger(__name__)

# คะแนนความคล้ายขั้นต่ำที่จะถือว่าโน้ต "เกี่ยวข้อง" พอจะยัดเข้า context/อ้างอิง
# วัดจาก prod 2026-08-02: คำถามที่ไม่เกี่ยวกับ vault ทำได้ ≤0.40 · ที่ตรงจริง 0.72-0.74
_VAULT_MIN_SCORE = float(os.getenv("VAULT_MIN_SCORE", "0.5"))

VAULT_PATH = os.getenv("OBSIDIAN_VAULT_PATH", "")
COLLECTION_NAME = "obsidian_notes"


def _get_collection():
    from utils.memory import _get_client, get_or_create_collection
    client = _get_client()
    if client is None:
        return None
    try:
        return get_or_create_collection(client, COLLECTION_NAME)
    except Exception as e:
        logger.warning(f"obsidian_sync: failed to get or create ChromaDB collection '{COLLECTION_NAME}': {e}")
        return None


def _parse_md(path: Path) -> dict:
    """Parse a markdown file: extract title, body, wiki-links."""
    text = path.read_text(encoding="utf-8", errors="ignore")

    frontmatter = {}
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            body = parts[2].strip()
            for line in parts[1].splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    frontmatter[k.strip()] = v.strip()

    wiki_links = re.findall(r"\[\[([^\]|#]+)", body)
    clean_links = [l.strip() for l in wiki_links]

    title = frontmatter.get("title") or path.stem
    return {
        "title": title,
        "body": body[:8000],
        "links": clean_links,
        "tags": frontmatter.get("tags", ""),
        "path": str(path),
    }


def _doc_id(path: Path) -> str:
    return hashlib.md5(str(path).encode()).hexdigest()


def sync_vault(vault_path: str = "") -> dict:
    """Sync all .md files in vault into ChromaDB. Returns stats."""
    vp = vault_path or VAULT_PATH
    if not vp or not os.path.isdir(vp):
        logger.error(f"Vault sync failed: Path not found: {vp}")
        return {"ok": False, "error": f"Vault path not found: {vp}"}

    col = _get_collection()
    if col is None:
        logger.error("Vault sync failed: ChromaDB not available")
        return {"ok": False, "error": "ChromaDB not available"}

    md_files = list(Path(vp).rglob("*.md"))
    added = 0
    skipped = 0

    for fp in md_files:
        if any(part.startswith(".") for part in fp.parts):
            continue
        try:
            info = _parse_md(fp)
            doc_id = _doc_id(fp)
            mtime = str(fp.stat().st_mtime)

            existing = col.get(ids=[doc_id])
            if existing["metadatas"] and existing["metadatas"][0].get("mtime") == mtime:
                skipped += 1
                continue

            combined = f"# {info['title']}\n\n{info['body']}"
            col.upsert(
                ids=[doc_id],
                documents=[combined],
                metadatas=[{
                    "title": info["title"],
                    "path": info["path"],
                    "links": ", ".join(info["links"][:20]),
                    "tags": info["tags"],
                    "mtime": mtime,
                }],
            )
            added += 1
        except Exception as e:
            logger.error(f"Vault sync error for {fp}: {str(e)}")
            skipped += 1

    logger.info(f"Vault sync complete: {added} added, {skipped} skipped out of {len(md_files)} total")
    return {"ok": True, "total": len(md_files), "synced": added, "skipped": skipped}


def search_vault(query: str, n: int = 5, min_score: float | None = None) -> list[dict]:
    """Search obsidian notes by semantic similarity (กรองด้วยเกณฑ์ความเกี่ยวข้อง)

    ⚠️ เดิมทิ้ง `distances` ทั้งดุ้นแล้วคืน top-N เสมอ → คำถามที่ไม่เกี่ยวกับ vault
    เลยก็ได้โน้ต 3 อันติดมาทุกครั้ง ถูกยัดเข้า context + โชว์เป็น citation
    (เห็นกับตาบน prod 2026-08-02: ถามราคาน้ำมัน แล้วอ้างโน้ตส่วนตัวที่ไม่เกี่ยวข้อง
    = ชื่อโน้ตส่วนตัวรั่วออกมาในคำถามที่ไม่เกี่ยวเลย)

    เกณฑ์วัดจาก prod จริง: คำถามไม่เกี่ยว ≤0.40 · โน้ตที่ตรงจริง 0.72-0.74
    """
    col = _get_collection()
    if col is None:
        logger.warning("Vault search failed: ChromaDB not available")
        return []
    threshold = _VAULT_MIN_SCORE if min_score is None else min_score
    try:
        results = col.query(query_texts=[query], n_results=min(n, col.count()))
        docs  = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        dists = results.get("distances", [[]])[0]
        out = []
        for doc, meta, dist in zip(docs, metas, dists):
            score = round(1 - float(dist), 4)
            if score < threshold:
                continue
            meta = meta or {}
            out.append({"title": meta.get("title", ""), "content": doc,
                        "path": meta.get("path", ""), "score": score})
        logger.info(f"Vault search: {len(out)}/{len(docs)} ผ่านเกณฑ์ {threshold} — query: {query[:50]}")
        return out
    except Exception as e:
        logger.error(f"Vault search error: {str(e)}")
        return []


def get_vault_stats() -> dict:
    """Return number of indexed notes."""
    col = _get_collection()
    if col is None:
        return {"indexed": 0, "available": False}
    try:
        return {"indexed": col.count(), "available": True}
    except Exception as e:
        logger.warning(f"get_vault_stats: failed to get collection count: {e}")
        return {"indexed": 0, "available": False}
