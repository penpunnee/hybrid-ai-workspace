from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool
from utils.obsidian_sync import sync_vault, search_vault, get_vault_stats

router = APIRouter(prefix="/api/vault", tags=["vault"])


@router.get("/stats")
def vault_stats():
    return get_vault_stats()


@router.post("/sync")
async def vault_sync(request: Request):
    """Sync vault → ChromaDB · path มาจาก `OBSIDIAN_VAULT_PATH` เท่านั้น

    เดิมรับ `vault_path` จาก body แล้วส่งต่อตรงๆ → ชี้ไปโฟลเดอร์ไหนก็ได้ในคอนเทนเนอร์
    แล้วดูด .md เข้า index ที่ระบบใช้ตอบคำถาม (อ่านกลับได้ทาง `/api/vault/search`)
    ผู้เรียกจริงมีที่เดียวและส่ง body ว่างอยู่แล้ว (`app.tsx` → `JSON.stringify({})`)
    """
    return await run_in_threadpool(sync_vault)


@router.get("/search")
def vault_search(q: str, n: int = 5):
    return {"results": search_vault(q, n)}
