"""GraphitiRAG 剩余路径：客户端装配、社区构建、空搜、摄取后重建。

对照契约：缺 group_ids 拒绝重建；空搜检查向量边但不抛错；社区构建在有节点时调用
build_communities；摄取后重建失败不中断 mapping。外部 Graphiti/Falkor/OpenAI 一律 mock。
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.documents import Document

from apps.opspilot.metis.llm.rag.graph_rag.graphiti.graphiti_rag import GraphitiRAG
from apps.opspilot.metis.llm.rag.graph_rag_entity import (
    DocumentIngestRequest,
    DocumentRetrieverRequest,
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
    return instance


def test_create_embed_and_rerank_clients_forward_config(rag):
    with (
        patch("apps.opspilot.metis.llm.rag.graph_rag.graphiti.graphiti_rag.MetisEmbedder") as embed_cls,
        patch("apps.opspilot.metis.llm.rag.graph_rag.graphiti.graphiti_rag.MetisEmbedderConfig") as embed_cfg,
        patch("apps.opspilot.metis.llm.rag.graph_rag.graphiti.graphiti_rag.MetisRerankerClient") as rerank_cls,
        patch("apps.opspilot.metis.llm.rag.graph_rag.graphiti.graphiti_rag.MetisRerankerConfig") as rerank_cfg,
    ):
        embed_cfg.return_value = "embed-cfg"
        rerank_cfg.return_value = "rerank-cfg"
        embed_cls.return_value = "embed-client"
        rerank_cls.return_value = "rerank-client"
        assert rag._create_embed_client({"url": "http://e", "model_name": "m", "api_key": "k"}) == "embed-client"
        assert rag._create_rerank_client({"url": "http://r", "model_name": "rm", "api_key": "rk"}) == "rerank-client"
    embed_cfg.assert_called_once_with(url="http://e", model_name="m", api_key="k")
    rerank_cfg.assert_called_once_with(url="http://r", model_name="rm", api_key="rk")


def test_create_llm_client_skips_ssrf_when_no_base_url(rag):
    with (
        patch("apps.opspilot.metis.llm.rag.graph_rag.graphiti.graphiti_rag.SSRFValidator.validate_llm_endpoint") as ssrf,
        patch("apps.opspilot.metis.llm.rag.graph_rag.graphiti.graphiti_rag.AsyncOpenAI", return_value="async-cli") as async_cls,
        patch("apps.opspilot.metis.llm.rag.graph_rag.graphiti.graphiti_rag.LLMConfig", return_value="llm-cfg"),
        patch("apps.opspilot.metis.llm.rag.graph_rag.graphiti.graphiti_rag.OpenAIClient", return_value="openai-cli") as cli,
    ):
        out = rag._create_llm_client({"api_key": "k", "model": "gpt", "base_url": None})
    assert out == "openai-cli"
    ssrf.assert_not_called()
    async_cls.assert_called_once()
    assert async_cls.call_args.kwargs["api_key"] == "k"
    assert async_cls.call_args.kwargs["base_url"] is None
    assert async_cls.call_args.kwargs["timeout"] == GraphitiRAG.LLM_TIMEOUT_SECONDS
    cli.assert_called_once()


def test_create_full_graphiti_wires_optional_clients(rag):
    rag._create_llm_client = MagicMock(return_value="llm")
    rag._create_embed_client = MagicMock(return_value="embed")
    rag._create_rerank_client = MagicMock(return_value="rerank")
    with (
        patch("apps.opspilot.metis.llm.rag.graph_rag.graphiti.graphiti_rag.FalkorDriver", return_value="driver") as driver,
        patch("apps.opspilot.metis.llm.rag.graph_rag.graphiti.graphiti_rag.Graphiti", return_value="graph") as graph,
    ):
        out = rag._create_full_graphiti(
            llm_config={"api_key": "k", "model": "m"},
            embed_config={"url": "http://e", "model_name": "e", "api_key": "ek"},
            rerank_config={"url": "http://r", "model_name": "r", "api_key": "rk"},
            graph_database="kb-1",
        )
    assert out == "graph"
    driver.assert_called_once()
    assert driver.call_args.kwargs["database"] == "kb-1"
    graph.assert_called_once_with(llm_client="llm", embedder="embed", cross_encoder="rerank", graph_driver="driver")


@pytest.mark.asyncio
async def test_safe_close_driver_swallows_sleep_error(rag):
    with (
        patch(
            "apps.opspilot.metis.llm.rag.graph_rag.graphiti.graphiti_rag.asyncio.sleep",
            new=AsyncMock(side_effect=RuntimeError("cancelled")),
        ),
        patch("apps.opspilot.metis.llm.rag.graph_rag.graphiti.graphiti_rag.logger") as mock_logger,
    ):
        await rag._safe_close_driver(SimpleNamespace())
    mock_logger.debug.assert_called_once()
    assert mock_logger.debug.call_args.args[0] == "等待后台任务时出现警告: cancelled"


@pytest.mark.asyncio
async def test_build_communities_runs_when_nodes_exist(rag):
    graphiti = SimpleNamespace(
        driver=SimpleNamespace(
            execute_query=AsyncMock(
                side_effect=[
                    ([{"count": 2}], None, None),
                    ([{"count": 1}], None, None),
                    ([{"count": 3}], None, None),
                ]
            )
        ),
        build_communities=AsyncMock(return_value="ok"),
    )
    await rag.build_communities(graphiti, "kb-1")
    graphiti.build_communities.assert_awaited_once()


@pytest.mark.asyncio
async def test_build_communities_reraises_check_failure(rag):
    graphiti = SimpleNamespace(
        driver=SimpleNamespace(execute_query=AsyncMock(side_effect=RuntimeError("graph down"))),
        build_communities=AsyncMock(),
    )
    with pytest.raises(RuntimeError, match="graph down"):
        await rag.build_communities(graphiti, "kb-1")
    graphiti.build_communities.assert_not_awaited()


@pytest.mark.asyncio
async def test_ingest_rebuild_community_failure_still_returns_mapping(rag):
    ok_episode = SimpleNamespace(episode=SimpleNamespace(uuid="ep-1"))
    graphiti = SimpleNamespace(add_episode=AsyncMock(return_value=ok_episode), driver=SimpleNamespace())
    rag._create_full_graphiti = MagicMock(return_value=graphiti)
    rag.build_communities = AsyncMock(side_effect=RuntimeError("community down"))
    rag._safe_close_driver = AsyncMock()
    docs = [Document(page_content="a", metadata={"knowledge_title": "t", "knowledge_id": 1, "chunk_id": "c1"})]
    progress = []
    result = await rag.ingest(
        DocumentIngestRequest(group_id="kb-1", docs=docs, rebuild_community=True),
        callback=lambda cur, total, task: progress.append((cur, total, task)),
        task_id="task-r",
    )
    assert result["success_count"] == 1
    assert result["failed_count"] == 0
    assert result["mapping"] == {"c1": "ep-1"}
    assert result["total_count"] == 1
    rag.build_communities.assert_awaited_once_with(graphiti, "kb-1")
    rag._safe_close_driver.assert_awaited_once()
    assert progress == [(1, 1, "task-r")]


@pytest.mark.asyncio
async def test_search_empty_results_checks_vectors(rag):
    graphiti = SimpleNamespace(
        driver=SimpleNamespace(
            execute_query=AsyncMock(
                side_effect=[
                    ([{"node_count": 1}], None, None),
                    ([{"edge_count": 1}], None, None),
                    ([{"vector_count": 0}], None, None),
                    ([{"rel_type": "USES", "fact": None, "has_embedding": False, "source_name": "a", "target_name": "b"}], None, None),
                ]
            )
        ),
        search=AsyncMock(return_value=[]),
    )
    rag._create_full_graphiti = MagicMock(return_value=graphiti)
    rag._safe_close_driver = AsyncMock()
    docs = await rag.search(DocumentRetrieverRequest(search_query="q", group_ids=["kb-1"], size=3))
    assert docs == []
    assert graphiti.driver.execute_query.await_count == 4
    graphiti.search.assert_awaited_once()


@pytest.mark.asyncio
async def test_rebuild_community_rejects_empty_and_reraises(rag):
    with pytest.raises(ValueError, match="group_ids"):
        await rag.rebuild_community(RebuildCommunityRequest(group_ids=[]))

    graphiti = SimpleNamespace(llm_client=None, driver=SimpleNamespace())
    rag._create_full_graphiti = MagicMock(return_value=graphiti)
    rag.build_communities = AsyncMock(side_effect=RuntimeError("build fail"))
    rag._safe_close_driver = AsyncMock()
    with pytest.raises(RuntimeError, match="build fail"):
        await rag.rebuild_community(RebuildCommunityRequest(group_ids=["kb-1"]))
    rag._safe_close_driver.assert_awaited_once()
