"""流式共享逻辑与 SSE 响应提取：think 拆分、最终文本、浏览器步骤。"""
import asyncio
import json

import pytest

from apps.opspilot.utils.chat_flow_utils.engine.sse_responder import SSEResponderMixin
from apps.opspilot.utils.stream_common import process_think_buffer, process_think_content, split_think_content

pytestmark = pytest.mark.unit


def test_process_think_buffer_emits_prefix_and_strips_block():
    out, buf, in_think = process_think_buffer("hello<think>secret", False)
    assert out == "hello"
    assert in_think is True
    # 未闭合的 think 块会丢弃缓冲区，避免把思考内容泄漏到可见输出
    assert buf == ""

    out2, buf2, in_think2 = process_think_buffer("hidden</think>world", True)
    assert out2 == ""
    assert in_think2 is False
    assert buf2 == "world"

    out3, buf3, in_think3 = process_think_buffer("abcdefghij", False)
    assert out3 == "ab"
    assert buf3 == "cdefghij"
    assert in_think3 is False


def test_process_think_content_show_think_passthrough_and_first_tag():
    chunk, buf, in_think, is_first, has_tags = process_think_content("keep", "", False, True, True, False)
    assert chunk == "keep"
    assert is_first is False

    visible, buf, in_think, is_first, has_tags = process_think_content("plain", "", False, True, False, False)
    assert visible == "plain"
    assert has_tags is False

    visible, buf, in_think, is_first, has_tags = process_think_content("<think>x", "", False, True, False, False)
    assert visible == ""
    assert in_think is True
    assert has_tags is True


def test_split_think_content_separates_visible_and_thinking():
    visible, thinking, buf, in_think, is_first, has_tags = split_think_content(
        "前<think>想</think>后", "", False, True, False
    )
    assert "前" in visible and "后" in visible
    assert "想" in thinking
    assert in_think is False
    assert has_tags is True

    visible2, thinking2, *_ = split_think_content("no-tags", "", False, True, False)
    assert visible2 == "no-tags"
    assert thinking2 == ""


class _Engine(SSEResponderMixin):
    execution_id = "exec-1"
    AGUI_SKIP_TYPES = {"RUN_STARTED", "TOOL_CALL_START"}


def test_sse_stream_headers_and_error_payload():
    mixin = _Engine()
    resp = mixin._create_sse_stream_response(lambda: iter(["data: x\n\n"]))
    assert resp["X-Execution-ID"] == "exec-1"
    assert resp["Cache-Control"].startswith("no-cache")
    err = mixin._create_error_response("boom")

    async def _read():
        chunks = []
        async for part in err.streaming_content:
            chunks.append(part.decode() if isinstance(part, bytes) else part)
        return "".join(chunks)

    text = asyncio.run(_read())
    assert "boom" in text
    assert "[DONE]" in text


def test_extract_final_message_skips_agui_and_reads_openai_delta():
    mixin = _Engine()
    assert mixin._extract_final_message([]) == ""
    content = mixin._extract_final_message(
        [
            "ignore",
            {"type": "RUN_STARTED"},
            {"type": "CUSTOM", "name": "browser_step_progress"},
            {"object": "chat.completion.chunk", "choices": [{"delta": {"content": "你好"}}]},
            {"type": "TEXT_MESSAGE_CONTENT", "delta": "世界"},
            {"object": "message", "content": "!"},
            {"text": "extra"},
        ]
    )
    assert content == "你好世界!extra"


def test_extract_browser_steps_appends_final_evaluation():
    mixin = _Engine()
    assert mixin._extract_browser_steps([]) == []
    steps = mixin._extract_browser_steps(
        [
            {"type": "CUSTOM", "name": "other"},
            {"type": "CUSTOM", "name": "browser_step_progress", "value": {"step_number": 1, "next_goal": "打开页面", "evaluation": ""}},
            {"type": "CUSTOM", "name": "browser_step_progress", "value": {"step_number": 2, "next_goal": "点击按钮", "evaluation": "完成"}},
        ]
    )
    assert steps[0] == "步骤1 打开页面"
    assert steps[1] == "步骤2 点击按钮"
    assert steps[-1] == "最终结果: 完成"
