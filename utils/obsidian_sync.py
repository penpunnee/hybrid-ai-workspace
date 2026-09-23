import os
import re
import hashlib
import socket
import threading
import logging
from pathlib import Path
from urllib.parse import urlsplit
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


# ── embedder ต่อไม่ได้ต้องจบเร็ว (2026-09-23) ──────────────────────────────────
# log prod: error ห่าง ~60 วิเป๊ะต่อไฟล์ ⇒ 22 ไฟล์ = 22 นาที · ต้นเหตุ: OllamaEmbeddingFunction
# ของ chromadb ตั้ง timeout=60 และ PC ที่เพิ่งปิด ARP ยังค้าง ⇒ SYN หายเงียบจนครบ timeout
# ⚠️ ไม่ลด timeout ของ EF ทั้งระบบ — EF ตัวนี้ใช้ร่วมทุก collection
_PREFLIGHT_TIMEOUT = 2.0
_MAX_CONSECUTIVE_CONN_FAILS = 2   # ครั้งเดียวแล้วหาย = ไปต่อ (tests/test_vault_sync_errors.py)


def _tcp_reachable(host: str, port: int, timeout: float) -> bool:
    try:
        socket.create_connection((host, port), timeout=timeout).close()
        return True
    except OSError:
        return False


def _embedder_endpoint(col) -> tuple[str, int] | None:
    """host/port ของ embedder ที่ collection นี้ใช้จริง — ไม่รู้ = None (ไม่บล็อก)"""
    url = getattr(getattr(col, "_embedding_function", None), "url", None)
    if not isinstance(url, str) or not url:
        return None
    parts = urlsplit(url)
    if not parts.hostname:
        return None
    return parts.hostname, parts.port or (443 if parts.scheme == "https" else 80)


def _is_conn_failure(e: Exception) -> bool:
    """ต่อ embedder ไม่ได้ (ไม่ใช่ไฟล์เสียเป็นรายไฟล์) — ของจริงคือ httpx.ConnectTimeout
    ที่ chromadb เติมข้อความเป็น "timed out in upsert." · ollama client โยน ConnectionError"""
    if isinstance(e, (TimeoutError, ConnectionError)):
        return True
    try:
        import httpx
        if isinstance(e, (httpx.TimeoutException, httpx.NetworkError)):
            return True
    except ImportError:
        pass
    msg = str(e).lower()
    return "timed out" in msg or "failed to connect" in msg


# ── กัน sync ซ้อนกัน (2026-09-23) ─────────────────────────────────────────────
# log prod: 2 รอบซ้อนกันจริง (เริ่ม 04:30:45 และ 04:37:52) · ความเสียหาย: รอบแรกสแกน
# รายชื่อไฟล์ตอนเริ่ม ⇒ prune ของมันลบโน้ตใหม่ที่รอบที่สองเพิ่ง sync (มีเทสจำลอง)
# · uvicorn process เดียว (ตรวจ /proc) ⇒ threading.Lock พอ
# · **รอคิว ไม่ปฏิเสธ** — ผู้เรียกทาง curl หลัง push vault ต้องได้การแก้ของตัวเองเข้า index
# · เพดาน 180 วิ: รอบยาวสุดตอนนี้ ≈ breaker 2×60 วิ (embedder ต่อติดแต่ค้าง)
_sync_lock = threading.Lock()
_SYNC_WAIT_TIMEOUT = 180.0

# "ค้าง" = sync ล่าสุดถูกหยุด/มี errors ⇒ job อัตโนมัติจะลองใหม่เมื่อ embedder กลับมา
# เริ่มเป็น True ทุกครั้งที่แอปเริ่ม — จับของที่เปลี่ยนตอนแอปดับ/ถูก restart ระหว่าง PC ปิด
_catchup_pending = True


def sync_vault(vault_path: str = "", wait_timeout: float | None = None) -> dict:
    """Sync all .md files in vault into ChromaDB. Returns stats. (ทีละรอบ — ดู _sync_lock)

    `wait_timeout` = รอคิวได้นานเท่าไร (None = `_SYNC_WAIT_TIMEOUT` · 0 = ไม่รอ)
    """
    global _catchup_pending
    wait = _SYNC_WAIT_TIMEOUT if wait_timeout is None else wait_timeout
    acquired = (_sync_lock.acquire(timeout=wait) if wait > 0
                else _sync_lock.acquire(blocking=False))
    if not acquired:
        # รอจริงแล้วไม่ได้ = ผิดปกติ (WARNING) · ไม่รอ (job อัตโนมัติ) = ข้ามตามปกติ (INFO)
        (logger.warning if wait > 0 else logger.info)(
            f"Vault sync: มีอีกรอบกำลังทำงาน (รอ {wait:.0f} วิ แล้วไม่ว่าง)")
        return {"ok": False, "busy": True,
                "error": f"มีอีกรอบกำลัง sync อยู่ (รอเกิน {wait:.0f} วิ) — ลองใหม่ภายหลัง"}
    try:
        res = _sync_vault_unlocked(vault_path)
    finally:
        _sync_lock.release()
    _catchup_pending = bool(res.get("halted") or res.get("errors"))
    return res


