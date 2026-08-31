"""NodeRunnerMixin 剩余契约：并行分支、自定义执行器包装、变量回填。"""
import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

for _mod_name in ("oracledb", "pyodbc"):
    sys.modules.setdefault(_mod_name, types.ModuleType(_mod_name))
_falkordb = types.ModuleType("falkordb")
_falkordb.Graph = type("Graph", (), {})
sys.modules.setdefault("falkordb", _falkordb)
_falkordb_async = types.ModuleType("falkordb.asyncio")
_falkordb_async.FalkorDB = type("FalkorDB", (), {})
sys.modules.setdefault("falkordb.asyncio", _falkordb_async)

from apps.opspilot.utils.chat_flow_utils.engine.core.base_executor import BaseNodeExecutor  # noqa: E402
from apps.opspilot.utils.chat_flow_utils.engine.core.enums import NodeStatus  # noqa: E402
from apps.opspilot.utils.chat_flow_utils.engine.node_runner import NodeRunnerMixin  # noqa: E402

pytestmark = pytest.mark.unit


class _Runner(NodeRunnerMixin):
    def __init__(self, nodes, executors=None, next_map=None, variables=None, interrupt=False):
        self._nodes = nodes
        self.custom_node_executors = executors or {}
        self._next_map = next_map or {}
        self.variable_manager = MagicMock()
        stored = dict(variables or {})
        self.variable_manager.get_variable.side_effect = lambda key, *a, **k: stored.get(key)
        self.variable_manager.delete_variable.side_effect = lambda key: stored.pop(key, None)
        self.recorded = []
        self.max_parallel_nodes = 4
        self.start_node_id = "start"
        self._interrupt = interrupt

    def _get_node_by_id(self, node_id):
        return self._nodes.get(node_id)

    def _raise_if_interrupted(self, *a, **k):
        return None

    def _check_interrupt_requested(self):
        return self._interrupt

    def _create_node_execution_context(self, node, input_data, status):
        return SimpleNamespace(start_time=0.0, end_time=None, status=status, error_message=None, output_data=None)

    def _update_node_execution_order(self, node_id):
        return None

    def _record_node_execution_result(self, node_id, context):
        self.recorded.append((node_id, context.status))

    def _get_next_nodes(self, node_id, node_result):
        return list(self._next_map.get(node_id, []))


def test_execute_chain_merges_single_and_parallel_next_nodes():
    nodes = {
        "n1": {"id": "n1", "type": "http", "data": {"config": {"inputParams": "last_message", "outputParams": "last_message"}}},
        "n2": {"id": "n2", "type": "http", "data": {"config": {}}},
        "n3": {"id": "n3", "type": "http", "data": {"config": {}}},
        "n4": {"id": "n4", "type": "http", "data": {"config": {}}},
    }

    def _exec(node_id, node_config, input_data):
        return {"last_message": f"out-{node_id}"}

    runner = _Runner(nodes, executors={"http": _exec}, next_map={"n1": ["n2"], "n2": ["n3", "n4"]})
    out = runner._execute_node_chain("n1", {"last_message": "hi"}, remaining_timeout=10)
    assert out["success"] is True
    assert out["current_node"]["node_id"] == "n1"
    n2 = out["next_nodes"]["n2"]
    assert n2["success"] is True
    assert set(n2["next_nodes"]) == {"n3", "n4"}
    assert n2["next_nodes"]["n3"]["success"] is True
    assert n2["next_nodes"]["n4"]["data"]["last_message"] == "out-n4"


def test_parallel_nodes_record_branch_exception():
    runner = _Runner({}, interrupt=False)
    runner.max_parallel_nodes = 2

    def boom(node_id, input_data, visited, timeout):
        if node_id == "bad":
            raise RuntimeError("branch fail")
        return {"success": True, "node_id": node_id}

    with patch.object(runner, "_execute_node_recursive", side_effect=boom):
        out = runner._execute_parallel_nodes(["ok", "bad"], {"last_message": "x"}, remaining_timeout=5)
    assert out["ok"] == {"success": True, "node_id": "ok"}
    assert out["bad"]["success"] is False
    assert out["bad"]["error"] == "branch fail"


def test_parallel_nodes_stop_submitting_when_interrupted():
    runner = _Runner({}, interrupt=True)
    with patch.object(runner, "_execute_node_recursive") as rec:
        out = runner._execute_parallel_nodes(["a", "b"], {}, remaining_timeout=3)
    assert out == {}
    rec.assert_not_called()


def test_single_node_uses_input_fallback_and_custom_output_key():
    nodes = {
        "n1": {
            "id": "n1",
            "type": "http",
            "data": {"config": {"inputParams": "prompt", "outputParams": "answer"}},
        }
    }
    captured = {}

    def _exec(node_id, node_config, input_data):
        captured["input"] = input_data
        return {"answer": "42"}

    runner = _Runner(nodes, executors={"http": _exec})
    result = runner._execute_single_node("n1", {"prompt": "from-input"})
    assert captured["input"] == {"prompt": "from-input"}
    assert result["success"] is True
    runner.variable_manager.set_variable.assert_any_call("answer", "42")
    runner.variable_manager.set_variable.assert_any_call("node_n1_result", {"answer": "42"})


def test_single_node_missing_executor_is_failed():
    nodes = {"n1": {"id": "n1", "type": "ghost", "data": {"config": {}}}}
    runner = _Runner(nodes)
    result = runner._execute_single_node("n1", {})
    assert result["success"] is False
    assert result["error"] == "找不到节点类型 ghost 的执行器"
    assert runner.recorded[-1] == ("n1", NodeStatus.FAILED)


def test_get_node_executor_wraps_callable_and_uses_registry():
    runner = _Runner({})
    runner.custom_node_executors = {"fn": lambda node_id, node, data: {"ok": node_id}}
    wrapped = runner._get_node_executor("fn")
    assert wrapped.execute("n1", {}, {}) == {"ok": "n1"}

    class Ready(BaseNodeExecutor):
        def execute(self, node_id, node_config, input_data):
            return "ready"

    runner.custom_node_executors = {"ready": Ready(runner.variable_manager)}
    assert runner._get_node_executor("ready") is runner.custom_node_executors["ready"]

    class Branch:
        def __init__(self, variable_manager, start_node_id):
            self.start_node_id = start_node_id

    class Plain:
        def __init__(self, variable_manager):
            self.variable_manager = variable_manager

    with patch(
        "apps.opspilot.utils.chat_flow_utils.engine.node_runner.node_registry.get_executor",
        side_effect=lambda node_type: {"condition": Branch, "http": Plain, "unknown": None}[node_type],
    ):
        branch = runner._get_node_executor("condition")
        assert isinstance(branch, Branch)
        assert branch.start_node_id == "start"
        plain = runner._get_node_executor("http")
        assert isinstance(plain, Plain)
        assert runner._get_node_executor("unknown") is None
