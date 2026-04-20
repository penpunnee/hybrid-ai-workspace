import os
import re
import hashlib
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

VAULT_PATH = os.getenv("OBSIDIAN_VAULT_PATH", "")
COLLECTION_NAME = "obsidian_notes"


def _get_collection():
    from utils.memory import _get_client
    client = _get_client()
    if client is None:
        return None
    try:
        return client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
    except Exception:
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
        return {"ok": False, "error": f"Vault path not found: {vp}"}

    col = _get_collection()
    if col is None:
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
        except Exception:
            skipped += 1

    return {"ok": True, "total": len(md_files), "synced": added, "skipped": skipped}


def search_vault(query: str, n: int = 5) -> list[dict]:
    """Search obsidian notes by semantic similarity."""
    col = _get_collection()
    if col is None:
        return []
    try:
        results = col.query(query_texts=[query], n_results=min(n, col.count()))
        out = []
        for i, doc in enumerate(results["documents"][0]):
            meta = results["metadatas"][0][i]
            out.append({"title": meta.get("title", ""), "content": doc, "path": meta.get("path", "")})
        return out
    except Exception:
        return []


def get_vault_stats() -> dict:
    """Return number of indexed notes."""
    col = _get_collection()
    if col is None:
        return {"indexed": 0, "available": False}
    try:
        return {"indexed": col.count(), "available": True}
    except Exception:
        return {"indexed": 0, "available": False}
