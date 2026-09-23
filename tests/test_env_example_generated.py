"""`.env.example` ส่วนบนต้อง generate จาก registry — ปิดทิศ *โค้ด → เอกสาร*

**ช่องที่ปิด** — `test_env_docs_ratchet.py` ตรวจว่า "เอกสารไม่โฆษณาของที่โค้ดไม่อ่าน"
(doc → code) แต่ทิศกลับเปิดโล่ง: เพิ่ม env ใหม่ในโค้ดแล้วไม่จดเอกสาร ไม่มีอะไรร้อง
(วัด 2026-09-23: **38 ตัว** ที่โค้ดอ่านแต่ไม่มีในเอกสารไหนเลย)

**ขอบเขตจริงของเทสนี้ — อย่าเข้าใจผิดว่าปิดครบ:** คุมเฉพาะชื่อที่อยู่ใน `REGISTRY`
(ตอนนี้ = เฉพาะที่ `core/config.py` อ่าน) · env อีก ~95 ชื่อที่ยังกระจายอยู่ในไฟล์อื่น
**ยังไม่ถูกคุม** จนกว่าจะย้ายเข้า registry (ก้อน 4)

**ทำไมต้องมีส่วน "เขียนมือ" ต่อท้าย** — ลบชื่อที่ยังไม่เข้า registry ออกจาก
`.env.example` เพื่อให้ "generate ได้ทั้งไฟล์" = ทำเอกสารแย่ลงเพื่อให้เทสสวย
ไฟล์จึงแบ่งสองส่วนด้วย marker: บน = generate · ล่าง = ของเดิมคงไว้ดิบๆ
"""

from __future__ import annotations

import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
ENV_EXAMPLE = REPO / ".env.example"


def test_env_example_ตรงกับที่_generate_ได้():
    """รันคำสั่ง generate แล้วผลต้องเท่ากับไฟล์ที่ commit ไว้ — ไม่งั้น CI แดง

    วิธีแก้เมื่อแดง: `python scripts/gen_env_example.py --write` แล้ว commit
    """
    import core.config  # noqa: F401  — เติม registry
    from core.env_registry import render_env_example

    expected = render_env_example(ENV_EXAMPLE.read_text())
    actual = ENV_EXAMPLE.read_text()
    assert actual == expected, (
        ".env.example ไม่ตรงกับ registry — รัน `python scripts/gen_env_example.py --write` "
        "แล้ว commit (env ที่เพิ่มใน core/config.py ต้องโผล่ในเอกสารเสมอ)"
    )


def test_ทุกชื่อใน_registry_ต้องอยู่ในไฟล์():
    import core.config  # noqa: F401
    from core.env_registry import REGISTRY

    text = ENV_EXAMPLE.read_text()
    ขาด = [name for name in REGISTRY if f"{name}=" not in text]
    assert ขาด == [], f"env พวกนี้อยู่ใน registry แต่ไม่โผล่ใน .env.example: {ขาด}"


def test_ชื่อใน_registry_ต้องไม่ซ้ำในส่วนที่เขียนมือ():
    """กันไฟล์บอกสองอย่างเรื่องเดียวกัน (บนบอกค่าหนึ่ง ล่างบอกอีกค่า)"""
    import core.config  # noqa: F401
    from core.env_registry import END_MARKER, REGISTRY

    text = ENV_EXAMPLE.read_text()
    manual = text.split(END_MARKER, 1)[1] if END_MARKER in text else ""
    ซ้ำ = [n for n in REGISTRY
           if any(line.strip().lstrip("# ").startswith(f"{n}=") for line in manual.splitlines())]
    assert ซ้ำ == [], f"ชื่อพวกนี้อยู่ทั้งส่วน generate และส่วนเขียนมือ: {ซ้ำ}"


def test_ส่วนเขียนมือไม่ถูกกลืนหาย():
    """generator ต้องคงของที่ยังไม่เข้า registry ไว้ครบ — ไม่ใช่ลบทิ้งให้ไฟล์สวย"""
    import core.config  # noqa: F401
    from core.env_registry import REGISTRY, render_env_example

    out = render_env_example(ENV_EXAMPLE.read_text())
    for name in ("GOOGLE_SEARCH_CX", "HEARTBEAT_URL", "NAS_IP", "EMBEDDING_MODEL"):
        assert name not in REGISTRY, f"{name} เข้า registry แล้ว — แก้เทสนี้ให้ใช้ตัวอื่น"
        assert f"{name}=" in out, f"{name} หายไปตอน generate"


