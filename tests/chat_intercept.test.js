// Tests สำหรับ static/chat_intercept.js — pure logic ของ fetch interceptor (§22)
// extract จาก enhanced.js เพื่อเทสได้ (scrutinize Minor 6, session 2026-06-10)
// รัน: node --test tests/chat_intercept.test.js
const { test } = require("node:test");
const assert = require("node:assert");
const { applyChatBodyMutations, reconcileMode } = require("../static/chat_intercept.js");

const OFF = { claudeMode: false, agentMode: false, obsidian: false, webSearch: false, mode: "ask" };

// ── applyChatBodyMutations ──────────────────────────────────────────────────

test("state ปิดหมด → ไม่ mutate", () => {
  const b = { prompt: "สวัสดี" };
  const r = applyChatBodyMutations(b, { ...OFF });
  assert.strictEqual(r.mutated, false);
  assert.strictEqual(r.needTimeline, false);
  assert.deepStrictEqual(b, { prompt: "สวัสดี" });
});

test("Claude mode → provider=claude", () => {
  const b = { prompt: "x" };
  const r = applyChatBodyMutations(b, { ...OFF, claudeMode: true });
  assert.strictEqual(b.provider, "claude");
  assert.strictEqual(r.mutated, true);
});

test("Agent mode → tool_agent + ต้องเปิด timeline", () => {
  const b = { prompt: "x" };
  const r = applyChatBodyMutations(b, { ...OFF, agentMode: true });
  assert.strictEqual(b.tool_agent, true);
  assert.strictEqual(r.needTimeline, true);
});

test("Claude ชนะ Agent — เปิดคู่กัน provider=claude ไม่ฉีด tool_agent", () => {
  const b = { prompt: "x" };
  applyChatBodyMutations(b, { ...OFF, claudeMode: true, agentMode: true });
  assert.strictEqual(b.provider, "claude");
  assert.strictEqual(b.tool_agent, undefined);
});

// regression Major 1 (scrutinize 2026-06-10): webSearch ห้าม hijack Claude
test("Major 1: webSearch + Claude mode → ห้ามฉีด tool_agent (กันเด้งไป gemini agent)", () => {
  const b = { prompt: "x" };
  const r = applyChatBodyMutations(b, { ...OFF, claudeMode: true, webSearch: true });
  assert.strictEqual(b.provider, "claude");
  assert.strictEqual(b.tool_agent, undefined);
  assert.strictEqual(r.needTimeline, false);
});

test("webSearch (ไม่มี Claude) → tool_agent + timeline", () => {
  const b = { prompt: "x" };
  const r = applyChatBodyMutations(b, { ...OFF, webSearch: true });
  assert.strictEqual(b.tool_agent, true);
  assert.strictEqual(r.needTimeline, true);
});

test("webSearch ไม่ทับ tool_agent ที่ client ส่งมาเองแล้ว", () => {
  const b = { prompt: "x", tool_agent: true };
  const r = applyChatBodyMutations(b, { ...OFF, webSearch: true });
  assert.strictEqual(b.tool_agent, true);
  assert.strictEqual(r.mutated, false); // ไม่มีอะไรเปลี่ยนจริง
});

test("Obsidian skill → obsidian_inject (idempotent)", () => {
  const b = { prompt: "x" };
  const r1 = applyChatBodyMutations(b, { ...OFF, obsidian: true });
  assert.strictEqual(b.obsidian_inject, true);
  assert.strictEqual(r1.mutated, true);
  const r2 = applyChatBodyMutations(b, { ...OFF, obsidian: true });
  assert.strictEqual(r2.mutated, false);
});

// regression Major 2 (scrutinize 2026-06-10): plan = flag เท่านั้น ห้ามแตะ prompt
test("Major 2: Plan mode → plan_mode flag, prompt ต้องไม่ถูกแก้", () => {
  const b = { prompt: "ช่วยทำเว็บ" };
  const r = applyChatBodyMutations(b, { ...OFF, mode: "plan" });
  assert.strictEqual(b.plan_mode, true);
  assert.strictEqual(b.prompt, "ช่วยทำเว็บ");
  assert.strictEqual(r.mutated, true);
});

test("Plan mode idempotent — plan_mode มีแล้วไม่นับ mutate", () => {
  const b = { prompt: "x", plan_mode: true };
  const r = applyChatBodyMutations(b, { ...OFF, mode: "plan" });
  assert.strictEqual(r.mutated, false);
});

test("state เป็น null/undefined → ไม่พัง ไม่ mutate", () => {
  const b = { prompt: "x" };
  const r = applyChatBodyMutations(b, null);
  assert.strictEqual(r.mutated, false);
  assert.deepStrictEqual(b, { prompt: "x" });
});

test("ครบทุกอย่างพร้อมกัน (ไม่มี claude): agent+obsidian+webSearch+plan", () => {
  const b = { prompt: "x" };
  const r = applyChatBodyMutations(b, { claudeMode: false, agentMode: true, obsidian: true, webSearch: true, mode: "plan" });
  assert.strictEqual(b.tool_agent, true);
  assert.strictEqual(b.obsidian_inject, true);
  assert.strictEqual(b.plan_mode, true);
  assert.strictEqual(r.mutated, true);
  assert.strictEqual(r.needTimeline, true);
});

// ── reconcileMode ───────────────────────────────────────────────────────────

test("pill Code แต่ agent ปิด → เด้งกลับ ask", () => {
  assert.strictEqual(reconcileMode("code", false), "ask");
});

test("pill Ask แต่ agent เปิด → เด้งเป็น code", () => {
  assert.strictEqual(reconcileMode("ask", true), "code");
});

test("สอดคล้องอยู่แล้ว → null (ไม่ต้องเปลี่ยน)", () => {
  assert.strictEqual(reconcileMode("code", true), null);
  assert.strictEqual(reconcileMode("ask", false), null);
});

test("plan ไม่แตะ agent state ทั้งสองทาง", () => {
  assert.strictEqual(reconcileMode("plan", true), null);
  assert.strictEqual(reconcileMode("plan", false), null);
});
