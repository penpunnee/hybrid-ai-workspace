// chat_intercept.js — pure logic ของ fetch interceptor (§22 ChatBox)
// extract จาก enhanced.js เพื่อเทสได้ (scrutinize Minor 6, session 2026-06-10)
// dual-export: browser (window.hwChatIntercept) + node (require) — โหลดก่อน enhanced.js
(function (root) {
  "use strict";

  // กติกาการ mutate body ของ /api/chat และ /api/regenerate ตาม state ของ UI
  //   b     : parsed JSON body (ถูกแก้ in-place)
  //   state : { claudeMode, agentMode, obsidian, webSearch, mode }
  // คืน { mutated, needTimeline }
  //   mutated      → ต้อง re-stringify body
  //   needTimeline → ต้องเปิด agent timeline queue รอ SSE events
  //
  // กติกาสำคัญ (อย่าแก้โดยไม่อ่าน):
  // 1. Claude mode ชนะเสมอ — ห้ามฉีด tool_agent ตอน Claude เปิด เพราะ backend
  //    เช็ค tool_agent ก่อน provider → "claude" จะถูกเด้งไป gemini agent เงียบๆ
  // 2. Plan mode = flag `plan_mode` เท่านั้น ห้ามแตะ prompt — backend ฉีด
  //    instruction เข้า system prompt เอง (กัน suffix ปนเปื้อน DB/fine-tune)
  function applyChatBodyMutations(b, state) {
    const s = state || {};
    let mutated = false;
    let needTimeline = false;

    if (s.claudeMode) {
      b.provider = "claude";
      mutated = true;
    } else if (s.agentMode && !b.tool_agent) {
      b.tool_agent = true;
      needTimeline = true;
      mutated = true;
    }

    if (s.obsidian && !b.obsidian_inject) {
      b.obsidian_inject = true;
      mutated = true;
    }

    if (s.webSearch && !b.tool_agent && !s.claudeMode) {
      b.tool_agent = true;
      needTimeline = true;
      mutated = true;
    }

    if (s.mode === "plan" && !b.plan_mode) {
      b.plan_mode = true;
      mutated = true;
    }

    return { mutated, needTimeline };
  }

  // pill Code/Ask ต้องตรงกับ _agentMode จริงเสมอ (FAB/Claude toggle เปลี่ยน
  // agent state ได้โดยไม่ผ่าน pill) — คืนโหมดใหม่ หรือ null ถ้าตรงอยู่แล้ว
  // "plan" ไม่ผูกกับ agent state → ไม่ reconcile
  function reconcileMode(cbMode, agentMode) {
    if (cbMode === "code" && !agentMode) return "ask";
    if (cbMode === "ask" && agentMode) return "code";
    return null;
  }

  const api = { applyChatBodyMutations, reconcileMode };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.hwChatIntercept = api;
})(typeof window !== "undefined" ? window : this);
