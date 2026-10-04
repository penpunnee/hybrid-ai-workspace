// ตรวจว่า overlay ไม่ฉีดปุ่มซ้ำกับที่ React มีอยู่แล้ว
//
// ที่มา (audit 2026-08-06 บน prod): overlay ฉีดปุ่มทับ React รวม 132 ตัว —
//   AI bubble  → copy 2 ปุ่ม (React 📋 + overlay "คัดลอก") · pin 2 ปุ่ม
//   user bubble → edit 2 ปุ่ม (React ✏️ + overlay "✏️ แก้ไข")
// และปุ่ม 📌 ของ overlay **ตาย 66/66** เพราะ pinMessage() จับคู่ข้อความแบบเป๊ะ
// แต่ bubble.innerText มีคำว่า "คัดลอก" (ปุ่ม React) ปนอยู่ → match ไม่เจอ
//
// ⚠️ "🗑️ ลบ" ของ overlay **ไม่มีคู่ใน React** → ห้าม gate ทั้ง section ทิ้ง

const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const SRC = fs.readFileSync(
  path.join(__dirname, "..", "static", "enhanced.js"),
  "utf8",
);

/** ตัดโค้ดช่วงหนึ่งออกมาด้วยหมุดข้อความ (คอมเมนต์ถูกตัดทิ้ง กันเทสจับคำเตือนของตัวเอง) */
function slice(startMark, endMark) {
  const i = SRC.indexOf(startMark);
  assert.ok(i > -1, `หาไม่เจอ: ${startMark}`);
  const j = SRC.indexOf(endMark, i + startMark.length);
  assert.ok(j > i, `หาไม่เจอ: ${endMark}`);
  return SRC.slice(i, j).replace(/\/\/[^\n]*/g, "");
}

const GATE = /if\s*\(\s*window\.__hwReactChatBox\s*\)\s*return\s*;/;

test("§19 COPY MESSAGE ถูก gate ด้วย __hwReactChatBox (React มี 📋 แล้ว)", () => {
  const sec = slice("// 19. COPY MESSAGE", "// 19. EDIT + RESEND");
  assert.match(sec, GATE);
});

test("pin observer ถูก gate (React มี 📌 Pin ที่ใช้ dbId ตรงๆ และทำงานจริง)", () => {
  const sec = slice("const pinObserver", "// 6. COPY CODE BUTTON");
  assert.match(sec, GATE);
});

test("§20 แนบปุ่ม '✏️ แก้ไข' เฉพาะ bundle เก่า (React มี ✏️ ที่ใช้ dbId)", () => {
  const sec = slice("// 19. EDIT + RESEND", "// 21.");
  assert.match(
    sec,
    /if\s*\(\s*!window\.__hwReactChatBox\s*\)\s*actRow\.appendChild\(editBtn\)/,
  );
});

// ── §20 ทั้งก้อนต้อง gate เมื่อ React ChatBox อยู่ (audit 2026-09-24 ข้อ 13) ────────────
// ปุ่ม 🗑️ ของ overlay `.remove()` DOM ที่ React เป็นเจ้าของ → state เปลี่ยนครั้งถัดไป
// (ลบอีกตัว/สลับเซสชัน) React throw NotFoundError → root unmount = จอขาวทั้งแอป (พิสูจน์ใน jsdom)
// และหา dbId ด้วยการเทียบข้อความ (ข้อความซ้ำ = ลบผิดตัว) · ปุ่มลบย้ายเข้า React แล้ว
// (utils/deletepair.ts + app.tsx) · overlay คงไว้เป็น fallback ของ bundle เก่าเท่านั้น
// ⚠️ gate ทั้ง IIFE ไม่ใช่แค่ปุ่ม — ไม่งั้น wireUserBubble ยัง appendChild(actRow) เปล่าเข้า bubble ของ React
test("§20 ต้อง return ทันทีเมื่อ __hwReactChatBox (React มีปุ่มลบแล้ว — overlay ห้ามแตะ DOM ของ React)", () => {
  const sec = slice("// 19. EDIT + RESEND", "// 21.");
  const iife = sec.indexOf("(function () {");
  const gate = sec.search(/if\s*\(\s*window\.__hwReactChatBox\s*\)\s*return;/);
  assert.ok(iife > -1, "หา IIFE ของ §20 ไม่เจอ");
  assert.ok(gate > iife, "ไม่มี `if (window.__hwReactChatBox) return;` ใน §20");
  // gate ต้องมาก่อนจุดที่เริ่มแตะ DOM (ก่อน MutationObserver และก่อน wireUserBubble)
  assert.ok(gate < sec.indexOf("function wireUserBubble"), "gate ต้องอยู่ก่อน wireUserBubble");
});

