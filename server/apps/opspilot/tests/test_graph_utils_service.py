"""GraphUtils：图谱搜索/获取/删除/分块删除的成功与失败契约。"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from apps.opspilot.utils.graph_utils import GraphUtils

pytestmark = pytest.mark.unit


def _graph(graph_id=9):
    llm = SimpleNamespace(openai_api_key="k", model_name="gpt", openai_api_base="http://llm")
    rerank = SimpleNamespace(base_url="http://rerank", model_name="r", api_key="rk")
    embed = SimpleNamespace(base_url="http://embed", model_name="e", api_key="ek")
    kb = SimpleNamespace(knowledge_index_name=lambda: "idx", name="kb", id=1)
    return SimpleNamespace(
        id=graph_id,
        llm_model=llm,
        rerank_model=rerank,
        embed_model=embed,
        knowledge_base=kb,
        knowledge_base_id=1,
        created_by="u",
        domain="domain.com",
        rebuild_community=False,
        doc_list=[{"id": 1}],
        status="success",
    )


def test_search_graph_returns_data_and_none_failure():
    graph = _graph()
    with patch.object(GraphUtils, "_run_async", return_value=[{"fact": "x"}]), patch(
        "apps.opspilot.utils.graph_utils.GraphitiRAG"
    ):
        ok = GraphUtils.search_graph(graph, size=3, search_query="cpu")
    assert ok == {"result": True, "data": [{"fact": "x"}]}

    with patch.object(GraphUtils, "_run_async", return_value=None), patch("apps.opspilot.utils.graph_utils.GraphitiRAG"):
        missing = GraphUtils.search_graph(graph)
    assert missing["result"] is False
    assert "message" in missing

    with patch.object(GraphUtils, "_run_async", side_effect=RuntimeError("down")), patch(
        "apps.opspilot.utils.graph_utils.GraphitiRAG"
    ):
        err = GraphUtils.search_graph(graph)
    assert err["result"] is False
    assert "down" in err["message"]


def test_get_graph_and_delete_paths():
    graph = _graph(12)
    with patch.object(GraphUtils, "_run_async", return_value=[{"id": "n1"}]), patch(
        "apps.opspilot.utils.graph_utils.GraphitiRAG"
    ):
        listed = GraphUtils.get_graph(12)
    assert listed == {"result": True, "data": [{"id": "n1"}]}

    with patch.object(GraphUtils, "_run_async", return_value=None), patch("apps.opspilot.utils.graph_utils.GraphitiRAG"):
        empty = GraphUtils.get_graph(12)
    assert empty["result"] is False

    with patch.object(GraphUtils, "_run_async", return_value=True) as run_async, patch("apps.opspilot.utils.graph_utils.GraphitiRAG") as rag_cls:
        rag = MagicMock()
        rag_cls.return_value = rag
        assert GraphUtils.delete_graph(graph) is None
        rag.delete_index.assert_called_once()
        index_req = rag.delete_index.call_args.args[0]
        assert index_req.group_id == "graph-12"
        assert run_async.call_args_list[0].args[0] is rag.delete_index.return_value

        assert GraphUtils.delete_graph_chunk(graph, ["c1", "c2"]) is None
        rag.delete_document.assert_called_once()
        doc_req = rag.delete_document.call_args.args[0]
        assert doc_req.group_id == "graph-12"
        assert list(doc_req.uuids) == ["c1", "c2"]
        assert run_async.call_args_list[1].args[0] is rag.delete_document.return_value
        assert run_async.call_count == 2

    with patch.object(GraphUtils, "_run_async", side_effect=RuntimeError("boom")), patch(
        "apps.opspilot.utils.graph_utils.GraphitiRAG"
    ):
        with pytest.raises(Exception, match="Failed to Delete graph"):
            GraphUtils.delete_graph(graph)
        with pytest.raises(Exception, match="Failed to Delete graph chunk"):
            GraphUtils.delete_graph_chunk(graph, ["c1"])


def test_get_documents_flattens_es_chunks():
    docs = {
        "documents": [
            {"page_content": "a", "metadata": {"chunk_id": "1"}},
            {"page_content": "b", "metadata": {"chunk_id": "2"}},
        ]
    }
    with patch.object(GraphUtils, "get_document_es_chunk", return_value=docs) as getter:
        out = GraphUtils.get_documents([{"id": 11}, {"id": 12}], "idx")
    assert [d["page_content"] for d in out] == ["a", "b", "a", "b"]
    assert getter.call_count == 2


def test_callback_swallows_progress_errors():
    with patch("apps.opspilot.tasks.update_graph_task", side_effect=RuntimeError("ignore")) as update:
        result = GraphUtils.callback(1, 10, 99)
    assert result is None
    update.assert_called_once_with(1, 10, 99)


def test_create_graph_success_and_missing_mapping():
    graph = _graph()
    task = SimpleNamespace(id=77)
    with (
        patch.object(GraphUtils, "get_documents", return_value=[{"page_content": "c", "metadata": {"chunk_id": "x"}}]),
        patch("apps.opspilot.utils.graph_utils.KnowledgeTask.objects") as tasks,
        patch("apps.opspilot.utils.graph_utils.GraphChunkMap.objects") as maps,
        patch("apps.opspilot.utils.graph_utils.GraphitiRAG") as rag_cls,
        patch.object(GraphUtils, "_run_async", return_value={"mapping": {"x": "g1"}, "success_count": 1, "failed_count": 0, "total_count": 1}),
    ):
        tasks.create.return_value = task
        tasks.filter.return_value.delete.return_value = None
        maps.bulk_create.return_value = None
        rag_cls.return_value = MagicMock()
        ok = GraphUtils.create_graph(graph)
    assert ok == {"result": True}
    maps.bulk_create.assert_called_once()
    tasks.filter.assert_called()

    with (
        patch.object(GraphUtils, "get_documents", return_value=[]),
        patch("apps.opspilot.utils.graph_utils.KnowledgeTask.objects") as tasks,
        patch("apps.opspilot.utils.graph_utils.GraphitiRAG"),
        patch.object(GraphUtils, "_run_async", return_value={}),
    ):
        tasks.create.return_value = task
        tasks.filter.return_value.delete.return_value = None
        failed = GraphUtils.create_graph(graph)
    assert failed["result"] is False
    assert "message" in failed
