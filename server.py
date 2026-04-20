import os, uuid, json, threading
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request, UploadFile, File
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from assistants.config import ASSISTANTS
from utils.llm import stream_response, OLLAMA_MODEL, GEMINI_MODEL, check_ollama_health
from utils.rag import inject_context_to_system
from utils.history import save_message, load_history, get_sessions, clear_session, export_history_md
from utils.memory import save_memory, search_memory, is_memory_available, save_lesson, save_preference, get_lessons, get_preferences
from utils.skills import get_all_skills, get_skill_count

app = FastAPI(title="Hybrid AI Workspace")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
if os.path.exists("static/assets"):
    app.mount("/assets", StaticFiles(directory="static/assets"), name="assets")


@app.get("/", response_class=HTMLResponse)
async def root():
    with open("static/index.html", encoding="utf-8") as f:
        return f.read()


@app.get("/api/config")
def get_config():
    return {
        "assistants": [
            {
                "name": name,
                "slug": cfg["slug"],
                "templates": cfg.get("prompt_templates", []),
            }
            for name, cfg in ASSISTANTS.items()
        ],
        "ollama_model": OLLAMA_MODEL,
        "gemini_model": GEMINI_MODEL,
    }


@app.get("/api/status")
def status():
    ollama_ok, _ = check_ollama_health()
    return {
        "ollama": ollama_ok,
        "gemini": bool(os.getenv("GEMINI_API_KEY", "")),
        "memory": is_memory_available(),
        "skills": get_skill_count(),
    }


@app.get("/api/sessions/{assistant}")
def list_sessions(assistant: str):
    return get_sessions(assistant)


@app.post("/api/sessions/{assistant}")
def new_session(assistant: str):
    sid = f"s_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    return {"session_id": sid}


@app.delete("/api/sessions/{assistant}/{session_id}")
def delete_session(assistant: str, session_id: str):
    clear_session(assistant, session_id)
    return {"ok": True}


@app.get("/api/history/{assistant}/{session_id}")
def get_history(assistant: str, session_id: str):
    return load_history(assistant, session_id)


@app.get("/api/export/{assistant}/{session_id}")
def export_session(assistant: str, session_id: str):
    md = export_history_md(assistant, session_id)
    return {"markdown": md}


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    content = await file.read()
    name = file.filename or "file"
    try:
        if name.lower().endswith(".json"):
            import json as _json
            data = _json.loads(content)
            text = f"[ไฟล์ JSON: {name}]\n{_json.dumps(data, ensure_ascii=False, indent=2)}"
        else:
            text = f"[ไฟล์: {name}]\n{content.decode('utf-8', errors='ignore')}"
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "filename": name, "text": text[:8000]}


@app.post("/api/memory/{assistant}")
async def save_mem(assistant: str, request: Request):
    data = await request.json()
    text = data.get("text", "")
    save_memory(assistant, "remember", f"ข้อมูลที่บันทึก: {text}")
    save_lesson("ข้อมูลจากพี่ปอย", text)
    return {"ok": True, "saved": text}


@app.post("/api/chat")
async def chat(request: Request):
    data = await request.json()
    assistant = data.get("assistant", list(ASSISTANTS.keys())[0])
    session_id = data.get("session_id", "default")
    prompt = data.get("prompt", "")
    provider = data.get("provider", "ollama")

    config = ASSISTANTS.get(assistant, list(ASSISTANTS.values())[0])
    base_prompt = config["system_prompt"]

    lessons = get_lessons(prompt)
    prefs = get_preferences()
    full_context = "\n\n".join(filter(None, [
        search_memory(assistant, prompt),
        get_all_skills(),
        f"[บทเรียนสะสม]\n{lessons}" if lessons else "",
        f"[ความชอบ]\n{prefs}" if prefs else "",
    ]))
    system_prompt = inject_context_to_system(base_prompt, full_context)

    history = load_history(assistant, session_id)
    save_message(assistant, "user", prompt, provider, session_id)

    messages = [{"role": "system", "content": system_prompt}]
    messages += [{"role": m["role"], "content": m["content"]} for m in history]
    messages.append({"role": "user", "content": prompt})

    def generate():
        full_response = ""
        try:
            for chunk in stream_response(messages, provider=provider):
                full_response += chunk
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            return

        save_message(assistant, "assistant", full_response, provider, session_id)
        save_memory(assistant, prompt, full_response)

        if len(full_response) > 100:
            def _learn(p=prompt, r=full_response, pv=provider):
                try:
                    msgs = [
                        {"role": "system", "content": "สรุปบทเรียนเป็นภาษาไทย 1-2 ประโยค ถ้าไม่มีตอบว่า SKIP"},
                        {"role": "user", "content": f"คำถาม: {p}\nคำตอบ: {r[:500]}"},
                    ]
                    lesson = "".join(stream_response(msgs, provider=pv)).strip()
                    if lesson and lesson != "SKIP" and len(lesson) > 10:
                        save_lesson(p[:50], lesson)
                    for kw, (k, v) in {"ตอบสั้น": ("style", "ชอบสั้น"), "อธิบาย": ("style", "ชอบละเอียด")}.items():
                        if kw in p:
                            save_preference(k, v)
                except Exception:
                    pass
            threading.Thread(target=_learn, daemon=True).start()

        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


if __name__ == "__main__":
    import uvicorn
    print("🚀 Hybrid AI Workspace  →  http://localhost:8000")
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
