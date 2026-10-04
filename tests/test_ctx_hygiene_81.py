"""ต่อ 81 (2026-10-04) — 3 ช่องที่ทำให้ context/ความจำปนเปื้อน (วัดจาก prod ทุกข้อ)

ก. คำพิมพ์ผิด: "เช็คเครื่อข่าย" ไม่ติด keyword "เครือข่าย" → ไม่ดึง ping จริง + หลุด gate ความจำ
   ⇒ เทียบแบบไม่สนวรรณยุกต์ แต่เฉพาะคำยาว ≥6 ตัว — คำสั้นชนกัน ("ว่าง"→"วาง" = "วางแผน" ไปเรียก tool ดิสก์)
ข. RAG เอกสาร: คลังมีไฟล์เดียว (สเปรดชีตครัวเรือนเปราะบาง 1,740 chunk) · คำถามจริง 106 ข้อ top-1 เป็นไฟล์นี้ทุกข้อ ·
   ผ่านเกณฑ์ 0.5 ถึง 17 ข้อ (นิยาย/"2+2"/"ping NAS" ได้ 0.50–0.675) ซ้อนกับคำถามที่เกี่ยวจริง (0.56–0.73 · 08-02)
   ⇒ แยกด้วยคะแนนไม่ได้ · แถวตาราง (ชื่อ+เลข) เป็น hub · ไม่ดึงเอกสารตารางเข้าแชทอัตโนมัติ
   (self-cosine ของ chunk = 1.0 → ไม่ใช่โมเดล embed ไม่ตรง · วัดแล้ว)
ค. ไฟล์แนบเข้าความจำ: mem_20260724080137_540018 "Q: ตรวจสอบ… --- [Excel: รายชื่อครัวเรือนเปราะบาง…]" (มีเลขบัตร)
"""
import pytest

import utils.documents as docs
from reasoning.learn_gate import should_auto_learn, should_remember
from utils.home_tools import detect_home_tools
from utils.response_cache import is_realtime_query


# ── ก. คำพิมพ์ผิดวรรณยุกต์ ────────────────────────────────────────────────────
@pytest.mark.parametrize("prompt", ["เช็คเครื่อข่าย", "เช็คเครือข่าย", "เครือข้าย ปกติไหม"])
def test_network_typo_detected(prompt):
    assert "ping_network" in detect_home_tools(prompt)
    assert should_auto_learn(prompt) == (False, "realtime_home_tool")
    assert is_realtime_query(prompt)


@pytest.mark.parametrize("prompt", ["วางแผนเที่ยวให้หน่อย", "ช่วยวางโครงเรื่อง", "ข้าวเหนียวมะม่วง"])
def test_short_keywords_stay_exact(prompt):
    """คำสั้น ("ว่าง" "เต็ม" "ข่าว") ห้ามเทียบแบบตัดวรรณยุกต์ — ชนคำทั่วไป"""
    assert detect_home_tools(prompt) == []


# ── ข. เอกสารตารางไม่เข้าแชทอัตโนมัติ ─────────────────────────────────────────
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _fake_query(captured, metas):
    def q(n_results, query_texts=None, query_embeddings=None, where=None):
        captured["n"] = n_results
        return {"documents": [[f"t{i}" for i in range(len(metas))]], "metadatas": [metas],
                "distances": [[0.3] * len(metas)]}
    return q


def test_exclude_tabular_drops_spreadsheet_keeps_text(monkeypatch):
    col = type("C", (), {})()
    captured = {}
    col.query = _fake_query(captured, [
        {"source": "บ้าน.xlsx", "content_type": _XLSX, "chunk_index": 0},
        {"source": "rows.csv", "chunk_index": 1},                       # ไม่มี content_type → ดูนามสกุล
        {"source": "คู่มือ.pdf", "content_type": "application/pdf", "chunk_index": 2},
        {"source": "notes.txt", "chunk_index": 3},                      # ไม่มี content_type แต่ไม่ใช่ตาราง → เก็บ
    ])
    monkeypatch.setattr(docs, "_get_collection", lambda: col)
    monkeypatch.setattr("utils.embed.embed_texts", lambda t: [[0.1, 0.2]])
    out = docs.retrieve_chunks("q", top_k=3, exclude_tabular=True)
    assert sorted(i["source"] for i in out) == ["notes.txt", "คู่มือ.pdf"]
    assert captured["n"] == 20, "กรองหลัง query ⇒ ต้องขอมากพอให้เอกสารอื่นโผล่พ้นแถวตาราง"


def test_default_keeps_tabular(monkeypatch):
    """ค้นเอกสารตรงๆ (/api/documents/search) ยังเห็นตารางเหมือนเดิม"""
    col = type("C", (), {})()
    col.query = _fake_query({}, [{"source": "บ้าน.xlsx", "content_type": _XLSX, "chunk_index": 0}])
    monkeypatch.setattr(docs, "_get_collection", lambda: col)
    monkeypatch.setattr("utils.embed.embed_texts", lambda t: [[0.1, 0.2]])
    assert [i["source"] for i in docs.retrieve_chunks("q", top_k=3)] == ["บ้าน.xlsx"]


def test_chat_requests_exclude_tabular():
    import ast
    import inspect

    import routers.chat as chatmod
    calls = [n for n in ast.walk(ast.parse(inspect.getsource(chatmod)))
             if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "retrieve_chunks"]
    assert calls, "หา retrieve_chunks ใน routers/chat.py ไม่เจอ"
    for c in calls:
        kw = {k.arg: k.value for k in c.keywords}
        assert isinstance(kw.get("exclude_tabular"), ast.Constant) and kw["exclude_tabular"].value is True


# ── ค. prompt ที่มีเนื้อหาไฟล์แนบ ไม่จดความจำ ────────────────────────────────
@pytest.mark.parametrize("marker", [
    "[Excel: รายชื่อ.xlsx]\n[Sheet: s1]\nชื่อ\tเลขบัตร",
    "[PDF: a.pdf — 3 หน้า]\nเนื้อหา",
    "[PDF scan: b.pdf — 2 หน้า (OCR via gemini)]\nข้อความ",
    "[DOCX: c.docx]\nข้อความ",
])
def test_attachment_prompt_not_remembered(marker):
    ok, reason = should_remember(f"ตรวจสอบ ดูว่ามีข้อมูลซ้ำกันไหม\n---\n{marker}", "พบข้อมูลซ้ำ 3 แถว")
    assert (ok, reason) == (False, "attachment")


def test_plain_prompt_mentioning_excel_still_remembered():
    """พูดถึงคำว่า Excel เฉยๆ ไม่ใช่ไฟล์แนบ"""
    assert should_remember("สูตร Excel หาค่าซ้ำใช้อะไร", "ใช้ COUNTIF") == (True, "ok")
