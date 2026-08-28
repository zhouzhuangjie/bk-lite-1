"""ChatFlowEngine：流程校验失败、中断契约、SSE 准备与 agents 输入。"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

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
