"""GraphitiRAG：配置提取、索引清空、文档摄取/搜索（驱动与 Graphiti 为外部边界）。

对照契约：缺 group_ids 拒绝搜索；空图谱跳过社区构建；摄取失败不中断后续文档；
搜索结果拼 source/target 节点信息。
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.documents import Document

from apps.opspilot.metis.llm.rag.graph_rag.graphiti.graphiti_rag import GraphitiRAG
from apps.opspilot.metis.llm.rag.graph_rag_entity import (
    DocumentDeleteRequest,
    DocumentIngestRequest,
    DocumentRetrieverRequest,
    IndexDeleteRequest,
    RebuildCommunityRequest,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def rag(monkeypatch):
    monkeypatch.setattr(
        "apps.opspilot.metis.llm.rag.graph_rag.graphiti.graphiti_rag.apply_openai_client_patch",
        lambda: None,
    )
    instance = GraphitiRAG()
    monkeypatch.setattr(instance, "_safe_close_driver", AsyncMock())
    return instance


def test_extract_configs_from_request_optional_fields(rag):
    empty = DocumentRetrieverRequest(search_query="q")
    assert rag._extract_configs_from_request(empty) == (None, None, None)

    req = DocumentIngestRequest(
        openai_api_key="k",
        openai_api_base="http://llm",
        openai_model="gpt",
        embed_model_base_url="http://embed",
        embed_model_name="e",
        embed_model_api_key="ek",
        rerank_model_base_url="http://rerank",
        rerank_model_name="r",
        rerank_model_api_key="rk",
        group_id="g1",
        docs=[],
    )
    llm, embed, rerank = rag._extract_configs_from_request(req)
    assert llm == {"api_key": "k", "base_url": "http://llm", "model": "gpt"}
    assert embed == {"url": "http://embed", "model_name": "e", "api_key": "ek"}
    assert rerank == {"url": "http://rerank", "model_name": "r", "api_key": "rk"}


def test_build_search_result_doc_fills_missing_nodes(rag):
    item = SimpleNamespace(
        fact="depends_on",
        name="rel",
        group_id="g1",
        source_node_uuid="s1",
        target_node_uuid="t-missing",
    )
    doc = rag._build_search_result_doc(item, {"s1": {"name": "svc-a", "summary": "前端", "labels": ["Service"]}})
    assert doc["fact"] == "depends_on"
    assert doc["source_node"]["name"] == "svc-a"
    assert doc["target_node"]["uuid"] == "t-missing"
    assert doc["target_node"]["name"] == ""


def _fake_graphiti(execute_query_side_effect=None, **extra):
    driver = SimpleNamespace(execute_query=AsyncMock(side_effect=execute_query_side_effect or []))
    graphiti = SimpleNamespace(driver=driver, **extra)
    return graphiti


@pytest.mark.asyncio
async def test_delete_index_swallows_missing_graph(rag):
    graphiti = _fake_graphiti(execute_query_side_effect=RuntimeError("graph gone"))
    with (
        patch("apps.opspilot.metis.llm.rag.graph_rag.graphiti.graphiti_rag.FalkorDriver"),
        patch("apps.opspilot.metis.llm.rag.graph_rag.graphiti.graphiti_rag.Graphiti", return_value=graphiti),
    ):
        await rag.delete_index(IndexDeleteRequest(group_id="kb-1"))
    graphiti.driver.execute_query.assert_awaited()
    rag._safe_close_driver.assert_awaited()


@pytest.mark.asyncio
async def test_list_index_document_requires_group_and_maps_records(rag):
    with pytest.raises(ValueError, match="group_ids"):
        await rag.list_index_document(DocumentRetrieverRequest(search_query="x", group_ids=[]))

    nodes = [{"name": "n1", "uuid": "u1", "fact": None, "summary": "s", "node_id": 1, "group_id": None, "labels": ["Entity"]}]
    edges = [
        {
            "relation_type": "USES",
            "source_uuid": "u1",
            "target_uuid": "u2",
            "source_name": "n1",
            "target_name": "n2",
            "fact": "uses",
            "source_id": 1,
            "target_id": 2,
        }
    ]
    graphiti = _fake_graphiti(execute_query_side_effect=[(nodes, None, None), (edges, None, None)])
    with (
        patch("apps.opspilot.metis.llm.rag.graph_rag.graphiti.graphiti_rag.FalkorDriver"),
        patch("apps.opspilot.metis.llm.rag.graph_rag.graphiti.graphiti_rag.Graphiti", return_value=graphiti),
    ):
        result = await rag.list_index_document(DocumentRetrieverRequest(search_query="x", group_ids=["kb-1"]))
    assert result["nodes"][0]["group_id"] == "kb-1"
    assert result["edges"][0]["relation_type"] == "USES"


@pytest.mark.asyncio
async def test_delete_document_and_setup_graph_close_driver(rag):
    graphiti = _fake_graphiti()
    graphiti.remove_episode = AsyncMock()
    graphiti.build_indices_and_constraints = AsyncMock()
    with (
        patch("apps.opspilot.metis.llm.rag.graph_rag.graphiti.graphiti_rag.FalkorDriver"),
        patch("apps.opspilot.metis.llm.rag.graph_rag.graphiti.graphiti_rag.Graphiti", return_value=graphiti),
    ):
        await rag.delete_document(DocumentDeleteRequest(group_id="kb-1", uuids=["e1", "e2"]))
        await rag.setup_graph("kb-1")
    assert graphiti.remove_episode.await_count == 2
    graphiti.build_indices_and_constraints.assert_awaited_once()


@pytest.mark.asyncio
async def test_build_communities_skips_empty_graph(rag):
    graphiti = _fake_graphiti(
        execute_query_side_effect=[
            ([{"count": 0}], None, None),
            ([{"count": 0}], None, None),
        ]
    )
    graphiti.build_communities = AsyncMock()
    await rag.build_communities(graphiti, "kb-1")
    graphiti.build_communities.assert_not_awaited()


@pytest.mark.asyncio
async def test_ingest_continues_after_one_failure_and_reports_counts(rag):
    ok_episode = SimpleNamespace(episode=SimpleNamespace(uuid="ep-ok"))
    graphiti = SimpleNamespace(
        add_episode=AsyncMock(side_effect=[ok_episode, RuntimeError("embed down")]),
        driver=SimpleNamespace(execute_query=AsyncMock()),
    )
    rag._create_full_graphiti = MagicMock(return_value=graphiti)
    docs = [
        Document(page_content="a", metadata={"knowledge_title": "t", "knowledge_id": 1, "chunk_id": "c1"}),
        Document(page_content="b", metadata={"knowledge_title": "t", "knowledge_id": 1, "chunk_id": "c2"}),
    ]
    progress = []

    result = await rag.ingest(
        DocumentIngestRequest(group_id="kb-1", docs=docs, rebuild_community=False),
        callback=lambda cur, total, task: progress.append((cur, total, task)),
        task_id="task-1",
    )
    assert result["success_count"] == 1
    assert result["failed_count"] == 1
    assert result["mapping"] == {"c1": "ep-ok"}
    assert progress[-1] == (2, 2, "task-1")


@pytest.mark.asyncio
async def test_search_requires_group_and_builds_documents(rag):
    with pytest.raises(ValueError, match="group_ids"):
        await rag.search(DocumentRetrieverRequest(search_query="q", group_ids=[]))

    hit = SimpleNamespace(
        fact="svc-a 依赖 svc-b",
        name="depends_on",
        group_id="kb-1",
        source_node_uuid="s1",
        target_node_uuid="t1",
    )
    graphiti = _fake_graphiti(
        execute_query_side_effect=[
            ([{"node_count": 2}], None, None),
            ([{"edge_count": 1}], None, None),
            (
                [
                    {"uuid": "s1", "name": "svc-a", "summary": "前端", "labels": ["Service"], "fact": None},
                    {"uuid": "t1", "name": "svc-b", "summary": "后端", "labels": ["Service"], "fact": None},
                ],
                None,
                None,
            ),
        ]
    )
    graphiti.search = AsyncMock(return_value=[hit])
    rag._create_full_graphiti = MagicMock(return_value=graphiti)

    docs = await rag.search(DocumentRetrieverRequest(search_query="依赖", group_ids=["kb-1"], size=5))
    assert len(docs) == 1
    assert docs[0]["fact"] == "svc-a 依赖 svc-b"
    assert docs[0]["source_node"]["name"] == "svc-a"
    assert docs[0]["target_node"]["name"] == "svc-b"


@pytest.mark.asyncio
async def test_rebuild_community_uses_first_group(rag):
    graphiti = SimpleNamespace(
        llm_client=object(),
        embedder=object(),
        cross_encoder=object(),
        driver=SimpleNamespace(execute_query=AsyncMock()),
    )
    rag._create_full_graphiti = MagicMock(return_value=graphiti)
    rag.build_communities = AsyncMock()
    await rag.rebuild_community(RebuildCommunityRequest(group_ids=["kb-1"]))
    rag.build_communities.assert_awaited_once_with(graphiti, "kb-1")
    assert rag._create_full_graphiti.call_args.kwargs["graph_database"] == "kb-1"