def test_เครื่องมือวัดมีตาจริง():
    """กลุ่มควบคุม: แก้คำอธิบายใน registry แล้วผลที่ generate ต้อง *ไม่* ตรงกับไฟล์เดิม
    — ถ้าเหมือนเดิมแปลว่า generator ไม่ได้ใช้ registry จริง แล้วเทสข้างบนเขียวฟรี"""
    import core.config  # noqa: F401
    from core.env_registry import REGISTRY, EnvSpec, render_env_example

    เดิม = REGISTRY["OLLAMA_MODEL"]
    REGISTRY["OLLAMA_MODEL"] = EnvSpec(เดิม.name, เดิม.default, เดิม.kind,
                                       "คำอธิบายปลอมสำหรับกลุ่มควบคุม", เดิม.group)
    try:
        assert render_env_example(ENV_EXAMPLE.read_text()) != ENV_EXAMPLE.read_text()
    finally:
        REGISTRY["OLLAMA_MODEL"] = เดิม


def test_คำอธิบายหลายบรรทัดกลายเป็นคอมเมนต์ทุกบรรทัด():
    """ความรู้ยาวๆ ที่เคยอยู่ใน .env.example (เช่น 'บน Docker ใช้ host.docker.internal')
    ต้องย้ายมาอยู่ใน doc ของ registry ได้ โดยไม่ทำให้ไฟล์ที่ generate พัง"""
    from core.env_registry import EnvSpec, _render_entry

    out = _render_entry(EnvSpec("FAKE", "ค่า", "str", "บรรทัดหนึ่ง\nบรรทัดสอง", "กลุ่ม"))
    assert out.splitlines()[0].startswith("# บรรทัดหนึ่ง")
    assert out.splitlines()[1].startswith("# บรรทัดสอง")
    assert out.splitlines()[-1] == "FAKE=ค่า"


@pytest.mark.parametrize("kind,default,expected", [
    ("bool", False, "FAKE=false"),
    ("bool", True, "FAKE=true"),
    ("int", 120, "FAKE=120"),
    ("float", 1.1, "FAKE=1.1"),
    ("str", "", "FAKE="),
])
def test_เขียนค่าตามชนิดให้ถูกแบบที่_dotenv_อ่านกลับได้(kind, default, expected):
    """bool ต้องเป็น `true`/`false` ตัวเล็ก — ไม่ใช่ `True` ของ Python
    (คนก๊อปไฟล์นี้ไปทำ .env จริง ถ้าเขียน `True` กติกา lower()=="true" จะยังใช้ได้
    แต่ `False` จะอ่านเป็นเท็จโดยบังเอิญ ไม่ใช่เพราะตั้งใจ — เขียนให้ตรงกติกาไปเลย)"""
    from core.env_registry import EnvSpec, _render_entry

    out = _render_entry(EnvSpec("FAKE", default, kind, "ทดสอบ", "กลุ่ม"))
    assert out.splitlines()[-1] == expected


def test_ไม่มี_path_เฉพาะเครื่องหลุดเข้าไฟล์():
    """default บางตัวคำนวณจากตำแหน่งรีโป (`NAS_DATA_PATH`, `READER_DB_PATH`)
    ⇒ ถ้าเขียนดิบๆ จะได้ `/Users/pawin/...` บนเครื่อง dev และ `/app/...` บน CI
    = ไฟล์ที่ generate ไม่มีทางตรงกัน (CI แดงตลอดโดยไม่ได้แปลว่ามีอะไรผิด)
    และคนอื่นที่ก๊อปไฟล์ไปใช้ก็ได้ path ของเครื่องเรา"""
    import core.config  # noqa: F401
    from core.env_registry import render_env_example

    out = render_env_example(ENV_EXAMPLE.read_text())
    repo = str(REPO)
    assert repo not in out, f"path ของเครื่องนี้ ({repo}) หลุดเข้า .env.example"
    assert "NAS_DATA_PATH=./data" in out
    assert "READER_DB_PATH=./data/reader.db" in out
