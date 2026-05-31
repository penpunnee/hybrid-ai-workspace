// Tests สำหรับ static/dream_stats.js — แปลง dream report → ตัวเลขจริงของการ์ด Light/REM/Deep
// รัน: node --test tests/dream_stats.test.js
const { test } = require("node:test");
const assert = require("node:assert");
const { dreamCardValues } = require("../static/dream_stats.js");

const DASH = { light: "—", rem: "—", deep: "—" };

test("null/undefined → ขีด (ไม่มีข้อมูล)", () => {
  for (const v of [null, undefined, 0, "x", []]) {
    const r = dreamCardValues(v);
    assert.strictEqual(r.light, "—");
    assert.strictEqual(r.rem, "—");
    assert.strictEqual(r.deep, "—");
  }
});

test("error report (ยังไม่เคยมี dream) → ขีด", () => {
  const r = dreamCardValues({ error: "no reports yet" });
  assert.deepStrictEqual({ light: r.light, rem: r.rem, deep: r.deep }, DASH);
});

test("available:false (ChromaDB offline) → ขีด", () => {
  const r = dreamCardValues({ available: false, started_at: "x" });
  assert.strictEqual(r.light, "—");
});

test("skipped report (ไม่มี memory) → 0/0/0 ตามจริง", () => {
  const rep = {
    started_at: "2026-05-30T02:00:01",
    phase1_light: { raw_count: 0 },
    skipped: "no memories in window",
  };
  const r = dreamCardValues(rep);
  assert.strictEqual(r.light, 0);
  assert.strictEqual(r.rem, 0);
  assert.strictEqual(r.deep, 0);
  assert.strictEqual(r.skipped, true);
});

test("full report → นับ raw_count / themes.length / phase3.count จริง", () => {
  const rep = {
    started_at: "2026-05-30T02:00:01",
    phase1_light: { raw_count: 12 },
    phase2_rem: { themes: [{ name: "a" }, { name: "b" }, { name: "c" }] },
    phase3_deep: { count: 2, promoted: [{}, {}] },
    phase3_prune: { pruned: 1, kept: 19 },
  };
  const r = dreamCardValues(rep);
  assert.strictEqual(r.light, 12);
  assert.strictEqual(r.rem, 3);
  assert.strictEqual(r.deep, 2);
  assert.strictEqual(r.skipped, false);
});

test("themes ไม่ใช่ array (malformed) → rem = 0 ไม่ crash", () => {
  const r = dreamCardValues({
    started_at: "x",
    phase1_light: { raw_count: 5 },
    phase2_rem: { themes: null },
  });
  assert.strictEqual(r.light, 5);
  assert.strictEqual(r.rem, 0);
  assert.strictEqual(r.deep, 0);
});

test("phase3 ใช้ promoted.length เมื่อไม่มี count", () => {
  const r = dreamCardValues({
    started_at: "x",
    phase1_light: { raw_count: 3 },
    phase3_deep: { promoted: [{}, {}, {}, {}] },
  });
  assert.strictEqual(r.deep, 4);
});
