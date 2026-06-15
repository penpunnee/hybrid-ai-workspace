import os
import json
import shutil
from datetime import datetime, date, timedelta
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from core.config import GEMINI_API_KEY, DB_PATH, NAS_DATA_PATH, LMSTUDIO_BASE_URL
from core.scheduler import scheduler
from assistants.config import ASSISTANTS
from utils.llm import OLLAMA_MODEL, GEMINI_MODEL, check_ollama_health, check_lmstudio_health, _last_failover, stream_response
from utils.memory import is_memory_available, get_memory_stats
from utils.skills import get_skill_count
from utils.dream import get_latest_report
from utils.tts import generate_tts, VOICE_MAP
from utils.history import search_messages

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/cache/stats")
def cache_stats():
    """รายงาน hit/size ของ cache layers ทั้งหมด — Phase E"""
    out = {}
    try:
        from utils.embed import cache_stats as _e
        out["embed"] = _e()
    except Exception as e:
        out["embed"] = {"error": str(e)}
    try:
        from utils.retrieval_cache import stats as _r
        out["retrieval"] = _r()
    except Exception as e:
        out["retrieval"] = {"error": str(e)}
    try:
        from utils.response_cache import stats as _rs
        out["response"] = _rs()
    except Exception as e:
        out["response"] = {"error": str(e)}
    return out


@router.get("/routing/preview")
def routing_preview(q: str):
    """ดูว่าคำถามนี้จะถูก route ไป model ไหน"""
    try:
        from reasoning.router import route
        from reasoning.classifier import classify_label
        decision = route(q, provider_hint="auto")
        return {
            "query": q,
            "complexity": classify_label(q),
            "provider": decision.provider,
            "model": decision.model,
            "reason": decision.reason,
        }
    except Exception as e:
        return {"error": str(e)}


@router.get("/config")
def get_config():
    import os
    from core.config import LMSTUDIO_BASE_URL, LMSTUDIO_CHAT_MODEL
    active_local_model = LMSTUDIO_CHAT_MODEL if LMSTUDIO_BASE_URL else OLLAMA_MODEL
    return {
        "assistants": [
            {"name": name, "slug": cfg["slug"], "templates": cfg.get("prompt_templates", [])}
            for name, cfg in ASSISTANTS.items()
        ],
        "ollama_model": active_local_model,
        "gemini_model": GEMINI_MODEL,
        "has_anthropic": bool(os.getenv("ANTHROPIC_API_KEY", "").strip()),
        "has_vault": bool(os.getenv("OBSIDIAN_VAULT_PATH", "").strip()),
    }


# curated cloud models สำหรับ dropdown — เลือกตัวไหน provider วิ่งตามตัวนั้น
# (id ยืนยันจาก docs ทางการ 2026-06-15) · available คำนวณตอน request ตามว่ามี key ไหม
_CLOUD_MODELS = [
    {"provider": "gemini", "model": "gemini-3.5-flash",       "label": "Gemini 3.5 Flash"},
    {"provider": "gemini", "model": "gemini-3-flash-preview", "label": "Gemini 3 Flash"},
    {"provider": "gemini", "model": "gemini-3.1-flash-lite",  "label": "Gemini 3.1 Flash Lite"},
    {"provider": "gemini", "model": "gemini-2.5-flash",       "label": "Gemini 2.5 Flash"},
    {"provider": "gemini", "model": "gemma-4-31b-it",         "label": "Gemma 4 31B"},
    {"provider": "claude", "model": "claude-opus-4-8",        "label": "Claude Opus 4.8"},
    {"provider": "claude", "model": "claude-sonnet-4-6",      "label": "Claude Sonnet 4.6"},
    {"provider": "claude", "model": "claude-haiku-4-5",       "label": "Claude Haiku 4.5"},
    {"provider": "kimi",   "model": "kimi-k2.6",              "label": "Kimi K2.6"},
]


