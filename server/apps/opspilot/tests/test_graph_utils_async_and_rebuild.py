"""GraphUtils._run_async 与 rebuild_graph_community 成功/失败契约。"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from apps.opspilot.utils.graph_utils import GraphUtils

pytestmark = pytest.mark.unit


def _graph():
    return SimpleNamespace(
        id=8,
        llm_model=SimpleNamespace(openai_api_key="k", model_name="gpt", openai_api_base="http://llm"),
        rerank_model=SimpleNamespace(base_url="http://rerank", model_name="r", api_key="rk"),
        embed_model=SimpleNamespace(base_url="http://embed", model_name="e", api_key="ek"),
    )


def test_run_async_executes_coroutine_in_worker_thread():
    async def _ok():
        return 42

    assert GraphUtils._run_async(_ok()) == 42


def test_rebuild_graph_community_success_and_exception():
    graph = _graph()
    with patch.object(GraphUtils, "_run_async", return_value=True) as run_async, patch(
        "apps.opspilot.utils.graph_utils.GraphitiRAG"
    ) as rag_cls:
        rag = MagicMock()
        rag_cls.return_value = rag
        assert GraphUtils.rebuild_graph_community(graph) == {"result": True}
    rag.rebuild_community.assert_called_once()
    req = rag.rebuild_community.call_args.args[0]
    assert req.group_ids == ["graph-8"]
    assert req.openai_model == "gpt"
    assert run_async.call_args.args[0] is rag.rebuild_community.return_value

    with patch.object(GraphUtils, "_run_async", side_effect=RuntimeError("neo4j down")), patch(
        "apps.opspilot.utils.graph_utils.GraphitiRAG"
    ):
        assert GraphUtils.rebuild_graph_community(graph) == {"result": False}

    with patch.object(GraphUtils, "_run_async", side_effect=RuntimeError("list down")), patch(
        "apps.opspilot.utils.graph_utils.GraphitiRAG"
    ):
        listed = GraphUtils.get_graph(8)
    assert listed["result"] is False
    assert listed["message"] == "list down"
