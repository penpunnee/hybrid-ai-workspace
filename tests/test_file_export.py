"""export_file — ขวัญเขียนข้อมูลเป็นไฟล์แล้วส่งลิงก์ดาวน์โหลดให้ user ในแชท

ครอบ 3 ชั้น: utils/file_export.py (เขียน+sanitize) · GET /api/files/{token}/{filename}
(เสิร์ฟ) · tool `export_file` ใน agents/tools.py (ผูกเข้า registry)
"""
import re

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def export_dir(tmp_path, monkeypatch):
    """ชี้ EXPORT_DIR ไป tmp — กันเทสเขียนปน data จริง"""
    from utils import file_export
    monkeypatch.setattr(file_export, "EXPORT_DIR", str(tmp_path))
    return tmp_path


# ── save_export ──────────────────────────────────────────────────────────────

def test_save_export_writes_file_and_returns_link(export_dir):
    from utils.file_export import save_export
    r = save_export("รายงาน.md", "# สวัสดี\nเนื้อหา")
    assert r["ok"] is True
    m = re.fullmatch(r"/api/files/([0-9a-f]{32})/(.+)", r["url"])
    assert m, f"url ผิดรูป: {r['url']}"
    token, fname = m.group(1), m.group(2)
    assert fname == "รายงาน.md"
    saved = export_dir / token / "รายงาน.md"
    assert saved.read_text(encoding="utf-8") == "# สวัสดี\nเนื้อหา"


def test_save_export_two_calls_get_distinct_tokens(export_dir):
    from utils.file_export import save_export
    u1 = save_export("a.txt", "1")["url"]
    u2 = save_export("a.txt", "2")["url"]
    assert u1 != u2


def test_save_export_sanitizes_traversal_and_specials(export_dir):
    from utils.file_export import save_export
    r = save_export("../../etc/passwd", "x")
    assert r["ok"] is True
    # เหลือแค่ basename ที่ปลอดภัย — ห้ามมี / หรือ ..
    fname = r["url"].rsplit("/", 1)[1]
    assert "/" not in fname and ".." not in fname
    # ช่องว่าง + วงเล็บพัง markdown link — ต้องถูกแทนที่
    r2 = save_export("my file (1).txt", "x")
    fname2 = r2["url"].rsplit("/", 1)[1]
    assert " " not in fname2 and "(" not in fname2 and ")" not in fname2


def test_save_export_rejects_empty_or_dotfile_name(export_dir):
    from utils.file_export import save_export
    assert save_export("", "x")["ok"] is False
    assert save_export("...", "x")["ok"] is False


def test_save_export_rejects_oversize(export_dir):
    from utils import file_export
    big = "ก" * (file_export.MAX_EXPORT_BYTES + 1)
    r = file_export.save_export("big.txt", big)
    assert r["ok"] is False
    assert "ใหญ่" in r["error"]


# ── GET /api/files/{token}/{filename} ────────────────────────────────────────

@pytest.fixture()
def client(export_dir):
    from server import app
    return TestClient(app)


def test_download_roundtrip(client, export_dir):
    from utils.file_export import save_export
    r = save_export("data.csv", "a,b\n1,2")
    resp = client.get(r["url"])
    assert resp.status_code == 200
    assert resp.text == "a,b\n1,2"
    # ให้เบราว์เซอร์ดาวน์โหลดเป็นไฟล์ ไม่ใช่เปิดทับหน้า
    assert "attachment" in resp.headers.get("content-disposition", "")


def test_download_unknown_token_404(client, export_dir):
    assert client.get("/api/files/" + "0" * 32 + "/x.txt").status_code == 404


def test_download_bad_token_format_404(client, export_dir):
    # token ไม่ใช่ hex 32 ตัว = ปฏิเสธก่อนแตะ filesystem
    assert client.get("/api/files/notahex/x.txt").status_code == 404


def test_download_traversal_in_filename_404(client, export_dir):
    from utils.file_export import save_export
    r = save_export("safe.txt", "x")
    token = r["url"].split("/")[3]
    # แอบเดินออกนอกโฟลเดอร์ token — ต้องไม่ได้อะไรกลับไป
    resp = client.get(f"/api/files/{token}/..%2F..%2Fsecret.txt")
    assert resp.status_code == 404


# ── tool registry ────────────────────────────────────────────────────────────

def test_export_file_tool_registered():
    from agents.tools import _ALL_TOOLS
    spec = _ALL_TOOLS["export_file"]
    assert set(spec["parameters"]["required"]) == {"filename", "content"}