@router.get("/models")
def list_models():
    """รายชื่อโมเดลให้ dropdown — local (LM Studio/Ollama dynamic) + cloud (curated).
    แต่ละ item: {provider, model, label, available}. available=False = ยังไม่มี key/ต่อไม่ได้
    (โชว์ใน list แต่ disable เลือก)"""
    from utils.llm import GEMINI_API_KEY, ANTHROPIC_API_KEY, MOONSHOT_API_KEY
    from core.config import LMSTUDIO_BASE_URL, LMSTUDIO_CHAT_MODEL

    # local: โชว์โมเดลแชท local ตัวที่ใช้งานจริง "ตัวเดียว" (active chat model จาก .env)
    # — LM Studio โหลด reason/vision/embedding ไว้ใช้ภายใน ไม่ต้องโผล่ใน picker
    #   (สถานะ online ดูที่ status dot / local_ok ไม่ใช่ที่นี่)
    active_local = LMSTUDIO_CHAT_MODEL if LMSTUDIO_BASE_URL else OLLAMA_MODEL
    prov = "lmstudio" if LMSTUDIO_BASE_URL else "ollama"
    local = ([{"provider": prov, "model": active_local, "label": active_local, "available": True}]
             if active_local else [])

    # cloud: curated + available ตาม key
    key_for = {"gemini": bool(GEMINI_API_KEY), "claude": bool(ANTHROPIC_API_KEY),
               "kimi": bool(MOONSHOT_API_KEY)}
    cloud = [{**m, "available": key_for.get(m["provider"], False)} for m in _CLOUD_MODELS]

    return {"local": local, "cloud": cloud}


@router.get("/status")
def status():
    from concurrent.futures import ThreadPoolExecutor
    import logging
    logger = logging.getLogger(__name__)
    with ThreadPoolExecutor(max_workers=3) as ex:
        f1 = ex.submit(check_ollama_health)
        f2 = ex.submit(is_memory_available)
        f3 = ex.submit(check_lmstudio_health)
        try:
            ollama_ok, ollama_msg = f1.result(timeout=5)
        except Exception as e:
            ollama_ok, ollama_msg = False, "Health check error"
            logger.warning(f"Ollama health check failed: {e}")
        try:
            mem_ok = f2.result(timeout=5)
        except Exception as e:
            mem_ok = False
            logger.warning(f"Memory check failed: {e}")
        try:
            lmstudio_ok, lmstudio_msg = f3.result(timeout=5)
        except Exception as e:
            lmstudio_ok, lmstudio_msg = False, "Health check error"
            logger.warning(f"LM Studio health check failed: {e}")
    next_dream = None
    job = scheduler.get_job("dream_nightly")
    if job and job.next_run_time:
        next_dream = job.next_run_time.strftime("%Y-%m-%d %H:%M")
    # local หลัก = LM Studio (DeepSeek R1) ถ้าตั้ง LMSTUDIO_BASE_URL, ไม่งั้น Ollama
    local_provider = "lmstudio" if LMSTUDIO_BASE_URL else "ollama"
    return {
        "ollama": ollama_ok,
        "ollama_message": ollama_msg,
        "lmstudio": lmstudio_ok,
        "lmstudio_message": lmstudio_msg,
        "local_provider": local_provider,
        "local_ok": lmstudio_ok if local_provider == "lmstudio" else ollama_ok,
        "gemini": bool(GEMINI_API_KEY),
        "memory": mem_ok,
        "skills": get_skill_count(),
        "failover_active": _last_failover.get("active", False),
        "next_dream_schedule": next_dream,
    }


@router.get("/health")
def health_detail():
    import logging
    logger = logging.getLogger(__name__)
    try:
        data_path = NAS_DATA_PATH
        usage = shutil.disk_usage(data_path if os.path.exists(data_path) else ".")
        disk = {
            "total_gb": round(usage.total / 1e9, 1),
            "used_gb": round(usage.used / 1e9, 1),
            "free_gb": round(usage.free / 1e9, 1),
            "used_pct": round(usage.used / usage.total * 100, 1),
        }
    except Exception as e:
        disk = {"error": str(e)}

    try:
        mem = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                mem[k.strip()] = int(v.strip().split()[0])
        total_mb = mem["MemTotal"] // 1024
        avail_mb = mem["MemAvailable"] // 1024
        used_mb = total_mb - avail_mb
        ram = {"total_mb": total_mb, "used_mb": used_mb, "free_mb": avail_mb,
               "used_pct": round(used_mb / total_mb * 100, 1)}
    except Exception as e:
        ram = {"error": str(e)}

    try:
        report = get_latest_report()
        last_dream = {
            "started_at": report.get("started_at", ""),
            "provider": report.get("provider", ""),
            "memories_processed": report.get("memories_processed", 0),
            "promoted": len(report.get("phase3_deep", {}).get("promoted", [])),
        } if "error" not in report else {"error": report["error"]}
    except Exception as e:
        last_dream = {"error": str(e)}

    next_dream = None
    job = scheduler.get_job("dream_nightly")
    if job and job.next_run_time:
        next_dream = job.next_run_time.strftime("%Y-%m-%d %H:%M")

    try:
        chroma = get_memory_stats()
    except Exception as e:
        chroma = {"available": False, "error": str(e)}

    try:
        db_size_mb = round(os.path.getsize(DB_PATH) / 1e6, 2) if os.path.exists(DB_PATH) else 0
    except Exception:
        db_size_mb = 0

    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "disk": disk, "ram": ram,
        "dream": {"last": last_dream, "next_scheduled": next_dream},
        "chromadb": chroma,
        "skills_count": get_skill_count(),
        "db_size_mb": db_size_mb,
    }


