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
  let _agentMode = false;  // fab-agent ตัดออกแล้ว (2026-06-15) — tool_agent มาจาก React Code pill แทน
  // ── Claude Mode state — override provider=claude บน /api/chat ────────────────
  let _claudeMode = false;  // fab-claude ตัดออกแล้ว (2026-06-15) — เลือก Claude ผ่าน Model picker
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
          // กติกา mutate body ทั้งหมดอยู่ใน static/chat_intercept.js (pure + node test)
          // — Claude ชนะ Agent/webSearch, Plan = flag เท่านั้นห้ามแตะ prompt
          const _ci = window.hwChatIntercept;
          if (_ci) {
            const _cbSkillState = window.__hwChatBoxSkills ? window.__hwChatBoxSkills() : null;
            const _cbResult = _ci.applyChatBodyMutations(b, {
              claudeMode: _claudeMode,
              agentMode: _agentMode,
              obsidian: !!(_cbSkillState && _cbSkillState.obsidian),
              webSearch: !!(_cbSkillState && _cbSkillState.webSearch),
              mode: window.__hwChatBoxMode ? window.__hwChatBoxMode() : null,
            });
            if (_cbResult.needTimeline)
              _pendingAgentTimeline = { events: [], sessionToken: Date.now().toString(36) };
            if (_cbResult.mutated) opts = { ...opts, body: JSON.stringify(b) };
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
      pointer-events: none;
    }
    #login-overlay.open { display: flex; pointer-events: auto; }
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

      /* Floating toolbar — มุมขวาล่างเหนือ composer (อย่าตั้ง top — จะยืดทาบกลางจอ) */
      #enh-toolbar {
        top: auto !important;
        transform: none !important;
        left: auto !important;
        right: 6px !important;
        bottom: 110px !important;
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

      /* ── Action buttons: React จัด row ใต้ bubble + .msg-action โชว์เองบน touch แล้ว
         (ถอด side-column hack เดิมออก 2026-06-11 — มันบีบ bubble + ปุ่มลอยรกจอ) ── */
      .group > div.flex-col > div.flex.items-center > button {
        opacity: 0.6 !important; /* fallback bundle เก่าที่ยังไม่มี .msg-action */
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
  if (!window.__hwReactChatBox) {                         // ported เข้า React แล้ว (utils/dreamstats.ts, 2026-06-16)
    fetchDreamStats();
    setInterval(fetchDreamStats, 300_000);                // refetch ทุก 5 นาที (dream รันกลางคืน)
    setInterval(() => applyDreamStats(_dreamVals), 2_000); // re-apply กัน React re-render ทับ
  }

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
    // Global Search ported เข้า React แล้ว (utils/globalsearch.ts, 2026-06-17) — React owns Ctrl+Shift+F
    if (!window.__hwReactChatBox && e.ctrlKey && e.shiftKey && e.key === "F") {
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
    // ported เข้า React แล้ว — React มี 📌 Pin ที่ยิง /api/pin/{dbId} ตรงๆ
    // ⚠️ ตัวนี้ต้องปิดไม่ใช่แค่เพราะซ้ำ แต่เพราะ "ตายสนิท": pinMessage() จับคู่ข้อความ
    //    แบบเป๊ะทุกตัวอักษร แต่ bubble.innerText มีป้ายปุ่มปนอยู่ ("คัดลอก" ของ React)
    //    → match ไม่เจอทุกครั้ง วัดจริงบน prod 2026-08-06: 0/66
    if (window.__hwReactChatBox) return;
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
    <button class="enh-fab" id="fab-vault" title="Vault Search" style="display:none">
      🌿 <span>Vault</span>
    </button>
  `;
  document.body.appendChild(toolbar);

  // Home Panel ported เข้า React แล้ว (utils/homepanel.ts, 2026-06-17) — ตัดปุ่ม 🏠 overlay
  // ทิ้งเพื่อกัน trigger ซ้ำ (React มีปุ่ม 🏠 ใน header). section 14 ด้านล่าง gate ด้วย flag เดียวกัน
  if (window.__hwReactChatBox) {
    const _fh = document.getElementById("fab-home");
    if (_fh) _fh.remove();
    // Global Search ported เข้า React แล้ว (utils/globalsearch.ts, 2026-06-17) — ตัดปุ่ม 🔍 overlay
    const _fs = document.getElementById("fab-search");
    if (_fs) _fs.remove();
  }

  // โหลด config จาก server — เปิดปุ่มเฉพาะที่พร้อมใช้จริง
  // (fab-claude ตัดออกแล้ว 2026-06-15 — เลือก Claude ผ่าน Model picker ใน React แทน)
  fetch("/api/config").then(r => r.json()).then(cfg => {
    if (cfg.has_vault) {
      const b = document.getElementById("fab-vault");
      if (b) b.style.display = "";
    }
  }).catch(() => {});

  document.getElementById("fab-search")?.addEventListener("click", () => {
    searchOverlay.classList.toggle("open");
    if (searchOverlay.classList.contains("open"))
      setTimeout(() => gsInput.focus(), 50);
  });
  document.getElementById("fab-vault").addEventListener("click", () => {
    vaultOverlay.classList.toggle("open");
    if (vaultOverlay.classList.contains("open"))
      setTimeout(() => vsInput.focus(), 50);
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
    /* desktop: sidebar เป็น md:relative w-64 (16rem) = กินที่ในโฟลว์จริง
       → บาร์ต้องเริ่มหลังมัน ไม่งั้น z-index 8998 จะพาดทับการ์ดผู้ใช้ล่างซ้าย
       มือถือ (<768px) sidebar เป็น fixed + translate ออกนอกจอ = ไม่กินที่ จึงคง left:0 */
    @media (min-width: 768px) {
      #enh-token-bar { left: 16rem; }
    }
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

  if (!window.__hwReactChatBox) {   // ported เข้า React แล้ว (utils/homepanel.ts, 2026-06-17)
    _fabHome && _fabHome.addEventListener("click", _hwToggle);
    document.addEventListener("click", (e) => {
      if (_hwOpen && !hcPanel.contains(e.target) && e.target !== _fabHome && !(_fabHome && _fabHome.contains(e.target)))
        _hwClose();
    });
  }

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
    if (isTA && el.closest && el.closest(".enh-cb-box")) return true;   // §22 overlay composer
    return isTA && document.querySelectorAll("textarea").length === 1;
  }

  // ─────────────────────────────────────────────────────────────────────────────
  // TOKEN / CHAR COUNTER — pill ลอยมุมขวาบนของ textarea ที่กำลังพิมพ์
  //   event delegation → ทนต่อ React re-render; ~4 ตัวอักษร ≈ 1 token (ตาม approx_tokens)
  // ─────────────────────────────────────────────────────────────────────────────
  (function initTokenCounter() {
    if (window.__hwReactChatBox) return;   // ported เข้า React แล้ว (utils/tokencount.ts, 2026-06-16)
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
      if (!e.target.getClientRects().length) return;  // composer ซ่อนอยู่ (§22) — กัน pill เด้งที่ (0,0)
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
    if (window.__hwReactChatBox) return;   // ported เข้า React แล้ว (utils/draft.ts, 2026-06-16)
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
      // composer ถูกซ่อน (§22 overlay ทับ) — synthetic input จาก doSend ห้าม save
      // ไม่งั้น debounce 400ms ยิงหลัง interceptor ลบ draft → ghost ของข้อความที่ส่งแล้ว
      if (!e.target.getClientRects().length) return;
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
    // composer ที่มองเห็นจริง — ถ้า §22 overlay ติดตั้งแล้ว native จะถูกซ่อน
    // ต้อง restore เข้า overlay (textarea แรกใน DOM = native ที่ซ่อน → draft มองไม่เห็น)
    function _visibleComposer() {
      const tas = [...document.querySelectorAll("textarea")];
      return tas.find((t) => _isComposerEl(t) && t.getClientRects().length) || tas.find(_isComposerEl) || null;
    }
    // observe จนเจอ composer ครั้งแรกแล้ว disconnect (กัน fire ทุก token ตอน stream)
    const mo = new MutationObserver(() => {
      const ta = _visibleComposer();
      if (ta) { mo.disconnect(); _restoreInto(ta); }
    });
    mo.observe(document.body, { childList: true, subtree: true });
    setTimeout(() => { const ta = _visibleComposer(); if (ta) { mo.disconnect(); _restoreInto(ta); } }, 800);
    setTimeout(() => mo.disconnect(), 10000);   // safety: เลิก observe หลัง 10s ไม่ว่ายังไง
    // สลับ session ผ่าน hash → ลองกู้ draft ของ session ใหม่
    window.addEventListener("hashchange", () => {
      _lastSid = null;
      setTimeout(() => { const ta = _visibleComposer(); if (ta) _restoreInto(ta); }, 200);
    });
  })();

  // ─────────────────────────────────────────────────────────────────────────────
  // SLASH / QUICK PROMPTS — พิมพ์ "/" ต้นกล่อง → เมนู template → เลือกแล้วเติมเข้า composer
  // ─────────────────────────────────────────────────────────────────────────────
  (function initSlashPrompts() {
    if (window.__hwReactChatBox) return;   // ported เข้า React แล้ว (utils/slash.ts, 2026-06-16)
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

  // ─────────────────────────────────────────────────────────────────────────────
  // 18. FILE MANAGER — 📎 upload PDF/DOCX/XLSX/image + doc list panel
  // ─────────────────────────────────────────────────────────────────────────────
  (function () {
    if (window.__hwReactChatBox) return;   // ported เข้า React แล้ว (utils/filemanager.ts, 2026-06-17) — attach + index + กล้อง + drag&drop
    // ── styles ──
    const css = `
      #enh-file-bar {
        position:fixed; bottom:56px; left:50%; transform:translateX(-50%);
        display:none; gap:6px; align-items:center; flex-wrap:wrap;
        background:rgba(15,23,42,0.95); border:1px solid rgba(99,102,241,0.35);
        border-radius:12px; padding:6px 12px; z-index:8996; max-width:90vw;
        backdrop-filter:blur(10px);
      }
      #enh-file-bar.has-files { display:flex; }
      .enh-file-chip {
        display:flex; align-items:center; gap:4px;
        background:rgba(99,102,241,0.2); border:1px solid rgba(99,102,241,0.4);
        border-radius:8px; padding:3px 8px; font-size:12px; color:#c7d2fe;
      }
      .enh-file-chip button {
        background:none; border:none; color:#94a3b8; cursor:pointer;
        font-size:13px; padding:0 2px; line-height:1;
      }
      .enh-file-chip button:hover { color:#f87171; }

      #enh-doc-panel {
        position:fixed; top:0; right:0; width:320px; height:100%;
        background:rgba(10,15,30,0.97); border-left:1px solid rgba(99,102,241,0.3);
        z-index:9100; display:none; flex-direction:column;
        backdrop-filter:blur(16px); padding:16px;
      }
      #enh-doc-panel.open { display:flex; }
      #enh-doc-panel h3 { color:#e2e8f0; margin:0 0 12px; font-size:15px; }
      #enh-doc-panel .enh-close { background:none; border:none; color:#94a3b8;
        font-size:18px; cursor:pointer; position:absolute; top:12px; right:14px; }
      .enh-doc-item {
        display:flex; align-items:flex-start; gap:8px;
        padding:8px; border-radius:8px; border:1px solid rgba(99,102,241,0.2);
        margin-bottom:8px; background:rgba(30,41,59,0.5);
      }
      .enh-doc-item .enh-doc-info { flex:1; min-width:0; }
      .enh-doc-item .enh-doc-name {
        font-size:13px; color:#c7d2fe; white-space:nowrap;
        overflow:hidden; text-overflow:ellipsis;
      }
      .enh-doc-item .enh-doc-meta { font-size:11px; color:#64748b; margin-top:2px; }
      .enh-doc-item button {
        background:none; border:none; color:#64748b; cursor:pointer; font-size:14px;
        flex-shrink:0; padding:2px;
      }
      .enh-doc-item button:hover { color:#f87171; }
      #enh-doc-upload-zone {
        border:2px dashed rgba(99,102,241,0.4); border-radius:10px;
        padding:20px; text-align:center; color:#64748b; font-size:13px;
        cursor:pointer; margin-bottom:12px; transition:border-color .2s;
      }
      #enh-doc-upload-zone:hover { border-color:rgba(99,102,241,0.8); color:#c7d2fe; }
      #enh-doc-list { flex:1; overflow-y:auto; }
      #enh-doc-empty { color:#475569; font-size:13px; text-align:center; padding:20px 0; }

      #enh-fab-file {
        position:fixed; bottom:14px; left:14px;
        width:38px; height:38px; border-radius:50%;
        background:rgba(30,41,59,0.9); border:1px solid rgba(99,102,241,0.35);
        color:#94a3b8; font-size:17px; cursor:pointer; z-index:8995;
        display:flex; align-items:center; justify-content:center;
        transition:all .2s;
      }
      #enh-fab-file:hover { background:rgba(99,102,241,0.25); color:#e2e8f0; }
      #enh-fab-file .enh-file-count {
        position:absolute; top:-4px; right:-4px;
        background:#6366f1; color:#fff; border-radius:50%;
        width:16px; height:16px; font-size:10px;
        display:none; align-items:center; justify-content:center;
      }
    `;
    document.head.appendChild(Object.assign(document.createElement("style"), { textContent: css }));

    // ── state ──
    const _pendingDocs = []; // { name, content } รอ inject เป็น context ถัดไป

    // ── file bar ──
    const fileBar = document.createElement("div");
    fileBar.id = "enh-file-bar";
    document.body.appendChild(fileBar);

    function _updateFileBar() {
      fileBar.innerHTML = "";
      if (!_pendingDocs.length) { fileBar.classList.remove("has-files"); return; }
      fileBar.classList.add("has-files");
      _pendingDocs.forEach((doc, i) => {
        const chip = document.createElement("div");
        chip.className = "enh-file-chip";
        chip.innerHTML = `📄 <span>${doc.name}</span>`;
        const rm = document.createElement("button");
        rm.textContent = "✕";
        rm.onclick = () => { _pendingDocs.splice(i, 1); _updateFileBar(); };
        chip.appendChild(rm);
        fileBar.appendChild(chip);
      });
      const hint = document.createElement("span");
      hint.style.cssText = "font-size:11px;color:#64748b";
      hint.textContent = "จะใช้เป็น context ในข้อความถัดไป";
      fileBar.appendChild(hint);
    }

    // inject pending docs เข้า chat body ก่อนส่ง
    const _origFetchFile = window.fetch.bind(window);
    window.fetch = function(url, opts) {
      if (typeof url === "string" && url === "/api/chat" && opts?.body && _pendingDocs.length) {
        try {
          const body = JSON.parse(opts.body);
          const docsCtx = _pendingDocs.map(d =>
            `=== ไฟล์: ${d.name} ===\n${d.content.slice(0, 3000)}`
          ).join("\n\n");
          body.prompt = body.prompt + `\n\n[เอกสารแนบ]\n${docsCtx}`;
          opts = { ...opts, body: JSON.stringify(body) };
          _pendingDocs.length = 0;
          _updateFileBar();
        } catch {}
      }
      return _origFetchFile(url, opts);
    };

    // ── doc panel ──
    const panel = document.createElement("div");
    panel.id = "enh-doc-panel";
    panel.innerHTML = `
      <button class="enh-close" id="enh-doc-close">✕</button>
      <h3>📎 เอกสาร</h3>
      <div id="enh-doc-upload-zone">คลิกหรือลาก PDF / DOCX / XLSX / TXT มาวาง</div>
      <div id="enh-doc-list"><div id="enh-doc-empty">ยังไม่มีเอกสาร</div></div>
    `;
    document.body.appendChild(panel);
    document.getElementById("enh-doc-close").onclick = () => panel.classList.remove("open");

    async function _loadDocList() {
      const list = document.getElementById("enh-doc-list");
      try {
        const r = await _origFetch("/api/documents");
        const { documents = [] } = await r.json();
        list.innerHTML = "";
        if (!documents.length) {
          list.innerHTML = '<div id="enh-doc-empty">ยังไม่มีเอกสาร</div>';
          return;
        }
        documents.forEach((doc) => {
          const item = document.createElement("div");
          item.className = "enh-doc-item";
          const date = doc.indexed_at ? new Date(doc.indexed_at * 1000).toLocaleDateString("th-TH") : "";
          item.innerHTML = `
            <div class="enh-doc-info">
              <div class="enh-doc-name" title="${doc.source}">📄 ${doc.source}</div>
              <div class="enh-doc-meta">${doc.chunks_count} chunks · ${date}</div>
            </div>`;
          const del = document.createElement("button");
          del.textContent = "🗑️";
          del.title = "ลบเอกสาร";
          del.onclick = async () => {
            await _origFetch(`/api/documents/${encodeURIComponent(doc.source)}`, { method: "DELETE" });
            showToast("🗑️ ลบเอกสารแล้ว");
            _loadDocList();
          };
          item.appendChild(del);
          list.appendChild(item);
        });
      } catch { list.innerHTML = '<div id="enh-doc-empty">โหลดไม่ได้</div>'; }
    }

    async function _handleFile(file) {
      const MAX = 10 * 1024 * 1024;
      if (file.size > MAX) { showToast("❌ ไฟล์ใหญ่เกิน 10 MB"); return; }

      const ext = file.name.split(".").pop().toLowerCase();
      const isImage = file.type.startsWith("image/") || ["jpg","jpeg","png","gif","webp"].includes(ext);

      showToast(`⏳ กำลังประมวลผล ${file.name}…`);

      if (isImage) {
        // รูปภาพ → base64 → hw_pending_image (ส่งพร้อม chat ได้เลย)
        const form = new FormData();
        form.append("file", file, file.name);
        try {
          const r = await _origFetch("/api/upload", {
            method: "POST",
            headers: _authToken ? { "x-auth-token": _authToken } : {},
            body: form,
          });
          const d = await r.json();
          if (d.ok && d.is_image) {
            localStorage.setItem("hw_pending_image", JSON.stringify({ b64: d.b64, mime: d.mime }));
            showToast(`✅ รูป ${file.name} พร้อมแล้ว — กด Send`);
          } else { showToast("❌ " + (d.error || "upload ล้มเหลว")); }
        } catch { showToast("❌ upload ล้มเหลว"); }
        return;
      }

      // เอกสาร → /api/documents/upload (index เข้า ChromaDB) + เก็บ pending context
      const form = new FormData();
      form.append("file", file, file.name);
      try {
        const r = await _origFetch("/api/documents/upload", {
          method: "POST",
          headers: _authToken ? { "x-auth-token": _authToken } : {},
          body: form,
        });
        const d = await r.json();
        if (d.ok) {
          showToast(`✅ index ${file.name} แล้ว (${d.chunks_count} chunks)`);
          _loadDocList();
          // ดึง text กลับมาเก็บเป็น pending context ด้วย
          const rText = await _origFetch("/api/upload", {
            method: "POST",
            headers: _authToken ? { "x-auth-token": _authToken } : {},
            body: (() => { const f2 = new FormData(); f2.append("file", file, file.name); return f2; })(),
          });
          const dText = await rText.json();
          if (dText.text) {
            _pendingDocs.push({ name: file.name, content: dText.text });
            _updateFileBar();
          }
        } else { showToast("❌ " + (d.error || d.detail || "index ล้มเหลว")); }
      } catch (e) { showToast("❌ " + e.message); }
    }

    // upload zone drag & drop
    const zone = document.getElementById("enh-doc-upload-zone");
    const fileInput = document.createElement("input");
    fileInput.type = "file";
    fileInput.accept = ".pdf,.docx,.xlsx,.xls,.txt,.md,.csv,.jpg,.jpeg,.png,.webp";
    fileInput.multiple = true;
    fileInput.style.display = "none";
    document.body.appendChild(fileInput);

    zone.onclick = () => { fileInput.value = ""; fileInput.click(); };
    fileInput.onchange = () => { [...fileInput.files].forEach(_handleFile); };

    zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.style.borderColor = "#6366f1"; });
    zone.addEventListener("dragleave", () => { zone.style.borderColor = ""; });
    zone.addEventListener("drop", (e) => {
      e.preventDefault(); zone.style.borderColor = "";
      [...(e.dataTransfer?.files || [])].forEach(_handleFile);
    });

    // ── FAB ปุ่มเปิด panel ──
    const fab = document.createElement("button");
    fab.id = "enh-fab-file";
    fab.title = "จัดการไฟล์ / เอกสาร";
    fab.innerHTML = `📎<span class="enh-file-count"></span>`;
    document.body.appendChild(fab);
    fab.onclick = () => { panel.classList.toggle("open"); if (panel.classList.contains("open")) _loadDocList(); };

    // camera input สำหรับมือถือ
    const camInput = document.createElement("input");
    camInput.type = "file";
    camInput.accept = "image/*";
    camInput.capture = "environment";
    camInput.style.display = "none";
    document.body.appendChild(camInput);
    camInput.onchange = () => { if (camInput.files[0]) _handleFile(camInput.files[0]); };

    // เพิ่มปุ่ม 📷 ใน panel header
    const camBtn = document.createElement("button");
    camBtn.textContent = "📷 ถ่ายรูป";
    camBtn.style.cssText = "margin-bottom:8px;background:rgba(99,102,241,0.2);border:1px solid rgba(99,102,241,0.3);color:#c7d2fe;border-radius:8px;padding:4px 12px;font-size:12px;cursor:pointer;";
    camBtn.onclick = () => { camInput.value = ""; camInput.click(); };
    panel.insertBefore(camBtn, document.getElementById("enh-doc-upload-zone"));
  })();

  // ─────────────────────────────────────────────────────────────────────────────
  // 19. COPY MESSAGE — ปุ่มคัดลอกข้อความทั้งก้อน (AI bubble)
  // ─────────────────────────────────────────────────────────────────────────────
  (function () {
    if (window.__hwReactChatBox) return;   // ported เข้า React แล้ว — ปุ่ม 📋 บนทุกบับเบิล
    const css = `
      .enh-copy-msg {
        position:absolute; top:6px; right:6px;
        background:rgba(99,102,241,0.15); border:1px solid rgba(99,102,241,0.3);
        color:#94a3b8; border-radius:6px; padding:2px 8px; font-size:11px;
        cursor:pointer; opacity:0; transition:opacity .2s;
      }
      .enh-copy-msg:hover { background:rgba(99,102,241,0.3); color:#e2e8f0; }
      .enh-copy-msg.copied { color:#34d399; border-color:rgba(52,211,153,0.4); }
    `;
    document.head.appendChild(Object.assign(document.createElement("style"), { textContent: css }));

    const obs = new MutationObserver(() => {
      document.querySelectorAll("div.flex.group.justify-start").forEach((container) => {
        if (container.dataset.copyMsgWired) return;
        const bubble = container.querySelector('[class*="rounded-3xl"]');
        if (!bubble) return;
        container.dataset.copyMsgWired = "1";
        bubble.style.position = "relative";

        const btn = document.createElement("button");
        btn.className = "enh-copy-msg";
        btn.textContent = "คัดลอก";
        bubble.appendChild(btn);

        container.addEventListener("mouseenter", () => (btn.style.opacity = "1"));
        container.addEventListener("mouseleave", () => (btn.style.opacity = "0"));

        btn.addEventListener("click", (e) => {
          e.stopPropagation();
          const text = bubble.innerText.replace(/คัดลอก$/,"").replace(/📌/g,"").trim();
          navigator.clipboard.writeText(text).then(() => {
            btn.textContent = "✓ คัดลอกแล้ว";
            btn.classList.add("copied");
            setTimeout(() => { btn.textContent = "คัดลอก"; btn.classList.remove("copied"); }, 2000);
          });
        });
      });
    });
    window.addEventListener("load", () => {
      obs.observe(document.getElementById("root"), { childList: true, subtree: true });
    });
  })();

  // ─────────────────────────────────────────────────────────────────────────────
  // 19. EDIT + RESEND — แก้ user message แล้วส่งใหม่ (truncate + resend)
  // 20. DELETE PAIR   — ลบ user message + AI response คู่นั้น
  // ─────────────────────────────────────────────────────────────────────────────
  (function () {
    const css = `
      .enh-user-actions {
        display:none; gap:4px; margin-top:4px; justify-content:flex-end;
      }
      div.flex.group.justify-end:hover .enh-user-actions { display:flex; }
      .enh-ua-btn {
        background:rgba(30,41,59,0.8); border:1px solid rgba(99,102,241,0.25);
        color:#94a3b8; border-radius:6px; padding:2px 8px; font-size:11px;
        cursor:pointer; transition:all .2s;
      }
      .enh-ua-btn:hover { color:#e2e8f0; border-color:rgba(99,102,241,0.5); }
      .enh-ua-btn.danger:hover { color:#f87171; border-color:rgba(248,113,113,0.4); }
      .enh-edit-area {
        width:100%; min-height:60px; background:rgba(15,23,42,0.9);
        border:1px solid rgba(99,102,241,0.4); border-radius:12px;
        color:#e2e8f0; padding:8px 12px; font-size:14px; resize:vertical;
        font-family:inherit;
      }
      .enh-edit-actions { display:flex; gap:6px; margin-top:6px; justify-content:flex-end; }
      .enh-edit-send {
        background:#6366f1; color:#fff; border:none; border-radius:8px;
        padding:4px 16px; font-size:13px; cursor:pointer;
      }
      .enh-edit-cancel {
        background:transparent; color:#94a3b8; border:1px solid rgba(148,163,184,0.3);
        border-radius:8px; padding:4px 12px; font-size:13px; cursor:pointer;
      }
    `;
    document.head.appendChild(Object.assign(document.createElement("style"), { textContent: css }));

    async function getMsgDbId(content) {
      await refreshHistory();
      const msg = _historyCache.find(
        (m) => (m.content || m.message || "").trim() === content.trim()
      );
      return msg?.id || msg?.db_id || null;
    }

    async function deletePair(dbId) {
      await _origFetch(`/api/message/${dbId}`, { method: "DELETE" });
      const next = _historyCache.find((m) => (m.id || m.db_id) > dbId && m.role === "assistant");
      if (next) await _origFetch(`/api/message/${next.id || next.db_id}`, { method: "DELETE" });
    }

    async function resendEdited(oldDbId, newText) {
      await _origFetch(`/api/truncate/${oldDbId}`, { method: "DELETE" });
      const body = JSON.stringify({
        assistant: ctx.assistant,
        session_id: ctx.session,
        prompt: newText,
        provider: localStorage.getItem("hw_provider") || "auto",
      });
      await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body });
      setTimeout(() => window.location.reload(), 800);
    }

    function showEditMode(container, bubble, originalText) {
      const originalHTML = bubble.innerHTML;
      bubble.innerHTML = "";

      const ta = document.createElement("textarea");
      ta.className = "enh-edit-area";
      ta.value = originalText;

      const acts = document.createElement("div");
      acts.className = "enh-edit-actions";

      const sendBtn = document.createElement("button");
      sendBtn.className = "enh-edit-send";
      sendBtn.textContent = "✓ ส่งใหม่";

      const cancelBtn = document.createElement("button");
      cancelBtn.className = "enh-edit-cancel";
      cancelBtn.textContent = "ยกเลิก";

      acts.appendChild(cancelBtn);
      acts.appendChild(sendBtn);
      // (showEditMode ถูกเรียกจาก editBtn เท่านั้น — ซึ่งแนบเฉพาะ bundle เก่า ดู wireUserBubble)
      bubble.appendChild(ta);
      bubble.appendChild(acts);
      ta.focus();

      cancelBtn.addEventListener("click", () => {
        bubble.innerHTML = originalHTML;
        delete container.dataset.editWired;
        wireUserBubble(container);
      });
      sendBtn.addEventListener("click", async () => {
        const newText = ta.value.trim();
        if (!newText) return;
        sendBtn.disabled = true;
        sendBtn.textContent = "กำลังส่ง…";
        const dbId = await getMsgDbId(originalText);
        if (!dbId) { showToast("❌ ไม่พบ message"); bubble.innerHTML = originalHTML; return; }
        await resendEdited(dbId, newText);
      });
    }

    function wireUserBubble(container) {
      if (container.dataset.editWired) return;
      const bubble = container.querySelector('[class*="rounded-3xl"]');
      if (!bubble) return;
      container.dataset.editWired = "1";

      const actRow = document.createElement("div");
      actRow.className = "enh-user-actions";

      const editBtn = document.createElement("button");
      editBtn.className = "enh-ua-btn";
      editBtn.textContent = "✏️ แก้ไข";

      const delBtn = document.createElement("button");
      delBtn.className = "enh-ua-btn danger";
      delBtn.textContent = "🗑️ ลบ";

      // ✏️ ported เข้า React แล้ว (inline textarea + submitEdit ที่ใช้ msg.dbId ตรงๆ)
      // แนบของ overlay เฉพาะ bundle เก่าที่ยังไม่ตั้ง __hwReactChatBox — ไม่งั้นผู้ใช้เห็นปุ่มแก้ไข 2 อัน
      if (!window.__hwReactChatBox) actRow.appendChild(editBtn);
      // 🗑️ ลบ ไม่มีคู่ใน React → ต้องแนบเสมอ ห้าม gate ตามไปด้วย
      actRow.appendChild(delBtn);
      container.appendChild(actRow);

      editBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        showEditMode(container, bubble, bubble.innerText.trim());
      });

      delBtn.addEventListener("click", async (e) => {
        e.stopPropagation();
        const dbId = await getMsgDbId(bubble.innerText.trim());
        if (!dbId) { showToast("❌ ไม่พบ message"); return; }
        await deletePair(dbId);
        showToast("🗑️ ลบแล้ว");
        // ลบ AI bubble ถัดไปออกจาก DOM
        const all = [...document.querySelectorAll("div.flex.group.justify-start, div.flex.group.justify-end")];
        const idx = all.indexOf(container);
        if (idx >= 0 && all[idx + 1]?.classList.contains("justify-start")) all[idx + 1].remove();
        container.remove();
      });
    }

    const userObs = new MutationObserver(() => {
      document.querySelectorAll("div.flex.group.justify-end").forEach(wireUserBubble);
    });
    window.addEventListener("load", () => {
      userObs.observe(document.getElementById("root"), { childList: true, subtree: true });
    });
  })();

  // ─────────────────────────────────────────────────────────────────────────────
  // 21. MOBILE KEYBOARD SCROLL — กัน input ถูก keyboard บัง (visualViewport)
  // ─────────────────────────────────────────────────────────────────────────────
  (function () {
    if (!window.visualViewport) return;
    let _lastVH = window.visualViewport.height;

    function _scrollInputIntoView() {
      const ta = document.querySelector("textarea");
      if (!ta) return;
      const rect = ta.getBoundingClientRect();
      const vvh = window.visualViewport.height;
      if (rect.bottom > vvh - 8) {
        window.scrollBy({ top: rect.bottom - vvh + 16, behavior: "smooth" });
      }
    }

    window.visualViewport.addEventListener("resize", () => {
      const newH = window.visualViewport.height;
      if (newH < _lastVH - 100) setTimeout(_scrollInputIntoView, 100); // keyboard เปิด
      _lastVH = newH;
    });

    document.addEventListener("focusin", (e) => {
      if (e.target.tagName === "TEXTAREA") setTimeout(_scrollInputIntoView, 300);
    });
  })();

  // ─────────────────────────────────────────────────────────────────────────────
  // 22. CUSTOM CHAT INPUT BAR — ChatBox redesign (mode/agent/skills pills)
  //     สถาปัตยกรรม: เป็น "skin + proxy" ทับ input เดิมของ React —
  //     ของจริงต่อ backend: ส่งข้อความ (proxy เข้า native input+form),
  //     สลับผู้ช่วย (คลิกปุ่มเดิมจริงใน sidebar), Obsidian/Web Search skill
  //     (inject obsidian_inject / tool_agent ผ่าน fetch interceptor — รูปแบบเดียวกับ _agentMode).
  //     ส่วน Mode (Code/Ask/Plan) และ Skills อื่น (Dream/TTS/ChromaDB) = cosmetic UI state ล้วน
  //     (backend ไม่มี hook ต่อข้อความ) — เก็บไว้เพื่อ UX ที่สอดคล้องกับดีไซน์ที่ส่งมา
  // ─────────────────────────────────────────────────────────────────────────────
  (function () {
    const MODES = [
      { id: "code", label: "Code", color: "#7EB8F7", glyph: "⌨", desc: "เปิด Agent Mode อัตโนมัติ — AI ใช้ tools จริง (รันโค้ด/ค้นไฟล์ ฯลฯ)" },
      { id: "ask",  label: "Ask",  color: "#B69EF5", glyph: "?", desc: "ปิด Agent Mode — ถาม-ตอบทั่วไป ไม่ใช้ tools" },
      { id: "plan", label: "Plan", color: "#5ECFA8", glyph: "≡", desc: "เติมคำสั่งให้ AI วางแผนเป็นขั้นตอนก่อนตอบจริง" },
    ];
    const SKILLS = [
      { id: "obsidian", label: "Obsidian",    icon: "📝", real: true,  hint: "ฉีด context จาก Obsidian Vault เข้าคำตอบจริง" },
      { id: "search",   label: "Web Search",  icon: "🔍", real: true,  hint: "บังคับ Agent ค้นเว็บจริงก่อนตอบ" },
      { id: "dream",    label: "Dream Cycle", icon: "🌙", real: false, hint: "Dream รันอัตโนมัติตอนตี 2 — ปุ่มนี้เป็นแค่ shortcut แสดงผล" },
      { id: "tts",      label: "TTS",         icon: "🔊", real: false, hint: "ยังไม่มีฟีเจอร์ TTS ใน backend" },
      { id: "chroma",   label: "ChromaDB",    icon: "🗄️", real: false, hint: "Memory ผ่าน ChromaDB ทำงานอัตโนมัติทุก turn อยู่แล้ว" },
    ];
    const AGENT_COLOR = { fa: "#7EB8F7", kwan: "#B69EF5", khim: "#5ECFA8" };
    const AGENT_EMOJI = { fa: "🩵", kwan: "🧡", khim: "💙" };

    function _shortAgentName(fullName) {
      const m = fullName.match(/[฀-๿]+/);
      return m ? m[0] : fullName;
    }

    // ── persisted cosmetic state ──────────────────────────────────────────────
    let _cbMode = localStorage.getItem("hw_cb_mode") || "ask";
    let _cbSkills = [];
    try { _cbSkills = JSON.parse(localStorage.getItem("hw_cb_skills") || "[]"); } catch { _cbSkills = []; }

    // ── real skill toggle state — wired into fetch interceptor ───────────────
    let _obsidianSkill  = _cbSkills.includes("obsidian");
    let _webSearchSkill = _cbSkills.includes("search");
    window.__hwChatBoxSkills = () => ({ obsidian: _obsidianSkill, webSearch: _webSearchSkill });
    // Plan mode → fetch interceptor เติมคำสั่ง "วางแผนก่อนตอบ" ต่อท้าย prompt จริง
    window.__hwChatBoxMode = () => _cbMode;

    function _persistSkills() {
      localStorage.setItem("hw_cb_skills", JSON.stringify(_cbSkills));
    }

    // fab-agent ตัดออกแล้ว (2026-06-15) — proxy เดิมเป็น no-op
    // (block §22 นี้ตายอยู่แล้วเมื่อ React ChatBox active ดู return ด้านล่าง — React ส่ง tool_agent เอง)
    function _setAgentMode() {}
    function _applyModeSideEffects(modeId) {
      if (modeId === "code") _setAgentMode(true);
      else if (modeId === "ask") _setAgentMode(false);
      // "plan" ไม่ยุ่งกับ Agent Mode — แค่เติมคำสั่งวางแผนต่อท้าย prompt (ดู fetch interceptor)
    }

    // ── wait for native chat input to mount ──────────────────────────────────
    function _findNativeInput() {
      return [...document.querySelectorAll("input[type='text'], textarea")].find(_isChatInput) || null;
    }

    function _waitFor(fn, retries = 40, delay = 250) {
      return new Promise((resolve) => {
        const tick = (n) => {
          const v = fn();
          if (v) return resolve(v);
          if (n <= 0) return resolve(null);
          setTimeout(() => tick(n - 1), delay);
        };
        tick(retries);
      });
    }

    // React bundle ใหม่ (2026-06-10) มี ChatBox ของตัวเองแล้ว — ข้าม overlay ทั้ง section
    // (flag ตั้งที่ module top-level ของ app.tsx ซึ่งรันก่อน defer script ตัวนี้เสมอ)
    if (window.__hwReactChatBox) return;

    Promise.all([
      _waitFor(_findNativeInput),
      fetch("/api/config").then((r) => r.json()).catch(() => null),
    ]).then(([nativeInput, cfg]) => {
      if (window.__hwReactChatBox) return; // กันเหนียว: flag มาช้า (bundle เก่า cache)
      if (!nativeInput) return; // ไม่เจอ input — ปล่อย React ทำงานปกติ ไม่ติดตั้ง overlay
      let nativeForm = nativeInput.closest("form") || nativeInput.parentElement;
      const assistants = (cfg && cfg.assistants) || [];
      const activeModel = (cfg && cfg.ollama_model) || "";

      let _agent = assistants.find((a) => a.slug === ctx.assistant) || assistants[0] || null;

      // ── CSS ──────────────────────────────────────────────────────────────
      const css = `
        .enh-cb-wrap { width:100%; max-width:620px; margin:10px auto 0; font-family:'DM Sans',sans-serif; }
        .enh-cb-box {
          background: linear-gradient(160deg,#13131A 0%,#0F0F15 100%);
          border: 1px solid #22222E; border-radius: 20px; position: relative;
          transition: border-color .25s, box-shadow .3s; overflow: visible;
        }
        .enh-cb-box::before {
          content:''; position:absolute; inset:-1px; border-radius:20px; z-index:-1;
          background: radial-gradient(ellipse at 60% 0%, color-mix(in srgb,var(--c) 12%,transparent), transparent 70%);
          opacity:0; transition:opacity .3s; pointer-events:none;
        }
        .enh-cb-box.on { border-color: color-mix(in srgb,var(--c) 45%,#22222E); }
        .enh-cb-box.on::before { opacity:1; }
        .enh-cb-box.on { box-shadow: 0 0 0 1px color-mix(in srgb,var(--c) 12%,transparent), 0 16px 50px #00000088; }
        .enh-cb-top { display:flex; align-items:center; gap:7px; padding:12px 14px 0; flex-wrap:wrap; }
        .enh-cb-pill {
          display:flex; align-items:center; gap:7px; padding:6px 13px; border-radius:50px; cursor:pointer;
          border:1px solid #242432; background:#16161E; font-size:13px; font-weight:500; user-select:none;
          transition:all .15s; position:relative; letter-spacing:.01em;
        }
        .enh-cb-pill:hover { background:#1C1C26; border-color:#2E2E3E; }
        .enh-cb-pill .enh-cb-chev { font-size:8px; color:#333; margin-left:2px; }
        .enh-cb-pill.active {
          background: color-mix(in srgb,var(--c) 10%,#13131A);
          border-color: color-mix(in srgb,var(--c) 35%,transparent);
          box-shadow: 0 0 12px color-mix(in srgb,var(--c) 12%,transparent);
        }
        .enh-cb-dd {
          position:absolute; bottom:calc(100% + 10px); left:0; background:#14141C; border:1px solid #222232;
          border-radius:14px; overflow:hidden; z-index:520; min-width:240px;
          box-shadow: 0 -4px 6px #00000044, 0 -12px 40px #00000077; backdrop-filter:blur(12px);
        }
        .enh-cb-dd-item { display:flex; align-items:flex-start; gap:11px; padding:11px 15px; cursor:pointer; transition:background .1s; position:relative; }
        .enh-cb-dd-item:hover { background:#1C1C28; }
        .enh-cb-dd-item+.enh-cb-dd-item { border-top:1px solid #1A1A24; }
        .enh-cb-dd-lbl { font-size:13px; font-weight:500; color:#D0D0E0; }
        .enh-cb-dd-sub { font-size:11px; color:#5A5A78; margin-top:2px; font-family:'Noto Sans Thai',sans-serif; }
        .enh-cb-dd-chk { position:absolute; right:14px; top:50%; transform:translateY(-50%); font-size:12px; }
        .enh-cb-dd-skills { padding:10px; display:flex; flex-direction:column; gap:5px; width:240px; }
        .enh-cb-sk {
          display:flex; align-items:center; gap:8px; padding:7px 11px; border-radius:9px; cursor:pointer;
          border:1px solid #1A1A26; background:#111118; color:#7A7A98; font-size:12px; transition:all .13s;
        }
        .enh-cb-sk:hover { background:#161622; color:#A0A0C0; border-color:#222232; }
        .enh-cb-sk.on { background:color-mix(in srgb,var(--c) 9%,#111118); border-color:color-mix(in srgb,var(--c) 30%,transparent); color:var(--c); }
        .enh-cb-sk .enh-cb-sk-dot { width:5px; height:5px; border-radius:50%; background:#34d399; flex-shrink:0; opacity:.85; }
        .enh-cb-sk-check { margin-left:auto; font-size:11px; }
        .enh-cb-chip {
          display:flex; align-items:center; gap:4px; padding:4px 10px; border-radius:50px;
          border:1px solid color-mix(in srgb,var(--c) 30%,transparent); background:color-mix(in srgb,var(--c) 9%,#111118);
          color:var(--c); font-size:11px; cursor:pointer; transition:opacity .13s;
        }
        .enh-cb-chip:hover { opacity:.65; }
        .enh-cb-box textarea {
          width:100%; background:transparent; border:none; outline:none; color:#C4C4D8; font-size:14px;
          line-height:1.7; resize:none; font-family:'Noto Sans Thai','DM Sans',sans-serif;
          min-height:52px; max-height:160px; padding:12px 18px 6px; caret-color:var(--c);
        }
        .enh-cb-box textarea::placeholder { color:#3A3A52; }
        .enh-cb-box textarea:disabled { opacity:.5; }
        .enh-cb-hr { height:1px; background:linear-gradient(90deg,transparent,#1C1C28 20%,#1C1C28 80%,transparent); margin:0 14px; }
        .enh-cb-bot { display:flex; align-items:center; gap:4px; padding:9px 11px 12px; }
        .enh-cb-ib {
          width:32px; height:32px; border-radius:9px; border:none; background:transparent; cursor:pointer;
          transition:all .14s; display:flex; align-items:center; justify-content:center; color:#4A4A68; font-size:14px;
        }
        .enh-cb-ib:hover { background:#17172A; color:#9090B0; }
        .enh-cb-ib.active { color:var(--c); background:color-mix(in srgb,var(--c) 12%,transparent); }
        .enh-cb-sep { width:1px; height:18px; background:#1A1A26; margin:0 4px; }
        .enh-cb-sp { flex:1; }
        .enh-cb-status { display:flex; align-items:center; gap:6px; font-size:11px; }
        .enh-cb-sdot { width:6px; height:6px; border-radius:50%; flex-shrink:0; }
        .enh-cb-send {
          width:38px; height:38px; border-radius:12px; border:none; background:var(--c); cursor:pointer;
          display:flex; align-items:center; justify-content:center; opacity:.18; transition:all .18s; flex-shrink:0;
        }
        .enh-cb-send.on { opacity:1; box-shadow:0 4px 18px color-mix(in srgb,var(--c) 35%,transparent); }
        .enh-cb-send.on:hover { filter:brightness(1.18); transform:scale(1.06); }
        .enh-cb-send.on:active { transform:scale(.95); }
        .enh-cb-send:disabled { cursor:not-allowed; }
        .enh-cb-hint { text-align:center; padding:8px 0 2px; font-size:10px; color:#2A2A40; line-height:1.7; font-family:'JetBrains Mono',monospace; letter-spacing:.03em; }
        .enh-cb-hint em { color:color-mix(in srgb,var(--c) 45%,#2A2A40); font-style:normal; }
      `;
      document.head.appendChild(Object.assign(document.createElement("style"), { textContent: css }));

      // ── build DOM ─────────────────────────────────────────────────────────
      const wrap = document.createElement("div");
      wrap.className = "enh-cb-wrap";
      wrap.innerHTML = `
        <div class="enh-cb-box">
          <div class="enh-cb-top">
            <div class="enh-cb-rel" style="position:relative">
              <div class="enh-cb-pill active" data-pill="mode"><span class="enh-cb-mode-glyph"></span><span class="enh-cb-mode-lbl"></span><span class="enh-cb-chev">▾</span></div>
            </div>
            <div class="enh-cb-rel" style="position:relative">
              <div class="enh-cb-pill" data-pill="agent"></div>
            </div>
            <div class="enh-cb-rel" style="position:relative">
              <div class="enh-cb-pill" data-pill="skills">
                <span>✨</span><span class="enh-cb-skills-lbl">Skills</span>
              </div>
            </div>
            <span class="enh-cb-chips"></span>
            <div class="enh-cb-sp"></div>
            <div class="enh-cb-status">
              <span class="enh-cb-sdot" style="background:#5ECFA8;box-shadow:0 0 6px #5ECFA888"></span>
              <span style="color:#5A7A6A">${activeModel ? _esc(activeModel) : "Local"}</span>
              <span style="color:#1E1E2E">·</span>
              <span class="enh-cb-mode2"></span>
            </div>
          </div>
          <textarea placeholder="" rows="2"></textarea>
          <div class="enh-cb-hr"></div>
          <div class="enh-cb-bot">
            <button class="enh-cb-ib" data-act="attach" title="แนบไฟล์">📎</button>
            <button class="enh-cb-ib" data-act="image" title="แนบรูป">🖼️</button>
            <button class="enh-cb-ib" data-act="search" title="Web Search (toggle skill)">🔍</button>
            <div class="enh-cb-sep"></div>
            <span class="enh-cb-sp"></span>
            <button class="enh-cb-send" title="ส่ง (Enter)">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.5" stroke-linecap="round">
                <line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/>
              </svg>
            </button>
          </div>
        </div>
        <div class="enh-cb-hint">Enter ส่ง · Shift+Enter ขึ้นบรรทัด · <em>Ctrl+[1/2/3]</em> เปลี่ยนโหมด</div>
      `;
      nativeForm.insertAdjacentElement("afterend", wrap);
      nativeForm.style.display = "none";

      const box      = wrap.querySelector(".enh-cb-box");
      const ta       = wrap.querySelector("textarea");
      const sendBtn  = wrap.querySelector(".enh-cb-send");
      const modePill = wrap.querySelector('[data-pill="mode"]');
      const agentPill= wrap.querySelector('[data-pill="agent"]');
      const skillsPill = wrap.querySelector('[data-pill="skills"]');
      const skillsLbl  = wrap.querySelector(".enh-cb-skills-lbl");
      const chipsEl  = wrap.querySelector(".enh-cb-chips");
      const mode2El  = wrap.querySelector(".enh-cb-mode2");

      function curMode() { return MODES.find((m) => m.id === _cbMode) || MODES[1]; }

      function applyAccent() {
        const c = curMode().color;
        box.style.setProperty("--c", c);
        wrap.querySelectorAll(".enh-cb-dd-skills, .enh-cb-sk").forEach((el) => el.style.setProperty("--c", c));
      }

      function syncModePill() {
        const m = curMode();
        modePill.querySelector(".enh-cb-mode-glyph").textContent = m.glyph;
        modePill.querySelector(".enh-cb-mode-lbl").textContent = m.label;
        modePill.style.setProperty("--c", m.color);
        modePill.style.color = m.color;
        applyAccent();
      }

      function syncAgentPill() {
        if (!_agent) { agentPill.style.display = "none"; return; }
        const color = AGENT_COLOR[_agent.slug] || "#B69EF5";
        const emoji = AGENT_EMOJI[_agent.slug] || "🤖";
        agentPill.innerHTML = `${emoji} ${_esc(_shortAgentName(_agent.name))} <span class="enh-cb-chev">▾</span>`;
        agentPill.style.color = color;
      }

      function syncSkillsUI() {
        skillsPill.style.color = _cbSkills.length ? curMode().color : "#3E3E5A";
        skillsLbl.textContent = _cbSkills.length ? `Skills · ${_cbSkills.length}` : "Skills";
        chipsEl.innerHTML = "";
        SKILLS.filter((s) => _cbSkills.includes(s.id)).forEach((s) => {
          const chip = document.createElement("span");
          chip.className = "enh-cb-chip";
          chip.style.setProperty("--c", curMode().color);
          chip.textContent = `${s.icon} ${s.label} ×`;
          chip.addEventListener("click", () => toggleSkill(s.id));
          chipsEl.appendChild(chip);
        });
        wrap.querySelector('[data-act="search"]')?.classList.toggle("active", _webSearchSkill);
      }

      function syncStatus() {
        // reconcile pill Code/Ask ↔ _agentMode จริง — กติกาอยู่ใน chat_intercept.js
        // (FAB Agent/Claude toggle เปลี่ยน _agentMode ได้โดยไม่ผ่าน pill → pill ห้ามโกหก)
        const _next = window.hwChatIntercept
          ? window.hwChatIntercept.reconcileMode(_cbMode, _agentMode) : null;
        if (_next) {
          _cbMode = _next; localStorage.setItem("hw_cb_mode", _cbMode);
          syncModePill(); syncSkillsUI();
        }
        mode2El.textContent = _claudeMode ? "Claude" : (_agentMode ? "Agent" : "Auto");
        mode2El.style.color = _claudeMode ? "#f9a8d4" : (_agentMode ? "#34d399" : "#7EB8F7");
      }

      // ── status dot = สุขภาพ local model จริงจาก /api/status (local_ok) ────
      // local หลัก = DeepSeek R1 via LM Studio — เดิม dot เขียว hardcode ตลอด
      // แม้ LM Studio ล่ม (ระบบตกไป Gemini เงียบๆ จน quota หมดโดยไม่รู้ตัว)
      const sdotEl = wrap.querySelector(".enh-cb-sdot");
      async function syncLocalHealth() {
        try {
          const s = await fetch("/api/status").then((r) => r.json());
          const ok = s.local_ok !== undefined ? s.local_ok : s.ollama; // fallback backend เก่า
          const c = ok ? "#5ECFA8" : "#ef4444";
          sdotEl.style.background = c;
          sdotEl.style.boxShadow = `0 0 6px ${c}88`;
          sdotEl.title = ok
            ? `${s.local_provider || "local"} พร้อมใช้งาน`
            : `${s.local_provider || "local"} ล่ม — ระบบจะ fallback ไป Gemini`;
        } catch {} // เช็คไม่ได้ → คงสีเดิมไว้
      }

      function toggleSkill(id) {
        const def = SKILLS.find((s) => s.id === id);
        if (_cbSkills.includes(id)) {
          _cbSkills = _cbSkills.filter((s) => s !== id);
        } else {
          _cbSkills = [..._cbSkills, id];
        }
        if (def?.real) {
          if (id === "obsidian")  _obsidianSkill  = _cbSkills.includes("obsidian");
          if (id === "search")    _webSearchSkill = _cbSkills.includes("search");
          if (id === "search" && _webSearchSkill && _claudeMode) {
            // Claude Mode ชนะ — interceptor จะไม่ฉีด tool_agent จนกว่าจะปิด Claude
            showToast("⚠️ Claude Mode เปิดอยู่ — Web Search จะยังไม่ทำงานจนกว่าจะปิด Claude (✨)", 3200);
          } else {
            showToast(`${_cbSkills.includes(id) ? "✅ เปิด" : "⭕ ปิด"} ${def.label} — ${def.hint}`, 2200);
          }
        }
        _persistSkills();
        syncSkillsUI();
      }

      // ── dropdowns (open/close + outside click) ───────────────────────────
      let _openDD = null; // { name, el }
      function closeDD() {
        if (_openDD) { _openDD.el.remove(); _openDD = null; }
      }
      function openDD(name, anchor, render) {
        if (_openDD && _openDD.name === name) return closeDD();
        closeDD();
        const dd = document.createElement("div");
        dd.className = "enh-cb-dd";
        render(dd);
        anchor.parentElement.appendChild(dd);
        _openDD = { name, el: dd };
      }
      document.addEventListener("mousedown", (e) => {
        if (_openDD && !_openDD.el.contains(e.target) &&
            !modePill.contains(e.target) && !agentPill.contains(e.target) && !skillsPill.contains(e.target)) {
          closeDD();
        }
      });

      modePill.addEventListener("click", () => {
        openDD("mode", modePill, (dd) => {
          MODES.forEach((m) => {
            const item = document.createElement("div");
            item.className = "enh-cb-dd-item";
            item.innerHTML = `<span style="color:${m.color};margin-top:2px;font-size:14px">${m.glyph}</span>
              <span style="flex:1"><div class="enh-cb-dd-lbl">${m.label}</div><div class="enh-cb-dd-sub">${_esc(m.desc)}</div></span>
              ${_cbMode === m.id ? `<span class="enh-cb-dd-chk" style="color:${m.color}">✓</span>` : ""}`;
            item.addEventListener("click", () => {
              _cbMode = m.id;
              localStorage.setItem("hw_cb_mode", _cbMode);
              _applyModeSideEffects(_cbMode);
              syncModePill(); syncSkillsUI(); syncStatus(); closeDD();
            });
            dd.appendChild(item);
          });
        });
      });

      agentPill.addEventListener("click", () => {
        if (!assistants.length) return;
        openDD("agent", agentPill, (dd) => {
          dd.style.minWidth = "220px";
          assistants.forEach((a) => {
            const color = AGENT_COLOR[a.slug] || "#B69EF5";
            const emoji = AGENT_EMOJI[a.slug] || "🤖";
            const item = document.createElement("div");
            item.className = "enh-cb-dd-item";
            item.innerHTML = `<span style="font-size:17px;line-height:1">${emoji}</span>
              <span style="flex:1"><div class="enh-cb-dd-lbl">${_esc(_shortAgentName(a.name))}</div><div class="enh-cb-dd-sub">${_esc(a.name)}</div></span>
              ${_agent?.slug === a.slug ? `<span class="enh-cb-dd-chk" style="color:${color}">✓</span>` : ""}`;
            item.addEventListener("click", () => {
              closeDD();
              // สลับผู้ช่วยจริง — คลิกปุ่มเดิมใน sidebar (จับคู่ด้วยข้อความชื่อเต็ม)
              const btn = [...document.querySelectorAll("button")].find((b) => b.textContent.trim() === a.name);
              if (btn) {
                btn.click();
                _agent = a;
                syncAgentPill();
                ta.placeholder = `พิมพ์ถึง ${_shortAgentName(a.name)}...`;
              } else {
                showToast("ℹ️ สลับผู้ช่วยได้ที่แถบด้านข้าง (ไม่พบปุ่มสลับในหน้านี้)");
              }
            });
            dd.appendChild(item);
          });
        });
      });

      function renderSkillsDD(dd) {
        dd.innerHTML = "";
        const inner = document.createElement("div");
        inner.className = "enh-cb-dd-skills";
        inner.style.setProperty("--c", curMode().color);
        SKILLS.forEach((s) => {
          const row = document.createElement("div");
          row.className = `enh-cb-sk${_cbSkills.includes(s.id) ? " on" : ""}`;
          row.title = s.hint;
          row.innerHTML = `<span>${s.icon}</span><span style="flex:1">${s.label}</span>
            ${s.real ? '<span class="enh-cb-sk-dot" title="ต่อ backend จริง"></span>' : ""}
            ${_cbSkills.includes(s.id) ? '<span class="enh-cb-sk-check">✓</span>' : ""}`;
          row.addEventListener("click", () => { toggleSkill(s.id); renderSkillsDD(dd); });
          inner.appendChild(row);
        });
        dd.appendChild(inner);
        const foot = document.createElement("div");
        foot.style.cssText = "padding:8px 15px;border-top:1px solid #181824;font-size:10px;color:#46466A;";
        foot.textContent = "● = มีผลต่อคำตอบจริง · อื่น ๆ เป็นตัวเลือกแสดงผล";
        dd.appendChild(foot);
      }
      skillsPill.addEventListener("click", () => openDD("skills", skillsPill, renderSkillsDD));

      // ── textarea: mirror ↔ native input proxy ────────────────────────────
      function _setNativeValue(el, value) {
        const proto = el.tagName === "TEXTAREA" ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
        const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
        if (setter) setter.call(el, value); else el.value = value;
        el.dispatchEvent(new Event("input", { bubbles: true }));
      }

      function autoResize() {
        ta.style.height = "auto";
        ta.style.height = Math.min(ta.scrollHeight, 160) + "px";
      }
      ta.addEventListener("input", () => {
        sendBtn.classList.toggle("on", !!ta.value.trim());
        sendBtn.disabled = nativeInput.disabled || !ta.value.trim();
        autoResize();
      });

      function doSend() {
        const text = ta.value.trim();
        if (!text) return;
        if (!_rebindNative()) { showToast("⚠️ หากล่องส่งของแอปไม่เจอ — ลอง refresh หน้า"); return; }
        if (nativeInput.disabled) return;
        _setNativeValue(nativeInput, text);
        const submitted = nativeForm.requestSubmit ? nativeForm.requestSubmit() : nativeForm.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
        void submitted;
        ta.value = "";
        sendBtn.classList.remove("on");
        autoResize();
        ta.focus();
      }

      ta.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); doSend(); }
        if (e.ctrlKey && ["1", "2", "3"].includes(e.key)) {
          e.preventDefault();
          _cbMode = ["code", "ask", "plan"][+e.key - 1];
          localStorage.setItem("hw_cb_mode", _cbMode);
          _applyModeSideEffects(_cbMode);
          syncModePill(); syncStatus();
        }
      });
      sendBtn.addEventListener("click", doSend);

      // ── toolbar buttons: proxy ไปไฟล์อินพุตที่ซ่อนของจริง ─────────────────
      wrap.querySelector('[data-act="attach"]').addEventListener("click", () => {
        document.querySelector('input[type="file"][accept*=".txt"]')?.click();
      });
      wrap.querySelector('[data-act="image"]').addEventListener("click", () => {
        document.querySelector('input[type="file"][accept="image/*"]')?.click();
      });
      wrap.querySelector('[data-act="search"]').addEventListener("click", () => toggleSkill("search"));

      // ── reflect native input's disabled (streaming) state ────────────────
      const _disabledObs = new MutationObserver(() => {
        ta.disabled = nativeInput.disabled;
        sendBtn.disabled = nativeInput.disabled || !ta.value.trim();
      });
      _disabledObs.observe(nativeInput, { attributes: true, attributeFilter: ["disabled"] });

      // ── re-bind เมื่อ React re-mount composer (เช่น สลับผู้ช่วย/session) ──
      // ไม่งั้น nativeInput ค้างเป็น detached node → requestSubmit เงียบ = ข้อความหาย
      // + form ใหม่โผล่มาเป็น input bar ซ้อนสอง (display:none ติดอยู่กับ node เก่า)
      function _rebindNative() {
        if (document.contains(nativeInput)) return true;
        const ni = _findNativeInput();
        if (!ni || wrap.contains(ni)) return false;
        nativeInput = ni;
        nativeForm = ni.closest("form") || ni.parentElement;
        nativeForm.style.display = "none";
        _disabledObs.disconnect();
        _disabledObs.observe(nativeInput, { attributes: true, attributeFilter: ["disabled"] });
        ta.disabled = nativeInput.disabled;
        sendBtn.disabled = nativeInput.disabled || !ta.value.trim();
        return true;
      }

      ta.addEventListener("focus", () => box.classList.add("on"));
      ta.addEventListener("blur",  () => box.classList.remove("on"));

      // ── keep agent pill in sync when assistant switches elsewhere (sidebar) ──
      setInterval(() => {
        _rebindNative();
        if (ctx.assistant && (!_agent || _agent.slug !== ctx.assistant)) {
          const found = assistants.find((a) => a.slug === ctx.assistant);
          if (found) { _agent = found; syncAgentPill(); ta.placeholder = `พิมพ์ถึง ${_shortAgentName(found.name)}...`; }
        }
      }, 1500);

      // ── init ──────────────────────────────────────────────────────────────
      syncModePill();
      syncAgentPill();
      syncSkillsUI();
      syncStatus();
      setInterval(syncStatus, 1000);
      syncLocalHealth();
      setInterval(syncLocalHealth, 60000); // backend cache 30s — poll 60s พอ
      // draft ที่ถูก restore เข้า native composer ก่อน overlay mount → ย้ายมาแสดงที่นี่
      if (nativeInput.value && !ta.value) {
        ta.value = nativeInput.value;
        sendBtn.classList.toggle("on", !!ta.value.trim());
      }
      autoResize();
      if (_agent) ta.placeholder = `พิมพ์ถึง ${_shortAgentName(_agent.name)}...`;
    });
  })();

})();
