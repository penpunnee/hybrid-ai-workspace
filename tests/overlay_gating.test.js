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