def test_export_file_tool_returns_markdown_link(export_dir):
    from agents.tools import execute_tool
    out = execute_tool("export_file", {"filename": "note.txt", "content": "hi"})
    assert re.search(r"\[[^\]]+\]\(/api/files/[0-9a-f]{32}/note\.txt\)", out), out


def test_export_file_tool_reports_error_not_crash(export_dir):
    from agents.tools import execute_tool
    out = execute_tool("export_file", {"filename": "", "content": "hi"})
    assert "❌" in out or "ไม่สำเร็จ" in out


def test_download_alias_name_404_canonical_only(client, export_dir):
    # "note.txt." sanitize แล้วเท่ากับ "note.txt" — ต้องเสิร์ฟเฉพาะชื่อ canonical เป๊ะ
    from utils.file_export import save_export
    r = save_export("note.txt", "x")
    url_alias = r["url"] + "."
    assert client.get(url_alias).status_code == 404
    assert client.get(r["url"]).status_code == 200


def test_download_non_token_dir_unreachable(client, export_dir):
    # กันอนาคต: โฟลเดอร์ใน exports ที่ชื่อไม่ใช่ 32-hex (temp/ของที่คนอื่นวาง)
    # ต้องเสิร์ฟไม่ได้ แม้ไฟล์จะมีอยู่จริง — invariant: เสิร์ฟเฉพาะ token ที่เราสร้าง
    # (ห้ามใช้ path แบบ /./ ทดสอบ — TestClient normalize ทิ้งก่อนถึง route = เทสผ่านฟรี)
    stray = export_dir / "notahexdir"
    stray.mkdir()
    (stray / "f.txt").write_text("secret")
    assert client.get("/api/files/notahexdir/f.txt").status_code == 404


def test_save_export_strips_hash_and_percent(export_dir):
    # '#' → เบราว์เซอร์ตัดเป็น fragment · '%' → percent-decode ฝั่ง server ทำชื่อไม่ตรง
    # ทั้งคู่ทำลิงก์ที่สร้างไป 404 — ต้องถูกแทนที่ตั้งแต่ตอนเซฟ (พบจาก /scrutinize 08-28)
    from utils.file_export import save_export
    for bad in ["รายงาน#1.md", "a%20b.md"]:
        fname = save_export(bad, "x")["url"].rsplit("/", 1)[1]
        assert "#" not in fname and "%" not in fname, fname


# ── auth: ลิงก์ดาวน์โหลดต้องกดได้จากนอกบ้าน ───────────────────────────────────
# บั๊กจริง 08-28: <a download> เป็น browser navigation แนบ header x-auth-token
# ไม่ได้ → ผ่าน Cloudflare โดน 401 → Safari เซฟ body ของ error เป็น "ไฟล์เปล่า"
# ความปลอดภัยของ /api/files อยู่ที่ token 128-bit เดาไม่ได้ (ระดับเดียวกับ /gen
# ที่เปิด public อยู่แล้ว) — จึงต้องอยู่ใน open allowlist

def test_download_works_without_auth_header_via_cloudflare(client, export_dir, monkeypatch):
    from core import auth
    from utils.file_export import save_export
    monkeypatch.setattr(auth, "UI_PASSWORD", "secret")
    r = save_export("จากนอกบ้าน.md", "เนื้อหา")
    resp = client.get(r["url"], headers={"cf-connecting-ip": "1.2.3.4"})
    assert resp.status_code == 200
    assert resp.text == "เนื้อหา"


def test_other_api_paths_still_locked_via_cloudflare(client, export_dir, monkeypatch):
    # กลุ่มควบคุม: เปิดเฉพาะ /api/files — path อื่นต้องยัง 401 เหมือนเดิม
    from core import auth
    monkeypatch.setattr(auth, "UI_PASSWORD", "secret")
    resp = client.get("/api/memory/stats", headers={"cf-connecting-ip": "1.2.3.4"})
    assert resp.status_code == 401


def test_api_files_prefix_no_segment_leak(client, export_dir, monkeypatch):
    # /api/filesecrets ต้องไม่หลุดตาม prefix (กติกา _under_open_prefix ตรงทั้ง segment)
    from core import auth
    monkeypatch.setattr(auth, "UI_PASSWORD", "secret")
    resp = client.get("/api/filesecrets", headers={"cf-connecting-ip": "1.2.3.4"})
    assert resp.status_code == 401
