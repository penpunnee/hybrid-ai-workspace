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
@import url('https://fonts.googleapis.com/css2?family=Sora:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

/* ===== BASE ===== */
html, body, [data-testid="stAppViewContainer"] {
    background: #080a11 !important;
    font-family: 'Sora', sans-serif !important;
}
.block-container {
    padding: 0.5rem 1.25rem 0 1.25rem !important;
    position: relative; z-index: 1;
}

/* ===== ORB BACKGROUND ===== */
.orb-field { position: fixed; inset: 0; pointer-events: none; z-index: 0; overflow: hidden; }
.orb {
    position: absolute; border-radius: 50%;
    filter: blur(90px); mix-blend-mode: screen;
    animation: orb-drift 14s ease-in-out infinite alternate;
}
.orb-1 {
    width: 380px; height: 380px;
    background: radial-gradient(circle, rgba(0,220,255,0.55) 0%, rgba(0,180,255,0.15) 50%, transparent 75%);
    top: -80px; right: 20%;
    animation-duration: 18s;
}
.orb-2 {
    width: 320px; height: 320px;
    background: radial-gradient(circle, rgba(230,60,200,0.5) 0%, rgba(180,40,180,0.15) 50%, transparent 75%);
    bottom: 60px; right: 28%;
    animation-duration: 22s; animation-delay: -6s;
}
.orb-3 {
    width: 220px; height: 220px;
    background: radial-gradient(circle, rgba(160,100,255,0.45) 0%, rgba(120,60,220,0.12) 50%, transparent 75%);
    bottom: 80px; right: 8%;
    animation-duration: 16s; animation-delay: -10s;
}
@keyframes orb-drift {
    0%   { transform: translate(0,0) scale(1); }
    50%  { transform: translate(-30px, 20px) scale(1.05); }
    100% { transform: translate(20px, -25px) scale(0.97); }
}

/* ===== SIDEBAR GLASS ===== */
[data-testid="stSidebar"] {
    min-width: 200px !important;
    max-width: 220px !important;
    background: rgba(10, 13, 22, 0.92) !important;
    backdrop-filter: blur(28px) saturate(150%) !important;
    border-right: 1px solid rgba(255,255,255,0.06) !important;
    box-shadow: 4px 0 50px rgba(0,0,0,0.6) !important;
}
[data-testid="stSidebar"] .block-container {
    padding: 0.75rem 0.65rem 5rem 0.65rem !important;
}

/* AI card at top */
.ai-card {
    display: flex; align-items: center; gap: 10px;
    padding: 10px 6px 14px 6px;
    margin-bottom: 4px;
}
.ai-avatar {
    width: 38px; height: 38px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-size: 1rem; font-weight: 700; color: #fff;
    flex-shrink: 0;
    box-shadow: 0 0 16px rgba(0,0,0,0.4);
}
.ai-avatar.fa  { background: linear-gradient(135deg,#0ea5e9,#38bdf8); }
.ai-avatar.kwan{ background: linear-gradient(135deg,#f97316,#fb923c); }
.ai-avatar.khim{ background: linear-gradient(135deg,#8b5cf6,#a78bfa); }
.ai-meta { flex: 1; min-width: 0; }
.ai-name-text {
    font-size: 0.92rem; font-weight: 700;
    color: #e2e8f0 !important; line-height: 1.2;
    -webkit-text-fill-color: unset !important;
}
.pro-badge {
    font-size: 0.6rem; font-weight: 600;
    background: linear-gradient(135deg,#3b82f6,#8b5cf6);
    color: #fff; border-radius: 4px;
    padding: 1px 6px; vertical-align: middle;
}

/* Session group header */
.sess-group-header {
    font-size: 0.65rem; font-weight: 600;
    color: rgba(148,163,184,0.6) !important;
    text-transform: uppercase; letter-spacing: 0.08em;
    padding: 8px 2px 4px 2px;
}

/* User profile bottom */
.user-profile-bar {
    display: flex; align-items: center; gap: 8px;
    padding: 10px 8px;
    border-top: 1px solid rgba(255,255,255,0.05);
    background: rgba(10,13,22,0.92);
    position: fixed; bottom: 0; left: 0; width: 220px; z-index: 100;
    backdrop-filter: blur(20px);
}
.user-avatar {
    width: 30px; height: 30px; border-radius: 50%;
    background: linear-gradient(135deg,#3b82f6,#1d4ed8);
    display: flex; align-items: center; justify-content: center;
    font-size: 0.78rem; font-weight: 700; color: #fff; flex-shrink: 0;
}
.user-info .user-name { font-size: 0.8rem; font-weight: 600; color: #e2e8f0 !important; }
.user-info .user-plan { font-size: 0.65rem; color: rgba(148,163,184,0.6) !important; }
.status-dot {
    width: 8px; height: 8px; border-radius: 50%;
    background: #22c55e; margin-left: auto; flex-shrink: 0;
    box-shadow: 0 0 8px #22c55e;
}

/* ===== BUTTONS ===== */
button[data-testid="baseButton-secondary"] {
    background: rgba(255,255,255,0.04) !important;
    border: 1px solid rgba(255,255,255,0.08) !important;
    border-radius: 10px !important;
    color: rgba(180,200,235,0.7) !important;
    font-family: 'Sora', sans-serif !important;
    font-size: 0.77rem !important;
    transition: all 0.18s ease !important;
    text-align: left !important;
}
button[data-testid="baseButton-secondary"]:hover {
    background: rgba(255,255,255,0.07) !important;
    color: rgba(220,235,255,0.9) !important;
    border-color: rgba(255,255,255,0.14) !important;
}
button[data-testid="baseButton-primary"] {
    background: rgba(255,255,255,0.07) !important;
    border: 1px solid rgba(255,255,255,0.12) !important;
    border-radius: 10px !important;
    color: rgba(220,235,255,0.95) !important;
    font-family: 'Sora', sans-serif !important;
    font-size: 0.77rem !important;
    font-weight: 600 !important;
    transition: all 0.18s ease !important;
    text-align: left !important;
}
button[data-testid="baseButton-primary"]:hover {
    background: rgba(255,255,255,0.11) !important;
}

/* New chat button — full width, gradient pill */
[data-testid="stSidebar"] button[data-testid="baseButton-primary"]:first-of-type {
    background: linear-gradient(135deg, rgba(0,180,255,0.18), rgba(120,60,240,0.18)) !important;
    border: 1px solid rgba(120,160,255,0.2) !important;
    border-radius: 12px !important;
    color: rgba(200,225,255,0.9) !important;
    font-size: 0.83rem !important;
    padding: 0.5rem !important;
}

/* ===== AI HEADER BAR ===== */
.ai-header-bar {
    display: flex; align-items: center; gap: 10px;
    padding: 10px 0 12px 0;
    border-bottom: 1px solid rgba(255,255,255,0.06);
    margin-bottom: 6px;
}
.ai-header-bar .ai-avatar { width: 34px; height: 34px; font-size: 0.9rem; }
.ai-header-meta .ai-title { font-size: 0.95rem; font-weight: 700; color: #e2e8f0 !important; }
.ai-header-meta .ai-status {
    font-size: 0.7rem; color: rgba(148,163,184,0.7) !important;
    display: flex; align-items: center; gap: 4px;
}
.ai-header-meta .ai-status::before {
    content: ''; display: inline-block;
    width: 7px; height: 7px; border-radius: 50%;
    background: #22c55e; box-shadow: 0 0 6px #22c55e;
}

/* ===== CHAT MESSAGES ===== */
[data-testid="stChatMessage"] {
    background: rgba(255,255,255,0.035) !important;
    backdrop-filter: blur(20px) !important;
    border: 1px solid rgba(255,255,255,0.07) !important;
    border-radius: 18px !important;
    margin: 4px 0 !important;
    transition: border-color 0.2s !important;
}
[data-testid="stChatMessage"]:hover {
    border-color: rgba(255,255,255,0.12) !important;
}

/* ===== CHAT INPUT ===== */
[data-testid="stBottom"] {
    background: rgba(8,10,17,0.6) !important;
    backdrop-filter: blur(24px) !important;
    padding: 0.5rem 2rem 0.75rem 2rem !important;
    border-top: 1px solid rgba(255,255,255,0.05) !important;
}
[data-testid="stChatInput"] textarea {
    background: rgba(255,255,255,0.05) !important;
    border: 1px solid rgba(255,255,255,0.12) !important;
    border-radius: 20px !important;
    color: rgba(220,235,255,0.9) !important;
    font-family: 'Sora', sans-serif !important;
    backdrop-filter: blur(20px) !important;
    padding: 0.65rem 1rem !important;
}
[data-testid="stChatInput"] textarea::placeholder { color: rgba(148,163,184,0.45) !important; }
[data-testid="stChatInput"] textarea:focus {
    border-color: rgba(148,163,210,0.3) !important;
    box-shadow: 0 0 0 3px rgba(100,120,255,0.06) !important;
}
[data-testid="stChatInputSubmitButton"] button {
    background: rgba(100,120,255,0.2) !important;
    border-radius: 50% !important; border: none !important;
}

/* ===== EXPANDERS ===== */
[data-testid="stExpander"] {
    background: rgba(255,255,255,0.025) !important;
    backdrop-filter: blur(16px) !important;
    border: 1px solid rgba(255,255,255,0.07) !important;
    border-radius: 14px !important;
    overflow: hidden !important;
}
[data-testid="stExpander"] summary {
    color: rgba(180,210,255,0.8) !important;
    font-family: 'Sora', sans-serif !important;
}

/* ===== SCROLLABLE CONTAINER ===== */
[data-testid="stVerticalBlockBorderWrapper"] > div {
    background: rgba(255,255,255,0.02) !important;
    border: 1px solid rgba(255,255,255,0.05) !important;
    border-radius: 16px !important;
    backdrop-filter: blur(12px) !important;
}

/* ===== HEADERS ===== */
h1, h2, h3 {
    color: rgba(210,228,255,0.9) !important;
    font-family: 'Sora', sans-serif !important;
    font-weight: 700 !important;
    letter-spacing: -0.5px !important;
}
/* Hide default streamlit header/subheader for main area */
.main-ai-header h3 { font-size: 0 !important; }

/* ===== TEXT & CAPTIONS ===== */
p, span, label, div {
    color: rgba(185,210,245,0.82) !important;
    font-family: 'Sora', sans-serif !important;
}
[data-testid="stCaptionContainer"] p {
    color: rgba(140,170,210,0.6) !important;
    font-size: 0.75rem !important;
}

/* ===== TEXT INPUT & SELECTBOX ===== */
[data-testid="stTextInput"] input,
[data-testid="stSelectbox"] select {
    background: rgba(255,255,255,0.04) !important;
    border: 1px solid rgba(255,255,255,0.09) !important;
    border-radius: 10px !important;
    color: rgba(210,230,255,0.88) !important;
    font-family: 'Sora', sans-serif !important;
}

/* ===== RADIO ===== */
[data-testid="stRadio"] label {
    color: rgba(180,210,250,0.78) !important;
}

/* ===== DIVIDER ===== */
hr {
    border-color: rgba(255,255,255,0.06) !important;
}

/* ===== ALERTS ===== */
[data-testid="stAlert"] {
    background: rgba(255,200,100,0.07) !important;
    border: 1px solid rgba(255,200,100,0.18) !important;
    border-radius: 12px !important;
    backdrop-filter: blur(12px) !important;
}

/* ===== SUCCESS / WARNING / ERROR ===== */
[data-testid="stNotification"] {
    background: rgba(0,200,100,0.08) !important;
    border-radius: 12px !important;
    backdrop-filter: blur(12px) !important;
}

/* ===== CODE / MONO ===== */
code, pre, [data-testid="stCode"] {
    font-family: 'JetBrains Mono', monospace !important;
    background: rgba(0,0,0,0.3) !important;
    border: 1px solid rgba(255,255,255,0.07) !important;
    border-radius: 10px !important;
}

/* ===== DOWNLOAD BUTTON ===== */
[data-testid="stDownloadButton"] button {
    background: rgba(255,255,255,0.04) !important;
    border: 1px solid rgba(255,255,255,0.09) !important;
    border-radius: 10px !important;
    color: rgba(200,220,255,0.75) !important;
}

/* ===== SCROLLBAR ===== */
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: rgba(255,255,255,0.02); }
::-webkit-scrollbar-thumb { background: rgba(56,217,245,0.2); border-radius: 10px; }
::-webkit-scrollbar-thumb:hover { background: rgba(56,217,245,0.35); }

/* ===== FILE UPLOADER ===== */
[data-testid="stFileUploader"] {
    background: rgba(255,255,255,0.025) !important;
    border: 1px dashed rgba(180,180,255,0.15) !important;
    border-radius: 12px !important;
}

/* ===== HIDE STREAMLIT BRANDING ===== */
#MainMenu, footer, header { visibility: hidden !important; }
[data-testid="stToolbar"] { display: none !important; }
</style>
""", unsafe_allow_html=True)

# --- Inject background orbs (fixed, behind everything) ---
st.markdown('<div class="orb-field"><div class="orb orb-1"></div><div class="orb orb-2"></div><div class="orb orb-3"></div></div>', unsafe_allow_html=True)

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
# Derive current AI metadata for sidebar card
_cur_name_for_sidebar = st.session_state.get("current_assistant", ASSISTANT_NAMES[0])
_cur_slug_for_sidebar = ASSISTANTS[_cur_name_for_sidebar]["slug"]
_ai_display = {"fa": ("F", "fa", "ฟ้า AI"), "kwan": ("K", "kwan", "ขวัญ AI"), "khim": ("K", "khim", "ขิม AI")}
_av_letter, _av_cls, _ai_label = _ai_display.get(_cur_slug_for_sidebar, ("A", "fa", "AI"))

with st.sidebar:
    # --- AI Card at top ---
    st.markdown(f"""
    <div class="ai-card">
        <div class="ai-avatar {_av_cls}">{_av_letter}</div>
        <div class="ai-meta">
            <div class="ai-name-text">{_ai_label} <span class="pro-badge">Pro</span></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # --- AI Switcher (compact) ---
    ai_short = ["🩵 ฟ้า", "🧡 ขวัญ", "💙 ขิม"]
    cur_idx = ASSISTANT_NAMES.index(st.session_state.current_assistant)
    sb_cols = st.columns(3)
    for i, (col, label) in enumerate(zip(sb_cols, ai_short)):
        with col:
            if st.button(label, key=f"ai_{i}", use_container_width=True,
                         type="primary" if i == cur_idx else "secondary"):
                st.session_state.current_assistant = ASSISTANT_NAMES[i]
                st.rerun()

    st.markdown("<div style='margin:6px 0'></div>", unsafe_allow_html=True)

    # --- New Chat ---
    cur_name = st.session_state.current_assistant
    if st.button("＋  เริ่มแชทใหม่", use_container_width=True, type="primary", key="new_chat_btn"):
        new_sid = _new_session_id()
        st.session_state.current_session[cur_name] = new_sid
        st.session_state.chat_history[cur_name] = []
        st.session_state.pending_prompt.pop(ASSISTANTS[cur_name]["slug"], None)
        st.rerun()

    # --- Session List ---
    sessions = get_sessions(cur_name)
    if not sessions:
        st.markdown("<div style='padding:8px 2px;font-size:0.72rem;color:rgba(148,163,184,0.4)'>ยังไม่มีประวัติ</div>", unsafe_allow_html=True)
    else:
        groups = _group_sessions(sessions)
        active_sid = st.session_state.current_session.get(cur_name, "default")
        for group_name, group_list in groups.items():
            if group_list:
                st.markdown(f"<div class='sess-group-header'>{group_name}</div>", unsafe_allow_html=True)
                for s in group_list:
                    is_active = s["session_id"] == active_sid
                    ts = s["started_at"][11:16] if len(s["started_at"]) > 15 else "เมื่อนี้"
                    title = s["first_msg"][:26] + ("…" if len(s["first_msg"]) > 26 else "")
                    if st.button(f"{title}\n{ts}", key=f"sess_{s['session_id']}",
                                 use_container_width=True,
                                 type="primary" if is_active else "secondary"):
                        st.session_state.current_session[cur_name] = s["session_id"]
                        st.session_state.chat_history[cur_name] = load_history(cur_name, s["session_id"])
                        st.rerun()

    st.markdown("<div style='height:4rem'></div>", unsafe_allow_html=True)

    # --- Settings (collapsible, bottom-ish) ---
    with st.expander("⚙️ Settings"):
        provider_choice = st.radio(
            "AI Engine",
            options=["ollama", "gemini"],
            format_func=lambda x: f"🏠 Local" if x == "ollama" else f"☁️ Gemini",
            index=0 if st.session_state.provider == "ollama" else 1,
        )
        st.session_state.provider = provider_choice
        st.divider()
        st.caption("📎 เพิ่มไฟล์ Context")
        uploaded = st.file_uploader(
            "files", type=["txt", "md", "json", "py"],
            accept_multiple_files=True, label_visibility="collapsed",
        )
        if uploaded:
            st.session_state.uploaded_files = uploaded
            for f in uploaded: st.caption(f"✅ {f.name}")
        else:
            st.session_state.uploaded_files = []
        st.divider()
        ollama_ok, _ = check_ollama_health()
        memory_ok = is_memory_available()
        st.caption(f"{'🟢' if ollama_ok else '🔴'} Ollama · {'🟢' if memory_ok else '🟡'} Mem · 📚{get_skill_count()}")

    # --- User profile bar (fixed bottom) ---
    st.markdown("""
    <div class="user-profile-bar">
        <div class="user-avatar">P</div>
        <div class="user-info">
            <div class="user-name">พี่ปอย</div>
            <div class="user-plan">Pro Plan</div>
        </div>
        <div class="status-dot"></div>
    </div>
    """, unsafe_allow_html=True)


# ==================== MAIN AREA (Detail) ====================
name = st.session_state.current_assistant
config = ASSISTANTS[name]
slug = config["slug"]
base_system_prompt = config["system_prompt"]
templates = config.get("prompt_templates", [])
session_id = st.session_state.current_session.get(name, "default")
avatar = _load_avatar(config)

# --- AI Status Header ---
_ai_disp2 = {"fa": ("F", "fa", name), "kwan": ("K", "kwan", name), "khim": ("K", "khim", name)}
_ltr, _cls, _nm = _ai_disp2.get(slug, ("A", "fa", name))
_engine_tag = f"Local · {OLLAMA_MODEL}" if st.session_state.provider == "ollama" else f"Cloud · {GEMINI_MODEL}"
st.markdown(f"""
<div class="ai-header-bar">
    <div class="ai-avatar {_cls}">{_ltr}</div>
    <div class="ai-header-meta">
        <div class="ai-title">{_nm}</div>
        <div class="ai-status">ออนไลน์ · {_engine_tag}</div>
    </div>
</div>
""", unsafe_allow_html=True)

# Action buttons (clear + export) — minimal row
c_del, c_exp, c_space = st.columns([1, 1, 10])
with c_del:
    if st.button("🗑️", key=f"clr_{slug}", help="ล้างการสนทนานี้"):
        clear_session(name, session_id)
        st.session_state.chat_history[name] = []
        st.rerun()
with c_exp:
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

st.caption("💡 พิมพ์ จำไว้ว่า... เพื่อให้ AI บันทึกข้อมูลลง Memory")

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
