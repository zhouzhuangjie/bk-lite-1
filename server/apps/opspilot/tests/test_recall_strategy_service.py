"""召回策略工厂与 chunk/segment/origin 合并行为。"""
from unittest.mock import MagicMock

import pytest
from langchain_core.documents import Document

from apps.opspilot.metis.llm.rag.naive_rag.recall_strategies.chunk_recall_strategy import ChunkRecallStrategy
from apps.opspilot.metis.llm.rag.naive_rag.recall_strategies.origin_recall_strategy import OriginRecallStrategy
from apps.opspilot.metis.llm.rag.naive_rag.recall_strategies.recall_strategy_factory import RecallStrategyFactory
from apps.opspilot.metis.llm.rag.naive_rag.recall_strategies.segment_recall_strategy import SegmentRecallStrategy
from apps.opspilot.metis.llm.rag.naive_rag_entity import DocumentRetrieverRequest

pytestmark = pytest.mark.unit


def _req(**kwargs):
    return DocumentRetrieverRequest(index_name="kb", **kwargs)


def test_factory_returns_builtin_strategies_and_rejects_unknown():
    names = RecallStrategyFactory.get_available_strategies()
    assert set(names) >= {"chunk", "segment", "origin"}
    assert isinstance(RecallStrategyFactory.get_strategy("chunk"), ChunkRecallStrategy)
    with pytest.raises(ValueError, match="不支持的召回策略"):
        RecallStrategyFactory.get_strategy("nope")


def test_chunk_strategy_returns_original_hits():
    docs = [Document(page_content="a", metadata={"segment_id": "s1"})]
    assert ChunkRecallStrategy().process_recall(_req(), docs, MagicMock()) is docs


def test_segment_strategy_merges_chunks_in_order_and_falls_back():
    hits = [
        Document(page_content="p1", metadata={"segment_id": "s1", "chunk_number": "1"}),
    ]
    client = MagicMock()
    client.list_index_document.return_value = [
        Document(page_content="后", metadata={"segment_id": "s1", "chunk_number": "2"}),
        Document(page_content="前", metadata={"segment_id": "s1", "chunk_number": "1"}),
    ]
    merged = SegmentRecallStrategy().process_recall(_req(), hits, client)
    assert len(merged) == 1
    assert merged[0].page_content == "前\n后"
    assert merged[0].metadata["is_merged_segment"] is True
    assert merged[0].metadata["merged_chunk_count"] == 2
    assert "chunk_number" not in merged[0].metadata

    no_id = [Document(page_content="x", metadata={})]
    assert SegmentRecallStrategy().process_recall(_req(), no_id, client) is no_id

    client.list_index_document.side_effect = ConnectionError("down")
    assert SegmentRecallStrategy().process_recall(_req(), hits, client) is hits


def test_origin_strategy_merges_by_knowledge_id():
    hits = [Document(page_content="h", metadata={"knowledge_id": "k1"})]
    client = MagicMock()
    client.list_index_document.return_value = [
        Document(page_content="二", metadata={"knowledge_id": "k1", "segment_number": "2"}),
        Document(page_content="一", metadata={"knowledge_id": "k1", "segment_number": "1"}),
    ]
    merged = OriginRecallStrategy().process_recall(_req(), hits, client)
    assert merged[0].page_content == "一\n二"
    assert merged[0].metadata["is_merged_origin"] is True
    assert merged[0].metadata["merged_segment_count"] == 2

    client.list_index_document.side_effect = ValueError("bad")
    assert OriginRecallStrategy().process_recall(_req(), hits, client) is hits
