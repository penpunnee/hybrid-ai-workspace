"""Test: sync_vault() ต้องนับ upsert ที่ล้มเป็น error แยกจาก skip และคืน ok:false

บั๊กจริง (เจอ 2026-08-12 ตอน Ollama บน PC .235 ตาย): ทุก upsert timeout
แต่ sync_vault รายงาน `{ok:true, synced:0, skipped:63}` — ตัวเลข skip โกหก
เพราะ except กลืน exception แล้วนับรวมกับ skip ที่เกิดจาก mtime ตรง (ไฟล์ไม่เปลี่ยน)
→ ผู้เรียกแยกไม่ออกเลยว่า "ไม่มีอะไรต้อง sync" กับ "sync ล้มทั้งหมด"
(ตระกูล measuring-instruments-lie — เครื่องมือวัดรายงานเขียวทั้งที่ระบบล่ม)

พฤติกรรมที่ถูก:
  - exception ระหว่างประมวลผลไฟล์ → นับ `errors` ไม่ใช่ `skipped`
  - มี error อย่างน้อย 1 → `ok: false`
  - skip เพราะ mtime ตรง (ของจริง) → ยังเป็น `skipped` และ `ok: true`
"""
import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils.obsidian_sync as ov


def _make_vault(tmp_path, n=3):
    for i in range(n):
        (tmp_path / f"note{i}.md").write_text(f"# โน้ต {i}\nเนื้อหา", encoding="utf-8")
    return str(tmp_path)


def _col_upsert_dies():
    """collection ที่ upsert timeout ทุกครั้ง (จำลอง Ollama embedding ตาย)"""
    col = MagicMock()
    col.get.return_value = {"metadatas": []}  # ยังไม่เคย index
    col.upsert.side_effect = Exception("timed out in _forward_request")
    return col


def test_all_upserts_fail_reports_errors_not_skipped(monkeypatch, tmp_path):
    """Ollama ตายทั้งเส้น → ต้อง ok:false + errors=จำนวนไฟล์ ไม่ใช่ skipped โกหก"""
    vault = _make_vault(tmp_path, n=3)
    monkeypatch.setattr(ov, "_get_collection", _col_upsert_dies)
    res = ov.sync_vault(vault)
    assert res["errors"] == 3, f"upsert ล้ม 3 ไฟล์ต้องนับ errors=3 ได้ {res}"
    assert res["skipped"] == 0, f"ไม่มีไฟล์ไหน skip จริง (mtime ตรง) ได้ {res}"
    assert res["ok"] is False, f"มี error ต้อง ok:false ได้ {res}"
    assert "error" in res, "ต้องมีข้อความ error ให้ UI โชว์ (app.tsx อ่าน res.error)"


def test_partial_failure_still_ok_false(monkeypatch, tmp_path):
    """ล้มแค่บางไฟล์ก็ต้อง ok:false — ไม่งั้นไฟล์ที่หายเงียบไม่มีใครรู้"""
    vault = _make_vault(tmp_path, n=3)
    col = MagicMock()
    col.get.return_value = {"metadatas": []}
    calls = {"n": 0}

    def _upsert(*a, **k):
        calls["n"] += 1
        if calls["n"] == 2:  # ไฟล์ที่ 2 ล้ม
            raise Exception("timed out")

    col.upsert.side_effect = _upsert
    monkeypatch.setattr(ov, "_get_collection", lambda: col)
    res = ov.sync_vault(vault)
    assert res["synced"] == 2 and res["errors"] == 1, f"ได้ {res}"
    assert res["ok"] is False, f"มี error 1 ไฟล์ก็ต้อง ok:false ได้ {res}"


def test_genuine_mtime_skip_stays_ok_true(monkeypatch, tmp_path):
    """skip ของจริง (ไฟล์ไม่เปลี่ยน) ต้องยังเป็น skipped + ok:true เหมือนเดิม"""
    vault = _make_vault(tmp_path, n=2)
    col = MagicMock()
    # mtime ตรงทุกไฟล์ = ไม่มีอะไรต้อง sync — จับคู่จาก doc_id
    id_to_mtime = {
        ov._doc_id(f): str(f.stat().st_mtime) for f in tmp_path.rglob("*.md")
    }
    col.get.side_effect = lambda ids: {"metadatas": [{"mtime": id_to_mtime[ids[0]]}]}
    monkeypatch.setattr(ov, "_get_collection", lambda: col)
    res = ov.sync_vault(vault)
    assert res["skipped"] == 2 and res["errors"] == 0, f"ได้ {res}"
    assert res["ok"] is True, f"skip ของจริงไม่ใช่ความผิด ต้อง ok:true ได้ {res}"
    col.upsert.assert_not_called()
