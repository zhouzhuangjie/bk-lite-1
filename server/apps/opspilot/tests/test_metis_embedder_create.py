"""MetisEmbedder.create：空输入报错；字符串/列表走 embed_documents。"""
import asyncio
from unittest.mock import MagicMock

import pytest

from apps.opspilot.metis.llm.rag.graph_rag.graphiti.metis_embedder import MetisEmbedder

pytestmark = pytest.mark.unit


def test_create_rejects_empty_and_embeds_text():
    embedder = MetisEmbedder.__new__(MetisEmbedder)
    embedder.embed = MagicMock()
    embedder.embed.embed_documents.return_value = [[0.1, 0.2, 0.3]]

    with pytest.raises(ValueError, match="输入数据不能为空"):
        asyncio.run(embedder.create(""))

    vec = asyncio.run(embedder.create("hello"))
    assert vec == [0.1, 0.2, 0.3]
    embedder.embed.embed_documents.assert_called_with(["hello"])

    batch = asyncio.run(embedder.create(["a", "b"]))
    assert batch == [0.1, 0.2, 0.3]
    embedder.embed.embed_documents.assert_called_with(["a", "b"])