_CATCHUP_INTERVAL_MIN = 5


def catchup_sync_if_pending() -> dict | None:
    """job ของ scheduler — sync ใหม่เมื่อรอบล่าสุดค้าง และ embedder ต่อได้แล้ว

    ไม่รอคิว (มีรอบอื่นรันอยู่ = ข้าม) · PC ยังปิด = ข้าม**เงียบ** (DEBUG) เพราะ job ยิงทุก
    5 นาทีทั้งคืน · embedder ต่อได้แล้วแต่ยังมี error = **เลิกลองอัตโนมัติ** กันวนไม่จบ
    (ของจริง 103 errors ที่เคยเกิดเป็นเรื่องต่อไม่ติดทั้งหมด แต่ไฟล์ล้มถาวรเป็นไปได้)
    """
    global _catchup_pending
    if not _catchup_pending:
        return None
    col = _get_collection()
    if col is None:
        logger.debug("Vault catch-up: ChromaDB ไม่พร้อม — ข้าม")
        return None
    ep = _embedder_endpoint(col)
    if ep and not _tcp_reachable(ep[0], ep[1], _PREFLIGHT_TIMEOUT):
        logger.debug(f"Vault catch-up: embedder {ep[0]}:{ep[1]} ยังต่อไม่ได้ — รอรอบหน้า")
        return None
    res = sync_vault(wait_timeout=0)
    if res.get("busy"):
        return res
    if res.get("halted"):
        logger.info(f"Vault catch-up: embedder หลุดอีกระหว่าง sync — ลองรอบหน้า ({res['halted']})")
    elif res.get("errors"):
        _catchup_pending = False
        logger.warning(f"Vault catch-up: embedder ต่อได้แต่ยังมี error {res['errors']} ไฟล์ — "
                       "เลิกลองอัตโนมัติ ให้กด sync เองหลังตรวจ log")
    else:
        logger.info(f"Vault catch-up: sync สำเร็จ (synced={res.get('synced')}, "
                    f"skipped={res.get('skipped')})")
    return res


