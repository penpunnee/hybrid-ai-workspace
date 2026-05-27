"""Tests สำหรับ utils/fs_tools.py — whitelist-restricted file ops

ทำไมสำคัญ (security): `_resolve_safe()` คือด่านกัน path traversal —
ถ้ารั่ว agent/tool จะอ่าน/เขียน/ลบไฟล์นอก sandbox ได้ (เช่น ~/.ssh, .env).
เทสต์เน้น escape vectors: '..', absolute path, symlink ที่ชี้ออกนอก root
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import utils.fs_tools as fs
from utils.fs_tools import FSError


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """ชี้ allowed root ไปที่ temp dir แยก → ไม่แตะ sandbox จริง"""
    root = (tmp_path / "sandbox").resolve()
    root.mkdir()
    monkeypatch.setattr(fs, "_ROOTS", [root])
    return root


# ─────────────────────────────────────────────────────────────
# _resolve_safe — ด่านความปลอดภัยหลัก
# ─────────────────────────────────────────────────────────────
def test_resolve_safe_allows_path_inside_root(sandbox):
    resolved = fs._resolve_safe("notes.txt")
    assert resolved == sandbox / "notes.txt"


def test_resolve_safe_blocks_dotdot_escape(sandbox):
    with pytest.raises(FSError, match="outside allowed roots"):
        fs._resolve_safe("../../etc/passwd")


def test_resolve_safe_blocks_absolute_outside(sandbox):
    with pytest.raises(FSError, match="outside allowed roots"):
        fs._resolve_safe("/etc/passwd")


def test_resolve_safe_empty_path_raises(sandbox):
    with pytest.raises(FSError, match="empty path"):
        fs._resolve_safe("")


def test_resolve_safe_blocks_symlink_escape(sandbox, tmp_path):
    """symlink ที่ชี้ออกนอก root ต้องถูกบล็อก (resolve symlink ก่อนเทียบ)"""
    outside = (tmp_path / "outside").resolve()
    outside.mkdir()
    (outside / "secret.txt").write_text("TOPSECRET")
    os.symlink(outside, sandbox / "link")
    with pytest.raises(FSError, match="outside allowed roots"):
        fs._resolve_safe("link/secret.txt")


# ─────────────────────────────────────────────────────────────
# write / read / delete — happy path + guard
# ─────────────────────────────────────────────────────────────
def test_write_then_read_roundtrip(sandbox):
    w = fs.write_file("a.txt", "hello world")
    assert w["ok"] is True
    assert w["bytes_written"] == len("hello world".encode())

    r = fs.read_file("a.txt")
    assert r["ok"] is True
    assert r["content"] == "hello world"
    assert r["truncated"] is False


def test_write_outside_root_rejected(sandbox):
    res = fs.write_file("../escape.txt", "x")
    assert res["ok"] is False
    assert "outside allowed roots" in res["error"]


def test_write_no_overwrite_then_overwrite(sandbox):
    assert fs.write_file("dup.txt", "v1")["ok"] is True
    blocked = fs.write_file("dup.txt", "v2")
    assert blocked["ok"] is False and "exists" in blocked["error"]
    assert fs.write_file("dup.txt", "v2", overwrite=True)["ok"] is True
    assert fs.read_file("dup.txt")["content"] == "v2"


def test_write_too_large_rejected(sandbox, monkeypatch):
    monkeypatch.setattr(fs, "_MAX_WRITE", 5)
    res = fs.write_file("big.txt", "123456789")  # 9 bytes > 5
    assert res["ok"] is False and "too large" in res["error"]


def test_read_nonexistent_returns_error(sandbox):
    res = fs.read_file("ghost.txt")
    assert res["ok"] is False and "not a file" in res["error"]


def test_read_symlink_escape_blocked(sandbox, tmp_path):
    outside = (tmp_path / "outside2").resolve()
    outside.mkdir()
    (outside / "secret.txt").write_text("LEAK")
    os.symlink(outside / "secret.txt", sandbox / "leak.txt")
    res = fs.read_file("leak.txt")
    assert res["ok"] is False and "outside allowed roots" in res["error"]


def test_delete_file_and_missing(sandbox):
    fs.write_file("tmp.txt", "bye")
    assert fs.delete_file("tmp.txt")["ok"] is True
    assert not (sandbox / "tmp.txt").exists()
    missing = fs.delete_file("tmp.txt")
    assert missing["ok"] is False and "not found" in missing["error"]


def test_delete_outside_root_rejected(sandbox):
    res = fs.delete_file("../../etc/hosts")
    assert res["ok"] is False and "outside allowed roots" in res["error"]


# ─────────────────────────────────────────────────────────────
# list_dir / search_files
# ─────────────────────────────────────────────────────────────
def test_list_dir_returns_entries(sandbox):
    fs.write_file("f1.txt", "a")
    fs.write_file("f2.txt", "bb")
    res = fs.list_dir("")
    assert res["ok"] is True
    names = {e["name"] for e in res["entries"]}
    assert {"f1.txt", "f2.txt"} <= names
    # file entry มี size
    f1 = next(e for e in res["entries"] if e["name"] == "f1.txt")
    assert f1["type"] == "file" and f1["size"] == 1


def test_search_files_finds_pattern(sandbox):
    fs.write_file("doc.txt", "line one\nfind the needle here\nline three")
    res = fs.search_files("needle")
    assert res["ok"] is True
    assert res["count"] >= 1
    assert any("needle" in m["text"] for m in res["matches"])


def test_search_empty_pattern_rejected(sandbox):
    assert fs.search_files("")["ok"] is False
