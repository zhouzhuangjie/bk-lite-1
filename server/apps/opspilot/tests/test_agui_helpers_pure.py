"""AGUI 辅助：think 标签清理、桥接前言剥离、隐式思考前缀。"""
import pytest

from apps.opspilot.utils.agui_chat import (
    _extract_post_tool_meta_preamble,
    _looks_like_implicit_thinking_prefix,
    _sanitize_think_tag_residue,
    _strip_post_tool_meta_preamble,
    _supports_thinking_events,
)

pytestmark = pytest.mark.unit


def test_looks_like_implicit_thinking_prefix():
    assert _looks_like_implicit_thinking_prefix("") is True
    assert _looks_like_implicit_thinking_prefix("thinking") is True
    assert _looks_like_implicit_thinking_prefix("思考过程如下") is True
    assert _looks_like_implicit_thinking_prefix("最终答案是 42") is False


def test_sanitize_think_tag_residue_strips_tags():
    assert _sanitize_think_tag_residue("", True) == ""
    assert _sanitize_think_tag_residue("a<think>x</think>b", False) == "axb"


def test_strip_and_extract_post_tool_preamble():
    assert _strip_post_tool_meta_preamble("") == ""
    text = "好的，我已经获取到结果。接下来给出结论。"
    stripped = _strip_post_tool_meta_preamble(text)
    assert "结论" in stripped
    prefix, rest = _extract_post_tool_meta_preamble(text)
    assert prefix
    assert "结论" in rest
    assert _extract_post_tool_meta_preamble("直接回答") == ("", "直接回答")


def test_supports_thinking_events_only_for_qwen():
    assert _supports_thinking_events(type("R", (), {"model": "qwen3"})()) is True
    assert _supports_thinking_events(type("R", (), {"model": "gpt-4o"})()) is False
    assert _supports_thinking_events(type("R", (), {"model": None})()) is False