// กลุ่มควบคุม — fallback ของ bundle เก่ายังต้องมีปุ่มลบ (ไม่ได้ลบ §20 ทิ้งทั้งก้อน)
test("§20 ยังมีปุ่ม '🗑️ ลบ' สำหรับ bundle เก่าที่ไม่ตั้ง __hwReactChatBox", () => {
  const sec = slice("// 19. EDIT + RESEND", "// 21.");
  assert.match(sec, /textContent\s*=\s*"🗑️ ลบ"/);
  assert.match(sec, /actRow\.appendChild\(delBtn\)/);
});

test("slice() ตัดโค้ดออกมาได้จริง ไม่ใช่สตริงว่าง", () => {
  assert.ok(slice("// 19. COPY MESSAGE", "// 19. EDIT + RESEND").length > 200);
  assert.ok(slice("const pinObserver", "// 6. COPY CODE BUTTON").length > 200);
  assert.ok(slice("// 19. EDIT + RESEND", "// 21.").length > 200);
});

// ── audit 2026-09-24 MEDIUM (frontend) — overlay ที่ React ทำเองแล้ว ห้ามทำซ้ำ (ก้อน 12 · 2026-09-29) ──
// §3 Ctrl+E: React (`app.tsx` onKey) export แล้ว · overlay ก็ export อีกไฟล์ = ได้ 2 ไฟล์ต่อการกดครั้งเดียว
test("§3 Ctrl+E ของ overlay ถูก gate (React export เองแล้ว — เดิมได้ 2 ไฟล์)", () => {
  const sec = slice("// 3. EXPORT SESSION", "// 4. PIN MESSAGE");
  const kd = sec.indexOf('addEventListener("keydown"');
  assert.ok(kd > -1, "หา keydown listener ของ §3 ไม่เจอ");
  assert.match(sec.slice(kd), GATE);
});

// §10 ↑/↓: ตั้ง `ta.value` ตรงๆ → value tracker ของ React ดัก setter ไว้ → onChange ไม่ยิง → state ไม่เปลี่ยน
// (Enter ส่งค่าเดิม) และยึด ArrowUp ทุกครั้งแม้เคอร์เซอร์อยู่กลางข้อความหลายบรรทัด · React ทำเอง (utils/prompthistory.ts)
test("§10 PROMPT HISTORY ถูก gate (React มี ↑/↓ ของตัวเอง)", () => {
  const sec = slice("// 10. PROMPT HISTORY", "// 11. PASTE IMAGE");
  assert.match(sec, GATE);
});

// §11 วางรูป: เขียน `hw_pending_image` ที่ React ไม่เคยอ่าน → toast "✅ รูปพร้อม" แต่รูปไม่ถูกส่ง · React รับ onPaste เอง
test("§11 PASTE IMAGE ถูก gate (React รับ onPaste เอง — overlay เขียน key ที่ไม่มีใครอ่าน)", () => {
  const sec = slice("// 11. PASTE IMAGE", "// 12. TYPING INDICATOR");
  assert.match(sec, GATE);
});

// tee + `_parseChatSSE`: ฉีด citations/reflection/cache/active_learning/timing ลงฟองที่ React render เองอยู่แล้ว
// = โชว์ซ้ำสอง + แก้ DOM ที่ React เป็นเจ้าของ (กติกา: overlay ห้ามแตะ DOM ของ React) · debate = ยัดผิดฟอง
test("tee stream + _parseChatSSE ทำเฉพาะ bundle เก่า (React render event พวกนี้เองแล้ว)", () => {
  const sec = slice("// Tee stream", "return resp;");
  const cond = sec.slice(0, sec.indexOf("{"));
  assert.match(cond, /!\s*window\.__hwReactChatBox/, `เงื่อนไข tee ต้องมี !window.__hwReactChatBox: ${cond}`);
});

