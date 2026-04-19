import os
import uuid
import threading
import streamlit as st
from datetime import datetime, date, timedelta
from assistants.config import ASSISTANTS
from utils.llm import stream_response, OLLAMA_MODEL, GEMINI_MODEL, check_ollama_health
from utils.rag import build_rag_context, inject_context_to_system
from utils.history import save_message, load_history, clear_session, get_sessions, export_history_md
from utils.tokens import count_tokens_approx, get_context_limit, get_token_status
from utils.memory import save_memory, search_memory, is_memory_available, save_lesson, save_preference, get_lessons, get_preferences
from utils.skills import get_all_skills, auto_extract_skills, get_skill_count
try:
    from streamlit_ace import st_ace
    ACE_AVAILABLE = True
except ImportError:
    ACE_AVAILABLE = False

# --- 1. Page config + CSS ---
st.set_page_config(page_title="Hybrid AI Workspace", page_icon="🧠", layout="wide")

st.markdown("""
<style>
.block-container { padding: 0.75rem 1.5rem 0 1.5rem !important; }
[data-testid="stSidebar"] { min-width: 270px !important; max-width: 300px !important; }
[data-testid="stSidebar"] .block-container { padding: 1rem 0.75rem !important; }
</style>
""", unsafe_allow_html=True)

# --- 2. Session State ---
ASSISTANT_NAMES = list(ASSISTANTS.keys())

