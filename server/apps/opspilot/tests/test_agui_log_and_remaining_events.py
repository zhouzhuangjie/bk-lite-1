"""AGUI 剩余：token 日志、kwargs 准备、工具过渡 / 消息结束 / 未知事件。

对照契约：无内容或无 skill_id 跳过落库；history_log 只回写 token/response；
新建日志固定 request_detail/response_detail 形状。工具结果后的前言剥离为空则不产出行。
"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from apps.opspilot.utils.agui_chat import (
    AguiStreamState,
    _flush_pending_content_as_thinking,
    _flush_pending_content_events,
    _flush_post_tool_pending_content_split,
    _handle_agui_data_event,
    _handle_text_message_end_event,
    _handle_tool_transition_event,
    _init_agui_stream_state,
    _log_and_update_tokens_agui,
    _looks_like_implicit_thinking_prefix,
    _prepare_agui_chat_kwargs,
    stream_agui_chat,
)

pytestmark = pytest.mark.unit


def _decode(line: str) -> dict:
    assert line.startswith("data: ")
    return json.loads(line[len("data: ") :].strip())


def test_looks_like_implicit_thinking_accepts_known_prefixes():
    assert _looks_like_implicit_thinking_prefix("  ") is True
    assert _looks_like_implicit_thinking_prefix("Reasoning") is True
    assert _looks_like_implicit_thinking_prefix("thought process") is True
    assert _looks_like_implicit_thinking_prefix("思考") is True
    assert _looks_like_implicit_thinking_prefix("th") is True


def test_flush_empty_and_whitespace_thinking_return_no_lines():
    assert _flush_pending_content_as_thinking(_init_agui_stream_state()) == []
    ws = _init_agui_stream_state()
    ws.pending_content_events = [{"type": "TEXT_MESSAGE_CONTENT", "delta": "   "}]
    assert _flush_pending_content_as_thinking(ws) == []
    assert ws.pending_content_events == []

    assert _flush_post_tool_pending_content_split(_init_agui_stream_state()) == []

    preamble_only = AguiStreamState()
    preamble_only.pending_content_events = [
        {"type": "TEXT_MESSAGE_CONTENT", "delta": "好的，我已经获取到结果。"}
    ]
    assert _flush_pending_content_events(preamble_only, strip_post_tool_preamble=True) == []


def test_handle_tool_transition_flushes_pending_on_tool_start():
    state = _init_agui_stream_state()
    state.active_message_id = "m1"
    state.buffer_pre_tool_content = True
    state.emit_pending_as_thinking = True
    state.pending_content_events = [{"type": "TEXT_MESSAGE_CONTENT", "delta": "推理中"}]
    lines = _handle_tool_transition_event(
        "TOOL_CALL_START",
        {"parent_message_id": "m1"},
        state,
        True,
        True,
    )
    assert _decode(lines[0])["type"] == "THINKING"
    assert _decode(lines[0])["delta"] == "推理中"
    assert state.buffer_pre_tool_content is False

    state2 = _init_agui_stream_state()
    state2.active_message_id = "m1"
    state2.buffer_pre_tool_content = True
    state2.emit_pending_as_thinking = False
    state2.pending_content_events = [{"type": "TEXT_MESSAGE_CONTENT", "delta": "可见"}]
    lines2 = _handle_tool_transition_event(
        "TOOL_CALL_START",
        {"parent_message_id": "m1"},
        state2,
        False,
        False,
    )
    assert _decode(lines2[0])["delta"] == "可见"

    after = _handle_tool_transition_event("TOOL_CALL_RESULT", {}, _init_agui_stream_state(), True, True)
    assert after == []


def test_handle_text_message_end_flushes_think_buffer_and_post_tool():
    state = _init_agui_stream_state()
    state.think_buffer = "<think>残留"
    state.in_think_block = False
    lines = _handle_text_message_end_event({"message_id": "m1", "timestamp": 9}, state, False, False)
    payloads = [_decode(line) for line in lines]
    content = [p for p in payloads if p.get("type") == "TEXT_MESSAGE_CONTENT"]
    assert content[0]["delta"] == "残留"
    assert content[0]["message_id"] == "m1"

    post = _init_agui_stream_state()
    post.active_message_id = "m2"
    post.buffer_pre_tool_content = True
    post.emit_pending_as_thinking = True
    post.pending_phase = "post_tool"
    post.pending_content_events = [
        {"type": "TEXT_MESSAGE_CONTENT", "delta": "好的，我已经获取到结果。最终答案"}
    ]
    end_lines = _handle_text_message_end_event({"message_id": "m2"}, post, True, True)
    types = [_decode(line)["type"] for line in end_lines]
    assert "THINKING" in types
    assert "TEXT_MESSAGE_CONTENT" in types
    assert post.active_message_id is None
    assert post.pending_phase is None


def test_handle_unknown_event_passthrough():
    state = _init_agui_stream_state()
    line, immediate = _handle_agui_data_event({"type": "CUSTOM", "name": "x"}, state, True, True)
    assert _decode(line) == {"type": "CUSTOM", "name": "x"}
    assert immediate == []


def test_prepare_agui_chat_kwargs_uses_model_and_formatter():
    params = {"llm_model": 7}
    model = SimpleNamespace(id=7)
    with (
        patch("apps.opspilot.utils.agui_chat.LLMModel.objects.get", return_value=model) as getter,
        patch(
            "apps.opspilot.utils.agui_chat.chat_service.format_chat_server_kwargs",
            return_value=({"prompt": "p"}, {}, {}),
        ) as fmt,
    ):
        out = _prepare_agui_chat_kwargs(params)
    assert out == {"prompt": "p"}
    getter.assert_called_once_with(id=7)
    fmt.assert_called_once_with(params, model)


def test_log_and_update_tokens_agui_skips_empty_and_missing_skill(mocker):
    create = mocker.patch("apps.opspilot.utils.agui_chat.SkillRequestLog.objects.create")
    _log_and_update_tokens_agui({"content": []}, "s", 1, "1.1.1.1", {}, "hi", True)
    create.assert_not_called()
    _log_and_update_tokens_agui({"content": [{"type": "TEXT"}]}, "s", None, "1.1.1.1", {}, "hi", True)
    create.assert_not_called()


def test_log_and_update_tokens_agui_updates_history_and_creates_log(mocker):
    history = SimpleNamespace(completion_tokens=9, prompt_tokens=8, total_tokens=7, response=None)
    history.save = MagicMock()
    _log_and_update_tokens_agui(
        {"content": [{"type": "TEXT", "delta": "ok"}]},
        "skill-a",
        12,
        "10.0.0.1",
        {"k": 1},
        "hello",
        False,
        history_log=history,
    )
    assert history.completion_tokens == 0
    assert history.prompt_tokens == 0
    assert history.total_tokens == 0
    assert history.response == [{"type": "TEXT", "delta": "ok"}]
    history.save.assert_called_once()

    create = mocker.patch("apps.opspilot.utils.agui_chat.SkillRequestLog.objects.create")
    _log_and_update_tokens_agui(
        {"content": [{"type": "TEXT", "delta": "ok"}]},
        "skill-a",
        12,
        "",
        {"k": 1},
        "hello",
        True,
    )
    create.assert_called_once()
    kwargs = create.call_args.kwargs
    assert kwargs["skill_id"] == 12
    assert kwargs["current_ip"] == "0.0.0.0"
    assert kwargs["state"] is True
    assert kwargs["user_message"] == "hello"
    assert kwargs["request_detail"] == {"skill_name": "skill-a", "show_think": True, "kwargs": {"k": 1}}
    assert kwargs["response_detail"]["response"] == [{"type": "TEXT", "delta": "ok"}]
    assert kwargs["response_detail"]["total_tokens"] == 0


def test_log_and_update_tokens_agui_swallows_save_error(mocker):
    history = SimpleNamespace()
    history.save = MagicMock(side_effect=RuntimeError("db down"))
    logger = mocker.patch("apps.opspilot.utils.agui_chat.logger")
    try:
        result = _log_and_update_tokens_agui(
            {"content": ["x"]}, "s", 1, "1.1.1.1", {}, "hi", True, history_log=history
        )
    except RuntimeError as exc:
        pytest.fail(f"history.save 异常不得外抛: {exc}")
    assert result is None
    history.save.assert_called_once()
    logger.error.assert_called_once()
    assert logger.error.call_args.args[0] == "AGUI log update error: db down"


def test_stream_agui_chat_fills_execution_id_and_exposes_header():
    with (
        patch("apps.opspilot.utils.agui_chat.create_sse_response_headers", return_value={"X-Accel-Buffering": "no"}),
        patch("apps.opspilot.utils.agui_chat.time.time", return_value=1700000000.5),
    ):
        resp = stream_agui_chat({"show_think": True, "skill_type": "chat"}, "s", {}, "1.1.1.1", "hi", skill_id=3)
    assert resp["X-Execution-ID"] == "1700000000500"
    assert resp["Access-Control-Expose-Headers"] == "X-Execution-ID"
    assert resp["X-Accel-Buffering"] == "no"
    assert resp["Content-Type"] == "text/event-stream"
