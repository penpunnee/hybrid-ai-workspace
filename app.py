import os
import streamlit as st
from assistants.config import ASSISTANTS
from utils.llm import stream_response, OLLAMA_MODEL, GEMINI_MODEL, check_ollama_health
from utils.rag import build_rag_context, inject_context_to_system
from utils.history import save_message, load_history, clear_history, export_history_md
from utils.tokens import count_tokens_approx, get_context_limit, get_token_status
from utils.memory import save_memory, search_memory, is_memory_available
from utils.skills import get_all_skills, auto_extract_skills, get_skill_count
try:
    from streamlit_ace import st_ace
    ACE_AVAILABLE = True
except ImportError:
    ACE_AVAILABLE = False

# --- 1. ตั้งค่าหน้าจอ ---
st.set_page_config(
    page_title="Hybrid AI Workspace",
    page_icon="🧠",
    layout="wide",
)

# --- 2. เริ่มต้น Session State ---
if "chat_history" not in st.session_state:
    # โหลดประวัติจาก SQLite อัตโนมัติ
    st.session_state.chat_history = {
        name: load_history(name) for name in ASSISTANTS
    }
if "provider" not in st.session_state:
    st.session_state.provider = "ollama"
if "uploaded_files" not in st.session_state:
    st.session_state.uploaded_files = []
if "skills_folder" not in st.session_state:
    st.session_state.skills_folder = ""
if "session_name" not in st.session_state:
    st.session_state.session_name = "โปรเจกต์ของฉัน"
if "pending_prompt" not in st.session_state:
    st.session_state.pending_prompt = {}

# --- 3. Sidebar: Global Settings ---
with st.sidebar:
    st.title("🧠 Hybrid AI Workspace")
    st.caption("Personal AI Developer Portal")

    # --- Session / Project Name ---
    session_name = st.text_input(
        "📁 ชื่อโปรเจกต์",
        value=st.session_state.session_name,
        placeholder="เช่น พมจ. Dashboard v2",
    )
    st.session_state.session_name = session_name
    st.divider()

    # --- Hybrid LLM Switcher ---
    st.subheader("⚙️ เลือก AI Engine")
    provider_choice = st.radio(
        "สมองกลที่ใช้งาน",
        options=["ollama", "gemini"],
        format_func=lambda x: f"🏠 Local — Llama ({OLLAMA_MODEL})" if x == "ollama" else f"☁️ Cloud — Gemini ({GEMINI_MODEL})",
        index=0 if st.session_state.provider == "ollama" else 1,
        help="Local = ข้อมูลปลอดภัย ไม่ออก Internet | Cloud = เร็ว วิเคราะห์กว้าง",
    )
    st.session_state.provider = provider_choice

    if provider_choice == "ollama":
        st.success(f"🔒 ปลอดภัย — รันในเครื่อง ({OLLAMA_MODEL})")
    else:
        st.info(f"⚡ Cloud Speed — Google Gemini ({GEMINI_MODEL})")

    st.divider()

    # --- RAG: File Upload ---
    st.subheader("📎 RAG Context")
    uploaded = st.file_uploader(
        "อัปโหลดไฟล์ให้ AI อ่าน (txt, md, json, py)",
        type=["txt", "md", "json", "py"],
        accept_multiple_files=True,
        help="ไฟล์เหล่านี้จะถูกแทรกใน system prompt ของทุก assistant",
    )
    if uploaded:
        st.session_state.uploaded_files = uploaded
        st.success(f"✅ โหลด {len(uploaded)} ไฟล์แล้ว")
        for f in uploaded:
            st.caption(f"📄 {f.name}")
    else:
        st.session_state.uploaded_files = []

    # --- RAG: Skills Folder Path ---
    skills_path = st.text_input(
        "📂 Skills Folder Path (optional)",
        value=st.session_state.skills_folder,
        placeholder="/path/to/skills",
        help="โฟลเดอร์ที่มีไฟล์ความรู้ เช่น identity.json, skills/*.md",
    )
    st.session_state.skills_folder = skills_path

    if skills_path:
        if os.path.isdir(skills_path):
            file_count = len([f for f in os.listdir(skills_path) if not f.startswith(".")])
            st.success(f"✅ พบ {file_count} ไฟล์ใน folder")
        else:
            st.warning("⚠️ ไม่พบโฟลเดอร์นี้")

    # --- Ollama Status ---
    st.divider()
    st.subheader("🔌 System Status")
    ollama_ok, _ = check_ollama_health()
    if ollama_ok:
        st.success(f"🟢 Ollama online ({OLLAMA_MODEL})")
    else:
        st.error("🔴 Ollama offline — รัน `ollama serve`")

    gemini_ok = bool(os.getenv('GEMINI_API_KEY', ''))
    if gemini_ok:
        st.success(f"🟢 Gemini key พร้อม ({GEMINI_MODEL})")
    else:
        st.warning("🟡 Gemini key ยังไม่ได้ตั้งค่า")

    st.divider()
    memory_ok = is_memory_available()
    skill_count = get_skill_count()
    if memory_ok:
        st.success("🧠 Long-term Memory พร้อม")
    else:
        st.warning("🟡 Memory offline (ChromaDB)")
    st.caption(f"📚 Skills สะสม: {skill_count} topics")
    st.divider()
    st.caption(f"📁 {st.session_state.session_name}\n\n🏗️ Hybrid LLM\n📚 RAG\n🔀 Decoupled")


