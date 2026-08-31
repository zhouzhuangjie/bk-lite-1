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


@pytest.mark.asyncio
async def test_generate_agent_stream_flushes_think_buffer_when_hidden():
    graph = _Graph(
        [
            'data: {"type": "TEXT_MESSAGE_CONTENT", "delta": "可见"}\n\n',
        ]
    )
    chunks = [item async for item in sse_chat._generate_agent_stream(graph, object(), "skill-d", False)]
    payloads = [json.loads(c[6:]) for c in chunks if isinstance(c, str) and c.startswith("data: ")]
    contents = [p["choices"][0]["delta"]["content"] for p in payloads if p.get("choices")]
    assert "可见" in contents
    assert chunks[-1] == ("STATS", "可见")


def _sync_to_async(func, thread_sensitive=True):
    async def wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    return wrapper


@pytest.mark.asyncio
async def test_create_stream_generator_yields_chunks_and_persists(monkeypatch):
    graph = _Graph(['data: {"type": "TEXT_MESSAGE_CONTENT", "delta": "答案"}\n\n'])
    monkeypatch.setattr(sse_chat, "_prepare_stream_prerequisites", lambda params: ("qa", {}))
    monkeypatch.setattr(sse_chat, "create_agent_instance", lambda skill_type, chat_kwargs: (graph, object()))
    logged = {}

    def _log(*args, **kwargs):
        logged["args"] = args

    monkeypatch.setattr(sse_chat, "_log_and_update_tokens_sync", _log)
    monkeypatch.setattr(sse_chat, "sync_to_async", _sync_to_async)
    gen = sse_chat.create_stream_generator({"llm_model": 1, "show_think": True}, "skill-e", {}, "1.1.1.1", "q", skill_id=8)
    chunks = [item async for item in gen]
    payloads = [json.loads(c[6:]) for c in chunks if isinstance(c, str) and c.startswith("data: ")]
    contents = [p["choices"][0]["delta"]["content"] for p in payloads if p.get("choices")]
    assert "答案" in contents
    assert logged["args"][1] == "skill-e"
    assert logged["args"][2] == 8


@pytest.mark.asyncio
async def test_create_stream_generator_error_emits_chat_error(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("prep failed")

    monkeypatch.setattr(sse_chat, "sync_to_async", lambda func, thread_sensitive=True: boom)
    gen = sse_chat.create_stream_generator({"llm_model": 1}, "skill-f", {}, None, "q")
    chunks = [item async for item in gen]
    assert len(chunks) == 1
    payload = json.loads(chunks[0][6:])
    assert "聊天错误: prep failed" in payload["choices"][0]["delta"]["content"]
    assert payload["id"] == "skill-f"


def test_stream_chat_sets_sse_headers(monkeypatch):
    monkeypatch.setattr(sse_chat, "create_stream_generator", lambda *a, **k: iter(()))
    monkeypatch.setattr(sse_chat, "create_sse_response_headers", lambda: {"X-Test": "1"})
    resp = sse_chat.stream_chat({}, "s", {}, "ip", "msg")
    assert resp["X-Test"] == "1"
    assert resp["Content-Type"].startswith("text/event-stream")
