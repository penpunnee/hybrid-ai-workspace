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

  window.fetch = function (url, opts) {
    if (typeof url === "string") {
      // 1. Track assistant + session + prompt history
      if (url === "/api/chat" && opts?.body) {
        try {
          const b = JSON.parse(opts.body);
          if (b.assistant) ctx.assistant = b.assistant;
          if (b.session_id) ctx.session = b.session_id;
          if (b.prompt?.trim()) {
            _promptHistory = [b.prompt, ..._promptHistory.filter(p => p !== b.prompt)].slice(0, 50);
            localStorage.setItem("hw_prompt_history", JSON.stringify(_promptHistory));
            _histIdx = -1;
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
        // ดัก 401 → login modal
        if (resp.status === 401) {
          loginOverlay.classList.add("open");
          setTimeout(() => document.getElementById("login-input")?.focus(), 100);
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

    /* Health Widget */
    #hw-btn {
      position: fixed; bottom: 16px; right: 16px; z-index: 9000;
      background: rgba(15,23,42,0.85); backdrop-filter: blur(12px);
      border: 1px solid rgba(99,102,241,0.3); border-radius: 12px;
      padding: 6px 12px; cursor: pointer; font-size: 11px;
      color: #94a3b8; display: flex; align-items: center; gap: 8px;
      transition: all .2s; user-select: none;
    }
    #hw-btn:hover { border-color: rgba(99,102,241,0.7); color: #e2e8f0; }
    #hw-panel {
      position: fixed; bottom: 52px; right: 16px; z-index: 9001;
      background: rgba(15,23,42,0.95); backdrop-filter: blur(16px);
      border: 1px solid rgba(99,102,241,0.25); border-radius: 16px;
      padding: 16px; min-width: 240px; display: none;
      box-shadow: 0 8px 32px rgba(0,0,0,0.4);
    }
    #hw-panel.open { display: block; }
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
      position: fixed; bottom: 16px; right: 76px; z-index: 9000;
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

    /* Toast */
    #enh-toast {
      position: fixed; bottom: 64px; left: 50%; transform: translateX(-50%);
      background: rgba(15,23,42,0.95); border: 1px solid rgba(99,102,241,0.4);
      border-radius: 10px; padding: 8px 16px; font-size: 12px; color: #e2e8f0;
      z-index: 9999; opacity: 0; transition: opacity .3s; pointer-events: none;
    }
    #enh-toast.show { opacity: 1; }

    /* ── Mobile responsive (< 640px) ───────────────────────────── */
    @media (max-width: 639px) {
      /* Login box */
      #login-box { padding: 28px 20px; border-radius: 18px; }

      /* Search / Vault overlay — nearly full-screen sheet */
      .enh-overlay { padding-top: 16px; align-items: flex-start; }
      .enh-box {
        width: calc(100vw - 24px) !important;
        max-height: 82vh; padding: 16px; border-radius: 16px;
      }

      /* Floating toolbar — icon-only, sit above token bar */
      #enh-toolbar { bottom: 28px; right: 8px; gap: 4px; }
      .enh-fab { padding: 7px 9px; }
      .enh-fab span { display: none; }

      /* Health widget — move to left so it doesn't clash with toolbar */
      #hw-btn { bottom: 28px; right: auto; left: 8px; }
      #hw-panel { bottom: 62px; left: 8px; right: 8px; min-width: 0; }

      /* Home control button + panel */
      #hw-home-btn { bottom: 70px; right: 8px; width: 36px; height: 36px; font-size: 18px; }
      #hw-home-panel { width: calc(100vw - 24px); right: 12px; left: 12px; bottom: 114px; }

      /* Scroll-to-bottom button */
      #enh-scroll-btn { bottom: 70px; right: 52px; }

      /* Pin button — inside bubble, always semi-visible (no hover on touch) */
      .enh-pin-btn { right: 6px !important; top: 6px !important; opacity: 0.5 !important; }
      [data-pinned="true"] .enh-pin-btn { opacity: 1 !important; }

      /* Token bar */
      #enh-token-bar { padding: 3px 10px; gap: 8px; }
      #enh-token-text { min-width: 0; font-size: 10px; }

      /* Typing indicator */
      #enh-typing { bottom: 28px; }
    }
  `;
  document.head.appendChild(css);

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
        // reload เพื่อให้ React โหลดใหม่พร้อม token
        window.location.reload();
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

  // ─────────────────────────────────────────────────────────────────────────────
  // 1. HEALTH WIDGET
  // ─────────────────────────────────────────────────────────────────────────────
  const hwBtn = document.createElement("div");
  hwBtn.id = "hw-btn";
  hwBtn.innerHTML = `<span id="hw-dot">●</span><span id="hw-summary">System</span>`;
  document.body.appendChild(hwBtn);

  const hwPanel = document.createElement("div");
  hwPanel.id = "hw-panel";
  hwPanel.innerHTML = `<div class="enh-title">📊 System Health</div><div id="hw-body"></div>`;
  document.body.appendChild(hwPanel);

  hwBtn.addEventListener("click", () => hwPanel.classList.toggle("open"));
  document.addEventListener("click", (e) => {
    if (!hwBtn.contains(e.target) && !hwPanel.contains(e.target))
      hwPanel.classList.remove("open");
  });

  function colorPct(pct) {
    return pct > 85 ? "#f87171" : pct > 65 ? "#fbbf24" : "#34d399";
  }
  function barColor(pct) {
    return pct > 85 ? "#f87171" : pct > 65 ? "#fbbf24" : "#6366f1";
  }

  async function fetchHealth() {
    try {
      const r = await _origFetch("/api/health");
      const d = await r.json();
      const disk = d.disk || {};
      const ram = d.ram || {};
      const chroma = d.chromadb || {};
      const dream = d.dream?.last || {};

      document.getElementById("hw-dot").style.color = "#34d399";
      document.getElementById("hw-summary").textContent =
        `💾${disk.used_pct ?? "?"}% 🧠${ram.used_pct ?? "?"}%`;

      document.getElementById("hw-body").innerHTML = `
        <div class="hw-row"><span>💾 Disk</span>
          <span class="hw-val" style="color:${colorPct(disk.used_pct)}">${disk.used_gb}/${disk.total_gb} GB</span></div>
        <div class="hw-bar"><div class="hw-fill" style="width:${disk.used_pct}%;background:${barColor(disk.used_pct)}"></div></div>

        <div class="hw-row"><span>🧠 RAM</span>
          <span class="hw-val" style="color:${colorPct(ram.used_pct)}">${ram.used_mb}/${ram.total_mb} MB</span></div>
        <div class="hw-bar"><div class="hw-fill" style="width:${ram.used_pct}%;background:${barColor(ram.used_pct)}"></div></div>

        <div class="hw-row"><span>🔵 ChromaDB</span>
          <span class="hw-val ${chroma.available ? "hw-ok" : "hw-err"}">
            ${chroma.available ? `✅ ${chroma.total ?? 0} entries` : "❌ Offline"}</span></div>

        <div class="hw-row"><span>🌙 Dream ล่าสุด</span>
          <span class="hw-val">${dream.started_at ? dream.started_at.slice(0,16) : "ยังไม่มี"}</span></div>

        <div class="hw-row"><span>📚 Skills</span>
          <span class="hw-val">${d.skills_count ?? 0} skills</span></div>

        <div class="hw-row"><span>🗄️ DB</span>
          <span class="hw-val">${d.db_size_mb ?? 0} MB</span></div>
      `;
    } catch {
      document.getElementById("hw-dot").style.color = "#f87171";
      document.getElementById("hw-summary").textContent = "Offline";
    }
  }

  fetchHealth();
  setInterval(fetchHealth, 60_000);

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
    <button class="enh-fab" id="fab-search" title="ค้นหาทุก Session (Ctrl+Shift+F)">
      🔍 <span>Search</span>
    </button>
    <button class="enh-fab" id="fab-export" title="Export Session (Ctrl+E)">
      📤 <span>Export</span>
    </button>
    <button class="enh-fab" id="fab-vault" title="Vault Search">
      🌿 <span>Vault</span>
    </button>`;
  document.body.appendChild(toolbar);

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

  // นับ token จาก DOM (ไม่ต้องรอ API) — 1 char ≈ 0.35 token (Thai/English mix)
  function _updateTokenBar() {
    try {
      const msgs = document.querySelectorAll("p.whitespace-pre-wrap, p[class*='whitespace-pre']");
      if (!msgs.length) return;
      let chars = 0;
      msgs.forEach(p => { chars += (p.innerText || "").length; });
      const estimated = Math.round(chars * 0.35);
      // ดึง limit จาก /api/status ที่ React เคย load (หรือ fallback)
      const statusRaw = localStorage.getItem("hw_status_cache");
      const limit = statusRaw ? (JSON.parse(statusRaw).context_limit || 4096) : 4096;
      const pct = Math.min(100, Math.round(estimated / limit * 100));
      const fill = document.getElementById("enh-token-fill");
      const text = document.getElementById("enh-token-text");
      if (fill) {
        fill.style.width = pct + "%";
        fill.style.background = pct > 85 ? "#ef4444" : pct > 65 ? "#f59e0b" : "#6366f1";
      }
      if (text) text.textContent = `~${estimated.toLocaleString()} / ${limit.toLocaleString()} tokens`;
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
  // 14. HOME CONTROL PANEL — NAS + PC + Wake-on-LAN (rewritten v2)
  // ─────────────────────────────────────────────────────────────────────────────
  // inject CSS
  document.head.insertAdjacentHTML("beforeend", `<style>
    #hw-home-btn {
      position:fixed; bottom:72px; right:18px; z-index:9300;
      width:42px; height:42px; border-radius:50%;
      background:rgba(15,23,42,0.9); border:1.5px solid rgba(99,102,241,0.5);
      cursor:pointer; font-size:20px; display:flex; align-items:center; justify-content:center;
      box-shadow:0 4px 16px rgba(0,0,0,0.5); transition:all .2s; user-select:none;
    }
    #hw-home-btn:hover { transform:scale(1.12); border-color:#818cf8; }
    #hw-home-btn.active { border-color:#6366f1; background:rgba(99,102,241,0.25); }
    #hw-home-panel {
      position:fixed; bottom:122px; right:18px; z-index:9299;
      width:min(308px, calc(100vw - 32px)); max-height:70vh; overflow-y:auto;
      background:rgba(8,12,24,0.96); border:1px solid rgba(99,102,241,0.35);
      border-radius:16px; backdrop-filter:blur(20px);
      padding:14px 14px 12px; display:none; flex-direction:column; gap:9px;
      box-shadow:0 12px 40px rgba(0,0,0,0.6); color:#e2e8f0; font-size:12px;
    }
    #hw-home-panel.show { display:flex; }
    .hw-h { font-size:10px; color:#6366f1; font-weight:700; letter-spacing:.06em; text-transform:uppercase; }
    .hw-row { display:flex; align-items:center; gap:7px; }
    .hw-bar { height:4px; border-radius:2px; background:rgba(255,255,255,0.07); margin-top:3px; }
    .hw-bar-fill { height:100%; border-radius:2px; transition:width .5s; }
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
  </style>`);

  // toggle button
  const hcBtn = document.createElement("div");
  hcBtn.id = "hw-home-btn";
  hcBtn.title = "Home Control";
  hcBtn.innerHTML = "🏠";
  document.body.appendChild(hcBtn);

  // panel skeleton (buttons wired via addEventListener, NOT onclick=)
  const hcPanel = document.createElement("div");
  hcPanel.id = "hw-home-panel";
  document.body.appendChild(hcPanel);

  function _hwBarColor(p) { return p > 85 ? "#ef4444" : p > 65 ? "#f59e0b" : "#10b981"; }

  function _hwRender() {
    hcPanel.innerHTML = `
      <div class="hw-row" style="margin-bottom:2px">
        <span class="hw-h" style="flex:1">🏠 Home Control</span>
        <span id="hw-ts" style="font-size:10px;color:#475569">—</span>
        <button id="hw-x" style="background:none;border:none;color:#64748b;cursor:pointer;font-size:13px;padding:0 0 0 8px">✕</button>
      </div>
      <hr class="hw-sep">
      <div class="hw-h" style="color:#94a3b8">💾 NAS Storage</div>
      <div id="hw-disk" style="color:#64748b;font-size:11px">กำลังโหลด…</div>
      <hr class="hw-sep">
      <div class="hw-h" style="color:#94a3b8">🐳 Docker Containers</div>
      <div id="hw-docker" style="color:#64748b;font-size:11px">กำลังโหลด…</div>
      <hr class="hw-sep">
      <div class="hw-h" style="color:#94a3b8">🖥️ PC 192.168.51.235</div>
      <div id="hw-pc" class="hw-row" style="color:#64748b;font-size:11px">กำลัง ping…</div>
      <hr class="hw-sep">
      <div class="hw-row">
        <button id="hw-refresh" class="hw-btn hw-g">🔄 Refresh</button>
        <button id="hw-wol" class="hw-btn hw-o">⚡ Wake PC</button>
        <button id="hw-pingnas" class="hw-btn hw-b">📡 Ping NAS</button>
      </div>`;

    document.getElementById("hw-x").addEventListener("click", _hwClose);
    document.getElementById("hw-refresh").addEventListener("click", _hwRefresh);
    document.getElementById("hw-wol").addEventListener("click", _hwWol);
    document.getElementById("hw-pingnas").addEventListener("click", _hwPingNAS);
  }

  let _hwOpen = false;

  function _hwClose() { hcPanel.classList.remove("show"); hcBtn.classList.remove("active"); _hwOpen = false; }
  function _hwToggle(e) {
    e.stopPropagation();
    if (_hwOpen) { _hwClose(); return; }
    _hwOpen = true;
    _hwRender();
    hcPanel.classList.add("show");
    hcBtn.classList.add("active");
    _hwRefresh();
  }

  hcBtn.addEventListener("click", _hwToggle);
  document.addEventListener("click", (e) => {
    if (_hwOpen && !hcPanel.contains(e.target) && e.target !== hcBtn && !hcBtn.contains(e.target))
      _hwClose();
  });

  async function _hwRefresh() {
    const h = _authToken ? { "x-auth-token": _authToken } : {};

    // disk
    try {
      const r = await _origFetch("/api/tools/home/disk", { headers: h }).then(x => x.json());
      const el = document.getElementById("hw-disk");
      if (!el) return;
      if (r.error) { el.textContent = "❌ " + r.error; }
      else if (!r.volumes?.length) { el.textContent = "ไม่พบข้อมูล volume"; }
      else {
        el.innerHTML = r.volumes.map(v => {
          const c = _hwBarColor(v.percent);
          return `<div style="margin-bottom:4px">
            <div class="hw-row"><span style="flex:1;color:#94a3b8">${v.path}</span>
            <span style="color:${c};font-weight:600">${v.free_gb} GB ว่าง</span></div>
            <div class="hw-bar"><div class="hw-bar-fill" style="width:${v.percent}%;background:${c}"></div></div>
            <div style="color:#475569;font-size:10px">${v.used_gb} / ${v.total_gb} GB · ${v.percent}%</div>
          </div>`;
        }).join("");
      }
    } catch(e) { const el=document.getElementById("hw-disk"); if(el) el.textContent="❌ " + e.message; }

    // docker
    try {
      const r = await _origFetch("/api/tools/home/docker", { headers: h }).then(x => x.json());
      const el = document.getElementById("hw-docker");
      if (!el) return;
      if (r.error) { el.textContent = "❌ " + r.error; }
      else {
        const cs = r.containers || [];
        el.innerHTML = cs.length ? cs.map(c =>
          `<div class="hw-row" style="margin-bottom:2px">
            <span>${c.running?"🟢":"🔴"}</span>
            <span style="flex:1;color:${c.running?"#e2e8f0":"#475569"}">${c.name}</span>
            <span style="color:#334155;font-size:10px">${c.status}</span>
          </div>`).join("") : "ไม่พบ container";
      }
    } catch(e) { const el=document.getElementById("hw-docker"); if(el) el.textContent="❌ " + e.message; }

    // ping PC
    try {
      const r = await _origFetch("/api/tools/home/ping/192.168.51.235", { headers: h }).then(x => x.json());
      const el = document.getElementById("hw-pc");
      if (!el) return;
      const lat = r.latency_ms != null ? ` · ${r.latency_ms.toFixed(1)}ms` : "";
      el.innerHTML = r.online
        ? `<span>🟢</span><span style="color:#34d399">Online${lat}</span>`
        : `<span>🔴</span><span style="color:#ef4444">Offline</span>`;
    } catch(e) { const el=document.getElementById("hw-pc"); if(el) el.textContent="❌ " + e.message; }

    const ts = document.getElementById("hw-ts");
    if (ts) ts.textContent = new Date().toLocaleTimeString("th-TH",{hour:"2-digit",minute:"2-digit"});
  }

  async function _hwWol() {
    const btn = document.getElementById("hw-wol");
    if (!btn) return;
    btn.textContent = "⏳…"; btn.disabled = true;
    try {
      const h = { "Content-Type": "application/json", ...(_authToken ? { "x-auth-token": _authToken } : {}) };
      const r = await _origFetch("/api/tools/home/wol", { method: "POST", headers: h }).then(x => x.json());
      btn.textContent = r.ok ? "✅ ส่งแล้ว!" : "❌ Error";
      if (!r.ok && r.error) alert(r.error);
      if (r.ok) setTimeout(_hwRefresh, 35000);
    } catch { btn.textContent = "❌ Error"; }
    setTimeout(() => { if(btn){btn.textContent="⚡ Wake PC";btn.disabled=false;} }, 5000);
  }

  async function _hwPingNAS() {
    const btn = document.getElementById("hw-pingnas");
    if (!btn) return;
    btn.textContent = "⏳…"; btn.disabled = true;
    try {
      const h = _authToken ? { "x-auth-token": _authToken } : {};
      const r = await _origFetch("/api/tools/home/ping/192.168.51.49", { headers: h }).then(x => x.json());
      const lat = r.latency_ms != null ? ` ${r.latency_ms.toFixed(1)}ms` : "";
      btn.textContent = r.online ? `📡 OK${lat}` : "📡 Offline";
    } catch { btn.textContent = "📡 Error"; }
    setTimeout(() => { if(btn){btn.textContent="📡 Ping NAS";btn.disabled=false;} }, 4000);
  }

  console.log("[Enhanced UI] v5 — Home Control rewritten — loaded ✅");
})();