# --- 4. ฟังก์ชันแสดงแชท ---
def render_assistant_chat(name: str, tab_obj):
    config = ASSISTANTS[name]
    slug = config["slug"]
    base_system_prompt = config["system_prompt"]
    templates = config.get("prompt_templates", [])

    with tab_obj:
        col_editor, col_chat, col_context = st.columns([3, 4, 3])

        # ==================== คอลัมน์ซ้าย: Code Editor ====================
        with col_editor:
            st.caption("💻 Code Editor")
            lang = st.selectbox(
                "ภาษา",
                ["python", "javascript", "typescript", "html", "css", "sql", "json", "markdown"],
                key=f"lang_{slug}",
                label_visibility="collapsed",
            )
            if ACE_AVAILABLE:
                code_content = st_ace(
                    placeholder="วางโค้ดที่นี่...",
                    language=lang,
                    theme="monokai",
                    font_size=13,
                    height=400,
                    key=f"ace_{slug}",
                    auto_update=True,
                )
            else:
                code_content = st.text_area(
                    "โค้ด",
                    placeholder="วางโค้ดที่นี่...",
                    height=400,
                    key=f"code_{slug}",
                    label_visibility="collapsed",
                )
            col_r, col_a = st.columns(2)
            with col_r:
                if st.button("🔍 Review", key=f"review_{slug}", use_container_width=True):
                    if code_content and code_content.strip():
                        st.session_state.pending_prompt[slug] = f"ช่วย review โค้ดนี้และแนะนำการปรับปรุง:\n\n```{lang}\n{code_content}\n```"
                        st.rerun()
            with col_a:
                if st.button("🐛 หา Bug", key=f"bug_{slug}", use_container_width=True):
                    if code_content and code_content.strip():
                        st.session_state.pending_prompt[slug] = f"ช่วยหา bug ในโค้ดนี้:\n\n```{lang}\n{code_content}\n```"
                        st.rerun()
            if st.button("✨ อธิบายโค้ด", key=f"explain_{slug}", use_container_width=True):
                if code_content and code_content.strip():
                    st.session_state.pending_prompt[slug] = f"ช่วยอธิบายโค้ดนี้ทีละบรรทัด:\n\n```{lang}\n{code_content}\n```"
                    st.rerun()

        # ==================== คอลัมน์กลาง: Chat ====================
        with col_chat:
            col_title, col_badge, col_clear = st.columns([5, 2, 1])
            with col_title:
                st.subheader(f"ช่องสนทนากับ {name}")
            with col_badge:
                st.write("")
                if st.session_state.provider == "ollama":
                    st.caption(f"🏠 {OLLAMA_MODEL}")
                else:
                    st.caption(f"☁️ {GEMINI_MODEL}")
            with col_clear:
                st.write("")
                col_del, col_exp = st.columns(2)
                with col_del:
                    if st.button("🗑️", key=f"clear_{slug}", help="ล้างประวัติแชท"):
                        clear_history(name)
                        st.session_state.chat_history[name] = []
                        st.session_state.pending_prompt.pop(slug, None)
                        st.rerun()
                with col_exp:
                    md_text = export_history_md(name)
                    st.download_button(
                        "💾",
                        data=md_text.encode("utf-8"),
                        file_name=f"chat_{slug}.md",
                        mime="text/markdown",
                        key=f"export_{slug}",
                        help="Export ประวัติแชทเป็น Markdown",
                    )

            current_model = OLLAMA_MODEL if st.session_state.provider == "ollama" else GEMINI_MODEL
            token_limit = get_context_limit(current_model)
            token_used = count_tokens_approx(st.session_state.chat_history[name])
            status_type, status_msg = get_token_status(token_used, token_limit)
            if status_type == "normal":
                st.caption(f"📊 {status_msg}")
            elif status_type == "warning":
                st.warning(status_msg)
            else:
                st.error(status_msg)

            if templates:
                st.caption("⚡ Shortcuts:")
                btn_cols = st.columns(len(templates))
                for i, (label, template_text) in enumerate(templates):
                    with btn_cols[i]:
                        if st.button(label, key=f"tpl_{slug}_{i}", use_container_width=True):
                            st.session_state.pending_prompt[slug] = template_text
                            st.rerun()

            st.divider()

            for msg in st.session_state.chat_history[name]:
                with st.chat_message(msg["role"]):
                    st.write(msg["content"])

            default_input = st.session_state.pending_prompt.pop(slug, "")

            if prompt := st.chat_input(
                f"สั่งงาน {name}...",
                key=f"input_{slug}",
            ) or default_input:
                rag_context = build_rag_context(
                    uploaded_files=list(st.session_state.uploaded_files),
                    skills_folder=st.session_state.skills_folder,
                )
                memory_context = search_memory(name, prompt)
                skills_context = get_all_skills()
                full_context = "\n\n".join(filter(None, [rag_context, memory_context, skills_context]))
                system_prompt = inject_context_to_system(base_system_prompt, full_context)
                for f in st.session_state.uploaded_files:
                    try:
                        content = f.read().decode("utf-8", errors="ignore")
                        auto_extract_skills(content, name)
                        f.seek(0)
                    except Exception:
                        pass

                st.session_state.chat_history[name].append({"role": "user", "content": prompt})
                save_message(name, "user", prompt, st.session_state.provider)
                with st.chat_message("user"):
                    st.write(prompt)

                messages = [{"role": "system", "content": system_prompt}]
                messages += [
                    {"role": m["role"], "content": m["content"]}
                    for m in st.session_state.chat_history[name]
                ]

                with st.chat_message("assistant"):
                    response_text = st.write_stream(
                        stream_response(messages, provider=st.session_state.provider)
                    )

                st.session_state.chat_history[name].append(
                    {"role": "assistant", "content": response_text}
                )
                save_message(name, "assistant", response_text, st.session_state.provider)
                save_memory(name, prompt, response_text)

        # ==================== คอลัมน์ขวา: Context ====================
        with col_context:
            st.caption("📚 Context & Memory")
            skill_count = get_skill_count()
            memory_ok = is_memory_available()
            st.caption(f"{'🟢' if memory_ok else '🔴'} Memory | 📖 {skill_count} skills")
            st.divider()
            recent_memory = search_memory(name, "recent", n_results=3)
            if recent_memory:
                with st.expander("🧠 ความจำล่าสุด", expanded=False):
                    st.caption(recent_memory[:500] + "..." if len(recent_memory) > 500 else recent_memory)
            all_skills = get_all_skills()
            if all_skills:
                with st.expander("💡 Skills สะสม", expanded=False):
                    st.caption(all_skills[:500] + "..." if len(all_skills) > 500 else all_skills)

# --- 5. สร้าง Tabs ---
tab_names = list(ASSISTANTS.keys())
tabs = st.tabs([
    "🩵 ฟ้า (Frontend)",
    "🧡 หมี (Backend)",
    "💙 ขิม (Planning)",
])

for tab_name, tab_obj in zip(tab_names, tabs):
    render_assistant_chat(tab_name, tab_obj)
