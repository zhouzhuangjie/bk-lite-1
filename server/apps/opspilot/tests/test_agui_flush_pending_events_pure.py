"""AGUI 流式缓冲：pending 内容冲刷为可见文本 / THINKING / 隐式 think 拆分。"""
import json

import pytest

from apps.opspilot.utils.agui_chat import (
    AguiStreamState,
    _build_thinking_event,
    _flush_pending_content_as_thinking,
    _flush_pending_content_detecting_implicit_think,
    _flush_pending_content_events,
    _flush_post_tool_pending_content_split,
)

pytestmark = pytest.mark.unit


def _decode_line(line: str) -> dict:
    assert line.startswith("data: ")
    assert line.endswith("\n\n")
    return json.loads(line[len("data: ") :].strip())


def test_flush_pending_content_events_passthrough_and_preamble_strip():
    empty = AguiStreamState()
    assert _flush_pending_content_events(empty) == []

    state = AguiStreamState()
    state.pending_content_events = [{"type": "TEXT_MESSAGE_CONTENT", "delta": "hello"}]
    lines = _flush_pending_content_events(state)
    assert _decode_line(lines[0])["delta"] == "hello"
    assert state.pending_content_events == []

    preamble = AguiStreamState()
    preamble.pending_content_events = [
        {"type": "TEXT_MESSAGE_CONTENT", "delta": "好的，我已经获取到结果。接下来给出结论。"}
    ]
    stripped = _flush_pending_content_events(preamble, strip_post_tool_preamble=True)
    payload = _decode_line(stripped[0])
    assert "结论" in payload["delta"]
    assert "我已经获取到结果" not in payload["delta"]


def test_flush_pending_content_as_thinking_emits_thinking_event():
    assert _flush_pending_content_as_thinking(AguiStreamState()) == []
    state = AguiStreamState()
    state.pending_content_events = [{"type": "TEXT_MESSAGE_CONTENT", "delta": "reasoning"}]
    lines = _flush_pending_content_as_thinking(state)
    payload = _decode_line(lines[0])
    assert payload["type"] == "THINKING"
    assert payload["delta"] == "reasoning"
    assert state.pending_content_events == []


def test_flush_post_tool_pending_splits_preamble_and_visible():
    state = AguiStreamState()
    state.pending_content_events = [
        {"type": "TEXT_MESSAGE_CONTENT", "delta": "好的，我已经获取到结果。最终答案是 42"}
    ]
    lines = _flush_post_tool_pending_content_split(state)
    types = [_decode_line(line)["type"] for line in lines]
    assert types == ["THINKING", "TEXT_MESSAGE_CONTENT"]
    assert "42" in _decode_line(lines[1])["delta"]


def test_flush_pending_detects_implicit_think_split():
    state = AguiStreamState()
    state.pending_content_events = [
        {"type": "TEXT_MESSAGE_CONTENT", "delta": "思考过程</think>可见答案", "timestamp": 1}
    ]
    lines = _flush_pending_content_detecting_implicit_think(state)
    assert _decode_line(lines[0])["type"] == "THINKING"
    assert "思考" in _decode_line(lines[0])["delta"]
    assert _decode_line(lines[1])["delta"] == "可见答案"

    plain = AguiStreamState()
    plain.pending_content_events = [{"type": "TEXT_MESSAGE_CONTENT", "delta": "直接回答"}]
    plain_lines = _flush_pending_content_detecting_implicit_think(plain)
    assert _decode_line(plain_lines[0])["delta"] == "直接回答"


def test_build_thinking_event_has_delta_and_timestamp():
    event = _build_thinking_event("x", timestamp=123)
    assert event == {"type": "THINKING", "delta": "x", "timestamp": 123}
