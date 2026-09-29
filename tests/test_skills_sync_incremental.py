"""sync skills ตอนบูต embed เฉพาะตัวที่เปลี่ยน + รวมเป็น upsert ชุดเดียว (2026-09-29)

วัดบน prod: ทุกบูต `sync_from_db` upsert ทีละตัว 22 ครั้ง = ยิง Ollama `/api/embed` 22 ครั้ง (EF ของ chromadb ไม่ผ่าน
cache ของ utils/embed.py) · ใช้ 34–55 วิทั้ง 10 รอบ restart · แย่งคิว embed กับ recall → agent step แรกช้า 19/14 วิ
(request นอกช่วง sync = 2–5 วิ)

แก้: `collection.get()` คืน documents+metadatas อยู่แล้ว (chromadb 1.5.9 `Collection.py:136`) → ข้ามตัวที่ไม่เปลี่ยน ·
ตัวที่เปลี่ยน upsert ครั้งเดียว (OllamaEmbeddingFunction ส่งทั้ง list ใน `embed(input=…)` — `ollama_embedding_function.py:66`
· https://docs.ollama.com/api/embed "Text or array of texts") · metadata มี `embed_model` → เปลี่ยน EMBEDDING_MODEL = re-embed
"""
import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.config as cfg
import utils.skills as sk
import utils.skills_search as ss

MODEL = "paraphrase-multilingual"


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setattr(sk, "SKILLS_DB_PATH", str(tmp_path / "skills_db.json"))   # reload ใต้ lock อ่านไฟล์นี้
    monkeypatch.setattr(cfg, "EMBEDDING_MODEL", MODEL)


def _search(col):
    s = MagicMock()
    s.available, s.collection = True, col
    s._skill_id = ss.SkillsSearch._skill_id
    s.add_skill = lambda **kw: ss.SkillsSearch.add_skill(s, **kw)
    s.sync_from_db = lambda db: ss.SkillsSearch.sync_from_db(s, db)
    return s


def _stored(db, model=MODEL):
    """สิ่งที่ index มีอยู่แล้วสำหรับ db นี้ (ตามรูปที่โค้ดเขียนลง)"""
    ids, docs, metas = [], [], []
    for topic, d in db.items():
        ids.append(ss.SkillsSearch._skill_id(topic))
        docs.append(f"{topic}: {d['summary']}")
        m = {"topic": topic, "category": "learned", "source": d.get("source", "unknown")}
        if model is not None:
            m["embed_model"] = model
        metas.append(m)
    return {"ids": ids, "documents": docs, "metadatas": metas}


DB = {"a": {"summary": "x", "source": "a.md"}, "b": {"summary": "y", "source": "b.md"}}


def _upserted(col):
    return [i for c in col.upsert.call_args_list for i in c.kwargs["ids"]]


def test_ไม่มีอะไรเปลี่ยน_ไม่_embed_เลย():
    col = MagicMock()
    col.get.return_value = _stored(DB)
    _search(col).sync_from_db(DB)
    assert col.upsert.call_count == 0, f"บูตปกติต้อง embed 0 ครั้ง (เดิม 1 ครั้ง/skill) · {col.upsert.call_args_list}"


def test_เปลี่ยน_1_เพิ่ม_1_upsert_ครั้งเดียว_2_รายการ():
    col = MagicMock()
    col.get.return_value = _stored(DB)
    db = {**DB, "a": {"summary": "แก้แล้ว", "source": "a.md"}, "c": {"summary": "ใหม่", "source": "c.md"}}
    _search(col).sync_from_db(db)
    assert col.upsert.call_count == 1
    kw = col.upsert.call_args.kwargs
    assert sorted(kw["ids"]) == ["skill_a", "skill_c"]
    got = dict(zip(kw["ids"], kw["documents"]))
    assert got["skill_a"] == "a: แก้แล้ว" and got["skill_c"] == "c: ใหม่"
    assert all(m["embed_model"] == MODEL for m in kw["metadatas"])


def test_metadata_เปลี่ยนอย่างเดียว_ก็ต้อง_upsert():
    col = MagicMock()
    col.get.return_value = _stored(DB)
    _search(col).sync_from_db({**DB, "b": {"summary": "y", "source": "ย้ายไฟล์.md"}})
    assert _upserted(col) == ["skill_b"]


def test_ของเก่าที่ยังไม่มี_embed_model_ต้อง_re_embed():
    col = MagicMock()
    col.get.return_value = _stored(DB, model=None)          # prod ตอนนี้: metadata ไม่มีฟิลด์นี้
    _search(col).sync_from_db(DB)
    assert sorted(_upserted(col)) == ["skill_a", "skill_b"] and col.upsert.call_count == 1


def test_เปลี่ยน_EMBEDDING_MODEL_ต้อง_re_embed(monkeypatch):
    col = MagicMock()
    col.get.return_value = _stored(DB)
    monkeypatch.setattr(cfg, "EMBEDDING_MODEL", "bge-m3")
    _search(col).sync_from_db(DB)
    assert sorted(_upserted(col)) == ["skill_a", "skill_b"]
    assert all(m["embed_model"] == "bge-m3" for m in col.upsert.call_args.kwargs["metadatas"])


def test_EMBEDDING_MODEL_ว่าง_ใช้ป้าย_default(monkeypatch):
    """"" = ปิด EF ของเรา → chroma ใช้ default EF ของมันเอง (utils/memory.py) · ป้ายต้องคงที่ ไม่ใช่สตริงว่าง"""
    monkeypatch.setattr(cfg, "EMBEDDING_MODEL", "")
    col = MagicMock()
    col.get.return_value = {"ids": []}
    _search(col).sync_from_db({"a": DB["a"]})
    assert col.upsert.call_args.kwargs["metadatas"][0]["embed_model"] == "default"


def test_อ่าน_get_ไม่ได้_upsert_ทั้งหมดชุดเดียว():
    col = MagicMock()
    col.get.side_effect = RuntimeError("chroma ล่ม")
    _search(col).sync_from_db(DB)
    assert col.upsert.call_count == 1 and sorted(_upserted(col)) == ["skill_a", "skill_b"]


def test_batch_ล้ม_ถอยไปทีละตัว_ตัวเสียไม่ลากตัวอื่น():
    col = MagicMock()
    col.get.return_value = {"ids": []}
    ok = []

    def upsert(**kw):
        if len(kw["ids"]) > 1:
            raise RuntimeError("batch ล้ม")
        if kw["ids"] == ["skill_a"]:
            raise RuntimeError("ตัวนี้เสีย")
        ok.extend(kw["ids"])

    col.upsert.side_effect = upsert
    _search(col).sync_from_db(DB)
    assert ok == ["skill_b"]


def test_add_skill_เดี่ยว_ใส่_embed_model_ด้วย():
    """ไม่งั้น skill ที่บันทึกระหว่างใช้งานจะถูก re-embed ทุกบูต"""
    col = MagicMock()
    _search(col).add_skill(topic="t", summary="s", category="learned", source="t.md")
    assert col.upsert.call_args.kwargs["metadatas"][0]["embed_model"] == MODEL