def _sync_vault_unlocked(vault_path: str = "") -> dict:
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
    errors = 0
    # id ของไฟล์ที่ "ยังอยู่จริง" ณ รอบนี้ — ใช้เทียบตอน prune ท้ายฟังก์ชัน
    # เก็บทุกไฟล์ที่สแกนเจอ **รวมตัวที่ error ด้วย** เพราะไฟล์ยังอยู่ แค่ embed ไม่ผ่าน
    # (ลบตัวที่ embed ล้ม = Ollama ดับหนึ่งรอบแล้ว index หายทั้ง vault)
    seen: set[str] = set()
    # หยุด upsert แล้ว (embedder ต่อไม่ได้) — ยังเดินลูปต่อแบบอ่านอย่างเดียว เพื่อให้
    # `errors` = ไฟล์ที่ต้อง sync แต่ไม่สำเร็จ และ `seen` ครบ (prune ไม่ลบของที่ยังไม่ได้ตรวจ)
    halted = ""
    preflight_done = False
    conn_fails = 0

    for fp in md_files:
        if any(part.startswith(".") for part in fp.parts):
            continue
        seen.add(_doc_id(fp))
        try:
            info = _parse_md(fp)
            doc_id = _doc_id(fp)
            mtime = str(fp.stat().st_mtime)

            existing = col.get(ids=[doc_id])
            if existing["metadatas"] and existing["metadatas"][0].get("mtime") == mtime:
                skipped += 1
                continue

            if halted:
                errors += 1
                continue
            if not preflight_done:
                preflight_done = True
                ep = _embedder_endpoint(col)
                if ep and not _tcp_reachable(ep[0], ep[1], _PREFLIGHT_TIMEOUT):
                    halted = f"ต่อ embedder ไม่ได้ ({ep[0]}:{ep[1]})"
                    logger.error(f"Vault sync: {halted} — ไม่ upsert รอบนี้")
                    errors += 1
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
            conn_fails = 0
        except Exception as e:
            # error ≠ skip: 2026-08-12 upsert ที่ timeout (Ollama ตาย) เคยถูกนับเป็น skip
            # ทำให้รายงาน ok:true ทั้งที่ sync ล้มทั้งหมด — ผู้เรียกต้องแยกสองอย่างนี้ออกได้
            logger.error(f"Vault sync error for {fp}: {str(e)}")
            errors += 1
            if _is_conn_failure(e):
                conn_fails += 1
                if conn_fails >= _MAX_CONSECUTIVE_CONN_FAILS and not halted:
                    halted = f"ต่อ embedder ไม่ได้ {conn_fails} ครั้งติด ({e})"
                    logger.error(f"Vault sync: {halted} — หยุด upsert ไฟล์ที่เหลือ")
            else:
                conn_fails = 0

    # ── prune: ลบเอกสารของไฟล์ที่หายไปจาก vault ────────────────────────────
    # 🔴 บั๊กจริง 2026-08-23: เดิม sync เป็น add/update อย่างเดียว ⇒ ลบหน้าใน vault แล้ว
    # เอกสารเก่าค้างใน ChromaDB และ **ชนะอันดับ 1 ในการค้น** (หน้าที่ลบได้ระยะ 0.276
    # หน้าจริง 0.372) = ตอบคำถามจากเนื้อหาที่เจ้าของตั้งใจลบทิ้ง
    # · ตัวชี้วัดโกหกด้วย: คืน ok:true errors:0 ทั้งที่ index 88 แต่ไฟล์จริง 87
    removed = 0
    prune_error = ""
    if seen:
        try:
            # `.get("ids") or []` ไม่ใช่ `["ids"]` — collection บางตัว (และ mock ในเทส)
            # ไม่คืนคีย์นี้เมื่อยังว่าง · KeyError ที่นี่ = prune ล้มทั้งที่ sync ปกติ
            all_ids = (col.get() or {}).get("ids") or []
            stale = [i for i in all_ids if i not in seen]
            if stale:
                col.delete(ids=stale)
                removed = len(stale)
                logger.info(f"Vault sync: prune {removed} เอกสารที่ไม่มีไฟล์แล้ว")
        except Exception as e:
            # 🔴 **ห้ามบวกเข้า `errors`** — คีย์นั้นมีสัญญาว่า "จำนวนไฟล์ที่ upsert ล้ม"
            # ตรึงไว้ด้วย tests/test_vault_sync_errors.py (บั๊ก 2026-08-12 ที่ skip โกหก)
            # เอา prune ไปปน = ตัวเลขคนละความหมายมารวมกัน = ตัวชี้วัดโกหกรอบใหม่
            logger.error(f"Vault sync prune failed: {e}")
            prune_error = str(e)
    elif md_files:
        # สแกนเจอไฟล์แต่ถูกกรองทิ้งหมด (ทุกตัวอยู่ใต้โฟลเดอร์ที่ขึ้นต้นด้วยจุด)
        logger.warning("Vault sync: ไม่มีไฟล์ที่ไม่ถูกซ่อนเลย ข้าม prune")
    else:
        # 🔴 vault ว่างเปล่า = แยกไม่ออกว่า "ลบหมดจริง" หรือ "mount หลุด"
        # ⇒ เลือกฝั่งที่กู้คืนได้: ปล่อยค้างไว้ (ลบทีหลังได้) ดีกว่าล้างแล้วต้อง
        # re-embed ทั้ง vault ตอน Ollama อาจไม่ว่าง
        logger.warning(f"Vault sync: ไม่พบไฟล์ .md เลยใน {vp} — ข้าม prune กันกรณี mount หลุด")

    logger.info(f"Vault sync complete: {added} added, {skipped} skipped, {removed} removed, {errors} errors out of {len(md_files)} total")
    out = {"ok": errors == 0, "total": len(md_files), "synced": added,
           "skipped": skipped, "removed": removed, "errors": errors}
    if prune_error:
        out["prune_error"] = prune_error
    if halted:
        out["halted"] = halted
        out["error"] = f"หยุด sync: {halted} — ไม่สำเร็จ {errors}/{len(md_files)} ไฟล์ (เปิด PC แล้วกด sync ใหม่)"
    elif errors:
        out["error"] = f"sync ไม่สำเร็จ {errors}/{len(md_files)} ไฟล์ (ดู log)"
    return out


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
