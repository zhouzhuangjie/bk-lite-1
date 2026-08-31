"""Graphiti MetisRerankerClient：空输入、成功重排、参数错误与失败回退。"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from apps.opspilot.metis.llm.rag.graph_rag.graphiti.metis_reranker_client import MetisRerankerClient
from apps.opspilot.metis.llm.rag.graph_rag.graphiti.metis_reranker_config import MetisRerankerConfig

pytestmark = pytest.mark.unit


def _client():
    return MetisRerankerClient(MetisRerankerConfig(url="http://rerank", model_name="bge", api_key="k"))


@pytest.mark.asyncio
async def test_rank_empty_query_keeps_original_passages():
    out = await _client().rank("   ", ["a", "b"])
    assert out == [("a", 0.0), ("b", 0.0)]


@pytest.mark.asyncio
async def test_rank_empty_passages_returns_empty_list():
    assert await _client().rank("cpu", []) == []


@pytest.mark.asyncio
async def test_rank_uses_relevance_score_and_falls_back_on_error():
    docs = [
        SimpleNamespace(page_content="high", metadata={"relevance_score": 0.9}),
        SimpleNamespace(page_content="low", metadata=None),
    ]
    with patch(
        "apps.opspilot.metis.llm.rag.graph_rag.graphiti.metis_reranker_client.ReRankManager.rerank_documents_with_config",
        return_value=docs,
    ) as rerank:
        out = await _client().rank("cpu", ["high", "low"])
    assert out == [("high", 0.9), ("low", 0.0)]
    assert rerank.call_args.args[0].query == "cpu"
    assert rerank.call_args.args[0].top_k == 2

    with patch(
        "apps.opspilot.metis.llm.rag.graph_rag.graphiti.metis_reranker_client.ReRankManager.rerank_documents_with_config",
        side_effect=ValueError("bad model"),
    ):
        with pytest.raises(ValueError, match="bad model"):
            await _client().rank("cpu", ["a"])

    with patch(
        "apps.opspilot.metis.llm.rag.graph_rag.graphiti.metis_reranker_client.ReRankManager.rerank_documents_with_config",
        side_effect=RuntimeError("timeout"),
    ):
        fallback = await _client().rank("cpu", ["a", "b"])
    assert fallback == [("a", 0.0), ("b", 0.0)]
