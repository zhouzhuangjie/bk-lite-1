"""BasicGraph.agui_stream / execute：编译失败、中断、自定义事件、工具 SSE 与 token 汇总。"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from apps.opspilot.metis.llm.chain.entity import BasicLLMRequest
from apps.opspilot.metis.llm.chain.graph import BasicGraph

pytestmark = pytest.mark.unit


class _FakeCompiledGraph:
    def __init__(self, events):
        self._events = events

    async def astream_events(self, *_args, **_kwargs):
        for event in self._events:
            yield event


class _FakeGraph(BasicGraph):
    def __init__(self, events=None, compiled=None):
        self._events = events or []
        self._compiled = compiled

    async def compile_graph(self, _request):
        if self._compiled is not None or self._events:
            return self._compiled if self._compiled is not None else _FakeCompiledGraph(self._events)
        return None


def _payloads(lines):
    out = []
    for line in lines:
        if line.startswith("data: "):
            out.append(json.loads(line[6:].strip()))
    return out


@pytest.mark.asyncio
async def test_agui_stream_compile_none_and_interrupt_and_custom_event(monkeypatch):
    missing = _FakeGraph()
    failed = _payloads([line async for line in missing.agui_stream(BasicLLMRequest(user_message="hi"))])
    assert failed[0]["type"] == "RUN_STARTED"
    assert failed[1]["type"] == "RUN_ERROR"
    assert failed[1]["code"] == "EXECUTION_ERROR"
    assert "graph is None" in failed[1]["message"]

    async def _stop(_execution_id):
        return True

    monkeypatch.setattr("apps.opspilot.metis.llm.chain.graph.is_interrupt_requested_async", _stop)
    graph = _FakeGraph(
        [
            {"event": "on_custom_event", "name": "agent_step_progress", "data": {"step": 1}},
        ]
    )
    interrupted = _payloads(
        [line async for line in graph.agui_stream(BasicLLMRequest(thread_id="t1", extra_config={"execution_id": "exec-1"}))]
    )
    assert interrupted[0]["type"] == "RUN_STARTED"
    assert interrupted[1]["type"] == "RUN_ERROR"
    assert interrupted[1]["code"] == "INTERRUPTED"
    assert interrupted[1]["message"] == "执行已中断"

    async def _never(_execution_id):
        return False

    monkeypatch.setattr("apps.opspilot.metis.llm.chain.graph.is_interrupt_requested_async", _never)
    custom = _FakeGraph(
        [
            {"event": "on_custom_event", "name": "agent_step_progress", "data": {"step": 2, "status": "running"}},
            {"event": "on_custom_event", "name": "", "data": {"ignored": True}},
        ]
    )
    payloads = _payloads([line async for line in custom.agui_stream(BasicLLMRequest(user_message="hi"))])
    customs = [p for p in payloads if p.get("type") == "CUSTOM"]
    assert len(customs) == 1
    assert customs[0]["name"] == "agent_step_progress"
    assert customs[0]["value"]["step"] == 2
    assert payloads[-1]["type"] == "RUN_FINISHED"


@pytest.mark.asyncio
async def test_graph_execute_aggregates_tokens_and_wraps_taskgroup_error():
    graph = _FakeGraph(compiled="compiled")
    ai = AIMessage(
        content="done",
        response_metadata={"token_usage": {"prompt_tokens": 3, "completion_tokens": 5}},
    )

    async def _invoke(_self, _compiled, request, extra_configurable=None):
        extra_configurable["browser_step_callback"]({"step_number": 1, "next_goal": "open page", "evaluation": "ok"})
        extra_configurable["browser_step_callback"]({"step_number": 2, "next_goal": "", "evaluation": ""})
        return {"messages": [ai]}

    with patch.object(BasicGraph, "invoke", _invoke):
        out = await graph.execute(BasicLLMRequest(user_message="hi"))
    assert out.message == "done"
    assert out.prompt_tokens == 3
    assert out.completion_tokens == 5
    assert out.total_tokens == 8
    assert out.browser_steps == ["step1 open page", "最终结果: ok"]

    async def _boom(_self, _compiled, request, extra_configurable=None):
        raise Exception("unhandled errors in a TaskGroup") from RuntimeError("inner-fail")

    with patch.object(BasicGraph, "invoke", _boom), pytest.raises(RuntimeError, match="Agent execution failed: TaskGroup error: inner-fail"):
        await graph.execute(BasicLLMRequest(user_message="hi"))

    class _Group(Exception):
        def __init__(self):
            super().__init__("unhandled errors in a TaskGroup")
            self.exceptions = [RuntimeError("a"), ValueError("b")]

    async def _group(_self, _compiled, request, extra_configurable=None):
        raise _Group()

    with patch.object(BasicGraph, "invoke", _group), pytest.raises(RuntimeError, match="TaskGroup errors: a, b"):
        await graph.execute(BasicLLMRequest(user_message="hi"))

    async def _empty(_self, _compiled, request, extra_configurable=None):
        return {"messages": []}

    with patch.object(BasicGraph, "invoke", _empty):
        blank = await graph.execute(BasicLLMRequest(user_message="hi"))
    assert blank.message == ""
    assert blank.total_tokens == 0
    assert blank.browser_steps == []


@pytest.mark.asyncio
async def test_agui_stream_emits_tool_and_model_events():
    chunk = SimpleNamespace(
        content="hello",
        additional_kwargs={},
        tool_call_chunks=[{"id": "tc-1", "name": "kubectl"}],
    )
    events = [
        {"event": "on_chat_model_stream", "data": {"chunk": chunk}},
        {"event": "on_tool_start", "name": "kubectl", "run_id": "r1", "data": {"input": {"cmd": "get"}}},
        {"event": "on_tool_end", "name": "kubectl", "run_id": "r1", "data": {"output": "ok"}},
        {
            "event": "on_chat_model_end",
            "data": {"output": SimpleNamespace(content="", tool_calls=[])},
        },
    ]
    graph = _FakeGraph(events=events)
    payloads = _payloads([line async for line in graph.agui_stream(BasicLLMRequest(user_message="hi"))])
    types = [p["type"] for p in payloads]
    assert types[0] == "RUN_STARTED"
    assert "TEXT_MESSAGE_CONTENT" in types
    assert "TOOL_CALL_START" in types
    assert "TOOL_CALL_END" in types
    assert types[-1] == "RUN_FINISHED"


@pytest.mark.asyncio
async def test_stream_forwards_messages_mode_and_tool_call_helpers():
    graph = _FakeGraph(compiled="compiled")
    streamed = object()

    async def _invoke(_self, compiled, request, stream_mode="values", extra_configurable=None):
        assert compiled == "compiled"
        assert stream_mode == "messages"
        return streamed

    with patch.object(BasicGraph, "invoke", _invoke):
        assert await graph.stream(BasicLLMRequest(user_message="hi")) is streamed

    encoder = MagicMock()
    encoder.encode.side_effect = lambda event: type(event).__name__
    dummy = _FakeGraph()
    empty = dummy._handle_tool_call_chunks(None, encoder, "m1", {})
    assert empty == []
    current = {}
    started = dummy._handle_tool_call_chunks(
        SimpleNamespace(tool_call_chunks=[{"id": "tc-new", "name": "search"}, {"id": "tc-new", "name": "search"}]),
        encoder,
        "m1",
        current,
    )
    assert started == ["ToolCallStartEvent"]
    assert current["tc-new"]["name"] == "search"

    obj_call = SimpleNamespace(id="obj-1", name="ssh", args={"password": "secret", "cmd": "ls"})
    emitted = [e async for e in dummy._handle_tool_calls([{"id": "d1", "name": "echo", "args": "plain"}, obj_call], encoder, "parent", {})]
    assert emitted.count("ToolCallStartEvent") == 2
    assert "ToolCallArgsEvent" in emitted
    encoded = [call.args[0] for call in encoder.encode.call_args_list]
    args_events = [e for e in encoded if type(e).__name__ == "ToolCallArgsEvent"]
    assert any("secret" not in e.delta and "***" in e.delta for e in args_events)
    assert any(e.delta == "plain" for e in args_events)