for key, default in [
    ("current_assistant", ASSISTANT_NAMES[0]),
    ("current_session", {}),
    ("chat_history", {}),
    ("provider", "ollama"),
    ("uploaded_files", []),
    ("skills_folder", ""),
    ("pending_prompt", {}),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# Initialize session IDs and load history
for aname in ASSISTANT_NAMES:
    if aname not in st.session_state.current_session:
        sessions = get_sessions(aname)
        st.session_state.current_session[aname] = sessions[0]["session_id"] if sessions else "default"
    if aname not in st.session_state.chat_history:
        sid = st.session_state.current_session[aname]
        st.session_state.chat_history[aname] = load_history(aname, sid)

# --- Helper ---
def _load_avatar(config: dict):
    path = config.get("avatar", "")
    if path and os.path.exists(path):
        from PIL import Image
        img = Image.open(path)
        w, h = img.size
        size = min(w, h)
        img = img.crop(((w - size) // 2, (h - size) // 2, (w + size) // 2, (h + size) // 2)).resize((64, 64))
        return img
    return "assistant"

def _new_session_id():
    return f"s_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

def _group_sessions(sessions: list) -> dict:
    today = date.today()
    groups = {"วันนี้": [], "เมื่อวาน": [], "ก่อนหน้า": []}
    for s in sessions:
        try:
            d = datetime.fromisoformat(s["started_at"]).date()
            if d == today:
                groups["วันนี้"].append(s)
            elif d == today - timedelta(days=1):
                groups["เมื่อวาน"].append(s)
            else:
                groups["ก่อนหน้า"].append(s)
        except Exception:
            groups["ก่อนหน้า"].append(s)
    return groups

# ==================== SIDEBAR (Master) ====================
with st.sidebar:
    st.markdown("## 🧠 Hybrid AI")

    # AI Selector
    ai_labels = ["🩵 ฟ้า", "🧡 ขวัญ", "💙 ขิม"]
    cur_idx = ASSISTANT_NAMES.index(st.session_state.current_assistant)
    cols = st.columns(3)
    for i, (col, label) in enumerate(zip(cols, ai_labels)):
        with col:
            btn_type = "primary" if i == cur_idx else "secondary"
            if st.button(label, key=f"ai_{i}", use_container_width=True, type=btn_type):
                st.session_state.current_assistant = ASSISTANT_NAMES[i]
                st.rerun()

    st.divider()

    # New Chat
    cur_name = st.session_state.current_assistant
    if st.button("➕ สนทนาใหม่", use_container_width=True, type="primary"):
        new_sid = _new_session_id()
        st.session_state.current_session[cur_name] = new_sid
        st.session_state.chat_history[cur_name] = []
        slug = ASSISTANTS[cur_name]["slug"]
        st.session_state.pending_prompt.pop(slug, None)
        st.rerun()

    # Session List (Master)
    st.caption("📋 ประวัติการสนทนา")
    sessions = get_sessions(cur_name)
    if not sessions:
        st.caption("_ยังไม่มีประวัติ_")
    else:
        groups = _group_sessions(sessions)
        active_sid = st.session_state.current_session.get(cur_name, "default")
        for group_name, group_list in groups.items():
            if group_list:
                st.caption(f"**{group_name}**")
                for s in group_list:
                    is_active = s["session_id"] == active_sid
                    label_text = ("▶ " if is_active else "") + s["first_msg"][:28] + ("…" if len(s["first_msg"]) > 28 else "")
                    if st.button(label_text, key=f"sess_{s['session_id']}", use_container_width=True,
                                 type="primary" if is_active else "secondary"):
                        st.session_state.current_session[cur_name] = s["session_id"]
                        st.session_state.chat_history[cur_name] = load_history(cur_name, s["session_id"])
                        st.rerun()

    st.divider()

    # Settings Expander
    with st.expander("⚙️ การตั้งค่า"):
        provider_choice = st.radio(
            "AI Engine",
            options=["ollama", "gemini"],
            format_func=lambda x: f"🏠 Local ({OLLAMA_MODEL})" if x == "ollama" else f"☁️ Gemini ({GEMINI_MODEL})",
            index=0 if st.session_state.provider == "ollama" else 1,
        )
        st.session_state.provider = provider_choice
        st.divider()

        st.markdown("**� เพิ่มไฟล์ Context**")
        st.caption("ลากมาวาง หรือคลิกเลือกไฟล์ (txt, md, json, py)")
        uploaded = st.file_uploader(
            "files", type=["txt", "md", "json", "py"],
            accept_multiple_files=True, label_visibility="collapsed",
        )
        if uploaded:
            st.session_state.uploaded_files = uploaded
            for f in uploaded:
                st.caption(f"✅ {f.name}")
        else:
            st.session_state.uploaded_files = []
        st.divider()

        ollama_ok, _ = check_ollama_health()
        memory_ok = is_memory_available()
        st.caption(f"{'🟢' if ollama_ok else '🔴'} Ollama &nbsp;|&nbsp; {'🟢' if memory_ok else '🟡'} Memory &nbsp;|&nbsp; 📚 {get_skill_count()} skills")


# ==================== MAIN AREA (Detail) ====================
name = st.session_state.current_assistant
config = ASSISTANTS[name]
slug = config["slug"]
base_system_prompt = config["system_prompt"]
templates = config.get("prompt_templates", [])
session_id = st.session_state.current_session.get(name, "default")
avatar = _load_avatar(config)

# Header
col_h1, col_h2, col_h3 = st.columns([7, 2, 1])
with col_h1:
    st.subheader(f"สนทนากับ {name}")
with col_h2:
    badge = f"🏠 {OLLAMA_MODEL}" if st.session_state.provider == "ollama" else f"☁️ {GEMINI_MODEL}"
    st.caption(badge)
with col_h3:
    c1, c2 = st.columns(2)
    with c1:
        if st.button("�️", key=f"clr_{slug}", help="ล้างการสนทนานี้"):
            clear_session(name, session_id)
            st.session_state.chat_history[name] = []
            st.rerun()
    with c2:
        md_text = export_history_md(name, session_id)
        st.download_button("💾", data=md_text.encode(), file_name=f"chat_{slug}.md",
                           mime="text/markdown", key=f"exp_{slug}", help="Export")

# Token status
current_model = OLLAMA_MODEL if st.session_state.provider == "ollama" else GEMINI_MODEL
token_used = count_tokens_approx(st.session_state.chat_history[name])
status_type, status_msg = get_token_status(token_used, get_context_limit(current_model))
if status_type == "warning":
    st.warning(status_msg)
elif status_type == "critical":
    st.error(status_msg)

# Shortcuts
if templates:
    st.caption("⚡ Shortcuts:")
    btn_cols = st.columns(len(templates))
    for i, (lbl, tpl) in enumerate(templates):
        with btn_cols[i]:
            if st.button(lbl, key=f"tpl_{slug}_{i}", use_container_width=True):
                st.session_state.pending_prompt[slug] = tpl
                st.rerun()

# Code Editor (collapsible)
with st.expander("💻 Code Editor"):
    lang = st.selectbox("ภาษา", ["python", "javascript", "typescript", "html", "css", "sql", "json", "markdown"],
                        key=f"lang_{slug}", label_visibility="collapsed")
    if ACE_AVAILABLE:
        code_content = st_ace(placeholder="วางโค้ดที่นี่...", language=lang, theme="monokai",
                              font_size=12, height=220, key=f"ace_{slug}", auto_update=True)
    else:
        code_content = st.text_area("โค้ด", placeholder="วางโค้ดที่นี่...", height=220,
                                    key=f"code_{slug}", label_visibility="collapsed")
    bc1, bc2, bc3 = st.columns(3)
    with bc1:
        if st.button("🔍 Review", key=f"rev_{slug}", use_container_width=True):
            if code_content and code_content.strip():
                st.session_state.pending_prompt[slug] = f"ช่วย review โค้ดนี้:\n\n```{lang}\n{code_content}\n```"
                st.rerun()
    with bc2:
        if st.button("🐛 Bug", key=f"bug_{slug}", use_container_width=True):
            if code_content and code_content.strip():
                st.session_state.pending_prompt[slug] = f"ช่วยหา bug:\n\n```{lang}\n{code_content}\n```"
                st.rerun()
    with bc3:
        if st.button("✨ อธิบาย", key=f"expl_{slug}", use_container_width=True):
            if code_content and code_content.strip():
                st.session_state.pending_prompt[slug] = f"อธิบายโค้ดนี้:\n\n```{lang}\n{code_content}\n```"
                st.rerun()

# Chat messages (fixed height, scrollable — ทำให้ input อยู่ด้านล่างเสมอ)
chat_container = st.container(height=520, border=False)
with chat_container:
    for msg in st.session_state.chat_history[name]:
        av = avatar if msg["role"] == "assistant" else "user"
        with st.chat_message(msg["role"], avatar=av):
            st.write(msg["content"])

st.caption("� พิมพ์ **จำไว้ว่า...** เพื่อให้ AI บันทึกข้อมูลลง Memory ทันที")

# Chat Input (fixed below container)
default_input = st.session_state.pending_prompt.pop(slug, "")

if prompt := st.chat_input(f"สั่งงาน {name}...", key=f"inp_{slug}") or default_input:

    # Special: "จำไว้ว่า..." command
    if any(prompt.startswith(kw) for kw in ["จำไว้ว่า", "จำไว้", "จำว่า"]):
        mem_text = prompt.split(" ", 1)[1].strip() if " " in prompt else prompt
        save_memory(name, prompt, f"ข้อมูลที่บันทึก: {mem_text}")
        save_lesson("ข้อมูลจากพี่ปอย", mem_text)
        confirm = f"✅ จำแล้วนะค่ะ!\n\n> {mem_text}"
        st.session_state.chat_history[name].append({"role": "user", "content": prompt})
        st.session_state.chat_history[name].append({"role": "assistant", "content": confirm})
        save_message(name, "user", prompt, st.session_state.provider, session_id)
        save_message(name, "assistant", confirm, st.session_state.provider, session_id)
        st.rerun()

    else:
        # Build context
        rag_context = build_rag_context(
            uploaded_files=list(st.session_state.uploaded_files),
            skills_folder=st.session_state.skills_folder,
        )
        for f in st.session_state.uploaded_files:
            try:
                auto_extract_skills(f.read().decode("utf-8", errors="ignore"), name)
                f.seek(0)
            except Exception:
                pass

        full_context = "\n\n".join(filter(None, [
            rag_context,
            search_memory(name, prompt),
            get_all_skills(),
            f"[บทเรียนสะสม]\n{get_lessons(prompt)}" if get_lessons(prompt) else "",
            f"[ความชอบ]\n{get_preferences()}" if get_preferences() else "",
        ]))
        system_prompt = inject_context_to_system(base_system_prompt, full_context)

        # Add user message
        st.session_state.chat_history[name].append({"role": "user", "content": prompt})
        save_message(name, "user", prompt, st.session_state.provider, session_id)

        with chat_container:
            with st.chat_message("user"):
                st.write(prompt)

        # Build message list
        messages = [{"role": "system", "content": system_prompt}]
        messages += [{"role": m["role"], "content": m["content"]} for m in st.session_state.chat_history[name]]

        # Stream AI response
        with chat_container:
            with st.chat_message("assistant", avatar=avatar):
                response_text = st.write_stream(
                    stream_response(messages, provider=st.session_state.provider)
                )

        st.session_state.chat_history[name].append({"role": "assistant", "content": response_text})
        save_message(name, "assistant", response_text, st.session_state.provider, session_id)
        save_memory(name, prompt, response_text)

        # Auto-learn (background)
        if len(response_text) > 100:
            prov = st.session_state.provider
            def _learn(p=prompt, r=response_text, pv=prov):
                try:
                    msgs = [
                        {"role": "system", "content": "สรุปบทเรียนเป็นภาษาไทย 1-2 ประโยค ถ้าไม่มีตอบว่า SKIP"},
                        {"role": "user", "content": f"คำถาม: {p}\nคำตอบ: {r[:500]}"},
                    ]
                    lesson = "".join(stream_response(msgs, provider=pv)).strip()
                    if lesson and lesson != "SKIP" and len(lesson) > 10:
                        save_lesson(p[:50], lesson)
                    for kw, (k, v) in {"ตอบสั้น": ("style", "ชอบสั้น"), "ตัวอย่าง": ("style", "ชอบ code"), "อธิบาย": ("style", "ชอบละเอียด")}.items():
                        if kw in p:
                            save_preference(k, v)
                except Exception:
                    pass
            threading.Thread(target=_learn, daemon=True).start()
