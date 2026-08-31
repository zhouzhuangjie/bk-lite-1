"""MetisEmbedder 剩余：配置校验、初始化失败、数值输入、批量校验与异常。"""
import asyncio
from unittest.mock import MagicMock, patch

import pytest

from apps.opspilot.metis.llm.rag.graph_rag.graphiti.metis_embedder import MetisEmbedder
from apps.opspilot.metis.llm.rag.graph_rag.graphiti.metis_embedder_config import MetisEmbedderConfig

pytestmark = pytest.mark.unit


def test_init_rejects_empty_config_and_wraps_embed_manager_error():
    with pytest.raises(ValueError, match="配置不能为空"):
        MetisEmbedder(None)
    cfg = MetisEmbedderConfig(url="http://e", model_name="m", api_key="k")
    with patch(
        "apps.opspilot.metis.llm.rag.graph_rag.graphiti.metis_embedder.EmbedManager"
    ) as mgr:
        mgr.return_value.get_embed.side_effect = RuntimeError("down")
        with pytest.raises(RuntimeError, match="down"):
            MetisEmbedder(cfg)


def test_init_passes_http_url_to_embed_manager():
    cfg = MetisEmbedderConfig(url="https://embed.local/v1", model_name="bge", api_key="")
    with patch(
        "apps.opspilot.metis.llm.rag.graph_rag.graphiti.metis_embedder.EmbedManager"
    ) as mgr:
        mgr.return_value.get_embed.return_value = "client"
        out = MetisEmbedder(cfg)
    mgr.return_value.get_embed.assert_called_once_with(
        "https://embed.local/v1", "bge", "", "https://embed.local/v1"
    )
    assert out.embed == "client"


def test_create_numeric_iterable_and_failure():
    embedder = MetisEmbedder.__new__(MetisEmbedder)
    embedder.embed = MagicMock()
    embedder.embed.embed_documents.return_value = [[0.5]]
    vec = asyncio.run(embedder.create([1, 2, 3]))
    assert vec == [0.5]
    embedder.embed.embed_documents.assert_called_with(["[1, 2, 3]"])
    embedder.embed.embed_documents.side_effect = RuntimeError("embed fail")
    with pytest.raises(RuntimeError, match="embed fail"):
        asyncio.run(embedder.create("x"))


def test_create_batch_validates_and_returns_vectors():
    embedder = MetisEmbedder.__new__(MetisEmbedder)
    embedder.embed = MagicMock()
    embedder.embed.embed_documents.return_value = [[1.0], [2.0]]
    with pytest.raises(ValueError, match="输入数据列表不能为空"):
        asyncio.run(embedder.create_batch([]))
    with pytest.raises(ValueError, match="必须全部为字符串"):
        asyncio.run(embedder.create_batch(["a", 1]))
    assert asyncio.run(embedder.create_batch(["a", "b"])) == [[1.0], [2.0]]
    embedder.embed.embed_documents.side_effect = RuntimeError("batch fail")
    with pytest.raises(RuntimeError, match="batch fail"):
        asyncio.run(embedder.create_batch(["a"]))
