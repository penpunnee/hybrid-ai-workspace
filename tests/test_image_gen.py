"""Image generation ผ่าน Gemini (gemini-2.5-flash-image)

ครอบคลุม: intent detection, generate+save ไฟล์, กรณีไม่มี API key
"""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import image_gen


# ── detect_image_request ─────────────────────────────────────────────────────
@pytest.mark.parametrize("prompt", [
    "วาดรูปแมวอวกาศให้หน่อย",
    "ช่วยสร้างรูปบ้านริมทะเล",
    "สร้างภาพโลโก้ร้านกาแฟ",
    "วาดภาพการ์ตูนหมาคอร์กี้",
    "generate image of a sunset",
    "ทำรูปโปสเตอร์งานวัด",
])
def test_detect_image_request_true(prompt):
    assert image_gen.detect_image_request(prompt) is True


@pytest.mark.parametrize("prompt", [
    "วันนี้อากาศเป็นยังไง",
    "รูปที่ส่งให้เมื่อกี้คืออะไร",       # ถามถึงรูป ไม่ใช่สั่งวาด
    "ช่วยอธิบายภาพรวมของโปรเจกต์",     # 'ภาพรวม' ห้าม false positive
    "สร้างระบบ login ให้หน่อย",
    "ขอสูตรทำรูปแบบรายงาน excel",
])
def test_detect_image_request_false(prompt):
    assert image_gen.detect_image_request(prompt) is False


# ── generate_image ───────────────────────────────────────────────────────────
def _fake_client_with_image(png_bytes: bytes, text: str = "นี่คือรูปค่ะ"):
    part_img = SimpleNamespace(inline_data=SimpleNamespace(data=png_bytes, mime_type="image/png"), text=None)
    part_txt = SimpleNamespace(inline_data=None, text=text)
    cand = SimpleNamespace(content=SimpleNamespace(parts=[part_txt, part_img]))
    resp = SimpleNamespace(candidates=[cand])

    class FakeModels:
        def generate_content(self, **kw):
            return resp

    return SimpleNamespace(models=FakeModels())


def test_generate_image_saves_file_and_returns_url(tmp_path, monkeypatch):
    monkeypatch.setattr(image_gen, "GEN_IMAGE_DIR", str(tmp_path))
    fake = _fake_client_with_image(b"\x89PNG fakebytes")
    with patch.object(image_gen, "_get_client", return_value=fake):
        out = image_gen.generate_image("วาดรูปแมว")
    assert out["ok"] is True
    assert out["url"].startswith("/gen/") and out["url"].endswith(".png")
    saved = tmp_path / out["url"].split("/")[-1]
    assert saved.exists() and saved.read_bytes() == b"\x89PNG fakebytes"
    assert "นี่คือรูป" in out.get("text", "")


def test_generate_image_no_client_returns_error(monkeypatch):
    with patch.object(image_gen, "_get_client", return_value=None):
        out = image_gen.generate_image("วาดรูปแมว")
    assert out["ok"] is False
    assert "GEMINI_API_KEY" in out["error"]


def _fake_client_raising(msg: str):
    class FakeModels:
        def generate_content(self, **kw):
            raise RuntimeError(msg)

    return SimpleNamespace(models=FakeModels())


def test_generate_image_quota_limit_zero_says_not_available(monkeypatch):
    # free tier limit=0 = โมเดลนี้ใช้ free tier ไม่ได้เลย — ห้ามบอก "ลองใหม่ภายหลัง"
    fake = _fake_client_raising(
        "429 RESOURCE_EXHAUSTED. Quota exceeded for metric: "
        "generate_content_free_tier_requests, limit: 0, model: gemini-2.5-flash-preview-image"
    )
    with patch.object(image_gen, "_get_client", return_value=fake):
        out = image_gen.generate_image("วาดรูปแมว")
    assert out["ok"] is False
    assert "free tier" in out["error"]
    assert "ลองใหม่" not in out["error"]


def test_generate_image_quota_temporary_says_retry(monkeypatch):
    fake = _fake_client_raising("429 RESOURCE_EXHAUSTED. Quota exceeded, limit: 250")
    with patch.object(image_gen, "_get_client", return_value=fake):
        out = image_gen.generate_image("วาดรูปแมว")
    assert out["ok"] is False
    assert "ลองใหม่" in out["error"]


def test_generate_image_no_image_in_response(tmp_path, monkeypatch):
    monkeypatch.setattr(image_gen, "GEN_IMAGE_DIR", str(tmp_path))
    part_txt = SimpleNamespace(inline_data=None, text="ขอโทษค่ะ ทำไม่ได้")
    cand = SimpleNamespace(content=SimpleNamespace(parts=[part_txt]))
    resp = SimpleNamespace(candidates=[cand])

    class FakeModels:
        def generate_content(self, **kw):
            return resp

    fake = SimpleNamespace(models=FakeModels())
    with patch.object(image_gen, "_get_client", return_value=fake):
        out = image_gen.generate_image("วาดรูปแมว")
    assert out["ok"] is False
