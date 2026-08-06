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

// ── กลุ่มควบคุม ────────────────────────────────────────────────────────────────
// ถ้าเผลอ gate §20 ทั้งก้อน หรือ gate ปุ่มลบตามไปด้วย เทสข้างบนจะผ่านฟรี
// ทั้งที่ผู้ใช้เสียปุ่มลบ (ทางเดียวที่ลบข้อความได้) ไปเลย
test("§20 ยังแนบปุ่ม '🗑️ ลบ' แบบไม่มีเงื่อนไข — React ไม่มีปุ่มลบข้อความ", () => {
  const sec = slice("// 19. EDIT + RESEND", "// 21.");
  assert.match(sec, /textContent\s*=\s*"🗑️ ลบ"/);
  assert.match(sec, /^\s*actRow\.appendChild\(delBtn\);\s*$/m);
});

test("slice() ตัดโค้ดออกมาได้จริง ไม่ใช่สตริงว่าง", () => {
  assert.ok(slice("// 19. COPY MESSAGE", "// 19. EDIT + RESEND").length > 200);
  assert.ok(slice("const pinObserver", "// 6. COPY CODE BUTTON").length > 200);
  assert.ok(slice("// 19. EDIT + RESEND", "// 21.").length > 200);
});
