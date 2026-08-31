"""BasicGraph 流合并、浏览器回调、chunk 解析与工具 SSE 事件。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.opspilot.metis.llm.chain.entity import BasicLLMRequest
from apps.opspilot.metis.llm.chain.graph import (
    BasicGraph,
    _merge_async_streams,
    create_browser_custom_event_callback,
    create_browser_step_callback,
)

pytestmark = pytest.mark.unit


class DummyGraph(BasicGraph):
    async def compile_graph(self, request):
        return MagicMock()


def test_prepare_graph_wires_start_to_rag():
    builder = MagicMock()
    node = SimpleNamespace(
        prompt_message_node="p",
        add_chat_history_node="h",
        naive_rag_node="r",
        user_message_node="u",
        suggest_question_node="s",
    )
    last = DummyGraph().prepare_graph(builder, node)
    assert last == "naive_rag_node"
    assert builder.add_node.call_count == 5
    assert builder.add_edge.call_count == 5


@pytest.mark.asyncio
async def test_invoke_values_and_messages_modes():
    graph = MagicMock()
    graph.ainvoke = AsyncMock(return_value={"ok": True})
    graph.astream = MagicMock(return_value="stream")
    request = BasicLLMRequest(user_message="hi", extra_config={"trace": 1})
    g = DummyGraph()
    values = await g.invoke(graph, request, stream_mode="values", extra_configurable={"k": "v"})
    assert values == {"ok": True}
    cfg = graph.ainvoke.call_args.args[1]
    assert cfg["configurable"]["graph_request"] is request
    assert cfg["configurable"]["k"] == "v"
    assert cfg["configurable"]["trace"] == 1
    streamed = await g.invoke(graph, request, stream_mode="messages")
    assert streamed == "stream"
    graph.astream.assert_called_once()


def test_extract_content_from_chunk_anthropic_and_fallback():
    g = DummyGraph()
    assert g._extract_content_from_chunk("plain") == ("plain", "")
    assert g._extract_content_from_chunk(12) == ("12", "")
    text, think = g._extract_content_from_chunk(
        [
            {"type": "thinking", "thinking": "reason"},
            {"type": "text", "text": "hello"},
            {"type": "other", "text": "more"},
            {"type": "other", "content": "block"},
            "raw",
        ]
    )
    assert think == "reason"
    assert "hello" in text
    assert "more" in text
    assert "block" in text
    assert "raw" in text


def test_handle_chat_model_stream_emits_think_tags_and_text():
    g = DummyGraph()
    encoder = MagicMock()
    encoder.encode.side_effect = lambda event: type(event).__name__
    chunk = SimpleNamespace(content="hi <think>plan</think> done", additional_kwargs={})
    events, msg_id, started, thinking = g._handle_chat_model_stream_content(
        chunk, encoder, "run-1", None, False, True, False
    )
    names = set(events)
    assert "ThinkingTextMessageStartEvent" in names
    assert "ThinkingTextMessageContentEvent" in names
    assert "ThinkingTextMessageEndEvent" in names
    assert "TextMessageStartEvent" in names
    assert "TextMessageContentEvent" in names
    assert started is True
    assert msg_id.startswith("msg_run-1_")

    rc_chunk = SimpleNamespace(content="", additional_kwargs={"reasoning_content": "why"})
    think_events, _, _, thinking_started = g._handle_chat_model_stream_content(
        rc_chunk, encoder, "run-2", None, False, True, False
    )
    assert thinking_started is True
    assert "ThinkingTextMessageContentEvent" in think_events


def test_handle_tool_call_chunks_and_start_end_mask_password():
    g = DummyGraph()
    encoder = MagicMock()
    encoder.encode.side_effect = lambda event: type(event).__name__
    chunk = SimpleNamespace(tool_call_chunks=[{"id": "tc1", "name": "ssh_exec"}])
    current = {}
    start_events = g._handle_tool_call_chunks(chunk, encoder, "msg-1", current)
    assert start_events == ["ToolCallStartEvent"]
    assert current["tc1"]["name"] == "ssh_exec"

    current["tc1"]["ended"] = False
    current["tc1"]["tool_started"] = False
    args_events = g._handle_tool_start_event(
        {"name": "ssh_exec", "run_id": "r1"},
        {"input": {"password": "secret", "cmd": "ls"}},
        encoder,
        "msg-1",
        current,
    )
    assert "ToolCallArgsEvent" in args_events
    encoded = [call.args[0] for call in encoder.encode.call_args_list]
    args_event = [e for e in encoded if type(e).__name__ == "ToolCallArgsEvent"][-1]
    assert "***" in args_event.delta
    assert "secret" not in args_event.delta

    end_events = g._handle_tool_end_event(
        {"name": "ssh_exec", "run_id": "r1"},
        {"output": "ok"},
        encoder,
        current,
    )
    assert "ToolCallEndEvent" in end_events
    assert current["tc1"]["ended"] is True


def test_handle_chat_model_end_emits_plain_text_and_tool_calls():
    g = DummyGraph()
    encoder = MagicMock()
    encoder.encode.side_effect = lambda event: type(event).__name__
    empty = g._handle_chat_model_end_event({}, encoder, None, {})
    assert empty == []
    output = SimpleNamespace(content="final answer", tool_calls=[])
    events = g._handle_chat_model_end_event({"output": output}, encoder, None, {}, message_started=False)
    assert events[:3] == ["TextMessageStartEvent", "TextMessageContentEvent", "TextMessageEndEvent"]
    skipped = g._handle_chat_model_end_event({"output": output}, encoder, "msg", {}, message_started=True)
    assert skipped == []
    current = {}
    tool_output = SimpleNamespace(
        content="",
        tool_calls=[{"id": "tc-end", "name": "search", "args": {"q": "host"}}],
    )
    tool_events = g._handle_chat_model_end_event({"output": tool_output}, encoder, "msg", current)
    assert "ToolCallStartEvent" in tool_events
    assert current["tc-end"]["name"] == "search"

    class FullQueue:
        def put_nowait(self, _item):
            raise asyncio.QueueFull()

    encoder = MagicMock()
    encoder.encode.return_value = "evt"
    queue = MagicMock()
    cb = create_browser_step_callback(queue, encoder)
    cb({"step_number": 2, "max_steps": 5, "url": "https://x", "title": "page"})
    queue.put_nowait.assert_called_once_with("evt")
    event = encoder.encode.call_args.args[0]
    assert event.name == "browser_step_progress"
    assert event.value["step_number"] == 2

    dropped = create_browser_step_callback(FullQueue(), encoder)
    dropped({"step_number": 1})
    custom = create_browser_custom_event_callback(queue, encoder)
    custom({"task": "open"})
    event2 = encoder.encode.call_args.args[0]
    assert event2.name == "browser_task_received"


@pytest.mark.asyncio
async def test_merge_async_streams_yields_langgraph_then_stops():
    async def langgraph_stream():
        yield "chunk-1"
        yield "chunk-2"

    event_queue: asyncio.Queue = asyncio.Queue()
    stop_event = asyncio.Event()
    await event_queue.put("browser-evt")
    out = []
    async for item in _merge_async_streams(langgraph_stream(), event_queue, stop_event):
        out.append(item)
    kinds = [kind for kind, _ in out]
    assert "langgraph" in kinds
    assert stop_event.is_set()
    assert ("langgraph", "chunk-1") in out
    assert ("langgraph", "chunk-2") in out
