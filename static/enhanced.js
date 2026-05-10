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

  // ── State tracker + auth header injector ────────────────────────────────────
  const ctx = { assistant: null, session: null };
  const _origFetch = window.fetch.bind(window);

  window.fetch = function (url, opts) {
    if (typeof url === "string") {
      // Track current assistant + session from /api/chat calls
      if (url === "/api/chat" && opts?.body) {
        try {
          const b = JSON.parse(opts.body);
          if (b.assistant) ctx.assistant = b.assistant;
          if (b.session_id) ctx.session = b.session_id;
        } catch {}
      }
      // Inject auth token into all /api/ calls
      if (url.startsWith("/api/") && _authToken) {
        opts = opts ? { ...opts } : {};
        opts.headers = { ...(opts.headers || {}), "x-auth-token": _authToken };
      }
    }
    return _origFetch(url, opts);
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
      border-radius: 24px; padding: 40px; width: 360px; text-align: center;
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
      padding: 24px; width: 640px; max-height: 70vh;
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
        loginOverlay.classList.remove("open");
        document.getElementById("login-err").textContent = "";
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

  // ตรวจสอบ auth ตอนโหลดหน้า
  async function checkAuth() {
    try {
      const r = await _origFetch("/api/auth/check");
      const d = await r.json();
      if (d.required && !d.ok) {
        loginOverlay.classList.add("open");
        setTimeout(() => document.getElementById("login-input")?.focus(), 100);
      }
    } catch {}
  }
  checkAuth();

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

  // Observe DOM for new message bubbles
  const pinObserver = new MutationObserver(() => {
    // ตามหา AI message bubbles (class ที่มี prose หรือ markdown content)
    document.querySelectorAll(
      '[class*="message"],[class*="bubble"],[class*="chat"],[class*="msg"]'
    ).forEach((el) => {
      if (el.dataset.pinWired) return;
      el.dataset.pinWired = "1";
      el.style.position = "relative";

      const btn = document.createElement("button");
      btn.className = "enh-pin-btn";
      btn.textContent = "📌";
      btn.title = "Pin message";
      el.appendChild(btn);

      el.addEventListener("mouseenter", () => (btn.style.opacity = "1"));
      el.addEventListener("mouseleave", () => (btn.style.opacity = "0"));

      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        pinMessage(el.innerText.replace("📌", "").trim());
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

  console.log("[Enhanced UI] Health Widget, Search, Export, Pin, @vault — loaded ✅");
})();
