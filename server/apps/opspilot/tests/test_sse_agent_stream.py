"""SSE Agent 流：TEXT_MESSAGE_CONTENT 输出、CUSTOM 透传、错误收口与日志。"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from apps.opspilot.utils import sse_chat

pytestmark = pytest.mark.unit


class _Graph:
    def __init__(self, lines=None, error=None):
        self.lines = lines or []
        self.error = error

    async def agui_stream(self, request):
        if self.error:
            raise self.error
        for line in self.lines:
            yield line


@pytest.mark.asyncio
async def test_generate_agent_stream_emits_content_custom_and_stats():
    graph = _Graph(
        [
            "event: ping\n",
            "data: not-json\n\n",
            'data: {"type": "CUSTOM", "name": "browser_step_progress", "delta": "step"}\n\n',
            'data: {"type": "THINKING", "delta": "think"}\n\n',
            'data: {"type": "TEXT_MESSAGE_CONTENT", "delta": ""}\n\n',
            'data: {"type": "TEXT_MESSAGE_CONTENT", "delta": "你好"}\n\n',
        ]
    )
    chunks = [item async for item in sse_chat._generate_agent_stream(graph, object(), "skill-a", True)]
    data_lines = [c for c in chunks if isinstance(c, str)]
    stats = [c for c in chunks if isinstance(c, tuple)]
    payloads = [json.loads(line[6:]) for line in data_lines if line.startswith("data: ")]
    contents = [p for p in payloads if p.get("id") == "skill-a" and p.get("choices")]
    customs = [p for p in payloads if p.get("type") == "CUSTOM"]
    assert any(p["choices"][0]["delta"]["content"] == "你好" for p in contents)
    assert contents[-1]["choices"][0]["finish_reason"] == "stop"
    assert customs == [{"type": "CUSTOM", "name": "browser_step_progress", "delta": "step"}]
    assert stats == [("STATS", "你好")]


@pytest.mark.asyncio
async def test_generate_agent_stream_error_yields_friendly_chunk(monkeypatch):
    monkeypatch.setattr(sse_chat, "normalize_llm_error_message", lambda msg: "模型超时")
    graph = _Graph(error=RuntimeError("timeout from upstream"))
    chunks = [item async for item in sse_chat._generate_agent_stream(graph, object(), "skill-b", True)]
    assert chunks[-1] == ("STATS", "")
    err = json.loads(chunks[0][6:])
    assert err["choices"][0]["delta"]["content"] == "模型超时"
    assert err["id"] == "skill-b"


def test_log_and_update_tokens_sync_writes_history_and_swallows(monkeypatch):
    history = SimpleNamespace(conversation="")
    history.save = MagicMock()
    insert = MagicMock()
    monkeypatch.setattr(sse_chat, "insert_skill_log", insert)
    sse_chat._log_and_update_tokens_sync(
        {"content": "<think>t</think>答案"},
        "skill-c",
        12,
        "1.1.1.1",
        {"bot": 1},
        "hello",
        False,
        history_log=history,
    )
    assert history.conversation == "答案"
    history.save.assert_called_once()
    insert.assert_called_once()
    assert insert.call_args.args[0] == "1.1.1.1"
    assert insert.call_args.args[1] == 12

    history.save.side_effect = RuntimeError("db")
    sse_chat._log_and_update_tokens_sync(
        {"content": "x"},
        "skill-c",
        12,
        "1.1.1.1",
        {},
        "hello",
        True,
        history_log=history,
    )
