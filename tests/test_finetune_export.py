"""Tests สำหรับ Stage 1 — export 👍 conversations → JSONL (SFT chat format)

ดึง assistant message ที่ได้ 👍 + user prompt ก่อนหน้า → ตัวอย่างเทรน
exclude 👎, skip orphan (ไม่มี user ก่อนหน้า). รันออฟไลน์ ไม่ต้อง GPU
"""
import os
import sys
import json
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.finetune_export import export_sft, _build_example


def _seed_db(path):
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY, assistant TEXT, role TEXT,
            content TEXT, session_id TEXT, pinned INTEGER DEFAULT 0
        );
        CREATE TABLE feedback (
            message_id INTEGER, rating TEXT, assistant TEXT,
            comment TEXT, created_at TEXT
        );
    """)
    # session s1: user → assistant(👍) ... user → assistant(👎)
    conn.executemany(
        "INSERT INTO messages (id,assistant,role,content,session_id) VALUES (?,?,?,?,?)",
        [
            (1, "kwan", "user", "2+2 เท่ากับเท่าไหร่", "s1"),
            (2, "kwan", "assistant", "เท่ากับ 4 ค่ะ", "s1"),       # 👍
            (3, "kwan", "user", "คำถามห่วย", "s1"),
            (4, "kwan", "assistant", "ตอบมั่ว", "s1"),             # 👎
            (5, "kwan", "assistant", "orphan ไม่มี user ก่อน", "s2"),  # 👍 แต่ orphan
        ],
    )
    conn.executemany(
        "INSERT INTO feedback (message_id,rating,assistant) VALUES (?,?,?)",
        [(2, "up", "kwan"), (4, "down", "kwan"), (5, "up", "kwan")],
    )
    conn.commit()
    conn.close()


# ── _build_example ──
def test_build_example_structure():
    ex = _build_example("SYS", "U", "A")
    assert ex["messages"] == [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "U"},
        {"role": "assistant", "content": "A"},
    ]


def test_build_example_omits_empty_system():
    ex = _build_example("", "U", "A")
    assert [m["role"] for m in ex["messages"]] == ["user", "assistant"]


# ── export_sft ──
def test_export_only_thumbs_up(tmp_path):
    db = str(tmp_path / "chat.db")
    out = str(tmp_path / "ds.jsonl")
    _seed_db(db)
    res = export_sft(db, out, system_prompts={"kwan": "คุณคือขวัญ"})

    assert res["count"] == 1          # เฉพาะ 👍 ที่มี user ก่อนหน้า (msg2); 👎 + orphan ตัดออก
    lines = [json.loads(l) for l in open(out, encoding="utf-8") if l.strip()]
    assert len(lines) == 1
    msgs = lines[0]["messages"]
    assert msgs[0] == {"role": "system", "content": "คุณคือขวัญ"}
    assert msgs[1]["content"] == "2+2 เท่ากับเท่าไหร่"   # user prompt ก่อนหน้า
    assert msgs[2]["content"] == "เท่ากับ 4 ค่ะ"          # 👍 assistant
    # ห้ามมีตัวอย่าง 👎
    assert all("ตอบมั่ว" not in json.dumps(l, ensure_ascii=False) for l in lines)


def test_export_empty_db_creates_empty_file(tmp_path):
    db = str(tmp_path / "empty.db")
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE messages (id INTEGER PRIMARY KEY, assistant TEXT, role TEXT, content TEXT, session_id TEXT, pinned INTEGER);
        CREATE TABLE feedback (message_id INTEGER, rating TEXT, assistant TEXT, comment TEXT, created_at TEXT);
    """)
    conn.commit(); conn.close()
    res = export_sft(db, str(tmp_path / "out.jsonl"))
    assert res["count"] == 0
    assert os.path.exists(res["path"])


def test_export_filter_by_assistant(tmp_path):
    db = str(tmp_path / "c.db")
    _seed_db(db)
    res = export_sft(db, str(tmp_path / "o.jsonl"), assistant="someone_else")
    assert res["count"] == 0   # ไม่มี 👍 ของ assistant นี้
