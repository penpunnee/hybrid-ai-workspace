"""Test: threshold ดึงเอกสารเข้า context ต้องไม่หลวมจนแปะ citation ทุกข้อความ

อาการที่เจอจริงบน prod (2026-08-02, เห็นกับตาบนหน้าเว็บ): ถาม "ตอนนี้กี่โมงแล้ว"
แต่ระบบขึ้น citation [1][2][3] อ้างไฟล์ "รายชื่อครัวเรือนเปราะบาง" ทุกครั้ง
เพราะ `retrieve_chunks(prompt, top_k=3, min_score=0.3)` ถูกเรียกทุกข้อความ
ด้วย threshold 0.3 ซึ่งต่ำกว่าคะแนนที่คำถามไม่เกี่ยวข้องได้จริง (0.33-0.42)

วัดจริงบน prod หลังแก้ embedding ภาษาไทยแล้ว:
  - คำถามไม่เกี่ยวกับเอกสาร: 0.33, 0.34, 0.34, 0.35, 0.42 (outlier 0.55 = คำถาม
    ตัวเลขล้วนไปตรงกับสเปรดชีตตัวเลข)
  - คำถามที่เกี่ยวกับเอกสารจริง: 0.56, 0.64, 0.68, 0.73
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import routers.chat as chatmod


def test_doc_min_score_is_above_measured_noise_floor():
    """ต้องสูงกว่าคะแนนที่คำถามทั่วไป (ไม่เกี่ยวเอกสาร) ทำได้จริงบน prod"""
    assert chatmod._DOC_MIN_SCORE >= 0.45, (
        f"threshold {chatmod._DOC_MIN_SCORE} ต่ำเกินไป — คำถามที่ไม่เกี่ยวกับเอกสาร "
        "ทำคะแนนได้ถึง 0.42 จะถูกดึงเข้ามาแปะเป็น citation ทุกข้อความ"
    )


def test_doc_min_score_not_so_high_it_blocks_real_hits():
    """ต้องไม่สูงจนคำถามที่เกี่ยวจริง (ต่ำสุดวัดได้ 0.564) หลุด"""
    assert chatmod._DOC_MIN_SCORE <= 0.55, (
        f"threshold {chatmod._DOC_MIN_SCORE} สูงเกินไป — คำถามที่เกี่ยวกับเอกสารจริง "
        "ทำคะแนนต่ำสุดได้ 0.564 จะค้นไม่เจอ"
    )


def test_doc_min_score_configurable_via_env():
    """ปรับได้ทาง .env โดยไม่ต้องแก้โค้ด (ค่าจะถูกอ่านตอน import module)"""
    import inspect
    src = inspect.getsource(chatmod)
    assert "DOC_RETRIEVAL_MIN_SCORE" in src
