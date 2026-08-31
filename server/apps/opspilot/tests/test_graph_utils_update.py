"""GraphUtils.update_graph：failed 整表替换 vs 增量差集，删除失败直接返回。"""
from unittest.mock import patch

import pytest

from apps.opspilot.tests.test_graph_utils_service import _graph
from apps.opspilot.utils.graph_utils import GraphUtils

pytestmark = pytest.mark.unit


def test_update_graph_failed_replaces_all_and_deletes_mapped_chunks():
    graph = _graph()
    graph.status = "failed"
    graph.doc_list = [{"id": 2}]
    old = [{"id": 1}]
    docs = [{"page_content": "old", "metadata": {"chunk_id": "c-old"}}]
    with (
        patch.object(GraphUtils, "get_documents", return_value=docs) as getter,
        patch("apps.opspilot.utils.graph_utils.GraphChunkMap.objects") as maps,
        patch.object(GraphUtils, "delete_graph_chunk") as deleter,
        patch.object(GraphUtils, "create_graph", return_value={"result": True, "data": 1}) as creator,
    ):
        maps.filter.return_value.values_list.return_value = [("c-old", "g-1"), ("keep", "g-2")]
        maps.filter.return_value.delete.return_value = (1, {})
        out = GraphUtils.update_graph(graph, old)
    assert out == {"result": True, "data": 1}
    getter.assert_called_once_with(old, "idx")
    deleter.assert_called_once_with(graph, ["g-1"])
    creator.assert_called_once_with(graph, [{"id": 2}])


def test_update_graph_success_uses_diff_and_delete_failure_short_circuits():
    graph = _graph()
    graph.status = "success"
    graph.doc_list = [{"id": 2}, {"id": 3}]
    old = [{"id": 1}, {"id": 2}]
    with (
        patch.object(
            GraphUtils,
            "get_documents",
            return_value=[{"page_content": "x", "metadata": {"chunk_id": "c1"}}],
        ) as getter,
        patch("apps.opspilot.utils.graph_utils.GraphChunkMap.objects") as maps,
        patch.object(GraphUtils, "delete_graph_chunk", side_effect=RuntimeError("neo4j down")),
        patch.object(GraphUtils, "create_graph") as creator,
    ):
        maps.filter.return_value.values_list.return_value = [("c1", "g1")]
        failed = GraphUtils.update_graph(graph, old)
    assert failed == {"result": False, "message": "neo4j down"}
    getter.assert_called_once_with([{"id": 1}], "idx")
    creator.assert_not_called()

    with (
        patch.object(GraphUtils, "get_documents", return_value=[]),
        patch("apps.opspilot.utils.graph_utils.GraphChunkMap.objects") as maps,
        patch.object(GraphUtils, "create_graph", return_value={"result": True}) as creator,
    ):
        maps.filter.return_value.values_list.return_value = []
        ok = GraphUtils.update_graph(graph, old)
    assert ok == {"result": True}
    creator.assert_called_once_with(graph, [{"id": 3}])
