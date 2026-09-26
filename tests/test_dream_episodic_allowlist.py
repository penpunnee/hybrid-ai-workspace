"""utils/dream.py ต้องตัดสิน "collection ที่ prune/decay/light_sleep แตะได้" ด้วย `is_episodic_collection()` ที่เดียว
(ค้างจากก้อน 4/5: prune ยังเขียนเงื่อนไข `startswith("memory_")` inline 3 จุด — เกณฑ์เปลี่ยนที่ dualvec แล้วที่นี่ไม่ตาม)"""
import ast
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _calls(src: str, attr: str) -> int:
    n = 0
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if name == attr:
                n += 1
    return n


def test_dream_ไม่มีเงื่อนไข_memory_prefix_inline():
    src = open(os.path.join(ROOT, "utils", "dream.py"), encoding="utf-8").read()
    starts = [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Attribute) and n.func.attr == "startswith"
              and n.args and isinstance(n.args[0], ast.Constant) and n.args[0].value == "memory_"]
    assert not starts, f"ยังมี startswith('memory_') inline {len(starts)} จุด — ใช้ is_episodic_collection()"
    assert _calls(src, "is_episodic_collection") >= 3


def test_semantics_ตรงกับเงื่อนไขเดิม():
    from memory.dualvec import is_episodic_collection
    for name, old in [("memory_kwan", True), ("memory_kwan__keys", False), ("long_term_memory", False),
                      ("user_facts", False), ("memory_", True), ("", False)]:
        assert is_episodic_collection(name) == old, name
