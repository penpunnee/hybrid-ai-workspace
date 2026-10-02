"""embed ผ่าน Ollama ต้องส่ง `keep_alive` — ไม่งั้นโมเดลหลุดจาก VRAM ทุก 5 นาที (2026-10-02)

วัดบน prod: ค้นเว็บครั้งแรกของทุกสายเสียงช้า 6.5–12.6 วิ · Brave ~1 วิ ที่เหลือคือ embed
ตอน rerank (Ollama โหลด `paraphrase-multilingual` ใหม่) · ครั้งถัดไปในสายเดียวกัน 2–3 วิ
ยิงตรง: ครั้งแรก 4.25 วิ → 0.019 วิ · `/api/ps` ว่างเปล่าหลังไม่มีใครใช้ 5 นาที

🔴 `/v1/embeddings` (OpenAI-compat ที่เดิมใช้) **เมิน `keep_alive`** — ส่ง "2h" ไปแล้ว
`expires_at` ยัง +5 นาที · `/api/embed` (native) ใช้ได้ → ต้องย้ายเส้น Ollama ไป native
ค่าที่ตั้งแล้วติดตัวโมเดล: คำขอที่ไม่ส่ง keep_alive (เช่น EF ของ chromadb) ไม่รีเซ็ตกลับ 5 นาที
"""
import json

import httpx
import pytest
from openai import APIConnectionError, APIStatusError

from utils import embed


def _client(handler, base_url="http://pc:11434/v1"):
    return embed._OllamaNativeClient(
        base_url=base_url, api_key="ollama", max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def _ok(seen):
    def handler(req: httpx.Request):
        seen.append(req)
        body = json.loads(req.content)
        return httpx.Response(200, json={
            "model": body["model"], "embeddings": [[0.1, 0.2] for _ in body["input"]]})
    return handler


def test_ยิง_native_api_embed_พร้อม_keep_alive(monkeypatch):
    monkeypatch.setattr(embed, "_OLLAMA_EMBED_KEEP_ALIVE", "24h")
    seen = []
    resp = _client(_ok(seen)).embeddings.create(model="paraphrase-multilingual", input=["ก", "ข"])

    assert len(seen) == 1
    req = seen[0]
    assert req.method == "POST"
    assert str(req.url) == "http://pc:11434/api/embed", "ต้องไม่ใช่ /v1/embeddings (เมิน keep_alive)"
    body = json.loads(req.content)
    assert body == {"model": "paraphrase-multilingual", "input": ["ก", "ข"], "keep_alive": "24h"}
    # รูปเดียวกับคำตอบของ openai — `_verify_model` + `d.embedding` ใช้ต่อได้ไม่ต้องแก้
    assert resp.model == "paraphrase-multilingual"
    assert [list(d.embedding) for d in resp.data] == [[0.1, 0.2], [0.1, 0.2]]


def test_base_url_ไม่มี_v1_ก็ชี้_api_embed(monkeypatch):
    seen = []
    _client(_ok(seen), base_url="http://pc:11434").embeddings.create(model="m", input=["ก"])
    assert str(seen[0].url) == "http://pc:11434/api/embed"


def test_keep_alive_ว่าง_ไม่ส่งฟิลด์(monkeypatch):
    """ว่าง = ปล่อยให้ Ollama ใช้ค่าของมันเอง (OLLAMA_KEEP_ALIVE ฝั่งเครื่อง)"""
    monkeypatch.setattr(embed, "_OLLAMA_EMBED_KEEP_ALIVE", "")
    seen = []
    _client(_ok(seen)).embeddings.create(model="m", input=["ก"])
    assert "keep_alive" not in json.loads(seen[0].content)


def test_ต่อไม่ติด_ยังเป็น_APIConnectionError():
    """`_embed_via` ใช้ชนิดนี้ตัดสินว่าเครื่องดับ → ข้าม 60 วิ (ต่อ 58) · ห้ามกลายเป็นอย่างอื่น"""
    def handler(req):
        raise httpx.ConnectError("ดับ", request=req)
    with pytest.raises(APIConnectionError):
        _client(handler).embeddings.create(model="m", input=["ก"])


def test_ไม่มีโมเดล_404_เป็น_error_ที่ไม่ใช่การเชื่อมต่อ():
    """404 = เครื่องยังอยู่ → ห้ามเข้าช่วงข้าม · ต้อง fallback LM Studio ตามเดิม"""
    def handler(req):
        return httpx.Response(404, json={"error": 'model "m" not found, try pulling it first'})
    with pytest.raises(APIStatusError) as ei:
        _client(handler).embeddings.create(model="m", input=["ก"])
    assert not isinstance(ei.value, APIConnectionError)


def test_client_ตัวจริงเป็น_native_และคงค่ากันเครื่องดับ():
    c = embed._ollama_client
    assert isinstance(c, embed._OllamaNativeClient)
    assert c.max_retries == 0
    assert c.timeout.connect == embed._EMBED_CONNECT_TIMEOUT


def test_ลงทะเบียน_env_default_24h():
    from core.env_registry import REGISTRY
    spec = REGISTRY["OLLAMA_EMBED_KEEP_ALIVE"]
    assert spec.default == "24h"
