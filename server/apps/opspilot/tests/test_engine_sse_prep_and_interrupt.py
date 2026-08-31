"""ChatFlowEngine：流程校验失败、中断契约、SSE 准备与 agents 输入。"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from django.http import StreamingHttpResponse

from apps.opspilot.utils.chat_flow_utils.engine.core.enums import NodeStatus
from apps.opspilot.utils.chat_flow_utils.engine.core.models import NodeExecutionContext
from apps.opspilot.utils.chat_flow_utils.engine.engine import ChatFlowEngine

pytestmark = pytest.mark.unit


def _engine(nodes, edges=None, start_node_id=None, entry_type=None):
    instance = SimpleNamespace(
        id=11,
        bot_id=7,
        flow_json={"nodes": nodes, "edges": edges or []},
    )
    return ChatFlowEngine(instance, start_node_id=start_node_id, entry_type=entry_type, execution_id="exec-sse")


def test_validate_flow_and_execute_reject_empty_graph():
    engine = _engine([])
    assert engine.validate_flow() == ["流程中没有节点"]
    out = engine.execute({"last_message": "hi"})
    assert out["success"] is False
    assert "流程中没有节点" in out["error"]
    assert out["execution_time"] == 0


def test_validate_flow_reports_missing_entry_and_unsupported_type():
    cycled = _engine(
        [{"id": "a", "type": "not-a-real-type", "data": {}}, {"id": "b", "type": "also-fake", "data": {}}],
        edges=[{"source": "a", "target": "b"}, {"source": "b", "target": "a"}],
    )
    errors = cycled.validate_flow()
    assert "流程中没有入口节点" in errors
    assert "流程存在循环依赖" in errors
    assert any("不支持的节点类型: not-a-real-type" in item for item in errors)
    assert any("不支持的节点类型: also-fake" in item for item in errors)


def test_interrupt_result_and_execute_type_from_entry():
    engine = _engine([], entry_type="web_chat")
    interrupted = engine._interrupt_result()
    assert interrupted == {
        "success": False,
        "interrupted": True,
        "error": "执行已中断",
        "execution_id": "exec-sse",
    }
    assert engine._get_execute_type() == "web_chat"
    engine.entry_type = None
    assert engine._get_execute_type("dingtalk") == "dingtalk"
    engine.entry_type = "not-a-type"
    assert engine._get_execute_type("dingtalk") == "openai"


def test_summarize_execution_contexts_keeps_keys_not_secrets():
    engine = _engine([])
    ctx = NodeExecutionContext(node_id="n1")
    ctx.status = NodeStatus.FAILED
    ctx.error_message = "boom"
    ctx.input_data = {"prompt": "secret-token"}
    ctx.output_data = {"answer": "leaked"}
    engine.execution_contexts = {"n1": ctx}
    summary = engine._summarize_execution_contexts()
    assert summary["n1"]["input_keys"] == ["prompt"]
    assert summary["n1"]["output_keys"] == ["answer"]
    assert "secret-token" not in str(summary)
    assert "leaked" not in str(summary)
    assert summary["n1"]["error_message"] == "boom"


def test_build_agent_input_uses_intent_previous_output_then_clears_it():
    engine = _engine([])
    engine.variable_manager.set_variable("intent_previous_output", "from-intent")
    agent = {"id": "a1", "data": {"config": {"inputParams": "last_message"}}}
    out = engine._build_agent_input_data(agent, {"last_message": "orig", "user_id": "u1"})
    assert out["last_message"] == "from-intent"
    assert out["user_id"] == "u1"
    assert engine.variable_manager.get_variable("intent_previous_output") is None

    engine.variable_manager.set_variable("last_message", "from-var")
    fallback = engine._build_agent_input_data(agent, {"last_message": "orig", "session_id": "s"})
    assert fallback["last_message"] == "from-var"
    assert fallback["session_id"] == "s"


def test_find_target_agent_node_uses_last_node_when_not_streaming_protocol():
    nodes = [
        {"id": "n1", "type": "openai", "data": {"label": "入口"}},
        {"id": "n2", "type": "agents", "data": {"label": "智能体"}},
    ]
    engine = _engine(nodes)
    target, before = engine._find_target_agent_node(nodes[0], nodes[1], False, False)
    assert target["id"] == "n2"
    assert [n["id"] for n in before] == ["n1"]


def test_prepare_sse_execution_returns_error_when_flow_invalid():
    engine = _engine([])
    with patch.object(ChatFlowEngine, "_record_conversation_history"):
        result = engine._prepare_sse_execution({"user_id": "u", "last_message": "hi", "entry_type": "openai"})
    start_node, last_node, user_id, entry_type, session_id, node_id, is_agui, is_openai, error = result
    assert start_node is None
    assert last_node is None
    assert user_id == "u"
    assert entry_type == "openai"
    assert isinstance(error, StreamingHttpResponse)


def test_resolve_sse_execute_method_requires_streaming_executor():
    engine = _engine([{"id": "a", "type": "agents", "data": {}}])
    agent = {"id": "a", "type": "agents"}
    dummy = object()
    with (
        patch.object(engine, "_get_node_executor", return_value=dummy),
        patch.object(engine, "_record_execution_result") as record,
        patch.object(engine, "_create_error_response", return_value="err-resp"),
    ):
        method, error = engine._resolve_sse_execute_method({"last_message": "hi"}, agent, agent, True)
    assert method is None
    assert error == "err-resp"
    record.assert_called_once()
    assert record.call_args.args[1]["error"] == "agents节点不支持流式执行"

    sse_executor = SimpleNamespace(sse_execute=MagicMock(name="sse"))
    with patch.object(engine, "_get_node_executor", return_value=sse_executor):
        method, error = engine._resolve_sse_execute_method({}, agent, agent, False)
    assert method is sse_executor.sse_execute
    assert error is None


def test_raise_if_interrupted_noop_then_finalize_and_raise():
    engine = _engine([{"id": "n1", "type": "openai", "data": {}}])
    with patch.object(engine, "_check_interrupt_requested", return_value=False):
        assert engine._raise_if_interrupted({"last_message": "hi"}, "openai") is None
    with (
        patch.object(engine, "_check_interrupt_requested", return_value=True),
        patch.object(engine, "_finalize_interrupted_execution") as finalize,
        pytest.raises(InterruptedError, match="执行已中断"),
    ):
        engine._raise_if_interrupted({"last_message": "hi"}, "openai")
    finalize.assert_called_once()
    assert finalize.call_args.args[0] == {"last_message": "hi"}
    assert finalize.call_args.args[1]["interrupted"] is True
    assert finalize.call_args.args[2] == "openai"


def test_prepare_sse_execution_rejects_non_streaming_flow():
    engine = _engine([{"id": "n1", "type": "http", "data": {"label": "请求"}}])
    engine.validate_flow = lambda: []
    with (
        patch.object(engine, "_record_conversation_history"),
        patch.object(engine, "_ensure_execution_result_started"),
        patch.object(engine, "_raise_if_interrupted"),
        patch.object(engine, "_record_execution_result") as record,
        patch.object(engine, "_create_error_response", return_value="sse-unsupported"),
    ):
        result = engine._prepare_sse_execution({"user_id": "u1", "last_message": "hi", "entry_type": "restful", "node_id": "n1"})
    start_node, last_node, user_id, entry_type, session_id, node_id, is_agui, is_openai, error = result
    assert start_node is None
    assert last_node is None
    assert user_id == "u1"
    assert entry_type == "restful"
    assert session_id == ""
    assert node_id == "n1"
    assert is_agui is False
    assert is_openai is False
    assert error == "sse-unsupported"
    record.assert_called_once()
    assert record.call_args.args[1] == {"success": False, "error": "当前流程不支持SSE"}
    assert record.call_args.args[2] is False


def test_resolve_sse_target_agent_intent_routing_failure():
    nodes = [
        {"id": "s", "type": "openai", "data": {}},
        {"id": "i", "type": "intent_classification", "data": {}},
        {"id": "a", "type": "agents", "data": {}},
    ]
    engine = _engine(nodes)
    intent_node = nodes[1]
    with (
        patch.object(engine, "_find_target_agent_node", return_value=(None, [intent_node])),
        patch.object(engine, "set_start_node_variable", side_effect=lambda data, _node: data),
        patch.object(engine, "_execute_prerequisite_nodes", return_value={"intent_result": "billing", "last_message": "hi"}),
        patch.object(engine, "_find_agent_by_intent", return_value=None) as find_agent,
        patch.object(engine, "_record_execution_result") as record,
        patch.object(engine, "_create_error_response", return_value="no-agent"),
    ):
        agent, final_input, error = engine._resolve_sse_target_agent(
            {"last_message": "hi"}, nodes[0], nodes[2], False, True
        )
    assert agent is None
    assert error == "no-agent"
    assert final_input["intent_result"] == "billing"
    find_agent.assert_called_once_with("i", "billing")
    record.assert_called_once()
    assert record.call_args.args[1]["error"] == "未找到可执行的agents节点（意图路由失败）"
    assert record.call_args.args[2] is False


def _collect_sse(resp):
    import asyncio

    async def _run():
        chunks = []
        async for part in resp.streaming_content:
            chunks.append(part.decode() if isinstance(part, bytes) else part)
        return "".join(chunks)

    return asyncio.run(_run())


def _sse_engine_ready():
    agent = {
        "id": "a1",
        "type": "agents",
        "data": {"label": "智能体", "config": {"inputParams": "last_message", "outputParams": "last_message"}},
    }
    start = {"id": "s1", "type": "openai", "data": {"config": {}}}
    engine = _engine([start, agent], start_node_id="s1", entry_type="openai")
    return engine, start, agent


def test_sse_execute_generate_stream_accumulates_json_skips_invalid_and_saves_browser_steps():
    engine, start, agent = _sse_engine_ready()

    def execute_method(_node_id, _node, _input):
        async def gen():
            yield 'data: {"type": "TEXT_MESSAGE_CONTENT", "delta": "hello"}\n\n'
            yield "data: {not-json\n\n"
            yield "plain-chunk\n"
            yield (
                'data: {"type": "CUSTOM", "name": "browser_step_progress", '
                '"value": {"step_number": 1, "next_goal": "打开页面", "evaluation": "完成"}}\n\n'
            )
            yield 'data: {"choices": [{"delta": {"content": " world"}}], "object": "chat.completion.chunk"}\n\n'

        return gen()

    recorded = {}

    async def capture_result(_input, result, success, _entry):
        recorded["result"] = result
        recorded["success"] = success

    with (
        patch.object(
            engine,
            "_prepare_sse_execution",
            return_value=(start, agent, "u1", "openai", "sess", "s1", False, True, None),
        ),
        patch.object(engine, "_resolve_sse_target_agent", return_value=(agent, {"last_message": "hi", "user_id": "u1"}, None)),
        patch.object(engine, "_resolve_sse_execute_method", return_value=(execute_method, None)),
        patch.object(engine, "_record_node_execution_result_async", new=AsyncMock()),
        patch.object(engine, "_record_execution_result_async", side_effect=capture_result),
        patch.object(engine, "_record_conversation_history_async", new=AsyncMock()),
        patch.object(engine, "_execute_subsequent_nodes_async", new=AsyncMock()) as subsequent,
        patch.object(engine, "_check_interrupt_requested_async", new=AsyncMock(return_value=False)),
        patch.object(engine, "_get_next_nodes", return_value=[]),
    ):
        resp = engine.sse_execute({"last_message": "hi"})
        assert isinstance(resp, StreamingHttpResponse)
        text = _collect_sse(resp)

    assert "hello" in text
    assert "plain-chunk" in text
    assert recorded["success"] is True
    assert recorded["result"] == "hello world"
    ctx = engine.execution_contexts["a1"]
    assert ctx.status == NodeStatus.COMPLETED
    assert ctx.output_data["last_message"] == "hello world"
    assert ctx.output_data["browser_steps"] == ["步骤1 打开页面", "最终结果: 完成"]
    subsequent.assert_awaited_once()


def test_sse_execute_generate_stream_interrupts_mid_chunk():
    engine, start, agent = _sse_engine_ready()

    def execute_method(_node_id, _node, _input):
        async def gen():
            yield 'data: {"type": "TEXT_MESSAGE_CONTENT", "delta": "first"}\n\n'
            yield 'data: {"type": "TEXT_MESSAGE_CONTENT", "delta": "second"}\n\n'

        return gen()

    checks = {"n": 0}

    async def interrupt_after_first():
        checks["n"] += 1
        return checks["n"] >= 2

    recorded = {}

    async def capture_result(_input, result, success, _entry):
        recorded["result"] = result
        recorded["success"] = success

    with (
        patch.object(
            engine,
            "_prepare_sse_execution",
            return_value=(start, agent, "u1", "openai", "sess", "s1", False, True, None),
        ),
        patch.object(engine, "_resolve_sse_target_agent", return_value=(agent, {"last_message": "hi"}, None)),
        patch.object(engine, "_resolve_sse_execute_method", return_value=(execute_method, None)),
        patch.object(engine, "_record_node_execution_result_async", new=AsyncMock()),
        patch.object(engine, "_record_execution_result_async", side_effect=capture_result),
        patch.object(engine, "_record_conversation_history_async", new=AsyncMock()),
        patch.object(engine, "_execute_subsequent_nodes_async", new=AsyncMock()),
        patch.object(engine, "_check_interrupt_requested_async", side_effect=interrupt_after_first),
        patch.object(engine, "_get_next_nodes", return_value=[]),
    ):
        text = _collect_sse(engine.sse_execute({"last_message": "hi"}))

    assert "INTERRUPTED" in text
    assert "second" not in text
    assert recorded["success"] is False
    assert recorded["result"]["interrupted"] is True


def test_sse_execute_generate_stream_interrupt_after_complete_skips_success_record():
    engine, start, agent = _sse_engine_ready()

    def execute_method(_node_id, _node, _input):
        async def gen():
            yield 'data: {"type": "TEXT_MESSAGE_CONTENT", "delta": "done"}\n\n'

        return gen()

    checks = {"n": 0}

    async def interrupt_after_stream():
        checks["n"] += 1
        return checks["n"] > 1

    recorded = []

    async def capture_result(_input, result, success, _entry):
        recorded.append((result, success))

    with (
        patch.object(
            engine,
            "_prepare_sse_execution",
            return_value=(start, agent, "u1", "openai", "sess", "s1", False, True, None),
        ),
        patch.object(engine, "_resolve_sse_target_agent", return_value=(agent, {"last_message": "hi"}, None)),
        patch.object(engine, "_resolve_sse_execute_method", return_value=(execute_method, None)),
        patch.object(engine, "_record_node_execution_result_async", new=AsyncMock()),
        patch.object(engine, "_record_execution_result_async", side_effect=capture_result),
        patch.object(engine, "_record_conversation_history_async", new=AsyncMock()),
        patch.object(engine, "_execute_subsequent_nodes_async", new=AsyncMock()),
        patch.object(engine, "_check_interrupt_requested_async", side_effect=interrupt_after_stream),
        patch.object(engine, "_get_next_nodes", return_value=["n2"]),
    ):
        text = _collect_sse(engine.sse_execute({"last_message": "hi"}))

    assert "done" in text
    assert recorded
    assert recorded[0][1] is False
    assert recorded[0][0]["interrupted"] is True


def test_sse_execute_generate_stream_yields_error_on_exception():
    engine, start, agent = _sse_engine_ready()

    def execute_method(_node_id, _node, _input):
        async def gen():
            yield 'data: {"type": "TEXT_MESSAGE_CONTENT", "delta": "partial"}\n\n'
            raise RuntimeError("stream boom")

        return gen()

    recorded = {}

    async def capture_result(_input, result, success, _entry):
        recorded["result"] = result
        recorded["success"] = success

    with (
        patch.object(
            engine,
            "_prepare_sse_execution",
            return_value=(start, agent, "u1", "openai", "sess", "s1", False, True, None),
        ),
        patch.object(engine, "_resolve_sse_target_agent", return_value=(agent, {"last_message": "hi"}, None)),
        patch.object(engine, "_resolve_sse_execute_method", return_value=(execute_method, None)),
        patch.object(engine, "_record_node_execution_result_async", new=AsyncMock()),
        patch.object(engine, "_record_execution_result_async", side_effect=capture_result),
        patch.object(engine, "_record_conversation_history_async", new=AsyncMock()),
        patch.object(engine, "_execute_subsequent_nodes_async", new=AsyncMock()),
        patch.object(engine, "_check_interrupt_requested_async", new=AsyncMock(return_value=False)),
        patch.object(engine, "_get_next_nodes", return_value=[]),
    ):
        text = _collect_sse(engine.sse_execute({"last_message": "hi"}))

    assert "ERROR" in text
    assert "stream boom" in text
    assert recorded["success"] is False
    assert recorded["result"]["error"] == "stream boom"
    assert engine.execution_contexts["a1"].status == NodeStatus.FAILED
    assert engine.execution_contexts["a1"].error_message == "stream boom"


def test_sse_execute_returns_prep_error_without_opening_stream():
    engine, start, agent = _sse_engine_ready()
    with (
        patch.object(engine, "_prepare_sse_execution", return_value=(None, None, "u", "openai", "", "s1", False, True, "prep-err")),
        patch.object(engine, "_resolve_sse_target_agent") as resolve,
    ):
        assert engine.sse_execute({"last_message": "hi"}) == "prep-err"
    resolve.assert_not_called()


def test_sse_execute_returns_target_error_without_opening_stream():
    engine, start, agent = _sse_engine_ready()
    with (
        patch.object(
            engine,
            "_prepare_sse_execution",
            return_value=(start, agent, "u", "openai", "", "s1", False, True, None),
        ),
        patch.object(engine, "_resolve_sse_target_agent", return_value=(None, {}, "target-err")),
        patch.object(engine, "_resolve_sse_execute_method") as resolve_method,
    ):
        assert engine.sse_execute({"last_message": "hi"}) == "target-err"
    resolve_method.assert_not_called()

