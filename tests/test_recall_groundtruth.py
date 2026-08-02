"""Tests for scripts/recall_groundtruth.py — คณิตศาสตร์ของการหาเกณฑ์ (backlog ข้อ 12)

ส่วนที่เทสคือ *การคำนวณ* ล้วนๆ ไม่แตะ ChromaDB — เพราะจุดที่พลาดง่ายคือการนับ
TP/FP/FN สลับกัน แล้วได้เกณฑ์ที่ดูดีบนกระดาษแต่ผิดจริง
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.recall_groundtruth import best_threshold, sweep_threshold


def _pair(score, label):
    return {"score": score, "label": label}


class TestSweep:
    def test_counts_are_not_swapped(self):
        pairs = [_pair(0.9, True), _pair(0.8, False), _pair(0.2, True)]
        m = next(x for x in sweep_threshold(pairs) if x.threshold == 0.5)
        assert (m.tp, m.fp, m.fn) == (1, 1, 1)

    def test_threshold_zero_keeps_everything(self):
        pairs = [_pair(0.9, True), _pair(0.1, False)]
        m = sweep_threshold(pairs)[0]
        assert m.threshold == 0.0
        assert m.fn == 0, "เกณฑ์ 0 ต้องไม่ตกอะไรเลย"
        assert m.recall == 1.0

    def test_threshold_one_rejects_almost_everything(self):
        pairs = [_pair(0.9, True), _pair(0.1, False)]
        m = sweep_threshold(pairs)[-1]
        assert m.threshold == 1.0
        assert m.tp == 0 and m.fn == 1

    def test_unlabelled_pairs_are_ignored(self):
        """ห้ามเดาแทนคน — คู่ที่ยังไม่มาร์คต้องไม่ถูกนับเป็นอะไรทั้งนั้น"""
        pairs = [_pair(0.9, True), {"score": 0.95, "label": None}]
        m = next(x for x in sweep_threshold(pairs) if x.threshold == 0.5)
        assert (m.tp, m.fp, m.fn) == (1, 0, 0)


class TestBestThreshold:
    def test_finds_clean_separation(self):
        pairs = [_pair(0.8, True), _pair(0.75, True), _pair(0.3, False), _pair(0.2, False)]
        b = best_threshold(pairs)
        assert 0.3 < b.threshold <= 0.75
        assert b.f1 == 1.0

    def test_prefers_recall_when_f1_ties(self):
        """เสมอกันให้เลือกเกณฑ์ต่ำกว่า — 'AI ลืมสิ่งที่สอนไว้' แย่กว่าแถม context เกิน"""
        pairs = [_pair(0.9, True), _pair(0.8, True)]
        b = best_threshold(pairs)
        assert b.recall == 1.0
        assert b.threshold <= 0.8

    def test_returns_none_when_nothing_marked(self):
        assert best_threshold([{"score": 0.5, "label": None}]) is None
        assert best_threshold([]) is None

    def test_metrics_do_not_divide_by_zero(self):
        pairs = [_pair(0.1, False)]
        for m in sweep_threshold(pairs):
            assert 0.0 <= m.precision <= 1.0
            assert 0.0 <= m.recall <= 1.0
            assert 0.0 <= m.f1 <= 1.0
