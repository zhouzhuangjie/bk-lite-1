"""工作流任务结果：鉴权、节点过滤与输出格式。"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from rest_framework.exceptions import NotFound, ValidationError

from apps.opspilot.viewsets.workflow_task_result_view import WorkFlowTaskResultViewSet

pytestmark = pytest.mark.unit


def test_authorize_execution_requires_id_and_matches_execution():
    vs = WorkFlowTaskResultViewSet()
    qs = MagicMock()
    qs.filter.return_value.first.return_value = None
    vs.get_queryset = lambda: qs
    with pytest.raises(ValidationError, match="至少提供一个"):
        vs._authorize_execution("", "")
    with pytest.raises(NotFound, match="未找到对应的执行记录"):
        vs._authorize_execution("e1", "")
    with pytest.raises(NotFound, match="未找到对应的执行记录"):
        vs._authorize_execution("", "9")

    task = SimpleNamespace(execution_id="e-ok", id=3)
    qs.filter.return_value.first.return_value = task
    execution_id, found = vs._authorize_execution("e-ok", "3")
    assert execution_id == "e-ok"
    assert found is task
    with pytest.raises(NotFound, match="execution_id 与 id 不匹配"):
        vs._authorize_execution("other", "3")

    empty = SimpleNamespace(execution_id="", id=4)
    qs.filter.return_value.first.return_value = empty
    with pytest.raises(NotFound, match="缺少有效的 execution_id"):
        vs._authorize_execution("", "4")


def test_build_node_filters_and_format_output():
    filt = WorkFlowTaskResultViewSet._build_node_filters("e1", SimpleNamespace(id=8), node_id="n1")
    assert filt.children
    node = SimpleNamespace(
        node_name="llm",
        node_type="agent",
        node_index=2,
        output_data={"a": 1},
        status="ok",
        input_data=None,
        error_message="boom",
    )
    formatted = WorkFlowTaskResultViewSet._format_node_output_data(node)
    assert formatted == {
        "name": "llm",
        "type": "agent",
        "index": 2,
        "output": {"a": 1},
        "status": "ok",
        "input_data": {},
        "error": "boom",
    }
    clean = SimpleNamespace(
        node_name="x",
        node_type="y",
        node_index=0,
        output_data=None,
        status="ok",
        input_data={"q": 1},
        error_message="",
    )
    assert "error" not in WorkFlowTaskResultViewSet._format_node_output_data(clean)
