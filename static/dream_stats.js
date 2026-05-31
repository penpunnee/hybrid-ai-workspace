// dream_stats.js — pure mapper: dream report → ตัวเลขจริงของการ์ด Light/REM/Deep
// แทนค่า hardcoded เดิม (40/40/20%) ด้วยข้อมูล dream cycle จริง
// dual-export: ใช้ได้ทั้ง browser (window.dreamCardValues) และ node (require) เพื่อเทสได้
(function (root) {
  "use strict";

  // คืน { light, rem, deep, skipped, ran } จาก /api/dream/report
  //   light = phase1: จำนวนความจำที่ดึงมาวิเคราะห์
  //   rem   = phase2: จำนวนธีมที่สกัดได้
  //   deep  = phase3: จำนวนที่ promote เข้า long-term
  // ถ้าไม่มี report จริง / offline → "—"
  function dreamCardValues(report) {
    const dash = { light: "—", rem: "—", deep: "—", skipped: false, ran: false };
    if (!report || typeof report !== "object" || Array.isArray(report)) return dash;
    if (report.available === false) return dash;
    // ยังไม่เคยมี dream จริง (เช่น {error:"no reports yet"})
    if (!report.started_at && !report.phase1_light) return dash;

    const light = Number((report.phase1_light && report.phase1_light.raw_count) || 0);

    const themes = report.phase2_rem && report.phase2_rem.themes;
    const rem = Array.isArray(themes) ? themes.length : 0;

    const deep3 = report.phase3_deep || {};
    let deep = Number(deep3.count || 0);
    if (!deep && Array.isArray(deep3.promoted)) deep = deep3.promoted.length;

    return { light, rem, deep, skipped: !!report.skipped, ran: true };
  }

  const api = { dreamCardValues };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.dreamCardValues = dreamCardValues;
})(typeof window !== "undefined" ? window : this);
