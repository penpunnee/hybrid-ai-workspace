from fastapi import APIRouter, Request
from utils.obsidian_sync import sync_vault, search_vault, get_vault_stats

router = APIRouter(prefix="/api/vault", tags=["vault"])


@router.get("/stats")
def vault_stats():
    return get_vault_stats()


@router.post("/sync")
async def vault_sync(request: Request):
    data = await request.json()
    vault_path = data.get("vault_path", "")
    return sync_vault(vault_path)


@router.get("/search")
def vault_search(q: str, n: int = 5):
    return {"results": search_vault(q, n)}