@router.get("/search")
def search_chat(q: str = "", assistant: str = "", limit: int = 20):
    if not q or len(q) < 2:
        return {"results": [], "query": q}
    results = search_messages(query=q, assistant=assistant, limit=limit)
    return {"results": results, "query": q, "count": len(results)}


@router.get("/stats")
def usage_stats():
    import sqlite3
    result = {"total_messages": 0, "today_messages": 0, "total_sessions": 0,
              "by_assistant": {}, "sessions_by_assistant": {}, "memory": {}}
    if os.path.exists(DB_PATH):
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM messages")
        result["total_messages"] = cur.fetchone()[0]
        today = date.today().isoformat()
        cur.execute("SELECT COUNT(*) FROM messages WHERE created_at >= ?", (today,))
        result["today_messages"] = cur.fetchone()[0]
        cur.execute("SELECT COUNT(DISTINCT session_id) FROM messages")
        result["total_sessions"] = cur.fetchone()[0]
        cur.execute("SELECT assistant, COUNT(*) FROM messages GROUP BY assistant")
        result["by_assistant"] = {r[0]: r[1] for r in cur.fetchall()}
        cur.execute("SELECT assistant, COUNT(DISTINCT session_id) FROM messages GROUP BY assistant")
        result["sessions_by_assistant"] = {r[0]: r[1] for r in cur.fetchall()}
        conn.close()
    result["memory"] = get_memory_stats()
    return result


@router.get("/digest")
def daily_digest():
    import sqlite3 as _sql
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    today = date.today().isoformat()
    if not os.path.exists(DB_PATH):
        return {"ok": False, "message": "ยังไม่มีข้อมูล"}
    conn = _sql.connect(DB_PATH)
    rows = conn.execute(
        "SELECT assistant, role, content FROM messages WHERE created_at >= ? AND created_at < ? ORDER BY id ASC LIMIT 80",
        (yesterday, today)
    ).fetchall()
    conn.close()
    if not rows:
        return {"ok": False, "message": "ไม่มีแชทเมื่อวาน"}
    chat_text = "\n".join([f"[{r[0]}] {r[1]}: {r[2][:150]}" for r in rows])
    msgs = [
        {"role": "system", "content": "สรุปการสนทนาเป็นภาษาไทย ใช้ bullet points ไม่เกิน 5 ข้อ กระชับมีประโยชน์"},
        {"role": "user", "content": f"สนทนา {yesterday}:\n{chat_text[:2500]}"},
    ]
    try:
        summary = "".join(stream_response(msgs, provider="gemini"))
    except Exception as e:
        summary = f"(สรุปไม่ได้: {e})"
    return {"ok": True, "date": yesterday, "summary": summary, "count": len(rows)}


@router.post("/tts")
async def text_to_speech(request: Request):
    data = await request.json()
    text = data.get("text", "").strip()
    slug = data.get("assistant_slug", "")
    if not text:
        return {"error": "no text"}
    try:
        wav = generate_tts(text, slug)
        return Response(content=wav, media_type="audio/wav", headers={"Cache-Control": "no-cache"})
    except Exception as e:
        return {"error": str(e)}


@router.post("/tts/stream")
async def text_to_speech_stream(request: Request):
    import re, base64
    data = await request.json()
    text = data.get("text", "").strip()
    slug = data.get("assistant_slug", "")
    if not text:
        return {"error": "no text"}
    sentences = [s.strip() for s in re.split(r"(?<=[.!?…\n])\s+", text) if s.strip()] or [text]

    async def event_gen():
        for sentence in sentences:
            if not sentence:
                continue
            try:
                wav = generate_tts(sentence, slug)
                b64 = base64.b64encode(wav).decode()
                yield f"data: {json.dumps({'chunk': b64, 'done': False})}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e), 'done': False})}\n\n"
        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/admin/unlock")
async def admin_unlock(request: Request):
    """ล้าง auth-fail lockout — LAN/loopback เท่านั้น (ไม่ผ่าน Cloudflare)"""
    from core.auth import is_local_request
    from core.ratelimit import unlock_ip, client_key
    if not is_local_request(request):
        return JSONResponse({"error": "forbidden — LAN only"}, status_code=403)
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    ip = body.get("ip") or client_key(request)
    unlock_ip(ip)
    return {"unlocked": ip}
