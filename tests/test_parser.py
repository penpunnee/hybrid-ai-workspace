"""Tests สำหรับ reasoning/parser.py — DeepSeek R1 <think> stream parser"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from reasoning.parser import parse_think_stream, stream_with_thinking, extract_final_answer


def _answers(events):
    return "".join(e["text"] for e in events if e["type"] == "answer")


def _thinks(events):
    return "".join(e["text"] for e in events if e["type"] == "think")


# ── parse_think_stream ──
def test_no_think_tag_is_all_answer():
    events = list(parse_think_stream(["hello ", "world"]))
    assert _answers(events) == "hello world"
    assert _thinks(events) == ""


def test_think_then_answer():
    events = list(parse_think_stream(["<think>reasoning</think>final answer"]))
    assert _thinks(events) == "reasoning"
    assert _answers(events) == "final answer"


def test_think_split_across_chunks():
    events = list(parse_think_stream(["<thi", "nk>step a ", "step b</think>", "the answer"]))
    assert _thinks(events) == "step a step b"
    assert _answers(events) == "the answer"


def test_text_before_think_is_answer():
    events = list(parse_think_stream(["pre<think>x</think>post"]))
    assert _answers(events) == "prepost"
    assert _thinks(events) == "x"


def test_unclosed_think_flushed_as_think():
    events = list(parse_think_stream(["<think>still thinking..."]))
    assert _thinks(events) == "still thinking..."
    assert _answers(events) == ""


# ── stream_with_thinking ──
def test_stream_hides_thinking_by_default():
    out = "".join(stream_with_thinking(["<think>secret reasoning</think>visible answer"]))
    assert out == "visible answer"
    assert "secret reasoning" not in out


def test_stream_shows_thinking_when_enabled():
    out = "".join(stream_with_thinking(
        ["<think>my reasoning</think>my answer"], show_thinking=True))
    assert "💭" in out
    assert "my reasoning" in out and "my answer" in out


def test_stream_plain_text_passthrough():
    assert "".join(stream_with_thinking(["just text"])) == "just text"


# ── extract_final_answer ──
def test_extract_separates_think_and_answer():
    thinking, answer = extract_final_answer("<think>because reasons</think>The result is 42")
    assert thinking == "because reasons"
    assert answer == "The result is 42"


def test_extract_no_think_returns_full_answer():
    thinking, answer = extract_final_answer("  plain answer  ")
    assert thinking == "" and answer == "plain answer"


def test_extract_handles_multiline_think():
    thinking, answer = extract_final_answer("<think>line1\nline2</think>done")
    assert "line1" in thinking and "line2" in thinking
    assert answer == "done"
