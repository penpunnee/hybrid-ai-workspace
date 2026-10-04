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


# ── ง. เลข 13 หลัก (รูปแบบเลขบัตรประชาชน) ไม่จดความจำ — ทั้งในคำถามและคำตอบ ──────────
# prod: mem_20260724080318_d44af4 คำถามต่อเนื่อง (ไม่มีไฟล์แนบ) แต่คำตอบมีชื่อ+เลขบัตร 3 คน — ตัวกัน ค. ไม่ครอบ
@pytest.mark.parametrize("q,a", [
    ("ที่เป็น 2026-02-11 แบบนี้ มีกี่ราย", "1. นาง ก (เลขบัตร: 5540000000524)"),
    ("หาคนนี้ 3540400629704 ให้หน่อย", "พบ 1 ราย"),
    ("เลขนี้ 1-5401-00012-34-5 ของใคร", "ไม่ทราบค่ะ"),          # เขียนแบบมีขีด
])
def test_national_id_not_remembered(q, a):
    assert should_remember(q, a) == (False, "national_id")


@pytest.mark.parametrize("q,a", [
    ("เงินเดือนปีละ 1,250,000 บาท ตกเดือนละเท่าไร", "ประมาณ 104,167 บาท"),
    ("timestamp 17848800720 คือวันไหน", "ปี 2026"),            # 11 หลัก
    ("เลข 12345678901234 มีกี่หลัก", "14 หลัก"),                # 14 หลัก ไม่ใช่เลขบัตร
])
def test_other_numbers_still_remembered(q, a):
    assert should_remember(q, a) == (True, "ok")


# ── จ. ทางเขียนอื่นนอก episodic: บทเรียน (LLM สรุป) + บันทึกการแก้ไข (teach) ─────────────
def test_lesson_with_national_id_dropped():
    from reasoning.learn_gate import clean_lesson
    assert clean_lesson("บ้านเลขที่ของนาง ก (3540400629704) ถูก Excel แปลงเป็นวันที่ ต้องจัดรูปแบบเป็นข้อความ") is None
    assert clean_lesson("Excel แปลงบ้านเลขที่เป็นวันที่ ต้องตั้งคอลัมน์เป็นข้อความก่อนวางข้อมูล") is not None


def test_correction_record_with_national_id_not_saved(monkeypatch):
    import memory.teach as t
    saved = []
    monkeypatch.setattr(t, "update_confidence", lambda *a, **k: True)
    monkeypatch.setattr(t, "save_entry", lambda e, collection_name=None: saved.append(e.content) or True)
    monkeypatch.setattr(t, "build_correction_record",
                        lambda u, p, extractor=None: "เลขบัตรที่ถูกของนาง ก คือ 3540400629704")
    t.process_teaching("kwan", "ไม่ใช่ เลขบัตรผิดแล้ว แก้ใหม่", ai_response="รับทราบ", prev_answer="นาง ก 3540400629705")
    assert saved == []


def test_user_explicit_remember_not_blocked(monkeypatch):
    """"จำไว้ว่า" = ผู้ใช้สั่งเอง (ตั้งใจไม่กัน · ต่อ 83)"""
    import memory.teach as t
    saved = []
    monkeypatch.setattr(t, "save_entry", lambda e, collection_name=None: saved.append(e.content) or True)
    monkeypatch.setattr(t, "detect_teaching", lambda text: ("เลขผู้เสียภาษีบริษัทคือ 0105500000000", "fact"))
    t.process_teaching("kwan", "จำไว้ว่า เลขผู้เสียภาษีบริษัทคือ 0105500000000")
    assert saved == ["เลขผู้เสียภาษีบริษัทคือ 0105500000000"]