// กลุ่มควบคุม — bundle เก่ายังได้ของเดิมครบ
test("bundle เก่ายังมี history ↑/↓ · paste · Ctrl+E · tee (ไม่ได้ลบทิ้ง)", () => {
  assert.match(slice("// 10. PROMPT HISTORY", "// 11. PASTE IMAGE"), /_promptHistory\[_histIdx\]/);
  assert.match(slice("// 11. PASTE IMAGE", "// 12. TYPING INDICATOR"), /\/api\/upload/);
  assert.match(slice("// 3. EXPORT SESSION", "// 4. PIN MESSAGE"), /doExport\(\)/);
  assert.match(slice("// Tee stream", "return resp;"), /_parseChatSSE\(/);
});

// ── §9 TOKEN USAGE BAR ย้ายไป React แล้ว (2026-10-04) ──────────────────────────────
// overlay นับแค่ข้อความบนจอแล้วหาร 4096 (hw_status_cache ไม่มีใครเขียน) · prod 10-04 จอ ~1,532/4,096 ของจริง 10,146/16,384
test("§9 แถบ token ของ overlay ถูก gate ด้วย __hwReactChatBox (React มีแถบ Context ที่ใช้ done.usage)", () => {
  const sec = slice("9. TOKEN USAGE BAR", "10. PROMPT HISTORY");
  const gate = sec.search(/if\s*\(\s*!\s*window\.__hwReactChatBox\s*\)\s*\{/);
  assert.ok(gate > -1, "ไม่มี `if (!window.__hwReactChatBox) {` ครอบ §9");
  assert.ok(sec.indexOf("appendChild(tokenBar)") > gate, "appendChild ต้องอยู่ใต้ gate");
  assert.ok(sec.indexOf("setInterval(_updateTokenBar") > gate, "setInterval ต้องอยู่ใต้ gate");
});

// ── §6 COPY CODE BUTTON ย้ายไป React แล้ว (2026-10-05) ─────────────────────────────
// React วางปุ่มในสตริงของ renderMarkdown (`utils/markdown.tsx` · `.md-copy`) + toast ของ React
// overlay เดิม: ปุ่ม opacity:0 โผล่ตอน hover (iPhone ไม่มี hover) · ไม่ gate = ได้ 2 ปุ่มต่อกล่อง
test("§6 COPY CODE BUTTON ถูก gate ก่อนแตะ pre.md-pre (React มีปุ่ม Copy ของกล่องโค้ดเองแล้ว)", () => {
  const sec = slice("// 6. COPY CODE BUTTON", "// 7. STOP GENERATION");
  const gate = sec.search(GATE);
  assert.ok(gate > -1, "ไม่มี `if (window.__hwReactChatBox) return;` ใน §6");
  assert.ok(gate > sec.indexOf("function _wireCopyButtons"), "gate ต้องอยู่ในตัว _wireCopyButtons (เช็คตอนถูกเรียก ไม่ใช่ตอนโหลดไฟล์)");
  assert.ok(gate < sec.indexOf('querySelectorAll("pre.md-pre")'), "gate ต้องมาก่อนจุดที่เริ่มแตะ pre.md-pre");
});

// กลุ่มควบคุม — bundle เก่า (ไม่มีธง) ยังได้ปุ่ม Copy ของ overlay
test("§6 ยังฉีดปุ่ม Copy ให้ bundle เก่าที่ไม่ตั้ง __hwReactChatBox", () => {
  const sec = slice("// 6. COPY CODE BUTTON", "// 7. STOP GENERATION");
  assert.match(sec, /pre\.appendChild\(btn\)/);
  assert.match(sec, /new MutationObserver\(_wireCopyButtons\)/);
});
