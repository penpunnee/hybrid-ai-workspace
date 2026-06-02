/* =====================================================
   Hybrid AI Workspace — Enhanced UI Layer
   Features: Auth, Health Widget, Global Search,
             Export, Pin Message, @vault Search
   Injected via index.html — no React source needed
   ===================================================== */
(function () {
  "use strict";

  // ── Auth token (stored in localStorage) ─────────────────────────────────────
  let _authToken = localStorage.getItem("hw_auth_token") || "";

  // ── Single unified fetch override (auth + stop + history + typing) ──────────
  const ctx = { assistant: null, session: null };
  const _origFetch = window.fetch.bind(window);

  // ตัวแปรที่ใช้ร่วมกันระหว่าง features (ประกาศ forward เพื่อให้ fetch ใช้ได้)
  let _abortCtrl = null;
  let _stopBtnEl = null;   // set ทีหลังเมื่อ DOM พร้อม
  let _typingElRef = null; // set ทีหลังเมื่อ DOM พร้อม
  let _promptHistory = JSON.parse(localStorage.getItem("hw_prompt_history") || "[]");
  let _histIdx = -1;
  let _draftPrompt = "";

  // ── Agent Mode state ────────────────────────────────────────────────────────
  let _agentMode = localStorage.getItem("hw_agent_mode") === "1";
  // ── Claude Mode state — override provider=claude บน /api/chat ────────────────
  let _claudeMode = localStorage.getItem("hw_claude_mode") === "1";
  // queue ของ agent events ที่ยังรอ AI bubble ใหม่มา attach timeline
  let _pendingAgentTimeline = null;  // { events: [], sessionToken: string }

  window.fetch = function (url, opts) {
    if (typeof url === "string") {
      // 1. Track assistant + session + prompt history + agent/claude injection
      //    N2: ครอบ /api/regenerate ด้วย → กด regenerate ก็ใช้ Claude/Agent ตามโหมด
      if ((url === "/api/chat" || url.includes("/api/regenerate")) && opts?.body) {
        try {
          const b = JSON.parse(opts.body);
          if (b.assistant) ctx.assistant = b.assistant;
          if (b.session_id) ctx.session = b.session_id;
          if (b.prompt?.trim()) {
            _promptHistory = [b.prompt, ..._promptHistory.filter(p => p !== b.prompt)].slice(0, 50);
            localStorage.setItem("hw_prompt_history", JSON.stringify(_promptHistory));
            _histIdx = -1;
            // ส่งแล้ว → เคลียร์ draft ที่ค้างของ session นั้น
            try { localStorage.removeItem("hw_draft_" + (b.session_id || "default")); } catch {}
          }
          // Claude Mode ชนะ Agent Mode — override provider=claude ส่งไป Claude API
          if (_claudeMode) {
            b.provider = "claude";
            opts = { ...opts, body: JSON.stringify(b) };
          } else if (_agentMode && !b.tool_agent) {
            // Inject tool_agent flag เมื่อเปิด Agent Mode
            b.tool_agent = true;
            opts = { ...opts, body: JSON.stringify(b) };
            // เปิด queue รอ events
            _pendingAgentTimeline = { events: [], sessionToken: Date.now().toString(36) };
          }
        } catch {}
      }

      // 2. Auth token injection
      if (url.startsWith("/api/") && _authToken) {
        opts = opts ? { ...opts } : {};
        opts.headers = { ...(opts.headers || {}), "x-auth-token": _authToken };
      }

      // 3. AbortController + typing indicator for streaming calls
      if (opts?.method === "POST" && (url === "/api/chat" || url.includes("/api/regenerate"))) {
        _abortCtrl = new AbortController();
        opts = { ...opts, signal: _abortCtrl.signal };

        // แสดง Stop button + typing indicator (ใช้ ref เพราะ DOM ยังไม่พร้อมตอน declare)
        if (_stopBtnEl) _stopBtnEl.style.display = "flex";
        if (_typingElRef) _typingElRef.classList.add("show");

        // Poll ซ่อนเมื่อ streaming cursor หายไป
        const poll = setInterval(() => {
          if (!document.querySelector('[class*="animate-pulse"][class*="opacity-70"]')) {
            if (_stopBtnEl) _stopBtnEl.style.display = "none";
            if (_typingElRef) _typingElRef.classList.remove("show");
            _abortCtrl = null;
            clearInterval(poll);
          }
        }, 300);
        // Timeout กัน poll ค้าง
        setTimeout(() => { clearInterval(poll); if (_typingElRef) _typingElRef.classList.remove("show"); }, 60000);
      }
    }

    return _origFetch(url, opts)
      .catch((err) => {
        if (_stopBtnEl) _stopBtnEl.style.display = "none";
        if (_typingElRef) _typingElRef.classList.remove("show");
        if (err.name === "AbortError") {
          // หยุด streaming อย่างสวยงาม — คืน empty stream แทน error
          return new Response(new ReadableStream({ start(c) { c.close(); } }),
            { status: 200, headers: { "Content-Type": "text/event-stream" } });
        }
        throw err;
      })
      .then((resp) => {
        // ดัก 401 → login modal เฉพาะกรณีไม่มี token (ยังไม่ login)
        // ถ้ามี token อยู่แล้วแต่ได้ 401 = endpoint อื่น ไม่ force logout
        if (resp.status === 401 && !_authToken) {
          loginOverlay.classList.add("open");
          setTimeout(() => document.getElementById("login-input")?.focus(), 100);
        }
        // Tee stream — React อ่านอันหนึ่ง, enhanced.js parse อีกอัน
        // ทำเสมอสำหรับ /api/chat เพื่อ render citations/reflection/cache_hit/feedback
        if (typeof url === "string" && (url === "/api/chat" || url.includes("/api/regenerate")) && resp.body) {
          try {
            const [reactStream, ourStream] = resp.body.tee();
            // start chat-event parser (citations, reflection, cache_hit, active_learning, message_id)
            _parseChatSSE(ourStream, _agentMode ? _pendingAgentTimeline : null);
            return new Response(reactStream, {
              status: resp.status,
              statusText: resp.statusText,
              headers: resp.headers,
            });
          } catch (e) {
            console.warn("[Chat] tee failed:", e);
          }
        }
        return resp;
      });
  };

  // ── Styles ──────────────────────────────────────────────────────────────────
  const css = document.createElement("style");
  css.textContent = `
    /* Login Modal */
    #login-overlay {
      position: fixed; inset: 0; z-index: 99999;
      background: rgba(2,6,23,0.97); backdrop-filter: blur(20px);
      display: none; align-items: center; justify-content: center;
    }
    #login-overlay.open { display: flex; }
    #login-box {
      background: rgba(15,23,42,0.98); border: 1px solid rgba(99,102,241,0.4);
      border-radius: 24px; padding: 40px; width: min(360px, calc(100vw - 32px));
      text-align: center; box-sizing: border-box;
      box-shadow: 0 32px 80px rgba(0,0,0,0.6);
    }
    #login-box h2 { color: #e2e8f0; font-size: 20px; margin: 0 0 6px; font-weight: 600; }
    #login-box p { color: #64748b; font-size: 13px; margin: 0 0 24px; }
    #login-input {
      width: 100%; padding: 12px 16px; background: rgba(30,41,59,0.8);
      border: 1px solid rgba(99,102,241,0.3); border-radius: 12px;
      color: #e2e8f0; font-size: 14px; outline: none;
      font-family: inherit; box-sizing: border-box; margin-bottom: 12px;
      text-align: center; letter-spacing: 2px;
    }
    #login-input:focus { border-color: rgba(99,102,241,0.7); }
    #login-btn {
      width: 100%; padding: 12px; background: linear-gradient(135deg,#6366f1,#8b5cf6);
      border: none; border-radius: 12px; color: #fff; font-size: 14px;
      font-weight: 600; cursor: pointer; font-family: inherit; transition: opacity .2s;
    }
    #login-btn:hover { opacity: 0.9; }
    #login-err { color: #f87171; font-size: 12px; margin-top: 10px; min-height: 18px; }

    .hw-row { display: flex; justify-content: space-between; align-items: center;
      padding: 4px 0; font-size: 12px; color: #94a3b8; }
    .hw-val { color: #e2e8f0; font-weight: 600; }
    .hw-bar { height: 4px; background: rgba(99,102,241,0.15); border-radius: 4px;
      margin: 2px 0 8px; }
    .hw-fill { height: 100%; border-radius: 4px; transition: width .4s; }
    .hw-ok { color: #34d399; } .hw-warn { color: #fbbf24; } .hw-err { color: #f87171; }

    /* Overlay base */
    .enh-overlay {
      position: fixed; inset: 0; z-index: 9100; display: none;
      background: rgba(0,0,0,0.6); backdrop-filter: blur(4px);
      align-items: flex-start; justify-content: center; padding-top: 80px;
    }
    .enh-overlay.open { display: flex; }
    .enh-box {
      background: rgba(15,23,42,0.97); backdrop-filter: blur(20px);
      border: 1px solid rgba(99,102,241,0.3); border-radius: 20px;
      padding: 24px; width: min(640px, calc(100vw - 24px)); max-height: 70vh;
      display: flex; flex-direction: column; gap: 12px;
      box-shadow: 0 24px 64px rgba(0,0,0,0.5);
    }
    .enh-title { font-size: 14px; font-weight: 600; color: #e2e8f0;
      display: flex; align-items: center; gap: 8px; }
    .enh-input {
      width: 100%; padding: 10px 14px; background: rgba(30,41,59,0.8);
      border: 1px solid rgba(99,102,241,0.3); border-radius: 10px;
      color: #e2e8f0; font-size: 13px; outline: none;
      font-family: inherit; box-sizing: border-box;
    }
    .enh-input:focus { border-color: rgba(99,102,241,0.7); }
    .enh-results { overflow-y: auto; display: flex; flex-direction: column; gap: 6px; }
    .enh-result {
      padding: 10px 12px; background: rgba(30,41,59,0.6);
      border: 1px solid rgba(71,85,105,0.3); border-radius: 10px;
      cursor: pointer; transition: all .15s;
    }
    .enh-result:hover { background: rgba(99,102,241,0.15);
      border-color: rgba(99,102,241,0.4); }
    .enh-result-meta { font-size: 11px; color: #64748b; margin-bottom: 3px; }
    .enh-result-text { font-size: 12px; color: #cbd5e1; line-height: 1.5; }
    .enh-result-text mark { background: rgba(99,102,241,0.4);
      color: #a5b4fc; border-radius: 3px; padding: 0 2px; }
    .enh-empty { font-size: 12px; color: #475569; text-align: center; padding: 24px; }
    .enh-close { margin-left: auto; background: none; border: none;
      color: #64748b; cursor: pointer; font-size: 18px; line-height: 1; }
    .enh-close:hover { color: #e2e8f0; }
    .enh-hint { font-size: 11px; color: #475569; }

    /* Floating toolbar */
    #enh-toolbar {
      position: fixed; bottom: 16px; right: 16px; z-index: 9000;
      display: flex; gap: 6px;
    }
    .enh-fab {
      background: rgba(15,23,42,0.85); backdrop-filter: blur(12px);
      border: 1px solid rgba(71,85,105,0.3); border-radius: 10px;
      padding: 6px 10px; cursor: pointer; font-size: 13px;
      color: #94a3b8; transition: all .2s; user-select: none;
      display: flex; align-items: center; gap: 5px;
    }
    .enh-fab:hover { border-color: rgba(99,102,241,0.6); color: #e2e8f0;
      background: rgba(99,102,241,0.15); }
    .enh-fab span { font-size: 10px; }

    /* Pin button on message bubble */
    .enh-pin-btn {
      position: absolute; top: 6px; right: -30px;
      background: rgba(15,23,42,0.9); border: 1px solid rgba(71,85,105,0.4);
      border-radius: 8px; padding: 3px 6px; cursor: pointer; font-size: 12px;
      color: #94a3b8; opacity: 0; transition: opacity .15s;
      z-index: 10;
    }
    .enh-pin-btn:hover { color: #fbbf24; border-color: rgba(251,191,36,0.5); }
    [data-pinned="true"] .enh-pin-btn { color: #fbbf24; opacity: 1; }

    /* Vault result badge */
    .vault-badge {
      display: inline-block; background: rgba(16,185,129,0.15);
      border: 1px solid rgba(16,185,129,0.3); border-radius: 6px;
      padding: 2px 8px; font-size: 11px; color: #34d399; margin-right: 6px;
    }

    /* Model indicator badge */
    .enh-model-badge {
      display: inline-flex; align-items: center; gap: 4px;
      font-size: 10px; color: rgba(148,163,184,0.5);
      margin-top: 6px; padding: 2px 8px;
      background: rgba(99,102,241,0.06);
      border: 1px solid rgba(99,102,241,0.15);
      border-radius: 20px; user-select: none;
      transition: opacity .2s;
    }
    .enh-model-badge:hover { color: rgba(148,163,184,0.85); }
    .enh-model-badge .enh-model-dot {
      width: 5px; height: 5px; border-radius: 50%;
      background: #6366f1; flex-shrink: 0;
    }

    /* Toast */
    #enh-toast {
      position: fixed; bottom: 64px; left: 50%; transform: translateX(-50%);
      background: rgba(15,23,42,0.95); border: 1px solid rgba(99,102,241,0.4);
      border-radius: 10px; padding: 8px 16px; font-size: 12px; color: #e2e8f0;
      z-index: 9999; opacity: 0; transition: opacity .3s; pointer-events: none;
    }
    #enh-toast.show { opacity: 1; }

    /* ── Chat bubble — global (all screen sizes) ───────────────── */
    /* ป้องกัน Thai text ล้นและ overflow */
    [class*="rounded-3xl"] {
      overflow-wrap: break-word !important;
      word-break: break-word !important;
      word-wrap: break-word !important;
    }
    [class*="rounded-3xl"] p,
    [class*="rounded-3xl"] div,
    [class*="rounded-3xl"] span {
      overflow-wrap: break-word !important;
      word-break: break-word !important;
    }
    /* leading สำหรับ Thai vowel marks — ป้องกันข้อความทับกัน */
    [class*="leading-relaxed"] {
      line-height: 1.75 !important;
    }

    /* ── Mobile responsive (< 640px) ───────────────────────────── */
    @media (max-width: 639px) {
      /* Login box */
      #login-box { padding: 28px 20px; border-radius: 18px; }

      /* ── iOS viewport lock — กัน 100vh ล้นจอ (header เลื่อน/input โดนตัด) ──
         body สูง = จอจริง (ตั้งโดย JS _fitMobileVH ด้านล่าง) แล้วไล่ chain
         body → #root → .h-screen ให้พอดีเป๊ะ, ล็อก overflow กัน pan ทั้งหน้า */
      html, body { overflow: hidden !important; }
      #root, .flex.h-screen { height: 100% !important; }
      /* main chat messages list ขาด min-h-0 → หดไม่ได้ → ล้น; ใส่ให้ scroll ในตัวเอง */
      .overflow-y-auto.space-y-5 { min-height: 0 !important; }

      /* Header — กัน item ล้นเกินจอ */
      /* header icons (🧩🌙🔗🤖🎙️📌): w-7 h-7 → 24x24 */
      h1[class*="text-sm"] ~ * button[class*="w-7"][class*="h-7"],
      .flex.items-center.gap-1 > button[class*="w-7"][class*="h-7"] {
        width: 24px !important;
        height: 24px !important;
        font-size: 11px !important;
      }
      /* header model badge: ห้ามล้น + ellipsis */
      .flex.items-center button[class*="text-\\[10px\\]"][class*="rounded-full"] {
        max-width: 100px !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
        white-space: nowrap !important;
        font-size: 9px !important;
        padding: 2px 6px !important;
      }
      /* status text ออนไลน์: ย่อ */
      .flex.items-center span[class*="text-\\[11px\\]"][class*="text-gray-500"] {
        font-size: 10px !important;
      }
      /* header icons row: gap เล็กลง */
      .flex.items-center.gap-1.flex-shrink-0 {
        gap: 2px !important;
      }
      /* outer header padding: ลดด้านข้าง */
      h1 + div, h1 ~ div { min-width: 0 !important; }

      /* Search / Vault overlay — nearly full-screen sheet */
      .enh-overlay { padding-top: 16px; align-items: flex-start; }
      .enh-box {
        width: calc(100vw - 24px) !important;
        max-height: 82vh; padding: 16px; border-radius: 16px;
      }

      /* Floating toolbar — ย้ายไปซ้ายมือ เรียงแนวตั้ง กลางหน้าจอ */
      #enh-toolbar {
        left: 4px !important;
        right: auto !important;
        bottom: auto !important;
        top: 50% !important;
        transform: translateY(-50%) !important;
        flex-direction: column !important;
        gap: 4px !important;
      }
      .enh-fab {
        padding: 0 !important;
        border-radius: 10px !important;
        font-size: 15px !important;
        line-height: 1 !important;
        justify-content: center !important;
        align-items: center !important;
        width: 32px !important;
        height: 32px !important;
        min-width: 32px !important;
      }
      .enh-fab span { display: none !important; }

      /* toolbar + home panel — ยกขึ้นเหนือ input + token bar */
      #enh-toolbar { bottom: 100px !important; right: 6px !important; }
      #hw-home-panel { width: calc(100vw - 24px); right: 12px; left: 12px; bottom: 144px; }

      /* Scroll-to-bottom button — เหนือปุ่มอื่น */
      #enh-scroll-btn { bottom: 148px !important; right: 6px !important; }

      /* ── Pin button (enh-js) — ซ่อนไว้ ใช้ React pin button แทน ── */
      .enh-pin-btn {
        display: none !important;
      }

      /* ── Chat bubble — layout ── */
      /* bubble wrapper max-width */
      [class*="max-w-\\[85\\%\\]"] {
        max-width: 88% !important;
      }
      /* bubble กัน content ล้น */
      [class*="rounded-3xl"] {
        min-width: 0 !important;
        max-width: 100% !important;
        overflow: visible !important;
        box-sizing: border-box !important;
      }
      /* font */
      [class*="text-\\[15px\\]"] {
        font-size: 14px !important;
        line-height: 1.8 !important;
      }

      /* ── Action buttons: เปลี่ยนจาก row ใต้ bubble → column ข้างๆ ── */

      /* content column (bubble + buttons): เปลี่ยนเป็น flex-row */
      .group > div.flex-col {
        flex-direction: row !important;
        align-items: flex-start !important;
        gap: 4px !important;
      }

      /* bubble div: ขยายเต็มพื้นที่ที่เหลือ */
      .group > div.flex-col > div[class*="rounded-3xl"] {
        flex: 1 1 auto !important;
        min-width: 0 !important;
      }

      /* action buttons row → เปลี่ยนเป็น column ด้านข้าง */
      .group > div.flex-col > div.flex.items-center {
        flex-direction: column !important;
        gap: 3px !important;
        align-items: center !important;
        justify-content: flex-start !important;
        flex-shrink: 0 !important;
        flex: 0 0 auto !important;
        align-self: flex-start !important;
        margin-top: 4px !important;
        width: 28px !important;
        order: 99 !important;
      }

      /* ปุ่มแต่ละอัน: ขนาดเท่ากันทุกปุ่ม แสดงตลอด ไม่มี text ส่วนเกิน */
      .group > div.flex-col > div.flex.items-center > button {
        opacity: 0.6 !important;
        padding: 0 !important;
        font-size: 13px !important;
        line-height: 1 !important;
        border-radius: 50% !important;
        width: 26px !important;
        height: 26px !important;
        min-width: 26px !important;
        max-width: 26px !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        overflow: hidden !important;
        white-space: nowrap !important;
        text-indent: 0 !important;
        flex-shrink: 0 !important;
        text-align: center !important;
        box-sizing: border-box !important;
        letter-spacing: -2px !important;  /* บีบให้ "📌 Pin" → โชว์แค่ emoji */
      }

      /* user message: ปุ่มอยู่ซ้ายมือ */
      .group.justify-end > div.flex-col {
        flex-direction: row-reverse !important;
      }
      .group.justify-end > div.flex-col > div.flex.items-center {
        margin-right: 0 !important;
      }

      /* Token bar */
      #enh-token-bar { padding: 3px 10px; gap: 8px; }
      #enh-token-text { min-width: 0; font-size: 10px; }

      /* Typing indicator */
      #enh-typing { bottom: 28px; }
    }
  `;
  document.head.appendChild(css);

  // ── iOS mobile viewport fit: body สูง = window.innerHeight จริง (กัน 100vh pan) ──
  function _fitMobileVH() {
    const h = window.innerWidth < 640 ? window.innerHeight + "px" : "";
    document.documentElement.style.height = h;
    document.body.style.height = h;
  }
  ["resize", "orientationchange", "pageshow"].forEach(function (ev) {
    window.addEventListener(ev, _fitMobileVH);
  });
  _fitMobileVH();
  setTimeout(_fitMobileVH, 300);  // เผื่อ React mount/toolbar settle

  // ── Toast helper ────────────────────────────────────────────────────────────
  const toast = document.createElement("div");
  toast.id = "enh-toast";
  document.body.appendChild(toast);

  function showToast(msg, ms = 2500) {
    toast.textContent = msg;
    toast.classList.add("show");
    setTimeout(() => toast.classList.remove("show"), ms);
  }

  // ── Helpers ─────────────────────────────────────────────────────────────────
  function esc(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function highlight(text, q) {
    if (!q) return esc(text);
    const re = new RegExp(`(${q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "gi");
    return esc(text).replace(re, "<mark>$1</mark>");
  }

  // ─────────────────────────────────────────────────────────────────────────────
  // 0. AUTH — Login modal (แสดงเมื่อ UI_PASSWORD ตั้งค่าไว้และยังไม่ได้ login)
  // ─────────────────────────────────────────────────────────────────────────────
  const loginOverlay = document.createElement("div");
  loginOverlay.id = "login-overlay";
  loginOverlay.innerHTML = `
    <div id="login-box">
      <h2>🔐 Hybrid AI Workspace</h2>
      <p>กรุณาใส่รหัสผ่านเพื่อเข้าใช้งาน</p>
      <input id="login-input" type="password" placeholder="••••••••" autocomplete="current-password">
      <button id="login-btn">เข้าสู่ระบบ</button>
      <div id="login-err"></div>
    </div>`;
  document.body.appendChild(loginOverlay);

  async function doLogin(pwd) {
    try {
      const r = await _origFetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: pwd }),
      });
      const d = await r.json();
      if (d.ok) {
        _authToken = d.token;
        localStorage.setItem("hw_auth_token", _authToken);
        loginOverlay.classList.remove("open");
        // reload เพื่อให้ React โหลด session ใหม่ด้วย token
        setTimeout(() => window.location.reload(), 100);
      } else {
        document.getElementById("login-err").textContent = d.error || "รหัสผ่านไม่ถูกต้อง";
      }
    } catch {
      document.getElementById("login-err").textContent = "เชื่อมต่อไม่ได้";
    }
  }

  document.getElementById("login-btn").addEventListener("click", () => {
    doLogin(document.getElementById("login-input").value);
  });
  document.getElementById("login-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") doLogin(e.target.value);
  });

  // ── เช็ค hostname synchronously ─────────────────────────────────────────────
  function _isLocalHost() {
    const h = window.location.hostname;
    return h === "localhost" || /^(192\.168\.|10\.|172\.|127\.)/.test(h);
  }

  function _openLogin() {
    loginOverlay.classList.add("open");
    setTimeout(() => document.getElementById("login-input")?.focus(), 50);
  }

  // Step 1 — แสดง modal ทันที ถ้าเป็น domain + ไม่มี token
  if (!_isLocalHost() && !_authToken) {
    _openLogin();
  }

  // Step 2 — validate token กับ server (จับกรณี token หมดอายุ/ผิด)
  (async () => {
    if (_isLocalHost()) return; // LAN ไม่ต้อง validate
    try {
      const r = await _origFetch("/api/auth/check", {
        headers: _authToken ? { "x-auth-token": _authToken } : {},
      });
      const d = await r.json();
      if (d.required && !d.ok) {
        // token ไม่ valid — clear แล้วโชว์ modal
        _authToken = "";
        localStorage.removeItem("hw_auth_token");
        _openLogin();
      }
    } catch {}
  })();

  // helper สีตาม % (ใช้ร่วมกับ home panel)
  function colorPct(pct) { return pct > 85 ? "#f87171" : pct > 65 ? "#fbbf24" : "#34d399"; }
  function barColor(pct)  { return pct > 85 ? "#f87171" : pct > 65 ? "#fbbf24" : "#6366f1"; }

  // ─────────────────────────────────────────────────────────────────────────────
  // 1.5 DREAM STATS — แทนค่า hardcoded 40/40/20% ด้วยข้อมูล dream cycle จริง
  //     (React bundle เป็น build แล้ว แก้ตรงไม่ได้ → overlay เขียนทับค่าใน DOM)
  // ─────────────────────────────────────────────────────────────────────────────
  const _DREAM_TITLES = {
    "Light Sleep": "Phase 1 — ความจำที่ดึงมาวิเคราะห์ (24 ชม.ล่าสุด)",
    "REM Sleep": "Phase 2 — ธีมที่ AI สกัดได้",
    "Deep Sleep": "Phase 3 — promote เข้า long-term memory",
  };
  let _dreamVals = null;

  function applyDreamStats(vals) {
    if (!vals) return;
    const map = { "Light Sleep": vals.light, "REM Sleep": vals.rem, "Deep Sleep": vals.deep };
    document.querySelectorAll("div, span").forEach((el) => {
      if (el.children.length > 0) return;                 // เอาเฉพาะ leaf (label จริง)
      const t = (el.textContent || "").trim();
      if (!(t in map)) return;
      const valEl = el.nextElementSibling;                // ค่า % เดิมเป็น sibling ถัดไป
      if (valEl && valEl !== el && valEl.children.length === 0) {
        const v = map[t];
        const next = v === "—" ? "—" : String(v);
        if (valEl.textContent !== next) {                 // เขียนเฉพาะตอนเปลี่ยน (กัน loop/flicker)
          valEl.textContent = next;
          valEl.style.opacity = "0.9";
        }
      }
      if (el.parentElement) el.parentElement.title = _DREAM_TITLES[t];
    });
  }

  async function fetchDreamStats() {
    try {
      const d = await _origFetch("/api/dream/report").then((r) => r.json());
      _dreamVals = (window.dreamCardValues || (() => null))(d);
      applyDreamStats(_dreamVals);
    } catch {}
  }
  fetchDreamStats();
  setInterval(fetchDreamStats, 300_000);                  // refetch ทุก 5 นาที (dream รันกลางคืน)
  setInterval(() => applyDreamStats(_dreamVals), 2_000);  // re-apply กัน React re-render ทับ

  // ─────────────────────────────────────────────────────────────────────────────
  // 2. GLOBAL CHAT SEARCH  (Ctrl+Shift+F)
  // ─────────────────────────────────────────────────────────────────────────────
  const searchOverlay = document.createElement("div");
  searchOverlay.className = "enh-overlay";
  searchOverlay.innerHTML = `
    <div class="enh-box" style="width:680px">
      <div class="enh-title">
        🔍 ค้นหาทุก Session
        <span class="enh-hint">Ctrl+Shift+F</span>
        <button class="enh-close" id="gs-close">✕</button>
      </div>
      <input class="enh-input" id="gs-input" placeholder="ค้นหาข้อความ… (Enter)">
      <div class="enh-results" id="gs-results" style="max-height:50vh">
        <div class="enh-empty">พิมพ์แล้วกด Enter เพื่อค้นหา</div>
      </div>
    </div>`;
  document.body.appendChild(searchOverlay);

  searchOverlay.addEventListener("click", (e) => {
    if (e.target === searchOverlay) searchOverlay.classList.remove("open");
  });
  document.getElementById("gs-close").addEventListener("click", () =>
    searchOverlay.classList.remove("open")
  );

  const gsInput = document.getElementById("gs-input");
  const gsResults = document.getElementById("gs-results");

  gsInput.addEventListener("keydown", async (e) => {
    if (e.key !== "Enter") return;
    const q = gsInput.value.trim();
    if (!q) return;
    gsResults.innerHTML = `<div class="enh-empty">กำลังค้นหา…</div>`;
    try {
      const r = await _origFetch(`/api/search?q=${encodeURIComponent(q)}&limit=30`);
      const data = await r.json();
      const hits = data.results || [];
      if (!hits.length) {
        gsResults.innerHTML = `<div class="enh-empty">ไม่พบผลลัพธ์</div>`;
        return;
      }
      gsResults.innerHTML = hits.map((h) => `
        <div class="enh-result">
          <div class="enh-result-meta">
            ${esc(h.assistant || "")} · ${esc(h.role || "")} ·
            ${esc((h.timestamp || "").slice(0, 16))}
          </div>
          <div class="enh-result-text">${highlight(
            (h.content || h.message || "").slice(0, 200), q
          )}</div>
        </div>`).join("");
    } catch {
      gsResults.innerHTML = `<div class="enh-empty">เกิดข้อผิดพลาด</div>`;
    }
  });

  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey && e.shiftKey && e.key === "F") {
      e.preventDefault();
      searchOverlay.classList.toggle("open");
      if (searchOverlay.classList.contains("open"))
        setTimeout(() => gsInput.focus(), 50);
    }
    if (e.key === "Escape") {
      searchOverlay.classList.remove("open");
      vaultOverlay.classList.remove("open");
    }
  });

  // ─────────────────────────────────────────────────────────────────────────────
  // 3. EXPORT SESSION  (Ctrl+E)
  // ─────────────────────────────────────────────────────────────────────────────
  async function doExport() {
    if (!ctx.assistant || !ctx.session) {
      showToast("⚠️ ยังไม่ได้แชท — ส่งข้อความก่อนแล้ว Export");
      return;
    }
    showToast("📤 กำลัง Export…");
    try {
      const r = await _origFetch(
        `/api/export/${encodeURIComponent(ctx.assistant)}/${encodeURIComponent(ctx.session)}`
      );
      const text = await r.text();
      const blob = new Blob([text], { type: "text/markdown" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `chat-${ctx.assistant}-${ctx.session.slice(-8)}.md`;
      a.click();
      URL.revokeObjectURL(url);
      showToast("✅ Export สำเร็จ");
    } catch {
      showToast("❌ Export ล้มเหลว");
    }
  }

  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey && e.key === "e" && !e.shiftKey) {
      e.preventDefault();
      doExport();
    }
  });

  // ─────────────────────────────────────────────────────────────────────────────
  // 4. PIN MESSAGE  (hover bubble → 📌)
  // ─────────────────────────────────────────────────────────────────────────────
  let _historyCache = [];

  async function refreshHistory() {
    if (!ctx.assistant || !ctx.session) return;
    try {
      const r = await _origFetch(
        `/api/history/${encodeURIComponent(ctx.assistant)}/${encodeURIComponent(ctx.session)}`
      );
      const data = await r.json();
      _historyCache = data.messages || data || [];
    } catch {}
  }

  async function pinMessage(content) {
    await refreshHistory();
    const msg = _historyCache.find(
      (m) => (m.content || m.message || "").trim() === content.trim()
    );
    if (!msg?.id && !msg?.db_id) {
      showToast("⚠️ ไม่พบ message ใน database");
      return;
    }
    const dbId = msg.id || msg.db_id;
    try {
      await _origFetch(`/api/pin/${dbId}`, { method: "POST" });
      showToast("📌 Pin แล้ว!");
    } catch {
      showToast("❌ Pin ล้มเหลว");
    }
  }

  // Observe DOM — ใช้ Tailwind class จริงจาก compiled React
  // AI bubble: div.flex.group.justify-start > div.rounded-3xl.rounded-tl-sm
  const pinObserver = new MutationObserver(() => {
    document.querySelectorAll("div.flex.group.justify-start").forEach((container) => {
      if (container.dataset.pinWired) return;
      const bubble = container.querySelector('[class*="rounded-3xl"]');
      if (!bubble) return;
      container.dataset.pinWired = "1";

      const btn = document.createElement("button");
      btn.className = "enh-pin-btn";
      btn.textContent = "📌";
      btn.title = "Pin message";

      bubble.style.position = "relative";
      bubble.appendChild(btn);

      container.addEventListener("mouseenter", () => (btn.style.opacity = "1"));
      container.addEventListener("mouseleave", () => (btn.style.opacity = "0"));

      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        pinMessage(bubble.innerText.replace("📌", "").trim());
      });
    });
  });

  // Start observing after React mounts
  window.addEventListener("load", () => {
    pinObserver.observe(document.getElementById("root"), {
      childList: true,
      subtree: true,
    });
  });

  // ─────────────────────────────────────────────────────────────────────────────
  // 5. @vault SEARCH  — พิมพ์ @vault <keyword> ใน textarea → inject note context
  // ─────────────────────────────────────────────────────────────────────────────
  const vaultOverlay = document.createElement("div");
  vaultOverlay.className = "enh-overlay";
  vaultOverlay.innerHTML = `
    <div class="enh-box">
      <div class="enh-title">
        🌿 Vault Search
        <span class="enh-hint">พิมพ์ @vault ใน chat หรือค้นหาที่นี่</span>
        <button class="enh-close" id="vs-close">✕</button>
      </div>
      <input class="enh-input" id="vs-input" placeholder="ค้นหาใน Obsidian vault…">
      <div class="enh-results" id="vs-results" style="max-height:50vh">
        <div class="enh-empty">พิมพ์แล้วกด Enter</div>
      </div>
    </div>`;
  document.body.appendChild(vaultOverlay);

  vaultOverlay.addEventListener("click", (e) => {
    if (e.target === vaultOverlay) vaultOverlay.classList.remove("open");
  });
  document.getElementById("vs-close").addEventListener("click", () =>
    vaultOverlay.classList.remove("open")
  );

  const vsInput = document.getElementById("vs-input");
  const vsResults = document.getElementById("vs-results");

  async function searchVault(q) {
    vsResults.innerHTML = `<div class="enh-empty">กำลังค้นหา…</div>`;
    try {
      const r = await _origFetch(`/api/vault/search?q=${encodeURIComponent(q)}`);
      const data = await r.json();
      const hits = data.results || [];
      if (!hits.length) {
        vsResults.innerHTML = `<div class="enh-empty">ไม่พบ note ที่ตรงกัน</div>`;
        return;
      }
      vsResults.innerHTML = hits.map((h) => `
        <div class="enh-result" data-content="${esc(h.content || "")}">
          <div class="enh-result-meta">
            <span class="vault-badge">📓 Vault</span>${esc(h.title || h.path || "")}
          </div>
          <div class="enh-result-text">${highlight(
            (h.content || h.snippet || "").slice(0, 250), q
          )}</div>
          <div style="font-size:11px;color:#6366f1;margin-top:4px">คลิกเพื่อคัดลอก content</div>
        </div>`).join("");

      vsResults.querySelectorAll(".enh-result").forEach((el) => {
        el.addEventListener("click", () => {
          const content = el.dataset.content;
          navigator.clipboard.writeText(content).then(() =>
            showToast("📋 คัดลอกแล้ว — วางใน chat ได้เลย")
          );
          vaultOverlay.classList.remove("open");
        });
      });
    } catch {
      vsResults.innerHTML = `<div class="enh-empty">เชื่อมต่อ Vault ไม่ได้</div>`;
    }
  }

  vsInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") searchVault(vsInput.value.trim());
  });

  // Detect @vault typing in any textarea/input in the page
  document.addEventListener("input", (e) => {
    const el = e.target;
    if (!["INPUT", "TEXTAREA"].includes(el.tagName)) return;
    const val = el.value;
    const match = val.match(/@vault\s+(.+)/i);
    if (!match) return;
    const q = match[1].trim();
    if (q.length < 2) return;
    // Auto-open vault search with the keyword
    vsInput.value = q;
    vaultOverlay.classList.add("open");
    vsInput.focus();
    searchVault(q);
  });

  // ─────────────────────────────────────────────────────────────────────────────
  // FLOATING TOOLBAR
  // ─────────────────────────────────────────────────────────────────────────────
  const toolbar = document.createElement("div");
  toolbar.id = "enh-toolbar";
  toolbar.innerHTML = `
    <button class="enh-fab" id="fab-home" title="Home — สถานะระบบ + บ้าน">
      🏠 <span>Home</span>
    </button>
    <button class="enh-fab" id="fab-search" title="ค้นหาทุก Session (Ctrl+Shift+F)">
      🔍 <span>Search</span>
    </button>
    <button class="enh-fab" id="fab-export" title="Export Session (Ctrl+E)">
      📤 <span>Export</span>
    </button>
    <button class="enh-fab" id="fab-vault" title="Vault Search" style="display:none">
      🌿 <span>Vault</span>
    </button>
    <button class="enh-fab" id="fab-agent" title="Agent Mode — AI ใช้ tools จริง (ค้นเว็บ, บ้าน, ไฟล์ ฯลฯ)">
      🤖 <span>Agent</span>
    </button>
    <button class="enh-fab" id="fab-claude" title="Claude (Anthropic)" style="display:none">
      ✨ <span>Claude</span>
    </button>`;
  document.body.appendChild(toolbar);

  // โหลด config จาก server — เปิดปุ่มเฉพาะที่พร้อมใช้จริง
  fetch("/config").then(r => r.json()).then(cfg => {
    if (cfg.has_anthropic) {
      const b = document.getElementById("fab-claude");
      if (b) b.style.display = "";
    }
    if (cfg.has_vault) {
      const b = document.getElementById("fab-vault");
      if (b) b.style.display = "";
    }
  }).catch(() => {});

  document.getElementById("fab-search").addEventListener("click", () => {
    searchOverlay.classList.toggle("open");
    if (searchOverlay.classList.contains("open"))
      setTimeout(() => gsInput.focus(), 50);
  });
  document.getElementById("fab-export").addEventListener("click", doExport);
  document.getElementById("fab-vault").addEventListener("click", () => {
    vaultOverlay.classList.toggle("open");
    if (vaultOverlay.classList.contains("open"))
      setTimeout(() => vsInput.focus(), 50);
  });

  // Agent Mode toggle
  const _agentBtn = document.getElementById("fab-agent");
  const _syncAgentBtn = () => _agentBtn.classList.toggle("enh-fab-active", _agentMode);
  // Claude Mode toggle
  const _claudeBtn = document.getElementById("fab-claude");
  const _syncClaudeBtn = () => _claudeBtn && _claudeBtn.classList.toggle("enh-fab-active", _claudeMode);
  _syncAgentBtn();
  _syncClaudeBtn();
  _agentBtn.addEventListener("click", () => {
    _agentMode = !_agentMode;
    localStorage.setItem("hw_agent_mode", _agentMode ? "1" : "0");
    _syncAgentBtn();
    // Agent กับ Claude ใช้พร้อมกันไม่ได้ — เปิด Agent → ปิด Claude
    if (_agentMode && _claudeMode) {
      _claudeMode = false;
      localStorage.setItem("hw_claude_mode", "0");
      _syncClaudeBtn();
    }
  });
  _claudeBtn && _claudeBtn.addEventListener("click", () => {
    _claudeMode = !_claudeMode;
    localStorage.setItem("hw_claude_mode", _claudeMode ? "1" : "0");
    _syncClaudeBtn();
    // เปิด Claude → ปิด Agent
    if (_claudeMode && _agentMode) {
      _agentMode = false;
      localStorage.setItem("hw_agent_mode", "0");
      _syncAgentBtn();
    }
  });

  // ─────────────────────────────────────────────────────────────────────────────
  // 6. COPY CODE BUTTON — เพิ่มปุ่ม copy บน code block อัตโนมัติ
  // ─────────────────────────────────────────────────────────────────────────────
  const copyCSS = `
    .enh-copy-wrap { position:relative; }
    .enh-copy-btn {
      position:absolute; top:8px; right:8px; opacity:0;
      background:rgba(30,41,59,0.9); border:1px solid rgba(99,102,241,0.4);
      border-radius:6px; padding:3px 8px; font-size:11px; color:#94a3b8;
      cursor:pointer; transition:opacity .15s; z-index:10;
    }
    .enh-copy-wrap:hover .enh-copy-btn { opacity:1; }
    .enh-copy-btn.copied { color:#34d399; border-color:rgba(52,211,153,0.5); }
  `;
  document.head.appendChild(Object.assign(document.createElement("style"), { textContent: copyCSS }));

  function _wireCopyButtons() {
    document.querySelectorAll("pre.md-pre").forEach((pre) => {
      if (pre.dataset.copyWired) return;
      pre.dataset.copyWired = "1";
      pre.classList.add("enh-copy-wrap");
      const btn = document.createElement("button");
      btn.className = "enh-copy-btn";
      btn.textContent = "Copy";
      btn.addEventListener("click", () => {
        const code = pre.querySelector("code")?.innerText || pre.innerText;
        navigator.clipboard.writeText(code).then(() => {
          btn.textContent = "✅ Copied";
          btn.classList.add("copied");
          setTimeout(() => { btn.textContent = "Copy"; btn.classList.remove("copied"); }, 2000);
        });
      });
      pre.appendChild(btn);
    });
  }

  new MutationObserver(_wireCopyButtons).observe(document.getElementById("root"), {
    childList: true, subtree: true,
  });

  // ─────────────────────────────────────────────────────────────────────────────
  // 7. STOP GENERATION — หยุด streaming กลางคัน
  // ─────────────────────────────────────────────────────────────────────────────
  let _stopBtn = null;

  // เพิ่มปุ่ม STOP ใน toolbar
  _stopBtn = document.createElement("button");
  _stopBtn.className = "enh-fab";
  _stopBtn.id = "fab-stop";
  _stopBtn.title = "หยุด AI (Stop)";
  _stopBtn.innerHTML = `⏹ <span>Stop</span>`;
  _stopBtn.style.display = "none";
  _stopBtn.style.background = "rgba(239,68,68,0.2)";
  _stopBtn.style.borderColor = "rgba(239,68,68,0.5)";
  _stopBtn.style.color = "#fca5a5";
  toolbar.insertBefore(_stopBtn, toolbar.firstChild);

  _stopBtn.addEventListener("click", () => {
    if (_abortCtrl) {
      _abortCtrl.abort();
      _abortCtrl = null;
    }
    _stopBtn.style.display = "none";
  });

  // ผูก ref stop button (DOM พร้อมแล้วตอนนี้)
  _stopBtnEl = _stopBtn;

  // ─────────────────────────────────────────────────────────────────────────────
  // 8. SCROLL TO BOTTOM BUTTON
  // ─────────────────────────────────────────────────────────────────────────────
  const scrollBtnCSS = `
    #enh-scroll-btn {
      position:fixed; bottom:70px; right:16px; z-index:8999;
      background:rgba(15,23,42,0.9); border:1px solid rgba(99,102,241,0.35);
      border-radius:50%; width:36px; height:36px; cursor:pointer;
      color:#94a3b8; font-size:16px; display:none;
      align-items:center; justify-content:center;
      transition:all .2s; backdrop-filter:blur(8px);
    }
    #enh-scroll-btn:hover { color:#e2e8f0; border-color:rgba(99,102,241,0.7); }
    #enh-scroll-btn.show { display:flex; }
  `;
  document.head.appendChild(Object.assign(document.createElement("style"), { textContent: scrollBtnCSS }));

  const scrollBtn = document.createElement("button");
  scrollBtn.id = "enh-scroll-btn";
  scrollBtn.textContent = "↓";
  scrollBtn.title = "ไปล่างสุด";
  document.body.appendChild(scrollBtn);

  function _getScrollContainer() {
    const el = document.querySelector("div.flex.group.justify-start, div.flex.group.justify-end");
    if (!el) return null;
    let p = el.parentElement;
    while (p && p !== document.body) {
      if (p.scrollHeight > p.clientHeight + 50) return p;
      p = p.parentElement;
    }
    return null;
  }

  let _scrollCont = null;
  window.addEventListener("load", () => {
    setTimeout(() => {
      _scrollCont = _getScrollContainer();
      if (_scrollCont) {
        _scrollCont.addEventListener("scroll", () => {
          const atBottom = _scrollCont.scrollHeight - _scrollCont.scrollTop - _scrollCont.clientHeight < 80;
          scrollBtn.classList.toggle("show", !atBottom);
        });
      }
    }, 2000);
  });

  scrollBtn.addEventListener("click", () => {
    if (!_scrollCont) _scrollCont = _getScrollContainer();
    _scrollCont?.scrollTo({ top: _scrollCont.scrollHeight, behavior: "smooth" });
  });

  // ─────────────────────────────────────────────────────────────────────────────
  // 9. TOKEN USAGE BAR — อ่านจาก localStorage ที่ React เก็บไว้
  // ─────────────────────────────────────────────────────────────────────────────
  const tokenCSS = `
    #enh-token-bar {
      position:fixed; bottom:0; left:0; right:0; z-index:8998;
      background:rgba(10,16,30,0.85); backdrop-filter:blur(8px);
      border-top:1px solid rgba(71,85,105,0.2);
      padding:3px 16px; display:flex; align-items:center; gap:12px;
      font-size:11px; color:#475569;
    }
    #enh-token-track {
      flex:1; height:3px; background:rgba(71,85,105,0.2); border-radius:2px; overflow:hidden;
    }
    #enh-token-fill {
      height:100%; border-radius:2px; background:#6366f1; transition:width .5s;
    }
    #enh-token-text { white-space:nowrap; min-width:100px; text-align:right; }
  `;
  document.head.appendChild(Object.assign(document.createElement("style"), { textContent: tokenCSS }));

  const tokenBar = document.createElement("div");
  tokenBar.id = "enh-token-bar";
  tokenBar.innerHTML = `
    <span>🔢 Context</span>
    <div id="enh-token-track"><div id="enh-token-fill" style="width:0%"></div></div>
    <span id="enh-token-text">— / —</span>`;
  document.body.appendChild(tokenBar);

  // นับ token แยก Thai / CJK / ASCII เพื่อความแม่นยำ
  function _countTokens(text) {
    let tokens = 0;
    for (const ch of text) {
      const cp = ch.codePointAt(0);
      if (cp >= 0x0E00 && cp <= 0x0E7F) tokens += 0.65;      // Thai
      else if (cp > 0x00FF)              tokens += 0.5;       // CJK / Unicode
      else                               tokens += 0.3;       // ASCII
    }
    return Math.round(tokens);
  }

  function _updateTokenBar() {
    try {
      const msgs = document.querySelectorAll("p.whitespace-pre-wrap, p[class*='whitespace-pre']");
      if (!msgs.length) return;
      let text = "";
      msgs.forEach(p => { text += (p.innerText || ""); });
      const estimated = _countTokens(text);
      // ดึง limit จาก /api/status ที่ React เคย load (หรือ fallback)
      const statusRaw = localStorage.getItem("hw_status_cache");
      const limit = statusRaw ? (JSON.parse(statusRaw).context_limit || 4096) : 4096;
      const pct = Math.min(100, Math.round(estimated / limit * 100));
      const fill = document.getElementById("enh-token-fill");
      const textEl = document.getElementById("enh-token-text");
      if (fill) {
        fill.style.width = pct + "%";
        fill.style.background = pct > 85 ? "#ef4444" : pct > 65 ? "#f59e0b" : "#6366f1";
      }
      if (textEl) textEl.textContent = `~${estimated.toLocaleString()} / ${limit.toLocaleString()} tokens`;
    } catch {}
  }

  setInterval(_updateTokenBar, 3000);
  setTimeout(_updateTokenBar, 3000); // รอ React render ก่อน

  // ─────────────────────────────────────────────────────────────────────────────
  // 10. PROMPT HISTORY — ↑/↓ เรียก prompt ก่อนหน้า (เหมือน terminal)
  // ─────────────────────────────────────────────────────────────────────────────
  // (ตัวแปรและ tracking อยู่ใน unified fetch override แล้ว)

  // ↑/↓ ใน input หรือ textarea (chat ใช้ input[type="text"])
  function _isChatInput(el) {
    return (el.tagName === "TEXTAREA" || el.tagName === "INPUT") &&
           (el.placeholder?.includes("ส่งความคิดให้") || el.placeholder?.includes("สั่งงาน"));
  }

  document.addEventListener("keydown", (e) => {
    const ta = e.target;
    if (!_isChatInput(ta)) return;
    if (e.key === "ArrowUp" && !e.shiftKey) {
      if (_promptHistory.length === 0) return;
      e.preventDefault();
      if (_histIdx === -1) _draftPrompt = ta.value;
      _histIdx = Math.min(_histIdx + 1, _promptHistory.length - 1);
      ta.value = _promptHistory[_histIdx];
      ta.dispatchEvent(new Event("input", { bubbles: true }));
    } else if (e.key === "ArrowDown" && !e.shiftKey && _histIdx >= 0) {
      e.preventDefault();
      _histIdx--;
      ta.value = _histIdx < 0 ? _draftPrompt : _promptHistory[_histIdx];
      ta.dispatchEvent(new Event("input", { bubbles: true }));
    }
  });

  // ─────────────────────────────────────────────────────────────────────────────
  // 11. PASTE IMAGE FROM CLIPBOARD — วาง Ctrl+V ได้เลยไม่ต้องกด upload
  // ─────────────────────────────────────────────────────────────────────────────
  document.addEventListener("paste", async (e) => {
    const items = [...(e.clipboardData?.items || [])];
    const img = items.find(i => i.type.startsWith("image/"));
    if (!img) return;
    const ta = e.target;
    if (ta.tagName !== "TEXTAREA") return;
    e.preventDefault();
    showToast("📎 กำลัง upload รูปจาก clipboard…");
    const file = img.getAsFile();
    const form = new FormData();
    form.append("file", file, "clipboard.png");
    try {
      const r = await _origFetch("/api/upload", {
        method: "POST",
        headers: _authToken ? { "x-auth-token": _authToken } : {},
        body: form,
      });
      const d = await r.json();
      if (d.ok && d.is_image) {
        // เก็บ base64 ใน localStorage ชั่วคราว แล้วแจ้งผู้ใช้
        localStorage.setItem("hw_pending_image", JSON.stringify({ b64: d.b64, mime: d.mime }));
        showToast("✅ รูปพร้อมแล้ว — กด Send เพื่อส่ง");
      } else if (d.text) {
        ta.value += (ta.value ? "\n" : "") + d.text;
        ta.dispatchEvent(new Event("input", { bubbles: true }));
        showToast("✅ วางข้อความจาก clipboard แล้ว");
      }
    } catch {
      showToast("❌ Upload ล้มเหลว");
    }
  });

  // ─────────────────────────────────────────────────────────────────────────────
  // 12. TYPING INDICATOR — "กำลังคิด…" ก่อน chunk แรกถึง
  // ─────────────────────────────────────────────────────────────────────────────
  const typingCSS = `
    #enh-typing {
      position:fixed; bottom:52px; left:50%; transform:translateX(-50%);
      background:rgba(15,23,42,0.9); border:1px solid rgba(99,102,241,0.3);
      border-radius:20px; padding:6px 16px; font-size:12px; color:#94a3b8;
      z-index:8997; display:none; align-items:center; gap:8px;
      backdrop-filter:blur(8px); pointer-events:none;
    }
    #enh-typing.show { display:flex; }
    .enh-typing-dot {
      width:5px; height:5px; border-radius:50%; background:#6366f1;
      animation:enh-dot-bounce 1.2s infinite;
    }
    .enh-typing-dot:nth-child(2) { animation-delay:.2s; }
    .enh-typing-dot:nth-child(3) { animation-delay:.4s; }
    @keyframes enh-dot-bounce {
      0%,60%,100% { transform:translateY(0); }
      30% { transform:translateY(-6px); }
    }
  `;
  document.head.appendChild(Object.assign(document.createElement("style"), { textContent: typingCSS }));

  const typingEl = document.createElement("div");
  typingEl.id = "enh-typing";
  typingEl.innerHTML = `
    <div class="enh-typing-dot"></div>
    <div class="enh-typing-dot"></div>
    <div class="enh-typing-dot"></div>
    <span>AI กำลังคิด…</span>`;
  document.body.appendChild(typingEl);

  // ผูก ref typing element (unified fetch override จะใช้ผ่าน _typingElRef)
  _typingElRef = typingEl;

  // ─────────────────────────────────────────────────────────────────────────────
  // 13. CHAT INPUT + BUTTON IMPROVEMENTS
  // ─────────────────────────────────────────────────────────────────────────────
  const chatCSS = `
    /* ── Chat input glow on focus ── */
    input[placeholder*="ส่งความคิดให้"]:focus,
    input[placeholder*="สั่งงาน"]:focus {
      box-shadow:
        0 0 0 1.5px rgba(139,92,246,0.55),
        0 0 24px rgba(99,102,241,0.18),
        inset 0 1px 0 rgba(255,255,255,0.06) !important;
      outline: none !important;
    }

    /* placeholder สว่างขึ้น */
    input[placeholder*="ส่งความคิดให้"]::placeholder,
    input[placeholder*="สั่งงาน"]::placeholder {
      color: rgba(148,163,184,0.55) !important;
    }

    /* ── Icon buttons ในแถบ input (w-7 h-7 rounded-full) ── */
    button.w-7.h-7.rounded-full {
      transition: all 0.2s !important;
      position: relative;
    }
    button.w-7.h-7.rounded-full:hover {
      transform: scale(1.15);
      filter: brightness(1.3);
    }

    /* Tooltip บน icon buttons */
    button.w-7.h-7.rounded-full[title]:hover::after {
      content: attr(title);
      position: absolute;
      bottom: calc(100% + 8px);
      left: 50%;
      transform: translateX(-50%);
      background: rgba(15,23,42,0.95);
      border: 1px solid rgba(99,102,241,0.3);
      border-radius: 8px;
      padding: 4px 10px;
      font-size: 11px;
      color: #e2e8f0;
      white-space: nowrap;
      z-index: 9500;
      pointer-events: none;
    }

    /* Send button ปุ่มส่ง */
    button[class*="rounded-full"][class*="pr"] svg,
    button[class*="rounded-full"] svg {
      transition: transform 0.2s;
    }
    button[class*="rounded-full"]:not(:disabled):hover svg {
      transform: translateX(2px) scale(1.05);
    }

    /* ── Toolbar pill buttons (text-[11px] px-3 py-1 rounded-full) ── */
    .text-\\[11px\\].px-3.py-1.rounded-full {
      transition: all 0.15s !important;
    }
    .text-\\[11px\\].px-3.py-1.rounded-full:hover {
      transform: translateY(-1px);
      filter: brightness(1.2);
    }

    /* ── Pulse animation บน token bar เมื่อใกล้เต็ม ── */
    #enh-token-fill[style*="ef4444"] {
      animation: token-pulse 1.5s ease-in-out infinite;
    }
    @keyframes token-pulse {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.6; }
    }
  `;
  document.head.appendChild(
    Object.assign(document.createElement("style"), { textContent: chatCSS })
  );

  // ─────────────────────────────────────────────────────────────────────────────
  // 14. HOME PANEL — System Health + NAS + Docker + PC + WoL (รวมใน FAB 🏠)
  // ─────────────────────────────────────────────────────────────────────────────
  document.head.insertAdjacentHTML("beforeend", `<style>
    #hw-home-panel {
      position:fixed; bottom:52px; right:16px; z-index:9299;
      width:min(320px, calc(100vw - 32px)); max-height:80vh; overflow-y:auto;
      background:rgba(8,12,24,0.97); border:1px solid rgba(99,102,241,0.35);
      border-radius:16px; backdrop-filter:blur(20px);
      padding:14px 14px 12px; display:none; flex-direction:column; gap:8px;
      box-shadow:0 12px 40px rgba(0,0,0,0.6); color:#e2e8f0; font-size:12px;
    }
    #hw-home-panel.show { display:flex; }
    .hw-h { font-size:10px; color:#6366f1; font-weight:700; letter-spacing:.06em; text-transform:uppercase; }
    .hw-sep { border:none; border-top:1px solid rgba(255,255,255,0.07); margin:1px 0; }
    .hw-btn {
      flex:1; padding:5px 6px; border-radius:8px; border:none; cursor:pointer;
      font-size:11px; font-weight:600; transition:all .18s;
    }
    .hw-g { background:rgba(16,185,129,.12); color:#34d399; border:1px solid rgba(16,185,129,.3); }
    .hw-g:hover { background:rgba(16,185,129,.22); }
    .hw-o { background:rgba(251,146,60,.12); color:#fb923c; border:1px solid rgba(251,146,60,.3); }
    .hw-o:hover { background:rgba(251,146,60,.22); }
    .hw-b { background:rgba(99,102,241,.12); color:#818cf8; border:1px solid rgba(99,102,241,.3); }
    .hw-b:hover { background:rgba(99,102,241,.22); }
    .hw-bar { height:4px; border-radius:2px; background:rgba(255,255,255,0.07); margin-top:3px; }
    .hw-bar-fill { height:100%; border-radius:2px; transition:width .5s; }
  </style>`);

  const hcPanel = document.createElement("div");
  hcPanel.id = "hw-home-panel";
  document.body.appendChild(hcPanel);

  function _hwBarColor(p) { return p > 85 ? "#ef4444" : p > 65 ? "#f59e0b" : "#10b981"; }

  function _hwRender() {
    hcPanel.innerHTML = `
      <div style="display:flex;align-items:center;gap:6px;margin-bottom:2px">
        <span style="font-size:14px">🏠</span>
        <span style="font-weight:700;font-size:13px;flex:1">Home</span>
        <span id="hw-ts" style="font-size:10px;color:#475569">—</span>
        <button id="hw-x" style="background:none;border:none;color:#64748b;cursor:pointer;font-size:13px;padding:0 0 0 8px">✕</button>
      </div>
      <hr class="hw-sep">

      <div class="hw-h">📊 System</div>
      <div id="hw-sys" style="color:#64748b;font-size:11px">กำลังโหลด…</div>
      <hr class="hw-sep">

      <div class="hw-h">💾 NAS Storage</div>
      <div id="hw-disk" style="color:#64748b;font-size:11px">กำลังโหลด…</div>
      <hr class="hw-sep">

      <div class="hw-h">🐳 Docker</div>
      <div id="hw-docker" style="color:#64748b;font-size:11px">กำลังโหลด…</div>
      <hr class="hw-sep">

      <div class="hw-h">🖥️ PC</div>
      <div id="hw-pc" style="color:#64748b;font-size:11px">กำลัง ping…</div>
      <hr class="hw-sep">

      <div style="display:flex;gap:6px">
        <button id="hw-refresh" class="hw-btn hw-g">🔄 Refresh</button>
        <button id="hw-wol" class="hw-btn hw-o">⚡ Wake PC</button>
        <button id="hw-pingnas" class="hw-btn hw-b">📡 NAS</button>
      </div>`;

    document.getElementById("hw-x").addEventListener("click", _hwClose);
    document.getElementById("hw-refresh").addEventListener("click", _hwRefresh);
    document.getElementById("hw-wol").addEventListener("click", _hwWol);
    document.getElementById("hw-pingnas").addEventListener("click", _hwPingNAS);
  }

  let _hwOpen = false;
  const _fabHome = document.getElementById("fab-home");

  function _hwClose() {
    hcPanel.classList.remove("show");
    _fabHome && _fabHome.classList.remove("enh-fab-active");
    _hwOpen = false;
  }
  function _hwToggle(e) {
    e.stopPropagation();
    if (_hwOpen) { _hwClose(); return; }
    _hwOpen = true;
    _hwRender();
    hcPanel.classList.add("show");
    _fabHome && _fabHome.classList.add("enh-fab-active");
    _hwRefresh();
  }

  _fabHome && _fabHome.addEventListener("click", _hwToggle);
  document.addEventListener("click", (e) => {
    if (_hwOpen && !hcPanel.contains(e.target) && e.target !== _fabHome && !(_fabHome && _fabHome.contains(e.target)))
      _hwClose();
  });

  async function _hwRefresh() {
    const h = _authToken ? { "x-auth-token": _authToken } : {};

    // system health (RAM + ChromaDB + Skills)
    try {
      const d = await _origFetch("/api/health", { headers: h }).then(x => x.json());
      const el = document.getElementById("hw-sys"); if (!el) return;
      const ram = d.ram || {};
      const chroma = d.chromadb || {};
      const rc = _hwBarColor(ram.used_pct);
      el.innerHTML = `
        <div style="display:flex;justify-content:space-between;margin-bottom:2px">
          <span style="color:#94a3b8">🧠 RAM</span>
          <span style="color:${rc};font-weight:600">${ram.used_mb ?? "?"}/${ram.total_mb ?? "?"}MB</span>
        </div>
        <div class="hw-bar"><div class="hw-bar-fill" style="width:${ram.used_pct ?? 0}%;background:${rc}"></div></div>
        <div style="display:flex;justify-content:space-between;margin-top:4px">
          <span style="color:#94a3b8">🔵 ChromaDB</span>
          <span style="color:${chroma.available?"#34d399":"#f87171"}">${chroma.available ? "Online" : "Offline"}</span>
        </div>
        <div style="display:flex;justify-content:space-between">
          <span style="color:#94a3b8">📚 Skills</span>
          <span style="color:#e2e8f0">${d.skills_count ?? 0}</span>
        </div>`;
    } catch(e) { const el=document.getElementById("hw-sys"); if(el) el.textContent="❌ " + e.message; }

    // disk
    try {
      const r = await _origFetch("/api/tools/home/disk", { headers: h }).then(x => x.json());
      const el = document.getElementById("hw-disk"); if (!el) return;
      if (r.error) { el.textContent = "❌ " + r.error; }
      else if (!r.volumes?.length) { el.textContent = "ไม่พบข้อมูล volume"; }
      else {
        el.innerHTML = r.volumes.map(v => {
          const c = _hwBarColor(v.percent);
          return `<div style="margin-bottom:4px">
            <div style="display:flex;justify-content:space-between">
              <span style="color:#94a3b8">${v.path}</span>
              <span style="color:${c};font-weight:600">${v.free_gb}GB ว่าง</span>
            </div>
            <div class="hw-bar"><div class="hw-bar-fill" style="width:${v.percent}%;background:${c}"></div></div>
          </div>`;
        }).join("");
      }
    } catch(e) { const el=document.getElementById("hw-disk"); if(el) el.textContent="❌ " + e.message; }

    // docker
    try {
      const r = await _origFetch("/api/tools/home/docker", { headers: h }).then(x => x.json());
      const el = document.getElementById("hw-docker"); if (!el) return;
      if (r.error) { el.textContent = "❌ " + r.error; }
      else {
        const cs = r.containers || [];
        el.innerHTML = cs.length ? cs.map(c =>
          `<div style="display:flex;align-items:center;gap:6px;margin-bottom:2px">
            <span>${c.running?"🟢":"🔴"}</span>
            <span style="flex:1;color:${c.running?"#e2e8f0":"#475569"}">${c.name}</span>
            <span style="color:#334155;font-size:10px">${c.status}</span>
          </div>`).join("") : "ไม่พบ container";
      }
    } catch(e) { const el=document.getElementById("hw-docker"); if(el) el.textContent="❌ " + e.message; }

    // ping PC
    try {
      const r = await _origFetch("/api/tools/home/ping/192.168.51.235", { headers: h }).then(x => x.json());
      const el = document.getElementById("hw-pc"); if (!el) return;
      const lat = r.latency_ms != null ? ` · ${r.latency_ms.toFixed(1)}ms` : "";
      el.innerHTML = r.online
        ? `<span style="color:#34d399">🟢 Online${lat}</span>`
        : `<span style="color:#ef4444">🔴 Offline</span>`;
    } catch(e) { const el=document.getElementById("hw-pc"); if(el) el.textContent="❌ " + e.message; }

    const ts = document.getElementById("hw-ts");
    if (ts) ts.textContent = new Date().toLocaleTimeString("th-TH",{hour:"2-digit",minute:"2-digit"});
  }

  async function _hwWol() {
    const btn = document.getElementById("hw-wol"); if (!btn) return;
    btn.textContent = "⏳…"; btn.disabled = true;
    try {
      const h = { "Content-Type": "application/json", ...(_authToken ? { "x-auth-token": _authToken } : {}) };
      const r = await _origFetch("/api/tools/home/wol", { method: "POST", headers: h }).then(x => x.json());
      btn.textContent = r.ok ? "✅ ส่งแล้ว!" : "❌ Error";
      if (r.ok) setTimeout(_hwRefresh, 35000);
    } catch { btn.textContent = "❌ Error"; }
    setTimeout(() => { if(btn){btn.textContent="⚡ Wake PC";btn.disabled=false;} }, 5000);
  }

  async function _hwPingNAS() {
    const btn = document.getElementById("hw-pingnas"); if (!btn) return;
    btn.textContent = "⏳…"; btn.disabled = true;
    try {
      const h = _authToken ? { "x-auth-token": _authToken } : {};
      const r = await _origFetch("/api/tools/home/ping/192.168.51.49", { headers: h }).then(x => x.json());
      const lat = r.latency_ms != null ? ` ${r.latency_ms.toFixed(1)}ms` : "";
      btn.textContent = r.online ? `📡 OK${lat}` : "📡 Offline";
    } catch { btn.textContent = "📡 Error"; }
    setTimeout(() => { if(btn){btn.textContent="📡 NAS";btn.disabled=false;} }, 4000);
  }

  // ─────────────────────────────────────────────────────────────────────────────
  // 15. MODEL INDICATOR — badge ใต้ AI message (อ่านจาก X-Model-Used header)
  // ─────────────────────────────────────────────────────────────────────────────
  const _PROVIDER_ICONS = { lmstudio: "🖥️", gemini: "☁️", ollama: "🦙", claude: "✨" };
  let _pendingModel = null;   // { model, provider } รอ inject หลัง response จบ

  function _injectModelBadge() {
    if (!_pendingModel) return;
    const { model, provider } = _pendingModel;
    _pendingModel = null;
    const bubbles = document.querySelectorAll("div.flex.group.justify-start");
    if (!bubbles.length) return;
    const last = bubbles[bubbles.length - 1];
    if (last.querySelector(".enh-model-badge")) return;
    const bubble = last.querySelector('[class*="rounded-3xl"]') || last;
    const icon = _PROVIDER_ICONS[provider] || "🤖";
    const badge = document.createElement("div");
    badge.className = "enh-model-badge";
    badge.innerHTML = `<span class="enh-model-dot"></span>${icon} ${model || provider}`;
    badge.title = `provider: ${provider}, model: ${model}`;
    bubble.appendChild(badge);
  }

  // อ่าน model จาก response header — ไม่ต้องแตะ stream body เลย
  const _fetchForModel = window.fetch.bind(window);
  window.fetch = function(url, opts) {
    const p = _fetchForModel(url, opts);
    if (typeof url === "string" && url.includes("/api/chat")) {
      p.then(resp => {
        const model    = resp.headers.get("x-model-used") || "";
        const provider = resp.headers.get("x-provider-used") || "";
        if (model || provider) {
          _pendingModel = { model, provider };
          // inject badge หลัง streaming จบ (poll จาก stop button logic)
          const iv = setInterval(() => {
            if (!_stopBtnEl || _stopBtnEl.style.display === "none") {
              clearInterval(iv);
              setTimeout(_injectModelBadge, 200);
            }
          }, 300);
          setTimeout(() => clearInterval(iv), 120000);
        }
      }).catch(() => {});
    }
    return p;
  };

  // ─────────────────────────────────────────────────────────────────────────────
  // 16. แทน "🦙 Llama" badge ด้วยชื่อ model จริงจาก /api/config
  // ─────────────────────────────────────────────────────────────────────────────
  (async () => {
    try {
      const cfg = await _origFetch("/api/config").then(r => r.json());
      const modelName = cfg?.ollama_model || "";
      if (!modelName || modelName === "llama3") return;
      // ตัดเอาแค่ชื่อ model สั้นๆ — รองรับมือถือ max 12 chars
      let shortName = modelName.split("/").pop();
      // ถ้า meta-llama-3.1-8b-instruct → llama-3.1-8b
      shortName = shortName
        .replace(/^meta-/, "")
        .replace(/-instruct$/i, "")
        .replace(/-chat$/i, "");
      if (shortName.length > 14) shortName = shortName.slice(0, 12) + "…";

      // Observer แทนที่ "🦙 Llama" ทุกครั้งที่ React render
      const _labelObs = new MutationObserver(() => {
        document.querySelectorAll("button, span, div").forEach(el => {
          if (el.childNodes.length === 1 &&
              el.childNodes[0].nodeType === 3 &&
              el.childNodes[0].textContent.trim() === "🦙 Llama") {
            el.childNodes[0].textContent = `🖥️ ${shortName}`;
          }
        });
      });
      _labelObs.observe(document.body, { childList: true, subtree: true, characterData: true });
    } catch {}
  })();

  // ─────────────────────────────────────────────────────────────────────────────
  // 17. AGENT MODE — Timeline UI สำหรับ tool calls
  // ─────────────────────────────────────────────────────────────────────────────
  const _agentCSS = document.createElement("style");
  _agentCSS.textContent = `
    .enh-fab-active {
      background: linear-gradient(135deg, rgba(168,85,247,0.4), rgba(236,72,153,0.3)) !important;
      border-color: rgba(168,85,247,0.6) !important;
      color: #f5d0fe !important;
      box-shadow: 0 0 12px rgba(168,85,247,0.4);
    }
    .enh-agent-timeline {
      margin: 8px 0 12px 0;
      padding: 10px 14px;
      background: linear-gradient(135deg, rgba(168,85,247,0.06), rgba(99,102,241,0.04));
      border: 1px solid rgba(168,85,247,0.25);
      border-radius: 12px;
      font-size: 0.78rem;
      line-height: 1.5;
      color: #cbd5e1;
      font-family: 'Sora', sans-serif;
    }
    .enh-agent-timeline-header {
      display: flex; align-items: center; gap: 6px;
      font-weight: 600; color: #c4b5fd;
      margin-bottom: 8px; font-size: 0.72rem;
      text-transform: uppercase; letter-spacing: 0.05em;
    }
    .enh-agent-step {
      padding: 4px 0;
      display: flex; gap: 8px; align-items: flex-start;
      border-left: 2px solid rgba(168,85,247,0.2);
      padding-left: 10px; margin-left: 4px;
      transition: all .2s;
    }
    .enh-agent-step-icon { flex-shrink: 0; font-size: 0.9rem; }
    .enh-agent-step-content { flex: 1; min-width: 0; }
    .enh-agent-step-title { color: #e2e8f0; font-weight: 500; }
    .enh-agent-step-meta { color: rgba(148,163,184,0.6); font-size: 0.7rem; margin-top: 2px; }
    .enh-agent-tool-args {
      color: #93c5fd; font-family: 'JetBrains Mono', monospace;
      font-size: 0.7rem;
      background: rgba(0,0,0,0.25);
      padding: 1px 6px; border-radius: 4px;
      display: inline-block; margin-top: 2px;
    }
    .enh-agent-tool-result {
      color: rgba(203,213,225,0.85);
      background: rgba(0,0,0,0.2);
      padding: 6px 10px; border-radius: 6px;
      margin-top: 4px;
      max-height: 80px; overflow: hidden;
      position: relative;
      cursor: pointer;
      transition: max-height .25s ease;
    }
    .enh-agent-tool-result.expanded { max-height: 400px; overflow-y: auto; }
    .enh-agent-tool-result:not(.expanded)::after {
      content: ""; position: absolute; left:0; right:0; bottom:0; height: 28px;
      background: linear-gradient(transparent, rgba(15,23,42,0.95));
      pointer-events: none;
    }
    .enh-agent-step.error { border-left-color: #ef4444; }
    .enh-agent-step.error .enh-agent-step-title { color: #fca5a5; }
  `;
  document.head.appendChild(_agentCSS);

  // อ่าน SSE จาก stream — เก็บ agent events ลง _pendingAgentTimeline
  async function _parseAgentSSE(stream, timelineRef) {
    const reader = stream.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() || "";
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const d = JSON.parse(line.slice(6));
            if (d.agent) {
              timelineRef.events.push(d.agent);
              _tryRenderTimeline(timelineRef);
            } else if (d.done) {
              // mark done — final render
              timelineRef.done = true;
              _tryRenderTimeline(timelineRef);
            }
          } catch {}
        }
      }
    } catch (e) {
      console.warn("[Agent] SSE parse error:", e);
    } finally {
      try { reader.releaseLock(); } catch {}
    }
  }

  // หา AI bubble ล่าสุดที่ยังไม่มี timeline แล้ว inject
  function _tryRenderTimeline(timelineRef) {
    if (!timelineRef.events.length) return;
    const bubbles = document.querySelectorAll("div.flex.group.justify-start");
    if (!bubbles.length) {
      // ยังไม่มี bubble — retry หลัง 200ms
      if (!timelineRef._retryTimer) {
        timelineRef._retryTimer = setTimeout(() => {
          timelineRef._retryTimer = null;
          _tryRenderTimeline(timelineRef);
        }, 200);
      }
      return;
    }
    const last = bubbles[bubbles.length - 1];
    const bubble = last.querySelector('[class*="rounded-3xl"]') || last;

    // find or create timeline container
    let card = bubble.querySelector(".enh-agent-timeline");
    if (!card) {
      card = document.createElement("div");
      card.className = "enh-agent-timeline";
      card.dataset.session = timelineRef.sessionToken;
      card.innerHTML = `<div class="enh-agent-timeline-header">🤖 Agent Steps</div><div class="enh-agent-steps"></div>`;
      // prepend ก่อน text content ใน bubble
      bubble.insertBefore(card, bubble.firstChild);
    } else if (card.dataset.session !== timelineRef.sessionToken) {
      // bubble นี้เป็น session อื่น — skip
      return;
    }

    const stepsEl = card.querySelector(".enh-agent-steps");
    const rendered = parseInt(stepsEl.dataset.rendered || "0", 10);
    for (let i = rendered; i < timelineRef.events.length; i++) {
      const ev = timelineRef.events[i];
      const stepEl = _renderAgentEvent(ev);
      if (stepEl) stepsEl.appendChild(stepEl);
    }
    stepsEl.dataset.rendered = String(timelineRef.events.length);
  }

  function _renderAgentEvent(ev) {
    const t = ev.type;
    const el = document.createElement("div");
    el.className = "enh-agent-step";
    if (t === "thinking") {
      el.innerHTML = `<span class="enh-agent-step-icon">🤔</span>
        <div class="enh-agent-step-content">
          <div class="enh-agent-step-title">คิดขั้นที่ ${ev.step}</div>
        </div>`;
    } else if (t === "tool_call") {
      const argsStr = Object.keys(ev.args || {}).length
        ? `(${Object.entries(ev.args).map(([k,v]) => `${k}=${JSON.stringify(v)}`).join(", ")})`
        : "()";
      el.innerHTML = `<span class="enh-agent-step-icon">🔧</span>
        <div class="enh-agent-step-content">
          <div class="enh-agent-step-title">เรียก <code>${_esc(ev.name)}</code></div>
          <div class="enh-agent-tool-args">${_esc(argsStr)}</div>
        </div>`;
    } else if (t === "tool_result") {
      el.innerHTML = `<span class="enh-agent-step-icon">📥</span>
        <div class="enh-agent-step-content">
          <div class="enh-agent-step-title">ผลจาก <code>${_esc(ev.name)}</code></div>
          <div class="enh-agent-step-meta">${ev.length} ตัวอักษร — คลิกเพื่อดูเต็ม</div>
          <div class="enh-agent-tool-result">${_esc(ev.preview || "")}</div>
        </div>`;
      const resEl = el.querySelector(".enh-agent-tool-result");
      resEl.addEventListener("click", () => resEl.classList.toggle("expanded"));
    } else if (t === "answering") {
      el.innerHTML = `<span class="enh-agent-step-icon">💬</span>
        <div class="enh-agent-step-content">
          <div class="enh-agent-step-title">กำลังสรุปคำตอบ...</div>
        </div>`;
    } else if (t === "error") {
      el.className = "enh-agent-step error";
      el.innerHTML = `<span class="enh-agent-step-icon">❌</span>
        <div class="enh-agent-step-content">
          <div class="enh-agent-step-title">Error</div>
          <div class="enh-agent-step-meta">${_esc(ev.message || "")}</div>
        </div>`;
    } else if (t === "max_steps_reached") {
      el.innerHTML = `<span class="enh-agent-step-icon">⏱️</span>
        <div class="enh-agent-step-content">
          <div class="enh-agent-step-title">ใช้ครบ max steps — บังคับสรุป</div>
        </div>`;
    } else {
      return null;
    }
    return el;
  }

  function _esc(s) {
    return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
  }

  // ────────────────────────────────────────────────────────────────────────────
  // F2 — Frontend SSE event handlers
  // citations / reflection / cache_hit / active_learning / feedback
  // ────────────────────────────────────────────────────────────────────────────

  const _chatCSS = document.createElement("style");
  _chatCSS.textContent = `
    .enh-bubble-meta { margin-top: 10px; display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
    .enh-badge {
      display: inline-flex; align-items: center; gap: 4px;
      padding: 3px 8px; border-radius: 999px;
      font-size: 11px; font-weight: 500; line-height: 1;
      border: 1px solid transparent; cursor: default; user-select: none;
    }
    .enh-badge.cache  { background: rgba(34,197,94,0.12); border-color: rgba(34,197,94,0.35); color: #4ade80; }
    .enh-badge.refl-ok{ background: rgba(99,102,241,0.10); border-color: rgba(99,102,241,0.30); color: #a5b4fc; }
    .enh-badge.refl-warn{ background: rgba(251,191,36,0.10); border-color: rgba(251,191,36,0.35); color: #fbbf24; }
    .enh-badge.al     { background: rgba(168,85,247,0.10); border-color: rgba(168,85,247,0.30); color: #c4b5fd; }
    .enh-badge.timing { background: rgba(100,116,139,0.10); border-color: rgba(100,116,139,0.30); color: #94a3b8; font-family: ui-monospace, monospace; }

    .enh-citations {
      margin-top: 12px; padding: 10px 12px;
      background: rgba(15,23,42,0.45); border: 1px solid rgba(99,102,241,0.20);
      border-radius: 12px; font-size: 12px; color: #cbd5e1;
    }
    .enh-citations-title { font-weight: 600; color: #818cf8; margin-bottom: 6px; }
    .enh-cite-row { display: flex; gap: 6px; padding: 4px 0; align-items: baseline; }
    .enh-cite-id { color: #818cf8; font-weight: 700; flex-shrink: 0; }
    .enh-cite-source { color: #e2e8f0; }
    .enh-cite-source a { color: #60a5fa; text-decoration: none; }
    .enh-cite-source a:hover { text-decoration: underline; }
    .enh-cite-snippet { color: #94a3b8; margin-top: 2px; font-size: 11px; line-height: 1.4; }
    .enh-cite-score { color: #64748b; font-family: ui-monospace, monospace; font-size: 10px; }

    .enh-reflection {
      margin-top: 10px; padding: 10px 12px; border-radius: 12px;
      background: rgba(251,191,36,0.08); border: 1px solid rgba(251,191,36,0.30);
      font-size: 12px; color: #fcd34d;
    }
    .enh-reflection-title { font-weight: 600; margin-bottom: 4px; }
    .enh-reflection-revised {
      margin-top: 8px; padding: 8px 10px; border-radius: 8px;
      background: rgba(255,255,255,0.04); color: #e2e8f0;
      white-space: pre-wrap;
    }

    .enh-feedback { margin-top: 8px; display: flex; gap: 6px; }
    .enh-fb-btn {
      padding: 4px 10px; border-radius: 8px; font-size: 12px; cursor: pointer;
      background: rgba(30,41,59,0.6); border: 1px solid rgba(99,102,241,0.20);
      color: #94a3b8; transition: all .15s; user-select: none;
    }
    .enh-fb-btn:hover { color: #e2e8f0; border-color: rgba(99,102,241,0.45); }
    .enh-fb-btn.active.up   { color: #4ade80; border-color: rgba(34,197,94,0.5); background: rgba(34,197,94,0.12); }
    .enh-fb-btn.active.down { color: #f87171; border-color: rgba(248,113,113,0.5); background: rgba(248,113,113,0.12); }
    .enh-fb-btn:disabled { opacity: 0.6; cursor: wait; }
  `;
  document.head.appendChild(_chatCSS);

  // หา bubble AI ล่าสุด (รอจนกว่า React จะ render)
  function _findLatestAIBubble(retries = 12) {
    return new Promise((resolve) => {
      const tick = (n) => {
        const bubbles = document.querySelectorAll("div.flex.group.justify-start");
        if (bubbles.length) {
          const last = bubbles[bubbles.length - 1];
          const bubble = last.querySelector('[class*="rounded-3xl"]') || last;
          resolve(bubble);
        } else if (n > 0) {
          setTimeout(() => tick(n - 1), 250);
        } else {
          resolve(null);
        }
      };
      tick(retries);
    });
  }

  function _getOrCreateMeta(bubble) {
    let meta = bubble.querySelector(".enh-bubble-meta");
    if (!meta) {
      meta = document.createElement("div");
      meta.className = "enh-bubble-meta";
      bubble.appendChild(meta);
    }
    return meta;
  }

  function _renderCacheHit(bubble, hit) {
    const meta = _getOrCreateMeta(bubble);
    if (meta.querySelector(".enh-badge.cache")) return; // dedupe
    const b = document.createElement("span");
    b.className = "enh-badge cache";
    b.title = `จาก cache (sim=${hit.similarity}) ของคำถาม: ${hit.source_prompt}`;
    b.textContent = `⚡ cached (${Math.round(hit.similarity * 100)}%)`;
    meta.appendChild(b);
  }

  function _renderActiveLearning(bubble, al) {
    const meta = _getOrCreateMeta(bubble);
    if (meta.querySelector(".enh-badge.al")) return;
    const b = document.createElement("span");
    b.className = "enh-badge al";
    b.title = al.reason || "AI ต้องการข้อมูลเพิ่ม";
    b.textContent = "💭 ถามกลับ";
    meta.appendChild(b);
  }

  function _renderTiming(bubble, timings, model) {
    if (!timings || !Object.keys(timings).length) return;
    const meta = _getOrCreateMeta(bubble);
    if (meta.querySelector(".enh-badge.timing")) return;
    const b = document.createElement("span");
    b.className = "enh-badge timing";
    const parts = Object.entries(timings).map(([k, v]) => `${k}:${v}ms`).join(" ");
    b.title = parts;
    const total = Object.values(timings).reduce((a, v) => a + v, 0);
    b.textContent = `⏱ ${Math.round(total)}ms`;
    meta.appendChild(b);
  }

  function _renderCitations(bubble, items) {
    if (!items || !items.length) return;
    let card = bubble.querySelector(".enh-citations");
    if (card) card.remove(); // re-render ใหม่ทุกครั้ง
    card = document.createElement("div");
    card.className = "enh-citations";
    const rows = items.map((c) => {
      const url = c.url ? `<a href="${_esc(c.url)}" target="_blank" rel="noopener">${_esc(c.source)}</a>` : _esc(c.source);
      const scoreStr = c.score ? `<span class="enh-cite-score">${c.score}</span>` : "";
      return `<div class="enh-cite-row">
        <span class="enh-cite-id">[${c.id}]</span>
        <div style="flex:1;min-width:0;">
          <div><span class="enh-cite-source">${url}</span> ${scoreStr}</div>
          <div class="enh-cite-snippet">${_esc(c.snippet || "")}</div>
        </div>
      </div>`;
    }).join("");
    card.innerHTML = `<div class="enh-citations-title">📎 แหล่งอ้างอิง (${items.length})</div>${rows}`;
    bubble.appendChild(card);
  }

  function _renderReflection(bubble, refl) {
    if (!refl || refl.verdict === "ok") {
      // ไม่ render badge สำหรับ ok เพราะ noise
      return;
    }
    let card = bubble.querySelector(".enh-reflection");
    if (card) card.remove();
    card = document.createElement("div");
    card.className = "enh-reflection";
    const issues = (refl.issues || []).map((i) => `<li>${_esc(i)}</li>`).join("");
    const revised = refl.revised
      ? `<div class="enh-reflection-revised">${_esc(refl.revised)}</div>`
      : "";
    card.innerHTML = `
      <div class="enh-reflection-title">⚠️ Reflection (score: ${refl.score})</div>
      ${issues ? `<ul style="margin:4px 0 0 16px;padding:0">${issues}</ul>` : ""}
      ${revised}
    `;
    bubble.appendChild(card);
  }

  function _renderFeedback(bubble, messageId, assistant, sessionId) {
    if (!messageId || messageId <= 0) return;
    if (bubble.querySelector(".enh-feedback")) return;
    const wrap = document.createElement("div");
    wrap.className = "enh-feedback";
    wrap.innerHTML = `
      <button class="enh-fb-btn up" data-r="up" title="ตอบดี">👍</button>
      <button class="enh-fb-btn down" data-r="down" title="ตอบไม่ดี">👎</button>
    `;
    bubble.appendChild(wrap);

    wrap.addEventListener("click", async (ev) => {
      const btn = ev.target.closest(".enh-fb-btn");
      if (!btn) return;
      const rating = btn.dataset.r;
      const all = wrap.querySelectorAll(".enh-fb-btn");
      all.forEach((b) => { b.disabled = true; b.classList.remove("active"); });
      try {
        const r = await fetch("/api/feedback", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            assistant, session_id: sessionId, message_id: messageId, rating,
          }),
        });
        if (r.ok) {
          btn.classList.add("active");
        } else {
          console.warn("[Feedback] POST failed:", r.status);
        }
      } catch (e) {
        console.warn("[Feedback] error:", e);
      } finally {
        all.forEach((b) => { b.disabled = false; });
      }
    });
  }

  // อ่าน chat SSE — handle ทุก event types
  async function _parseChatSSE(stream, agentTimelineRef) {
    const reader = stream.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    const collected = {
      citations: null, reflection: null, cache_hit: null,
      active_learning: null, message_id: 0, timings: null, model: "",
      assistant: _getAssistantFromUrl(),
      session_id: _getSessionId(),
    };
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() || "";
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          let d;
          try { d = JSON.parse(line.slice(6)); } catch { continue; }

          // agent timeline (delegate to existing handler)
          if (d.agent && agentTimelineRef) {
            agentTimelineRef.events.push(d.agent);
            _tryRenderTimeline(agentTimelineRef);
            continue;
          }

          // new event types — render immediately if bubble exists, else collect
          if (d.cache_hit) collected.cache_hit = d.cache_hit;
          if (d.citations) collected.citations = d.citations;
          if (d.reflection) collected.reflection = d.reflection;
          if (d.active_learning) collected.active_learning = d.active_learning;
          if (d.done) {
            collected.message_id = d.message_id || 0;
            collected.timings = d.timings || null;
            collected.model = d.model || "";
            if (agentTimelineRef) { agentTimelineRef.done = true; _tryRenderTimeline(agentTimelineRef); }
          }
        }
      }
    } catch (e) {
      console.warn("[Chat SSE] parse error:", e);
    } finally {
      try { reader.releaseLock(); } catch {}
    }

    // หลัง stream จบ → render UI ทั้งหมดลง bubble ล่าสุด
    const bubble = await _findLatestAIBubble();
    if (!bubble) return;
    if (collected.cache_hit) _renderCacheHit(bubble, collected.cache_hit);
    if (collected.active_learning) _renderActiveLearning(bubble, collected.active_learning);
    if (collected.citations) _renderCitations(bubble, collected.citations);
    if (collected.reflection) _renderReflection(bubble, collected.reflection);
    if (collected.timings) _renderTiming(bubble, collected.timings, collected.model);
    // feedback 👍/👎 ย้ายไป render ใน React แล้ว (always-visible, กดได้บนมือถือ) — เลิก inject ที่นี่ กันปุ่มซ้ำ
    // _renderFeedback(bubble, collected.message_id, collected.assistant, collected.session_id);
  }

  function _getAssistantFromUrl() {
    // หา assistant จาก React state — fallback อ่านจาก URL ถ้ามี
    try {
      const m = location.hash.match(/assistant=([^&]+)/);
      if (m) return decodeURIComponent(m[1]);
    } catch {}
    return "kwan"; // sensible default
  }

  function _getSessionId() {
    try {
      const m = location.hash.match(/session=([^&]+)/);
      if (m) return decodeURIComponent(m[1]);
    } catch {}
    return "default";
  }

  // ─────────────────────────────────────────────────────────────────────────────
  // composer detector ใช้ร่วมกัน (token counter / draft / slash)
  //   N1 fix: เดิมจับ textarea ตัวไหนก็ได้ → หน้าที่มีหลาย textarea (settings) ทำงานผิดช่อง
  //   จับเฉพาะกล่องแชตหลัก: placeholder ของทุก assistant มี "ส่งความคิด...ได้เลย"
  //   fallback: ถ้าเป็น textarea เดียวในหน้า (กัน placeholder เปลี่ยน)
  // ─────────────────────────────────────────────────────────────────────────────
  function _isComposerEl(el) {
    if (!el) return false;
    const isTA = el.tagName === "TEXTAREA";
    if (!isTA && !el.isContentEditable) return false;
    const ph = (el.getAttribute && el.getAttribute("placeholder")) || el.placeholder || "";
    if (/ส่งความคิด|ได้เลย/.test(ph)) return true;
    return isTA && document.querySelectorAll("textarea").length === 1;
  }

  // ─────────────────────────────────────────────────────────────────────────────
  // TOKEN / CHAR COUNTER — pill ลอยมุมขวาบนของ textarea ที่กำลังพิมพ์
  //   event delegation → ทนต่อ React re-render; ~4 ตัวอักษร ≈ 1 token (ตาม approx_tokens)
  // ─────────────────────────────────────────────────────────────────────────────
  (function initTokenCounter() {
    const tcCss = `
      #enh-tokcount {
        position: fixed; z-index: 9999; pointer-events: none;
        font: 11px/1 ui-monospace, SFMono-Regular, Menlo, monospace;
        padding: 3px 8px; border-radius: 999px; white-space: nowrap;
        background: rgba(15,23,42,0.85); border: 1px solid rgba(99,102,241,0.35);
        color: #94a3b8; opacity: 0; transition: opacity .12s; backdrop-filter: blur(4px);
      }
      #enh-tokcount.show { opacity: 1; }
      #enh-tokcount.warn { color: #fbbf24; border-color: rgba(251,191,36,0.5); }
      #enh-tokcount.hot  { color: #f87171; border-color: rgba(248,113,113,0.6); }
    `;
    document.head.appendChild(Object.assign(document.createElement("style"), { textContent: tcCss }));

    const pill = document.createElement("div");
    pill.id = "enh-tokcount";
    document.body.appendChild(pill);

    let _activeTA = null;

    const _isComposer = _isComposerEl;   // N1: เฉพาะกล่องแชตหลัก

    const _textOf = (el) =>
      el.value != null ? el.value : (el.innerText || "");

    function _update(el) {
      const len = _textOf(el).length;
      if (!len) { pill.classList.remove("show"); return; }
      const toks = Math.max(1, Math.ceil(len / 4));   // ~4 ตัวอักษร/token
      pill.textContent = `${len} ตัวอักษร · ~${toks} tokens`;
      pill.classList.toggle("warn", toks > 1500 && toks <= 3000);
      pill.classList.toggle("hot", toks > 3000);
      const r = el.getBoundingClientRect();
      pill.style.left = Math.max(8, r.right - pill.offsetWidth - 6) + "px";
      pill.style.top  = Math.max(8, r.top - pill.offsetHeight - 4) + "px";
      pill.classList.add("show");
    }

    document.addEventListener("input", (e) => {
      if (!_isComposer(e.target)) return;
      _activeTA = e.target; _update(e.target);
    }, true);
    document.addEventListener("focusin", (e) => {
      if (!_isComposer(e.target)) return;
      _activeTA = e.target;
      if (_textOf(e.target)) _update(e.target);
    }, true);
    document.addEventListener("focusout", (e) => {
      if (_isComposer(e.target)) pill.classList.remove("show");
    }, true);
    const _reposition = () => {
      if (_activeTA && pill.classList.contains("show")) _update(_activeTA);
    };
    window.addEventListener("scroll", _reposition, true);
    window.addEventListener("resize", _reposition);
  })();

  // ─────────────────────────────────────────────────────────────────────────────
  // DRAFT AUTOSAVE — เก็บข้อความที่พิมพ์ค้างต่อ session, กู้คืนตอน reload/สลับ
  //   save: localStorage (ทำงานแน่นอน). restore: เขียนกลับเข้า React composer ผ่าน
  //   native value setter + input event (มาตรฐาน React-controlled input)
  // ─────────────────────────────────────────────────────────────────────────────
  (function initDraftAutosave() {
    const KEY = (sid) => "hw_draft_" + (sid || "default");
    const _isComposer = _isComposerEl;   // N1: เฉพาะกล่องแชตหลัก

    // เขียนค่ากลับเข้า controlled input ของ React (ไม่งั้น state ไม่อัปเดต)
    function _reactSet(el, val) {
      try {
        const desc = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value");
        desc.set.call(el, val);
        el.dispatchEvent(new Event("input", { bubbles: true }));
      } catch {
        el.value = val;   // fallback (อาจไม่ sync React state แต่ไม่พัง)
      }
    }

    // ── save (debounced) ──
    let _t = null;
    document.addEventListener("input", (e) => {
      if (!_isComposer(e.target)) return;
      const val = e.target.value;
      clearTimeout(_t);
      _t = setTimeout(() => {
        const k = KEY(_getSessionId());
        if (val && val.trim()) localStorage.setItem(k, val);
        else localStorage.removeItem(k);
      }, 400);
    }, true);

    // ── restore — รอ composer mount (React async) แล้วเติม draft ถ้ากล่องว่าง ──
    let _lastSid = null;
    function _restoreInto(ta) {
      const sid = _getSessionId();
      if (sid === _lastSid) return;          // session เดิม + เคยเช็คแล้ว → ข้าม
      _lastSid = sid;
      const draft = localStorage.getItem(KEY(sid));
      if (draft && !ta.value) _reactSet(ta, draft);
    }
    // observe จนเจอ composer ครั้งแรกแล้ว disconnect (กัน fire ทุก token ตอน stream)
    const mo = new MutationObserver(() => {
      const ta = document.querySelector("textarea");
      if (ta) { mo.disconnect(); _restoreInto(ta); }
    });
    mo.observe(document.body, { childList: true, subtree: true });
    setTimeout(() => { const ta = document.querySelector("textarea"); if (ta) { mo.disconnect(); _restoreInto(ta); } }, 800);
    setTimeout(() => mo.disconnect(), 10000);   // safety: เลิก observe หลัง 10s ไม่ว่ายังไง
    // สลับ session ผ่าน hash → ลองกู้ draft ของ session ใหม่
    window.addEventListener("hashchange", () => {
      _lastSid = null;
      setTimeout(() => { const ta = document.querySelector("textarea"); if (ta) _restoreInto(ta); }, 200);
    });
  })();

  // ─────────────────────────────────────────────────────────────────────────────
  // SLASH / QUICK PROMPTS — พิมพ์ "/" ต้นกล่อง → เมนู template → เลือกแล้วเติมเข้า composer
  // ─────────────────────────────────────────────────────────────────────────────
  (function initSlashPrompts() {
    const PROMPTS = [
      { cmd: "review",    label: "🔍 Review โค้ด",  text: "ช่วย review โค้ดนี้ แล้วชี้จุดที่ควรปรับปรุง:\n\n" },
      { cmd: "bug",       label: "🐛 หา bug",       text: "ช่วยหา bug ในโค้ดนี้ และเสนอวิธีแก้:\n\n" },
      { cmd: "explain",   label: "💡 อธิบาย",        text: "อธิบายสิ่งนี้แบบเข้าใจง่าย ทีละขั้น:\n\n" },
      { cmd: "summary",   label: "📝 สรุป",          text: "สรุปใจความสำคัญของข้อความนี้:\n\n" },
      { cmd: "translate", label: "🌐 แปลเป็น EN",    text: "แปลข้อความนี้เป็นภาษาอังกฤษ:\n\n" },
      { cmd: "improve",   label: "✨ ปรับสำนวน",     text: "ช่วยปรับสำนวนข้อความนี้ให้กระชับ ชัดเจน:\n\n" },
      { cmd: "plan",      label: "🗺️ วางแผน",        text: "ช่วยวางแผนทีละขั้นสำหรับ:\n\n" },
    ];

    const css = `
      #enh-slash {
        position: fixed; z-index: 10000; display: none; min-width: 220px; max-width: 320px;
        background: rgba(15,23,42,0.96); border: 1px solid rgba(99,102,241,0.45);
        border-radius: 12px; padding: 5px; box-shadow: 0 8px 28px rgba(0,0,0,0.5);
        backdrop-filter: blur(8px); font-size: 13px;
      }
      #enh-slash.show { display: block; }
      .enh-slash-item {
        padding: 8px 10px; border-radius: 8px; cursor: pointer; color: #cbd5e1;
        display: flex; gap: 8px; align-items: center; white-space: nowrap;
      }
      .enh-slash-item .cmd { color: #64748b; font-size: 11px; margin-left: auto; }
      .enh-slash-item.sel, .enh-slash-item:hover {
        background: rgba(99,102,241,0.22); color: #fff;
      }
    `;
    document.head.appendChild(Object.assign(document.createElement("style"), { textContent: css }));

    const menu = document.createElement("div");
    menu.id = "enh-slash";
    document.body.appendChild(menu);

    let _open = false, _items = [], _sel = 0, _ta = null;

    function _reactSet(el, val) {
      try {
        Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set.call(el, val);
        el.dispatchEvent(new Event("input", { bubbles: true }));
      } catch { el.value = val; }
    }

    function _close() { _open = false; menu.classList.remove("show"); }

    function _render() {
      menu.innerHTML = _items.map((p, i) =>
        `<div class="enh-slash-item${i === _sel ? " sel" : ""}" data-i="${i}">` +
        `<span>${p.label}</span><span class="cmd">/${p.cmd}</span></div>`
      ).join("");
    }

    function _position() {
      const r = _ta.getBoundingClientRect();
      menu.style.left = Math.max(8, r.left) + "px";
      menu.style.top = Math.max(8, r.top - menu.offsetHeight - 6) + "px";   // ลอยเหนือ composer
    }

    function _select(item) {
      if (!item || !_ta) return;
      _reactSet(_ta, item.text);
      _close();
      _ta.focus();
      setTimeout(() => { try { const n = _ta.value.length; _ta.setSelectionRange(n, n); } catch {} }, 0);
    }

    // เปิด/กรองเมนูจากสิ่งที่พิมพ์
    document.addEventListener("input", (e) => {
      const ta = e.target;
      if (!_isComposerEl(ta) || ta.tagName !== "TEXTAREA") return;   // N1: เฉพาะกล่องแชตหลัก
      const v = ta.value;
      if (v.startsWith("/") && !v.includes(" ") && !v.includes("\n")) {
        const f = v.slice(1).toLowerCase();
        _items = PROMPTS.filter(p => p.cmd.startsWith(f) || !f);
        if (_items.length) {
          _ta = ta; _open = true; _sel = 0; _render();
          menu.classList.add("show"); _position();
          return;
        }
      }
      _close();
    }, true);

    // คีย์บอร์ด — เมื่อเมนูเปิด ดักก่อน React (กัน Enter ส่งข้อความ)
    document.addEventListener("keydown", (e) => {
      if (!_open || e.target !== _ta) return;
      if (e.key === "ArrowDown") { _sel = (_sel + 1) % _items.length; _render(); e.preventDefault(); e.stopPropagation(); }
      else if (e.key === "ArrowUp") { _sel = (_sel - 1 + _items.length) % _items.length; _render(); e.preventDefault(); e.stopPropagation(); }
      else if (e.key === "Enter") { _select(_items[_sel]); e.preventDefault(); e.stopPropagation(); }
      else if (e.key === "Escape") { _close(); e.preventDefault(); e.stopPropagation(); }
      else if (e.key === "Tab") { _select(_items[_sel]); e.preventDefault(); e.stopPropagation(); }
    }, true);

    menu.addEventListener("mousedown", (e) => {
      const item = e.target.closest(".enh-slash-item");
      if (!item) return;
      e.preventDefault();   // กัน blur ก่อนคลิกติด
      _select(_items[+item.dataset.i]);
    });

    document.addEventListener("focusout", (e) => {
      if (e.target === _ta) setTimeout(_close, 150);   // delay ให้ mousedown ของเมนูทำงานก่อน
    }, true);
    window.addEventListener("scroll", () => { if (_open) _position(); }, true);
  })();

})();
