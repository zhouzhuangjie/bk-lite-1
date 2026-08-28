"""ChatFlowEngine：入口类型回退、起始节点选择、执行摘要统计。"""
from types import SimpleNamespace

import pytest

from apps.opspilot.utils.chat_flow_utils.engine.core.enums import NodeStatus
from apps.opspilot.utils.chat_flow_utils.engine.core.models import NodeExecutionContext
from apps.opspilot.utils.chat_flow_utils.engine.engine import ChatFlowEngine

pytestmark = pytest.mark.unit


def _engine(nodes, start_node_id=None):
    instance = SimpleNamespace(id=1, flow_json={"nodes": nodes, "edges": []})
    return ChatFlowEngine(instance, start_node_id=start_node_id, execution_id="exec-test")


def test_get_start_node_and_entry_type_fallback():
    engine = _engine(
        [
            {"id": "n1", "type": "openai", "data": {"label": "入口"}},
            {"id": "n2", "type": "agents", "data": {"label": "智能体"}},
        ],
        start_node_id="n2",
    )
    assert engine._get_start_node()["id"] == "n2"
    assert engine._determine_entry_type(None) == "restful"
    assert engine._determine_entry_type({"type": "web_chat"}) == "web_chat"
    assert engine._determine_entry_type({"type": "unknown"}) == "restful"

    empty = _engine([])
    assert empty._get_start_node() is None


def test_build_execution_summary_counts_failed_and_final_node():
    engine = _engine(
        [
            {"id": "a", "type": "openai", "data": {"label": "A"}},
            {"id": "b", "type": "agents", "data": {"label": "B"}},
        ]
    )
    ctx_ok = NodeExecutionContext(node_id="a")
    ctx_ok.status = NodeStatus.COMPLETED
    ctx_ok.node_index = 1
    ctx_fail = NodeExecutionContext(node_id="b")
    ctx_fail.status = NodeStatus.FAILED
    ctx_fail.node_index = 2
    ctx_fail.error_message = "timeout"
    engine.execution_contexts = {"a": ctx_ok, "b": ctx_fail}
    engine.variable_manager.set_variable("node_a_index", 1)
    engine.variable_manager.set_variable("node_b_index", 2)
    engine.variable_manager.set_variable("node_b_name", "B")
    summary = engine._build_execution_output_data()["summary"]
    assert summary["completed_nodes"] == 1
    assert summary["failed_nodes"] == 1
    assert summary["failed_node"]["error"] == "timeout"
    assert summary["final_node"]["node_id"] == "b"
